# 150-Student Performance Recheck — Phase 1

Measured on Ryzen 5 7430U (6 cores/12 threads), 15 GiB RAM, three isolate instances, four API processes, PostgreSQL 17, verified HTTPS through nginx. Both runs used disposable volumes and five tasks with ten cases each. Normal services were restored. Raw results: [single lab](performance-2026-10-15-baseline.json) and [three labs](performance-2026-10-15-mixed.json).

| Metric | One lab × 150 | Three labs × 50, mixed | Target |
| --- | ---: | ---: | ---: |
| Read API p95, all four endpoints | 33.0 ms | 35.8 ms | ≤300 ms per endpoint |
| Slowest read endpoint p95 | 34.7 ms | 38.9 ms | ≤300 ms |
| Upload acceptance p95 | **5,902 ms** | 112 ms | ≤300 ms |
| 150 submissions judged from first acceptance | 64.6 s | 60.4 s | ≤300 s |
| Incorrect or lost submissions | 0 | 0 | 0 |

The single-lab run warmed histories, measured 18,000 reads over 120 seconds, then submitted 150 files over 60 seconds. Five light submissions took 0.64–1.06 seconds. Fifteen intentional timeouts finished in 18.0 seconds; their queue-delay p95 was 13.7 seconds. The mixed run also measured 18,000 reads, held 150 SSE connections, and submitted 150 files during the read window. Its read failure count was zero; each lab's 50 submissions completed within 20.3 seconds. Mixed queue-delay p95 was 45 ms and judging-duration p95 was 324 ms. Sampled peak CPU was 299% worker/259% API in the single-lab run, and 247% worker/234% API in the mixed run.

**Assessment:** read latency, judging throughput, and three-lab behavior pass. Single-lab upload acceptance exceeds the proposed 300 ms p95 endpoint limit, despite its legacy `passed: true` result; that legacy gate checks read latency, completion time, and light judging, but not upload acceptance. The two upload scenarios differ in lab distribution and client concurrency, so one run does not identify the cause. Reproduce the single-lab tail and inspect admission/database wait time before choosing an optimization. Do not change application code in phase 1.

This measures server-side HTTPS behavior on this machine. Physical LAN latency, browser rendering, and simultaneous saturation fairness across labs remain unverified.

## Matched Follow-up

The practical targets agreed after phase 1 are read API p95 ≤300 ms and upload acceptance p95 ≤1 second; <100 ms reads and <300 ms uploads are ideal. Both follow-up runs used the same images, three sandboxes, 150 upload threads paced over 60 seconds, 150 read clients, 150 SSE connections, and 18,000 measured reads. Three-lab uploads alternated between labs. Raw reports: [one lab](performance-2026-10-15-matched-single.json), [three labs](performance-2026-10-15-matched-three.json).

| Metric | One lab × 150 | Three labs × 50 |
| --- | ---: | ---: |
| Overall read p95 | 37.3 ms | 38.3 ms |
| Slowest read endpoint p95 | 40.8 ms | 46.1 ms |
| Upload acceptance p95 | 763 ms | 446 ms |
| Upload acceptance p99 | 2,314 ms | 1,230 ms |
| Accepted-to-result p95 | 2,194 ms | 817 ms |
| First acceptance to last result | 62.6 s | 61.4 s |
| Incorrect/lost submissions or read failures | 0 | 0 |

Client scheduling p99 stayed below 1 ms. Database sampling found no blocked queries in the single-lab run. The three-lab run sampled WAL sync waits up to 1.34 seconds and advisory/object lock waits up to 1.32 seconds. These are sparse five-second samples across warm-up and measurement, not proof of which operation caused each slow upload.

**Decision:** both matched runs pass the acceptable p95 targets; the original 5.9-second p95 did not reproduce. No application optimization is warranted from these results. Uploads miss the ideal target and p99 exceeds one second, so retain the tail measurements for comparison. If delays recur, investigate storage/commit latency with finer timing before changing locks or durability. Normal services were restored; no application code, database schema, sandbox count, or resource limit changed.
