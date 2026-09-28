# Product Requirements

Source of truth for cJudge v1 product behavior. Planned functionality; the repository currently contains a Python scaffold. See [design.md](design.md) for organization and [technical-requirements.md](technical-requirements.md) for implementation constraints.

## Scope

An offline-operable LAN judge for C programming labs: one admin, one active lab, 150 students, five tasks, ten cases per task, and a two-hour lab. Installation and maintenance may use internet; running a lab must not.

Deferred: other submission languages, TAs/multiple admins, concurrent labs, individual extensions, weighted cases, subtask groups, testlib, plagiarism detection, an in-browser editor, offline installation bundles, automated backups, server restoration, and archive import.

## Accounts and Tasks

- Import student roll numbers/names from CSV, generate printable credentials, and support password resets. Keep admin authentication separate.
- Bind each student's browser per lab. Missing/invalid tokens require admin release even at the same IP; release revokes old sessions. Allow and flag IP changes with a valid token; optional strict mode requires matching IPs.
- Tasks have a title, optional Markdown statement, maximum marks, scoring mode, checker, and resource limits. Require at least one case before publication; no per-task PDF is required or stored.
- Accept paired `N.in`/`N.out` ZIPs, pasted cases, and reviewed output from sandboxed Python/C generators with a reference C solution.
- Support exact comparison, optional trailing-newline handling, token comparison with optional case/float tolerance, and Python custom checkers. Use reusable tasks with immutable grading revisions pinned to lab assignments.

## Lab and Submission Rules

- Attach one or more PDFs containing the lab tasks to the lab. Task Markdown statements are optional supplements; leave the statement section hidden when empty.
- Lifecycle: Draft → Scheduled → Running → Ended → Results released → Archived. Hide lab PDFs and task statements until start and allow only assigned students to participate.
- Use a common server-authoritative deadline. Allow whole-lab extensions and reopening before first release; never reopen after release, even if results are hidden again.
- Prevent overlapping labs. Require explicit rescheduling before an extension conflicts with another lab.
- Accept one `.c` file up to 64 KiB only after complete upload, validation, and durable acceptance strictly before the deadline. Queued judging may finish afterward.
- Enforce a 30-second cooldown across tasks and at most three pending submissions per student. Rejudge jobs do not consume upload slots.
- Show Queued, Judging, Passed/Failed, configured compile-error feedback, or Judging delayed. Compile-error feedback defaults to approximately 20 lines, with full/verdict-only options.
- During labs, expose no partial marks or hidden-case details. Scoreboards may be disabled, admin-only (default), or student-visible with solved tasks only.

## Grading and Corrections

- Partial score = maximum marks × passed cases / total cases. All-or-nothing awards marks only when every case passes. Compile errors earn zero.
- Count the best active submission by unrounded score; ties use earliest acceptance, then submission ID. Display two decimals with half-up rounding and sum displayed task marks for totals.
- Show admin attempts best to worst, separating pending/deleted attempts. Soft deletion requires a reason, excludes the attempt from marks/student history, preserves evidence, and permits restoration. Recompute marks on either action.
- No submission means zero; unresolved infrastructure failure means pending, never zero.
- Corrections publish a new revision and rejudge every active attempt for the affected lab task. Preserve earlier results and replace official marks consistently after completion. Support single-submission rejudges without changing grading configuration.

## Release and Exports

- Release manually after the lab ends; block release and final mark sheets while active judging/rejudging remains unresolved. Admins may retry or explicitly invalidate affected runs.
- After release, show each active submission's marks, per-case verdicts, and failed-case inputs, expected outputs, and student stdout/stderr. Retain the first 64 KiB per stream/case and label truncation.
- Warn before revealing tests used by another scheduled lab. Admin controls release timing; hiding results cannot undo disclosure.
- Students access only their own private data, apart from the configured scoreboard.
- CSV/XLSX exports contain roll number, name, per-task marks/pass percentages, total marks, active submission count, and last active submission time. Percentages come from counted submissions.
- Lab ZIPs include lab PDFs, optional task Markdown statements, tests, configurations/revisions, all retained sources including deleted attempts, judge history, marks, and audit records. Export does not delete the lab; permanent deletion is a separate action after successful export. ZIPs are not full-server backups.

## Success Targets

Validate on target hardware: API p95 below 300 ms at 150 concurrent users; ordinary light-load judging within 30 seconds; 150 representative submissions arriving over 60 seconds completed within five minutes of first acceptance. Measure timeout-heavy behavior separately. Correct grading, access control, isolation, and recovery are release prerequisites.
