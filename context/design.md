# Design

Organization for the requirements in [product-requirements.md](product-requirements.md). M0–M15 and M17–M26 are implemented; M19 code is complete pending physical network checks. M16 and M27 remain planned. Physical LAN/offline/mobile acceptance remains. Technical constraints and unresolved contracts live in [technical-requirements.md](technical-requirements.md).

## System

Current architecture: [database schema](../docs/schema.md), [Docker deployment](../docs/docker.md), and [network diagram](../docs/network.md).

Docker Compose separates `web`, `api`, `db`, and runtime `worker`; standalone `judge` runs isolation gates without networking. The worker container holds an environment-configured process pool, with independent isolate boxes/cgroups/UIDs. PostgreSQL distributes fair leased jobs. The API owns authentication, lab policy, and admission; release/export are implemented with shared grading and lab policies. Only web ports are public. Protected volumes hold artifacts; workers mount source/test data read-only. API and workers share writable `authoring_files` for protected staged generation and cached binaries. Student isolate processes cannot access this volume.

Admin Isolates uses worker registration, startup sandbox checks, and heartbeat freshness rather than periodic probes. Admin SSE carries invalidations; stale workers become Offline locally even if updates disconnect. Student SSE refreshes admission/history without exposing hidden grading data.

M23 adds TA accounts in the same identity database and `lab_tas` assignment rows. TA routes recheck active account, session, lab assignment, and archive state inside each transaction. Admin assignment edits and TA actions hold an exclusive lab lock; TA reads hold a shared lock, so removal cannot pass an in-flight authorization check. TA SSE carries scoped invalidations and rechecks access on every event and keepalive, including judging changes when the scoreboard is hidden. Assigned TAs see one student's automatic marks and submissions before release through scoped endpoints; accepted-case streams remain hidden. Admin lab/TA pages read assignment status, current penalties, and lab-scoped audit activity.

M24 adds TA maxima to lab assignments and student review claims with per-task earned fractions/completion flags. Authorized TA review responses include unsaved suggestions scaled from settled counted automatic results. One versioned transaction saves all filled marks; saved marks override suggestions. Lab-row locks and review versions serialize claims, saves, finalization, and admin transfers. Admin-only totals and CSV combine rounded automatic and TA marks; student responses and scoreboard remain automatic-only. Grading changes flag saved reviews for recheck and invalidate claimed drafts; TA maximum changes also invalidate claimed drafts. Archive v3 retains TA evidence; v1/v2 receipt verification remains compatible.

M25 adds optional identifier lists to immutable task revisions. A bounded scanner runs in the judge worker before isolate compilation; an empty list skips scanning. Restricted runs retain a matched name/line and zero score, and tester sources use the same scanner. New archive format v4 includes that evidence; older receipts keep their original snapshot shape.

M26 persists C11/C++17 source language from upload extensions. Task revision policies control admission; lab locks serialize correction narrowing with acceptance. Isolate compiles fixed GCC/g++ profiles. Authoring selects generator/reference languages independently. Task ZIP v2 transfers policy and lab archive v5 retains source language; legacy imports, artifacts and receipt snapshots remain compatible.

Suggested backend boundaries: identity, tasks, labs, submissions, judging, results, and exports. Keep scoring and timing policy separate from HTTP handlers; keep sandbox management in worker-only code.

## Screens

Use a DOMjudge-inspired layout for both student and admin interfaces: compact navigation, dense task/submission tables, clear status labels, and a visible server-based lab countdown. Use a light theme and native form controls: consistent blue buttons, yellow notices/announcements, and red blocked states or errors. M13 changes frozen roster rows to muted yellow; M15 uses muted red for cancelled rows. Keep labels and visible focus; do not rely on color alone. DOMjudge is a layout reference; exact visual matching and source-code reuse are not required. Retain React and Tailwind without adding a UI framework.

| Student | Admin |
| --- | --- |
| Login and binding-block explanation | Accounts, CSV import, credentials, binding release |
| Lab countdown, lab PDF links, and ordered task table | Lab overview, PDF uploads, common deadline, student table, progress |
| Optional task Markdown, file upload, submission history table | Task library, Markdown textarea/preview, test editor, generation review, revisions |
| Submission status and released details | Submission filters, best-to-worst attempts, deleted runs, judging faults |
| Own retained grading runs | Corrections, release, marks, archive export |

Use one login form with username/roll number and password. The server resolves admin, TA, or student from a globally unique case-insensitive username; `ADMIN` is reserved.

