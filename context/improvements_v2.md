# Improvements v2 — Agreed Plan

Checklist: [todo.md](todo.md#m17--architecture-documentation--independent). M17, M18, and M20 are complete; M19 code is complete pending physical network checks. M21–M27 remain planned. M16 remains pending. Work one module at a time with small tested commits and review at each gate.

## Documentation — M17

Add `docs/schema.md`: every table, primary/foreign keys, and relationships in a minimal Mermaid diagram. Add `docs/docker.md`: all services, worker pool, volumes, networks, startup/shutdown. Add `docs/network.md`: browsers, TLS/proxy, API/SSE, private services, workers. Link from README/design rather than duplicating diagrams. Separate current architecture from planned changes.

## Lab Access and Enrollment — M18 (implemented)

Hide archived labs from students and deny direct access to URLs, APIs, protected files, submission details, scoreboard, and events. Admin retains archive access.

Remove enrollments individually, by selection, or CSV **before start only**. CSV identifies students by normalized roll number (`roll_number` or `roll_number,name` headers; names ignored), up to 1 MiB/1,000 rows. Preview current identities and reject invalid batches atomically. Stale preview versions require a fresh upload. Preserve scheduled-lab last-student protection. Removal never deletes global accounts. After start use cancellation.

## Network — M19

Support localhost without external connectivity and simultaneous Wi-Fi/Ethernet access. Listen on configured interfaces; explicitly allow localhost/LAN hosts. Use relative links and validated HTTPS request origins instead of one canonical IP. Preserve CSRF, secure cookies, TLS, and trusted-proxy rules. Document certificate coverage and interface changes. Different addresses have separate browser sessions; strict-IP binding still applies.

## Lab-Owned Marks — M20

Automatic maximum marks belong to lab-task assignments; task revisions retain scoring rules, not a maximum. Require marks on assignment. Backfill existing assignments from current revisions while preserving historical runs/configuration, archived results, and verified export receipts.

Until archive, admin may change maxima with an audited reason and announcement. Recompute current automatic marks from retained outcomes without rerunning code. Update official displays, best-attempt selection, totals, scoreboard, CSV, and archives consistently. Preserve exact fractions and half-up display rounding.

## Task Transfer and Tester — M21–M22

Export one selected published revision in a versioned task ZIP: statement, configuration, cases, and associated generator/reference/checker scripts. Import into a new draft without overwriting tasks, transferring lab/student data, or automatically executing imported scripts.

Admin tests published revisions using one source or a ZIP batch, without labs/student submissions or student cooldown. Reuse isolated workers; show source, diagnostics, case streams, verdicts, and pass counts/percentages. Default batch cap: 20 sources, 16 MiB compressed, existing per-source limits; bound expanded archives and outstanding work. Keep separate tester history until explicit admin deletion. Tester work never affects marks, scoreboards, or lab exports.

## TA Access and Operations — M23

Admin creates TA accounts and assigns labs. Use unified login with server-enforced permissions. Mobile-first flow: select lab, look up student, inspect compact status, perform permitted actions. Avoid full roster/detail tables. TAs may inspect released evidence in assigned labs; students can show their code on their own screen while TAs record marks on their own phones.

Until archive, TA may freeze/unfreeze, cancel/reinstate, and release browser bindings. Only acting TA or admin reverses freeze/cancellation; show actor to authorized TAs/admin. Existing reason, audit, private-announcement, password-reset, and session-revocation rules apply. TA cannot change scheduling, tasks, enrollment, release, grading corrections, or main settings.

TA may explicitly reveal the selected assigned student's current password. Audit access without logging passwords; return no-store responses. No bulk credential export or access outside assigned labs.

## TA Review Marks — M24

Admin sets a separate TA maximum per lab task, default disabled. Marking starts after release. TA claims a student, saves task marks and explicit Done flags (including zero/no submission), then finalizes when every TA-enabled task is Done. Reject competing claims/saves transactionally.

Other TAs see reviewer/completion but cannot overwrite. Original TA or admin may reopen finalized reviews. Owner may release unfinished claims; admin may transfer them, retaining saved marks/audit history.

Admin sees remaining reviews and automatic/TA/combined totals. TA marks add to automatic marks for admin totals/exports, but remain hidden from students and do not affect scoreboard. Cancelled students are excluded from review requirements/totals; retain prior review evidence. Freeze alone does not exclude marks.

Maximum changes scale awarded TA marks from stored earned fractions, avoiding repeated-rounding drift; display half-up to two decimals. Zero maximum disables marking only if no reviews exist. Rejudge/deletion retains TA marks/completion and flags Needs recheck; admin chooses whether to reopen. Archive may contain incomplete reviews and locks further changes.

## Source Restrictions and C++ — M25–M26

Task revisions may ban exact, case-sensitive C/C++ identifier tokens, excluding comments and string literals. Scan before compilation. Retain rejected student source with **Restricted source**, zero automatic marks, matched identifier/line; do not compile/run it. Apply to judging, rejudging, and tester sources. Teaching rules have bypass limitations and are not a sandbox security boundary.

Task revisions allow C11, C++17, or both; existing tasks default C11. Store explicit submission language. Add sandboxed C++17 compilation and generator/reference support; extend tester, task ZIPs, rejudge, diagnostics, and archives. Never run submitted or authoring programs directly on the host.

## UI — M27

Add independent frozen/cancelled filters to admin roster only, preserving search/URL state. Add student top-bar quick-submit dialog with task/file selection, reusing upload retries, idempotency, cooldown, deadline, binding, freeze, and cancellation checks. Preserve mobile/keyboard accessibility.

## Acceptance

Each module includes necessary migrations, API/UI changes, documentation, and meaningful tests. Preserve outstanding M9 physical LAN/offline acceptance and 150-total-user baseline. No new services, automatic backups, full task-history transfer, or bulk TA credentials are planned.
