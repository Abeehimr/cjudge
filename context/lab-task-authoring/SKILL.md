---
name: lab-task-authoring
description: Create or review cJudge C/C++ lab tasks with settings, importable task ZIPs, reproducible Python generators, reference and wrong solutions, coverage reports, and custom checkers when needed.
---

# cJudge Lab Task Authoring

## Establish the task

Establish the learning objective, permitted concepts/languages, input bounds, output format, marks, and scoring policy. Ask about material gaps; label reasonable defaults. Keep cases within the statement's constraints. This skill is self-contained; repository access is optional. When available, verify contracts in `src/cjudge/tasks/grading.py`, `bundle.py`, and `cases.py`.

## Deliverables and settings

Provide one importable ZIP per task and a downloadable source package containing a shared `build_and_test.py`, a short report, and one directory per task with `task-config.json`, `generator.py`, `reference.c` or `reference.cpp`, and deliberate wrong solutions in `wrong/`. Include statements in configuration, settings/marks in the report, and produced task ZIPs in the package. The outer source package is not a cJudge import ZIP; import each task's ZIP separately. Include a working rebuild command, such as `python build_and_test.py`.

- Statement: input/output specification, constraints, and worked examples. Markdown is optional when the lab PDF supplies the statement; PDFs belong to labs.
- State maximum marks explicitly for the lab assignment, not the task ZIP. Default scoring is `partial`: equal case weights; use `all_or_nothing` when requested. Case distribution therefore affects marks.
- Set `languages` to `["c11"]` (default), `["cpp17"]`, or `["c11", "cpp17"]`. Upload extensions select the compiler: `.c` or `.cpp`. Generator/reference languages are independent; identifier restrictions remain case-sensitive.
- Checker: `exact` compares bytes; optionally ignore exactly one final LF/CRLF. Prefer `tokens` when ASCII whitespace is immaterial; case-sensitive, zero tolerance by default. `ignore_case` uses ASCII case folding. Numeric tolerance applies only to finite numeric tokens: `abs(a-b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))`; NaN/Infinity receive no numeric tolerance. Set tolerances only for specified numeric requirements.
- Resource defaults: CPU **2 s**, wall **6 s**, memory **256 MiB**, stack **8 MiB**, stdout **10 MiB**. Justify changes; wall must be at least CPU, stack at most memory.

## Task ZIP v2

Use this format for **Import task ZIP**:

```text
task.zip
├── manifest.json
└── cases/
    ├── 1.in
    ├── 1.out
    ├── 2.in
    └── 2.out
```

Complete UTF-8 `manifest.json` example; change settings and `case_count` for the task:

```json
{
  "format": "cjudge-task",
  "version": 2,
  "config": {
    "title": "Add two integers",
    "statement": "Read two integers and print their sum.",
    "scoring": "partial",
    "languages": ["c11"],
    "checker": {
      "kind": "tokens",
      "source": "",
      "ignore_final_newline": false,
      "ignore_case": false,
      "absolute_tolerance": "0",
      "relative_tolerance": "0"
    },
    "banned_identifiers": [],
    "cpu_seconds": 2,
    "wall_seconds": 6,
    "memory_mib": 256,
    "stack_mib": 8,
    "stdout_mib": 10
  },
  "case_count": 2
}
```