Keep the student path short: read, upload, check status. Explain disabled uploads with the actual reason: closed lab, cooldown, or pending limit. Server checks remain authoritative. Show infrastructure faults separately from student failures.

Store PDFs on the lab, not individual tasks. List all lab PDFs on the dashboard and link back to them from task pages. Omit empty task statements; render provided Markdown safely. Hide both document types until the lab starts.

Use readable layouts, labeled controls, keyboard-accessible navigation, visible focus, and text alongside status colors. Keep tables usable on narrow screens. Render source and diagnostics as escaped monospace text. Bundle assets locally. Preserve cJudge's grading and visibility rules: student submission views hide partial marks and cases before release by default; optional early feedback exposes partial-task passed/total and marks; admin may separately enable live scoreboard standings.

Confirm destructive or grading-changing admin actions and show their effects. Collect required audit reasons. Separate archive download from permanent deletion.

### Page Organization

Navigation uses browser URLs, breadcrumbs, and lab sections. Refresh and Back/Forward retain the selected page; pagination, filters, and published revision selections use query parameters.

- Admin: global Labs, Students, TAs, Task Library, and Isolates. Each lab has Overview (settings, schedule, PDFs, announcements, compiler feedback, TA assignment), Students (enrollment), Tasks (assignments), Submissions (newest first), and Scoreboard (ranked marks/times and participant visibility toggle).
- Admin student detail: identity, binding/IP, freeze/release controls, and that student's lab submissions. Admin task detail: assigned revision statement/limits and task submissions; editing stays in the task library.
- Admin submission detail: `/admin/labs/:labId/submissions/:submissionId`, inline escaped source, download, current status/score, compiler feedback, case verdicts/resources/input/output previews, and IP/MAC. Inputs come from the pinned immutable revision. Available before release. Student `/labs/:labId/submissions/:submissionId` shows own source and retained grading runs after release with reveal enabled; failed-case previews enforce server authorization and size limits.
- Student: assigned labs, lab overview with PDFs/announcements/task links, task statement/limits/upload/task history together, own lab submission history, and Scoreboard when enabled. Submissions stay per lab; no global submission page.
- TA: assigned labs including released archives, bounded roll/name search, compact student status/actions, and released student submission details. Pre-release status omits verdicts, marks, source, and cases. Archived labs are read-only.
- Existing browser bindings resume through authorized reads. Creating a binding still requires explicit entry. Dirty forms warn before navigation; unconfirmed upload files/keys survive within the lab session. Reload requires file reselection and warns before discarding it. Credentials and sources are never stored in browser storage.

### Scoreboard

`labs.scoreboard_visible` defaults off. Admin and participant scoreboard routes share official-result selection and a table component. GET endpoints use consistent database snapshots; participant authorization checks enrollment/binding and visibility, returning submission links only for the viewer's own work. Rank by displayed total descending, then exact summed elapsed time of positive-score counted tasks ascending. Pending work retains official marks and uses blue provisional boxes; first-to-solve derives from current non-deleted full-score attempts. Admin toggles are version-checked, audited and announced; archived visibility is read-only.

Reuse the lab SSE connection for participants and admin SSE for admins. Acceptance, judging and review changes invalidate visible standings; SSE transmits no scores or private evidence. Manual refresh and reconnect fetch authoritative snapshots without periodic polling.

### UI Acceptance Checks

- Student: login → lab PDFs / optional task statement → upload → result; verify multiple PDFs and tasks without Markdown.
- Admin: task setup → lab management → review → release.
- Verify keyboard navigation, narrow-screen tables, countdown updates, and role-based visibility.

## Data Model

- Globally named admin/student/TA account, revocable session, per-lab TA assignment, and student browser binding. Enrollment retains the acting account for active freeze/cancellation flags.
- Lab with versioned PDF attachments, public/private announcements, frozen/bound enrollment, and ordered pinned task revisions with lab-owned automatic maxima. Admin changes automatically announce their effect and supplied reason; individual actions address only the affected student.
- Reusable task with optional Markdown statement, immutable revision, and test cases.
- Submission with immutable source, acceptance time, and soft-delete metadata.
- Submission network snapshot: client IP, optional trusted MAC, MAC source/observation time. Admin attempt review displays addresses, unavailable MACs, and possible PC-switch flags across the student's lab submissions.
- Queue job/attempt with lease identity; judge run and case results tied to a revision.
- Rejudge batch, audit event, and export metadata.
- Generation job, leased attempts, checkpointed cases, and retained source/seed/hash provenance.

