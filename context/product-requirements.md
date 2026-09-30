# Product Requirements

Source of truth for cJudge v1 product behavior. M0–M8 are implemented; deployment acceptance remains M9. See [design.md](design.md) for organization and [technical-requirements.md](technical-requirements.md) for implementation constraints.

## Scope

An offline-operable LAN judge for C programming labs: one admin, one active lab, 150 students, five tasks, ten cases per task, and a two-hour lab. Installation and maintenance may use internet; running a lab must not.

Deferred: other submission languages, TAs/multiple admins, concurrent labs, individual extensions, weighted cases, subtask groups, testlib, plagiarism detection, scoreboards, an in-browser editor, offline installation bundles, automated backups, server restoration, and archive import.

## Accounts and Tasks

- Keep one global account and unique credentials per student across labs. Create accounts manually or from CSV; retain existing credentials and flag name mismatches. Admin can reprint credentials and reset student passwords. Use one login form with server-enforced role separation. Enroll accounts into labs in M4.
- Bind each student's browser per lab. Missing/invalid tokens require admin release even at the same IP; release revokes old sessions. Allow and flag IP changes with a valid token; optional strict mode requires matching IPs.
- Tasks have a title, optional Markdown statement, maximum marks, scoring mode, checker, and resource limits. Require at least one case before publication; no per-task PDF is required or stored.
- Accept paired `N.in`/`N.out` ZIPs, pasted cases, and reviewed output from sandboxed Python/C generators with a reference C solution.
- Support exact comparison, optional trailing-newline handling, token comparison with optional case/float tolerance, and Python custom checkers. Use reusable tasks with immutable grading revisions pinned to lab assignments.

## Lab and Submission Rules

- Attach PDFs containing the lab tasks to the lab; PDFs are optional only when every assigned task has nonempty Markdown. Leave empty statement sections hidden. During a running lab, PDF additions/replacements automatically announce the change; retain previous PDFs for admin access.
- Lifecycle: Draft → Scheduled → Running → Ended → Results released → Archived. Hide lab PDFs and task statements until start and allow only assigned students to participate.
- Freeze task assignments and enrollment removals at start; allow late enrollment additions.
- Require explicit Enter lab to bind the browser, including after the lab ends.
- Admin may stop a running lab immediately with confirmation and a reason. Stop closes new uploads but finishes accepted judging; reopening remains possible before first release.
- Admin may freeze/unfreeze new submissions per student and lab with an audit reason; retain materials access and prior accepted work. Unfreezing adds no time.
- Admin posts plain-text announcements; enrolled students can read the full history after start.
- Use a common server-authoritative deadline. Allow whole-lab extensions and reopening before first release; never reopen after release, even if results are hidden again.
- Prevent overlapping labs. Require explicit rescheduling before an extension conflicts with another lab.
- Accept one `.c` file up to 64 KiB only after complete upload, validation, and durable acceptance strictly before the deadline. Queued judging may finish afterward.
- Save each accepted submission's client IP and MAC address when available from a trusted LAN source. Admin review shows these values and flags changes across a student's submissions within the lab as possible PC switches, not proof. Missing MAC values display as unavailable and do not block submission.
- Enforce a 30-second cooldown across tasks and at most three pending submissions per student. Rejudge jobs do not consume upload slots.
- Configure independent sandbox instances through the environment. Admin's Isolates panel shows configured, healthy, and working counts, current work, heartbeat freshness, and faults.
- Show Queued, Judging, Passed/Failed, configured compile-error feedback, or Judging delayed. Compile-error feedback defaults to approximately 20 lines, with full/verdict-only options.
- During labs, expose no partial marks or hidden-case details. Scoreboards are deferred.

## Navigation

- Separate lab overview, enrollment, assigned tasks, and submission review into meaningful pages. Keep reading and submission together on student task pages.
- Admin student pages combine lab controls and student history; admin task pages show assigned revisions and per-task submissions. Keep submission lists per lab, newest first, with student/task filters.
- Refresh, bookmarks, and browser history restore location and filters. Resume valid lab bindings without re-entering; warn before discarding unsaved forms or selected files.

## Grading and Corrections

- Partial score = maximum marks × passed cases / total cases. All-or-nothing awards marks only when every case passes. Compile errors earn zero.
- Count the best active submission by unrounded score; ties use earliest acceptance, then submission ID. Display two decimals with half-up rounding and sum displayed task marks for totals.
- Show admin attempts best to worst, separating pending/deleted attempts. Soft deletion requires a reason, excludes the attempt from marks/student history, preserves evidence, and permits restoration. Recompute marks on either action.
- Shade the newest highest-scoring active official attempt per student/task in admin and released student lists, labeled Best for review. This review preference does not change the earliest-tie rule for counted marks.
- No submission means zero; unresolved infrastructure failure means pending, never zero.
- Allow corrections during running or ended labs, including after release with a warning and audit reason; never reopen a released lab. Corrections publish a new revision and rejudge every active attempt for the affected lab task. Preserve earlier results and replace official marks consistently after completion. Support single-submission rejudges without changing grading configuration.

## Release and Exports

- Release manually after the lab ends; block release and final mark sheets while active judging/rejudging remains unresolved. Admins may retry or exclude affected attempts through audited soft deletion.
- After release with reveal enabled, show each active submission's source, marks, all retained grading runs, per-case verdicts, and failed-case inputs, expected outputs, and student stdout/stderr. Retain the first 64 KiB per stream/case and label truncation.
- Open submissions from history on a dedicated page with inline source and details. Admins can inspect submissions before release; students can inspect only their own after release while reveal is enabled. During labs, keep student histories limited to status and configured compiler feedback.
- Warn before revealing tests used by another scheduled lab. Admin controls release timing; hiding results cannot undo disclosure.
- Students access only their own private data, with no student access to network metadata or infrastructure diagnostics.
- CSV exports contain roll number, name, per-task marks/pass percentages, total marks, active submission count, and last active submission time. Percentages come from counted submissions.
- Explicit Archive after release freezes lab and grading edits; reveal and exports remain available.
- Lab ZIPs include lab PDFs, optional task Markdown statements, tests, configurations/revisions, all retained sources including deleted attempts, judge history, marks, and audit records. Export does not delete the lab; permanent deletion requires a current verified export, saved-copy acknowledgment, matching typed lab title, and audit reason. Global accounts and shared tasks remain. ZIPs are not full-server backups.

## Success Targets

Validate on target hardware: API p95 below 300 ms at 150 concurrent users; ordinary light-load judging within 30 seconds; 150 representative submissions arriving over 60 seconds completed within five minutes of first acceptance. Measure timeout-heavy behavior separately. Correct grading, access control, isolation, and recovery are release prerequisites.
