# Design

Organization for the requirements in [product-requirements.md](product-requirements.md). M0–M5 are implemented; later modules remain planned. Technical constraints and unresolved contracts live in [technical-requirements.md](technical-requirements.md).

## System

```mermaid
flowchart LR
    Browser[Student / admin browser] -->|HTTPS| Nginx[nginx]
    Nginx --> Assets[Local frontend assets]
    Nginx --> API[FastAPI and SSE]
    API --> DB[(PostgreSQL)]
    API --> Files[(Protected artifacts)]
    Workers[Judge container: workers] --> DB
    Workers --> Files
    Workers --> Sandbox[isolate]
```

Docker Compose separates `web`, `api`, `db`, and runtime `worker`; standalone `judge` runs isolation gates without networking. The worker container holds an environment-configured process pool, with independent isolate boxes/cgroups/UIDs. PostgreSQL distributes fair leased jobs. The API owns authentication, lab policy, and admission; marks/release remain planned. Only web ports are public. Protected volumes hold artifacts; workers mount source/test data read-only.

Admin Isolates uses worker registration, startup sandbox checks, and heartbeat freshness rather than periodic probes. Admin SSE carries invalidations; stale workers become Offline locally even if updates disconnect. Student SSE refreshes admission/history without exposing hidden grading data.

Suggested backend boundaries: identity, tasks, labs, submissions, judging, results, and exports. Keep scoring and timing policy separate from HTTP handlers; keep sandbox management in worker-only code.

## Screens

Use a DOMjudge-inspired layout for both student and admin interfaces: compact navigation, dense task/submission tables, clear status labels, and a visible server-based lab countdown. Use a light theme and native form controls: consistent blue buttons, yellow notices/announcements, and red frozen/blocked states or errors. Keep labels and visible focus; do not rely on color alone. DOMjudge is a layout reference; exact visual matching and source-code reuse are not required. Retain React and Tailwind without adding a UI framework.

| Student | Admin |
| --- | --- |
| Login and binding-block explanation | Accounts, CSV import, credentials, binding release |
| Lab countdown, lab PDF links, and ordered task table | Lab overview, PDF uploads, common deadline, student table, progress |
| Optional task Markdown, file upload, submission history table | Task library, Markdown textarea/preview, test editor, generation review, revisions |
| Submission status and released details | Submission filters, best-to-worst attempts, deleted runs, judging faults |
| Optional solved-task scoreboard | Corrections, release, marks, archive export |

Use one login form with username/roll number and password. Detect `admin` automatically, case-insensitively; reserve that identifier from student roll numbers.

Keep the student path short: read, upload, check status. Explain disabled uploads with the actual reason: closed lab, cooldown, or pending limit. Server checks remain authoritative. Show infrastructure faults separately from student failures.

Store PDFs on the lab, not individual tasks. List all lab PDFs on the dashboard and link back to them from task pages. Omit empty task statements; render provided Markdown safely. Hide both document types until the lab starts.

Use readable layouts, labeled controls, keyboard-accessible navigation, visible focus, and text alongside status colors. Keep tables usable on narrow screens. Render source and diagnostics as escaped monospace text. Bundle assets locally. Preserve cJudge's grading and visibility rules: student views expose no partial marks or hidden cases before release.

Confirm destructive or grading-changing admin actions and show their effects. Collect required audit reasons. Separate archive download from permanent deletion.

### Page Organization

Navigation uses browser URLs, breadcrumbs, and lab sections. Refresh and Back/Forward retain the selected page; pagination, filters, and published revision selections use query parameters.

- Admin: global Labs, Students, Task Library, and Isolates. Each lab has Overview (settings, schedule, PDFs, announcements, compiler feedback), Students (enrollment), Tasks (assignments), and Submissions (newest first).
- Admin student detail: identity, binding/IP, freeze/release controls, and that student's lab submissions. Admin task detail: assigned revision statement/limits and task submissions; editing stays in the task library.
- Admin submission detail: `/admin/labs/:labId/submissions/:submissionId`, inline escaped source, download, current status/score, compiler feedback, case verdicts/resources/output previews, and IP/MAC. Available before release. Student own-submission detail and failed-case input/expected output are planned for M8, with server-enforced release/reveal authorization.
- Student: assigned labs, lab overview with PDFs/announcements/task links, task statement/limits/upload/task history together, and own lab submission history. Submissions stay per lab; no global submission page.
- Existing browser bindings resume through authorized reads. Creating a binding still requires explicit entry. Dirty forms warn before navigation; unconfirmed upload files/keys survive within the lab session. Reload requires file reselection and warns before discarding it. Credentials and sources are never stored in browser storage.

### UI Acceptance Checks

- Student: login → lab PDFs / optional task statement → upload → result; verify multiple PDFs and tasks without Markdown.
- Admin: task setup → lab management → review → release.
- Verify keyboard navigation, narrow-screen tables, countdown updates, and role-based visibility.

## Data Model

- Account, revocable session, and per-lab browser binding.
- Lab with versioned PDF attachments, announcements, frozen/bound enrollment, and ordered pinned task revisions.
- Reusable task with optional Markdown statement, immutable revision, and test cases.
- Submission with immutable source, acceptance time, and soft-delete metadata.
- Submission network snapshot: client IP, optional trusted MAC, MAC source/observation time. Admin attempt review displays addresses, unavailable MACs, and possible PC-switch flags across the student's lab submissions.
- Queue job/attempt with lease identity; judge run and case results tied to a revision.
- Rejudge batch, audit event, and export metadata.

A submission can have multiple judge runs. Store first-release history separately from current reveal visibility. Exact tables and schemas must be designed before implementation.

## Main Flows

1. **Submit:** receive/validate source, persist safely, enforce deadline/cooldown/backlog atomically, create submission and job, then acknowledge durable acceptance.
2. **Judge:** claim a lease, compile, execute every case in clean environments, check complete permitted output, and publish results only for the current attempt.
3. **Correct:** publish a revision, queue all affected active attempts, preserve prior results, and switch official marks together after the replacement batch succeeds. Define concurrent arrivals/deletions explicitly before implementing this transaction.
4. **Release:** verify lab closure and resolved judging, warn on test reuse, record first release permanently, and enable authorized details.
5. **Export:** use official marks for sheets and include retained history in archives; never implicitly delete data.

SSE prompts state refresh. Reconnect by fetching authoritative state; a dropped connection does not change grades or deadlines. Never show upload success without a confirmed submission record.

## Delivery Order

Follow [todo.md](todo.md) for module dependencies, milestones, and per-module test gates.