- `task-config.json` contains only the `config` object; the generated build script adds `format`, `version`, and the actual case count. Never include `maximum_marks` or unknown fields.
- Write exactly `manifest.json` and `cases/1.in`/`cases/1.out` through `cases/N.in`/`cases/N.out`. No gaps, duplicate names, explicit directory entries, enclosing task folder, PDFs, source files, or reports inside the import ZIP. Preserve case bytes without stripping whitespace.
- Use Python `zipfile.ZipFile(..., 'w', compression=zipfile.ZIP_STORED)` with `writestr`; serialize the manifest with `json.dumps(...).encode('utf-8')`. Reopen and verify names, pair counts, JSON, and sizes before delivering. Unencrypted regular deflated entries are also accepted.
- Limits: ZIP **17 MiB**, manifest **1 MiB**, **1–100 pairs**, each input/answer **1 MiB**, combined case bytes **16 MiB**. Titles: 1–160 characters; statements: at most 65,536 characters. CPU/wall: positive, at most 60 s; memory: 1–512 MiB; stack: 1–64 MiB; stdout: 1–10 MiB. Keep wall ≥ CPU and stack ≤ memory. Banned identifiers: at most 100 distinct case-sensitive ASCII C identifiers, at most 128 characters each.
- Checker kinds: `exact`, `tokens`, `python`. `exact` permits only `ignore_final_newline`; `tokens` permits only `ignore_case` and absolute/relative tolerances (0–1, at most 15 decimal places). Built-in checker `source` must be empty. Python checking requires source and all built-in options at defaults.
- The separate **Replace cases from ZIP** control expects flat `N.in`/`N.out` pairs, without a manifest or settings. Do not confuse it with whole-task import.

## Generate, test, and package

The delivered Python build/test script must use the standard library without cJudge imports. Compile reference and wrong C/C++ solutions with GCC C11 or g++ C++17 (`-O2`, libm when needed). Generate each input, run the reference on it to obtain the expected output, exercise wrong solutions against the same cases/checking policy, then write each task ZIP. Abort packaging on reference, generator, checker, or validation failure; do not fabricate outputs.

Generate one input per invocation; read the seed from `sys.argv[1]` and seed Python's `random` explicitly. Specify starting seed/count and use consecutive seeds. Write only input to stdout and diagnostics to stderr. Reference solutions read stdin and write expected answers to stdout. Combine deliberate boundary cases with varied cases, rather than random-only coverage. Generator/reference/checker sources are at most **64 KiB**; include existing cases when checking case limits.

Run trusted authoring programs in Claude's execution sandbox or another isolated environment; never execute student submissions directly on the host. Bound process time and captured output, clean up timed-out processes, and keep source paths/commands explicit. A generated Python wrapper is not itself a sandbox. If compilers or safe execution are unavailable, deliver the runnable source package and clearly mark unexecuted checks/ZIPs as unverified; never claim execution that did not happen.

## Custom checking

Add a Python checker only for multiple valid answers or semantic validation not expressible by built-in checking. Put its source in `checker.source`. cJudge supplies `read_input()`, `read_output()`, and `read_answer()` returning bytes, plus `accept()`/`reject()`; no imports from cJudge are needed. Every normal path must produce a verdict; print no verdict/debug output. Reject malformed output and extra tokens. Exceptions, missing verdicts, and resource failures are checker failures, not valid rejections. The generated test harness must use the same checker semantics, supply these helpers for a custom checker, and test valid and invalid outputs.

## Edge cases and review

Select applicable cases and state the mistake each detects:

- Minimum/maximum sizes and values; singleton; empty input only when allowed.
- Zero, negatives, duplicates, all-equal, sorted/reversed, first/last positions.
- Overflow/signedness, integer division, precision/rounding.
- Whitespace, line endings, case sensitivity, missing/extra tokens, malformed output, NaN/Infinity, valid alternative answers.
- Worst-case runtime, memory, and output size.

Cross-check small reference answers independently. Provide wrong solutions for plausible mistakes and report a matrix of each wrong solution against the cases that reject it. Compilation failures do not count as coverage; wrong answers, runtime failures, or timeouts on valid inputs can. Investigate surviving wrong solutions, strengthen relevant cases, and disclose unresolved survivors. Rejecting selected wrong solutions does not prove exhaustive edge coverage.

Deliver the task ZIPs, reproducible source package, tested/unverified status, seed/count, coverage matrix, and remaining limitations. Whole-task import creates drafts: review cases before publishing. When using cJudge's generator UI, **Apply reviewed cases** appends to existing cases; draft changes invalidate application.