Official automatic marks recompute from retained pass counts, revision scoring rules, and the current lab-task maximum; runs retain their original score fraction. Archived legacy labs keep their original official scores and v1 archive receipts. Submissions retain immutable evidence. `submission_reviews` holds deletion state and official-run pointers; `judge_jobs` holds current work while attempts/runs retain history. `correction_batches` and `correction_members` stage atomic replacements. First-release history, current reveal visibility, and explicit archiving remain separate states. `lab_exports` holds verified snapshot receipts; `lab_cleanup_files` retains cleanup work after permanent deletion.

## Main Flows

1. **Submit:** receive/validate source, persist safely, enforce deadline/cooldown/backlog atomically, create submission and job, then acknowledge durable acceptance.
2. **Judge:** claim a lease, compile, execute every case in clean environments, check complete permitted output, and publish results only for the current attempt.
3. **Correct:** publish a revision, queue all affected active attempts, preserve prior results, and switch official marks together after the replacement batch succeeds. New uploads target the correction revision; active existing attempts form the publication gate. Deleted members do not block, and restoration adds missing work. Lab locks serialize acceptance, review changes, and publication.
4. **Release:** verify lab closure and resolved judging, warn on test reuse, record first release permanently, and enable authorized details.
5. **Export:** use official marks for CSV and include retained history in verified ZIPs. Explicit Archive locks edits; permanent deletion separately requires a current saved archive.

Generation uses the existing worker pool after submission/rejudge work. Each seed checkpoints one case and yields. Admins preview staged results and explicitly append to cases in an unchanged draft; publication remains a separate immutable operation. Python checker helpers run in a separate checker sandbox with input, complete output, and answer bytes.

SSE prompts state refresh. Reconnect by fetching authoritative state; a dropped connection does not change grades or deadlines. Never show upload success without a confirmed submission record.

## Planned Improvements — M11–M16

- **Accounts:** extend the existing roster with search, row selection, selected credential actions, and active/inactive filtering. Explain global session revocation before reset/browser release. Keep account lifecycle separate from per-lab penalties.
- **Lab pages:** keep the newest announcement visible with older messages collapsed. Add early-feedback settings to overview and cancellation/reinstatement controls to student detail. Show status text with muted row/verdict colors; retain task-box grading colors.
- **Data:** add account activity, enrollment cancellation metadata, and a default-off early-feedback setting. Preserve immutable submissions and independent freeze/deletion states. Cancelled scoreboard rows remain visible but unranked; reasons never enter public standings.
- **Flows:** cancellation excludes participation from counting and publication gates without deleting evidence. Reinstatement reconciles current grading before final results. Account deactivation independently revokes access and preserves marks.
- **Scheduling:** replace global overlap exclusion with per-student conflict checks across every enrollment/schedule mutation. Keep one shared sandbox pool and fair queue; no additional service or queue partition.

## Delivery Order

Follow [todo.md](todo.md) for module dependencies, milestones, and per-module test gates.

## Planned Architecture Changes — M17–M27

Agreed decisions: [improvements_v2.md](improvements_v2.md); implementation gates: [todo.md](todo.md#m17--architecture-documentation--independent). The system diagram above describes current architecture.

Reuse existing web/API/PostgreSQL/artifact storage and isolate workers. M17 adds linked schema, Docker and network documents under `docs/`; M19 supports validated localhost/multiple LAN addresses. M20 moves current automatic maxima into lab assignments while preserving historical evidence. M21 transfers published task settings/checker/cases through bounded ZIPs; M22 adds separate admin tester jobs/history through the existing pool. M23 adds assigned-lab TA authorization, mobile student lookup, and operation ownership. M24 adds review claims/marks while student responses and scoreboard remain automatic-only. M25–M26 extend immutable task policy and sandbox language profiles. M18/M27 extend access and existing interface flows.

No new runtime services, polling, or student-program host execution. Refresh diagrams as modules land; planned features must not appear as deployed components.

### M18 Access and Roster Removal

Archived student access is denied in shared authorization, including revalidation of existing SSE. Student views discard materials/upload drafts and refresh the assigned list on denial. Admin archive review remains available. Before start, roster checkboxes retain selections across search, select-all affects visible rows, and CSV preview resolves rolls to current identities before confirmed atomic removal. Lab version/locks fence stale previews and competing starts; removal does not alter global accounts or other labs. No schema change is required.
