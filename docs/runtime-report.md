# Docker Compose runtime verification

Executed successfully at 2026-10-15T17:45:48+00:00 using `python scripts/verify_runtime.py`.
All data are synthetic. Task/import/row operations used the authenticated live API.
Stack: this checkout's `batchflow` Compose project; PostgreSQL and two worker threads.
Observed worker configuration: lease 15 s; maximum 3 attempts.
Host/runtime recorded for this run: Docker 28.3, 8 logical CPUs, 16,731,451,392 bytes
of Docker host RAM; Python 3.12.15 and PostgreSQL 17.11 in the containers.

| Check | Observed result |
|---|---|
| HTTP input | 3,000 original rows; 2,400 unique identifiers; 600 duplicate identifiers |
| HTTP completion | 3,000 succeeded; each original ID and row position present exactly once |
| Ground truth | All seven fields checked against deterministic demo registry values |
| Source requests | 3,000, counted in demo-source access logs by unique run prefix |
| Attempts | Every HTTP row has exactly one committed attempt |
| Elapsed | 601.91 s from import/task creation through terminal-state polling |
| Observed throughput | 4.98 original rows/s over that measured interval |
| Worker memory | 135 Docker samples; min 46.45 MiB; median 58.74 MiB; sampled max 108.70 MiB |
| CSV and XLSX | Both exports checked for all 3,000 originals, order, statuses and seven output fields |
| Actual crash | SIGKILL of the resolved Compose worker, confirmed stopped, same container restarted |
| Recovery | 10 completed rows unchanged; 2 interrupted attempt(s) closed as lease_expired |
| Recovery duration | 35.80 s from kill through task completion |
| Real browser | Container Chromium filled calculator form and matched all seven expected fields |

The crash task deliberately includes two TIMEOUT identifiers (20 s source delay vs
10 s HTTP timeout). These exhaust the configured retry budget and correctly finish
as failed; all 18 normal rows succeed. Its expected terminal state is
completed_with_errors. Recovery uses the deployment's configured lease duration.

Docker memory values are the worker container's `docker stats --no-stream` samples,
not a process RSS peak or continuous maximum; short spikes can fall between samples.
This is a local controlled-source measurement, not an external-service SLA or a
claim about 3,000 browser rows. Verification API requests: 796.
Other Docker activity, including image builds, can compete for shared host resources;
this script does not require or establish an otherwise idle benchmark host.
During this measured run, the final application image was concurrently exported
and unpacked; this disk activity ended before the batch completed. The numbers
above describe this shared-host run and are not an isolated capacity benchmark.
Synthetic tasks remain available for inspection; the script does not delete data.

- HTTP task: `52ddecc1-849c-46a1-ab98-7ab4ff129ec4`
- Crash task: `1b348499-efac-47ac-99b9-d90881f65907`
- Chromium task: `613ebe57-c189-4e65-b2d8-0d4df2ae9792`
