# Product Requirements

Source of truth for cJudge v1 product behavior. M0–M14 are implemented; M15–M16 remain planned. The M9 physical LAN/offline release check remains. See [design.md](design.md) for organization and [technical-requirements.md](technical-requirements.md) for implementation constraints.

## Scope

An offline-operable LAN judge for C programming labs: one admin, with a performance baseline of 150 concurrent students total, five tasks, ten cases per task, and a two-hour lab. M16 will allow concurrent labs without a configured lab-count limit; current scheduling permits only one active lab. Installation and maintenance may use internet; running a lab must not.

Deferred: other submission languages, TAs/multiple admins, individual extensions, weighted cases, subtask groups, testlib, plagiarism detection, an in-browser editor, offline installation bundles, automated backups, server restoration, and archive import.

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
- Admin posts plain-text announcements; enrolled students can read public and their own private history after start. Lab time, PDF, problem, rejudge and result changes automatically announce the action and any supplied reason. Individual submission, freeze and binding actions notify only the affected student; admins see every notice and its audience.
- Use a common server-authoritative deadline. Allow whole-lab extensions and reopening before first release; never reopen after release, even if results are hidden again.
- Until M16, prevent overlapping labs globally. M16 replaces this with per-student overlap checks for enrollment and all schedule changes; see the planned requirements below.
- Accept one `.c` file up to 64 KiB only after complete upload, validation, and durable acceptance strictly before the deadline. Queued judging may finish afterward.
- Save each accepted submission's client IP and MAC address when available from a trusted LAN source. Admin review shows these values and flags changes across a student's submissions within the lab as possible PC switches, not proof. Missing MAC values display as unavailable and do not block submission.
- Enforce a 30-second cooldown across tasks and at most three pending submissions per student. Rejudge jobs do not consume upload slots.
- Configure independent sandbox instances through the environment. Admin's Isolates panel shows configured, healthy, and working counts, current work, heartbeat freshness, and faults.
- Show Queued, Judging, Passed/Failed, configured compile-error feedback, or Judging delayed. Compile-error feedback defaults to approximately 20 lines, with full/verdict-only options.
- During labs, expose no partial marks or hidden-case details by default; M14 adds optional partial-task passed/total counts. M10's optional scoreboard exposes live standings only when admin enables it.

## Navigation

- Separate lab overview, enrollment, assigned tasks, and submission review into meaningful pages. Keep reading and submission together on student task pages.
- Admin student pages combine lab controls and student history; admin task pages show assigned revisions and per-task submissions. Keep submission lists per lab, newest first, with student/task filters.
- Refresh, bookmarks, and browser history restore location and filters. Resume valid lab bindings without re-entering; warn before discarding unsaved forms or selected files.

## Grading and Corrections

- Partial score = maximum marks × passed cases / total cases. All-or-nothing awards marks only when every case passes. Compile errors earn zero.
- Count the best active submission by unrounded score; ties use earliest acceptance, then submission ID. Display two decimals with half-up rounding and sum displayed task marks for totals.
- Show admin attempts best to worst, separating pending/deleted attempts. Soft deletion requires a reason, excludes the attempt from marks, preserves evidence, and permits restoration. Students retain their own deleted rows with the reason and exclusion label; detailed evidence remains release-gated. Recompute marks on either action.
- Shade the newest highest-scoring active official attempt per student/task in admin and released student lists, labeled Best for review. This review preference does not change the earliest-tie rule for counted marks.
- No submission means zero; unresolved infrastructure failure means pending, never zero.
- Allow corrections during running or ended labs, including after release with a warning and audit reason; never reopen a released lab. Corrections publish a new revision and rejudge every active attempt for the affected lab task. Preserve earlier results and replace official marks consistently after completion. Support single-submission rejudges without changing grading configuration.

## Release and Exports

- Release manually after the lab ends; block release and final mark sheets while counted judging/rejudging remains unresolved. M15 excludes cancelled participation from this gate. Admins may retry or exclude affected attempts through audited soft deletion.
- After release with reveal enabled, show each active submission's source, marks, all retained grading runs, per-case verdicts, and failed-case inputs, expected outputs, and student stdout/stderr. Retain the first 64 KiB per stream/case and label truncation.
- Open submissions from history on a dedicated page with inline source and details. Admins can inspect submissions before release; students can inspect only their own after release while reveal is enabled. During labs, keep student histories limited to status and configured compiler feedback, except M14’s optional passed/total counts.
- Warn before revealing tests used by another scheduled lab. Admin controls release timing; hiding results cannot undo disclosure.
- Students access only their own private data, with no student access to network metadata or infrastructure diagnostics.
- CSV exports contain roll number, name, per-task marks/pass percentages, total marks, active submission count, and last active submission time. Percentages come from counted submissions.
- Explicit Archive after release freezes lab and grading edits; reveal and exports remain available.
- Lab ZIPs include lab PDFs, optional task Markdown statements, tests, configurations/revisions, all retained sources including deleted attempts, judge history, marks, and audit records. Export does not delete the lab; permanent deletion requires a current verified export, saved-copy acknowledgment, matching typed lab title, and audit reason. Global accounts and shared tasks remain. ZIPs are not full-server backups.

## M10 Lab Scoreboard

