---
name: lab-task-authoring
description: Create cJudge C lab tasks with task settings, seeded generators, reference solutions, edge cases, and custom checkers when needed. Use when preparing or reviewing lab problems and test data.
---

# cJudge Lab Task Authoring

## Establish the task

In the cJudge repository, read README's task-library and Python-authoring sections. Verify current contracts in `src/cjudge/tasks/grading.py`, `src/cjudge/tasks/authoring.py`, and `src/cjudge/tasks/cases.py` before choosing settings.

Establish the learning objective, permitted C concepts, input bounds, output format, marks, and scoring policy. Ask about material gaps; explicitly label reasonable defaults. Keep cases within the statement's constraints.

## Deliverables and settings

Provide a concise task statement, settings table, complete Python generator, reference C solution, starting seed/count, and edge-case checklist. Add a custom checker only if built-in checking cannot express correctness.

- Statement: input/output specification, constraints, and worked examples. Markdown is optional when the lab PDF supplies the statement; PDFs belong to labs.
- State maximum marks explicitly. Default scoring is `partial`: equal case weights; use `all_or_nothing` when requested. Case distribution therefore affects marks.
- Checker: `exact` for byte-sensitive output; optionally ignore one final LF/CRLF. Prefer `tokens` when ASCII whitespace is immaterial; case-sensitive, zero tolerance by default. Set absolute/relative tolerances only for specified numeric requirements.
- Resource defaults: CPU **2 s**, wall **6 s**, memory **256 MiB**, stack **8 MiB**, stdout **10 MiB**. Justify changes; wall must be at least CPU, stack at most memory.

## Generator and reference

Generate one input per invocation. Read the seed from `sys.argv[1]`; Python's standard `random` is already seeded. Make generation deterministic; write only input to stdout, diagnostics to stderr. Reference C reads stdin and writes the expected answer to stdout.

Choose seed/count explicitly; generation uses consecutive seeds. Combine deliberate boundary cases with varied cases, rather than random-only coverage. Sources are at most **64 KiB**; inputs/answers **1 MiB each**; combined cases **16 MiB**, at most **100 cases**, including existing cases.

## Custom checking

Use Python for multiple valid answers or task-specific semantic validation. `read_input()`, `read_output()`, and `read_answer()` return bytes. Every path must call `accept()` or `reject()`; print no verdict/debug output. Reject malformed student output and extra tokens. Do not broadly suppress checker bugs: exceptions, missing verdicts, and resource failures block judging rather than award zero.

## Edge cases and review

Select applicable cases and state the mistake each detects:

- Minimum/maximum sizes and values; singleton; empty input only when allowed.
- Zero, negatives, duplicates, all-equal, sorted/reversed, first/last positions.
- Overflow/signedness, integer division, precision/rounding.
- Whitespace, line endings, case sensitivity, missing/extra tokens, malformed output, NaN/Infinity, valid alternative answers.
- Worst-case runtime, memory, and output size.

Cross-check small answers independently; include known incorrect solutions. Test custom checkers against valid and invalid outputs. Execute programs through cJudge's Docker/isolate flow. Review generated previews, **Apply reviewed cases** to append, then publish separately; draft changes invalidate generation application.
