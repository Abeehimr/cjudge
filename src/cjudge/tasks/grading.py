"""Versioned built-in checker and rational score contracts."""

from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Checker(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["exact", "tokens", "python"] = "exact"
    source: str = Field(default="", max_length=65536)
    ignore_final_newline: bool = False
    ignore_case: bool = False
    absolute_tolerance: Decimal = Field(default=Decimal(0), ge=0, le=1, max_digits=16, decimal_places=15)
    relative_tolerance: Decimal = Field(default=Decimal(0), ge=0, le=1, max_digits=16, decimal_places=15)

    @model_validator(mode="after")
    def options_match_kind(self) -> Self:
        if len(self.source.encode()) > 65536:
            raise ValueError("Checker source exceeds 64 KiB")
        if self.kind == "python":
            if not self.source.strip() or self.ignore_final_newline or self.ignore_case or self.absolute_tolerance or self.relative_tolerance:
                raise ValueError("Python checking requires source and no built-in options")
        elif self.source:
            raise ValueError("Checker source applies only to Python checking")
        if self.kind == "exact" and (self.ignore_case or self.absolute_tolerance or self.relative_tolerance):
            raise ValueError("Case and numeric tolerance apply only to token checking")
        if self.kind == "tokens" and self.ignore_final_newline:
            raise ValueError("Final newline option applies only to exact checking")
        return self


class TaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    title: str = Field(min_length=1, max_length=160)
    statement: str = Field(default="", max_length=65536)
    maximum_marks: Decimal = Field(default=Decimal(100), gt=0, le=10000, max_digits=7, decimal_places=2)
    scoring: Literal["partial", "all_or_nothing"] = "partial"
    checker: Checker = Field(default_factory=Checker)
    cpu_seconds: float = Field(default=2, gt=0, le=60)
    wall_seconds: float = Field(default=6, gt=0, le=60)
    memory_mib: int = Field(default=256, ge=1, le=512)
    stack_mib: int = Field(default=8, ge=1, le=64)
    stdout_mib: int = Field(default=10, ge=1, le=10)

    @model_validator(mode="after")
    def validate_limits(self) -> Self:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("Title cannot be blank")
        if self.wall_seconds < self.cpu_seconds or self.stack_mib > self.memory_mib:
            raise ValueError("Wall must be at least CPU; stack must not exceed memory")
        return self


_NUMBER = re.compile(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,4})?\Z")


def compare_output(actual: bytes, expected: bytes, checker: Checker) -> bool:
    if checker.kind == "python":
        raise ValueError("Python checkers require the isolate runner")
    if checker.kind == "exact":
        if checker.ignore_final_newline:
            # Ignore precisely one LF or CRLF at EOF; preserve all other bytes.
            actual = actual.removesuffix(b'\r\n') if actual.endswith(b'\r\n') else actual.removesuffix(b'\n')
            expected = expected.removesuffix(b'\r\n') if expected.endswith(b'\r\n') else expected.removesuffix(b'\n')
        return actual == expected
    left, right = actual.split(), expected.split()  # bytes.split uses ASCII whitespace only.
    if len(left) != len(right):
        return False
    for a, b in zip(left, right):
        if (a.lower() == b.lower()) if checker.ignore_case else (a == b):
            continue
        if not (checker.absolute_tolerance or checker.relative_tolerance):
            return False
        # Bound numeric parsing cost. Other tokens, including NaN/Infinity, compare literally.
        if len(a) > 128 or len(b) > 128 or not _NUMBER.fullmatch(a) or not _NUMBER.fullmatch(b):
            return False
        try:
            with localcontext() as context:
                context.prec = 160
                x, y = Decimal(a.decode('ascii')), Decimal(b.decode('ascii'))
                if abs(x - y) > max(checker.absolute_tolerance,
                                    checker.relative_tolerance * max(abs(x), abs(y))):
                    return False
        except InvalidOperation:
            return False
    return True


def score(maximum: Decimal, passed: int, total: int, mode: Literal["partial", "all_or_nothing"]) -> Fraction:
    if total < 1 or not 0 <= passed <= total or maximum < 0 or mode not in ("partial", "all_or_nothing"):
        raise ValueError("Invalid score inputs")
    return Fraction(maximum) * (Fraction(passed, total) if mode == "partial" else int(passed == total))
