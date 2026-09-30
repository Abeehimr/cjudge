"""Teacher programs run only inside isolate; protocol failures never award marks."""
from dataclasses import replace
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from cjudge import runner


class GenerationConfig(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Literal['python', 'c'] = 'python'
    generator: str = Field(min_length=1, max_length=65536)
    reference: str = Field(min_length=1, max_length=65536)
    seed: int = Field(default=0, ge=0, le=2**63 - 1, strict=True)
    count: int = Field(default=1, ge=1, le=100, strict=True)

    @model_validator(mode='after')
    def bounded(self) -> Self:
        if any(len(source.encode()) > runner.SOURCE_BYTES or not source.strip()
               for source in (self.generator, self.reference)):
            raise ValueError('Sources must contain 1–65536 bytes')
        if self.seed + self.count - 1 > 2**63 - 1:
            raise ValueError('Final seed exceeds signed 64-bit range')
        return self


# The wrapper is platform-owned; submitted source keeps its own coding declaration.
CHECKER_WRAPPER = b'''import runpy
from pathlib import Path
import sys
class Verdict(BaseException):
    pass
def accept():
    raise Verdict('AC')
def reject():
    raise Verdict('WA')
helpers = dict(read_input=lambda: Path('/box/input').read_bytes(),
               read_output=lambda: Path('/box/output').read_bytes(),
               read_answer=lambda: Path('/box/answer').read_bytes(),
               accept=accept, reject=reject)
try:
    runpy.run_path('/box/checker.py', init_globals=helpers)
except Verdict as verdict:
    sys.stdout.write(str(verdict) + '\\n')
else:
    raise RuntimeError('Checker must call accept() or reject()')
'''
GENERATOR_WRAPPER = b'''import random
import runpy
import sys
random.seed(int(sys.argv[1]))
sys.argv[0] = '/box/generator.py'
runpy.run_path('/box/generator.py', run_name='__main__')
'''


def check_python(source: str, input_bytes: bytes, output: bytes, answer: bytes) -> bool:
    result = runner.run_python(CHECKER_WRAPPER, runner.Profile.CHECKER,
        {'checker.py': source.encode(), 'input': input_bytes, 'output': output, 'answer': answer})
    if result.verdict != 'OK' or result.stdout not in (b'AC\n', b'WA\n'):
        raise runner.SandboxError('Invalid Python checker verdict')
    return result.stdout == b'AC\n'


class AuthoringError(ValueError):
    """Confirmed teacher program failure, not a retryable infrastructure failure."""


def compile_source(source: str, label: str) -> bytes:
    result = runner.compile_c(source.encode())
    if result.verdict != 'OK':
        raise AuthoringError(f'{label} compile error: ' + result.stderr.decode('utf-8', errors='replace'))
    return result.executable


def generate_case(config: GenerationConfig, seed: int, reference: bytes,
                  generator: bytes | None = None) -> tuple[bytes, bytes]:
    limits = replace(runner.PROFILES[runner.Profile.GENERATOR], stdout_bytes=1024 * 1024)
    if config.language == 'python':
        result = runner.run_python(GENERATOR_WRAPPER, runner.Profile.GENERATOR,
            {'generator.py': config.generator.encode()}, args=(str(seed),), limits=limits)
    else:
        result = runner._run(runner.Profile.GENERATOR, ['/box/main', str(seed)],
                             {'main': generator}, limits=limits)
    if result.verdict != 'OK':
        raise AuthoringError(f'Generator seed {seed}: {result.verdict}\n' + result.stderr.decode('utf-8', errors='replace'))
    answer = runner.execute(reference, result.stdout, limits)
    if answer.verdict != 'OK':
        raise AuthoringError(f'Reference seed {seed}: {answer.verdict}\n' + answer.stderr.decode('utf-8', errors='replace'))
    return result.stdout, answer.stdout