- Add a dedicated lab Scoreboard page, always available to admin. A persisted **Visible to participants** toggle defaults off, including existing labs. When enabled, enrolled participants see live standings before release, subject to existing lab-entry/binding checks.
- Include all enrolled students, including frozen students. M15 adds cancelled students as unranked rows at the bottom, excluded from totals and first-solve awards. Show rank, roll number/name, total marks, summed submission time, and one box per assigned task.
- Count each task's highest unrounded official score from non-deleted submissions; ties choose earliest acceptance, then submission ID. Match existing displayed task marks and total marks.
- Rank by total marks descending, then summed elapsed time ascending. Sum acceptance minus lab start only for positive-score counted tasks; exclude zero-score tasks and impose no failed-attempt penalty. Compare time without rounding; display `HH:MM:SS`.
- Equal total and time share a rank; order tied rows by roll number. Admin links open counted submissions; participants can open only their own, with existing release/reveal restrictions.
- Task boxes show marks and counted submission time. No graded submission is blank; queued/judging work without an official result shows **Pending**. Graded zero shows `0` on a neutral background.
- Use muted shades: partial positive score yellow; full score green; earliest current non-deleted full-score submission per task darker green. Resolve exact first-solve timestamp ties by submission ID. Provide status text and a legend.
- Pending judging/rejudging overrides the box color with blue; preserve prior official marks/time and label the row provisional. Delayed judging shows a warning. Recompute rankings and first-solve after deletion, restoration, rejudging or correction.
- Audit and publicly announce visibility changes. Archived labs preserve their saved visibility and remain read-only. Other students' code, test data and private notices remain inaccessible.

## Planned Improvements — M11–M16

M11–M14 are implemented; M15–M16 remain planned. Each module has its own test/review gate in [todo.md](todo.md).

### M11 — Roster and Credentials

- Add roster search, keyboard-accessible row selection, confirmed bulk password reset, and CSV credentials for selected students only. Nested controls do not select rows; select-all selects visible rows. Keep explicit selections across filtering and show the selected count.
- New/reset student passwords contain six random lowercase letters/digits. Do not rotate existing credentials automatically. Browser release also resets the global password and revokes all sessions; show the new credential to admin.

### M12 — Account Lifecycle

- Delete unused accounts with no enrollment/submission history; retain an audit identity snapshot. Deactivate accounts with history instead: revoke sessions and deny login while preserving marks and evidence.
- Provide inactive-account filtering and reactivation with a new password. Reserve deactivated roll numbers; imports must not silently reactivate accounts. Account deactivation and lab cancellation remain independent.

### M13 — Interface Readability

- Show the latest announcement and collapse older messages, preserving audience filtering and live updates.
- Use muted yellow for frozen roster rows and muted red for cancelled rows, with cancellation taking precedence. Keep scoreboard task colors and visible status labels.
- Color testcase verdict rows in admin and released-student views: AC green, WA/RE red, and time/memory/output limits yellow. Preserve accessible focus and readable text.

### M14 — Optional Early Feedback

- Add a per-lab, default-off toggle to show passed/total before release for partial-scoring tasks only. This intentionally reveals partial-score information; scoreboard visibility remains independent.
- Show official-result counts; no counts without an official result. During rejudge, retain official counts and mark them provisional. Source, testcase details, and test streams remain release/reveal-gated.
- Audit and announce toggle changes; archived labs remain read-only.

### M15 — Reversible Lab Cancellation

- Require an audit reason for cancellation/reinstatement; allow both until archive, including after release. Notify only the affected student; reasons remain private to student/admin.
- Preserve all submissions and existing deletion/freeze states. Cancelled students retain materials, announcements, and own history under existing access/reveal gates, but cannot upload.
- Exclude cancelled participation from counted marks, ranks, and first-solve awards. Show a muted red Cancelled row at the bottom of visible standings, without rank or counting total. CSV includes cancellation status without counted marks; archives retain evidence.
- Continue accepted judging, but cancelled-only unfinished work must not block others’ release or correction publication. Reinstatement queues any required current-revision judging and shows provisional results until resolved.
- Cancellation retains enrollment and reserves its time slot. Reinstatement does not unfreeze, restore individually deleted attempts, reactivate an account, extend time, or reopen a released lab. Future exports reflect corrections; downloaded exports remain snapshots.

### M16 — Concurrent Labs

- Allow concurrent labs with disjoint rosters and historical/non-overlapping enrollment for a student. Enforce conflicts during manual/CSV enrollment, scheduling, start-now, extensions, and reopening. Adjacent schedules are allowed.
- Reject conflicts with the student and conflicting lab/time identified. Draft enrollments are checked when scheduled; cancelled/deactivated students retain their enrollment reservations.
- Share the existing sandbox pool and fair queue. No configured lab-count limit; the performance baseline remains 150 concurrent users total, not a product enrollment cap. Higher capacity remains unverified.

## Success Targets

Validate on target hardware: API p95 below 300 ms at 150 concurrent users; ordinary light-load judging within 30 seconds; 150 representative submissions arriving over 60 seconds completed within five minutes of first acceptance. Measure timeout-heavy behavior separately. Correct grading, access control, isolation, and recovery are release prerequisites.
