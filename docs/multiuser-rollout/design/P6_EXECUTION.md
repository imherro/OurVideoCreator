# P6 execution boundary map — implementation in progress

> Historical, superseded scope: P6-SINGLE-01 now governs execution. The platform
> plan below is retained for provenance, not authorization or completed behavior.
> See ../prompts/P6_SINGLE_01_CODEX_PROMPT.md and deferred/p6-platform/README.md.

Authorized task: P6-JOBS-01. Base `afd1eb0d3eed36b3dcd818ed0c29aec2989c2259`. P5 external PASS originals in reviews/P5-R2; no P7, public deployment or paid Provider authorization. This document is a plan mapped to inspected code, not a completion claim.

## Boundaries observed at the P5 baseline (not completion claims)

- worker.py start owns a database-wide WorkerAdvisoryLock and resets every running row; _loop selects queued rows SKIP LOCKED but has no task lease/token. P6 must replace both assumptions together, not merely allow the second process.
- store.job_update, attach_provider_job_id, cancelled_phase and providers.common.register currently write without an attempt token. The protocol adapters reach these same helpers; legacy Maestro/Comfy/video_api/Minimax/Replicate also attach handles through job_update.
- app.create_job_record checks globally unique submission_id before target validation; it freezes P4 binding and P5 collaboration target in the creating transaction, but has no quota plan. Batch endpoints reuse this function. Scope/actor/entrypoint keys and atomic reservation must be applied centrally without weakening batch rollback.
- platform_models.check_job_call runs at authenticated egress and rechecks P4 enable/revocation; it currently lacks full P6 actor/target/attempt/step/quota validation. HTTP POST is not itself a billable-step classifier (RunningHub query is POST; uploads and HC asset registration are separate side effects).
- Current resume can requeue a no-handle interrupted job; P6 must distinguish proven unsent from possibly accepted, rather than equating no handle with safe resubmission.
- Current result registration chooses a new asset UUID on each attempt. P6 requires persistent output identity and finalization-only recovery; successful/paid work must not be regenerated after download/registration failure.

## Intended state, side effect and accounting table

Public job.status can remain queued/running/interrupted/succeeded/failed/cancelled. A separate execution phase records the following facts; exact schema remains under implementation.

| Execution phase | Admission/transition guard | New fee possible | Recovery and counts |
|---|---|---|---|
| queued | Scope+actor+input hash, fixed target and binding; reserve planned units in same transaction | No | Original quota date; queue age expiry/unsent cancellation releases reservation |
| claimed/preflight | Current attempt + DB-clock lease; current permissions/model/pause; short transactions only | No | Expired unsent attempt may safely be replaced; local slot distinct from remote |
| submitting | Current attempt, named step, reserved units and remote capacity persisted before send | Yes | If no durable outcome after loss, unknown; never automatically POST twice |
| submission_unknown | Prior send may have reached provider | Possibly already charged | Keep remote occupancy and submitted units; admin evidence-based reconciliation |
| remote_running | Known original handle + fixed original credential/config | No new generation | Reclaim expired local lease, query original handle, never change account or input |
| finalizing | Durable generation outcome, current attempt; download/registration output identity | No new generation | Retry only bounded download/probe/register; unique output prevents duplicate asset |
| succeeded | Current attempt + persisted result/candidate | No | Release local/remote concurrency; retain submitted daily units; never adopt content automatically |
| cancelled/failed | Distinguish unsent, confirmed remote terminal, still-running/unknown | Depends on prior send | Local cancellation is not remote cancellation; remote count remains until trustworthy terminal evidence |

Lock order must be explicit before adding quota writes: current identity barrier, stable resource keys, then job/attempt rows, then result/asset and event publication. No transaction holds a network/FFmpeg wait. Multi-resource acquisition uses a consistent sort order. Fencing prevents late local writes, not already dispatched network requests; no exactly-once promise.

## Provider recovery inventory to finish before adapter integration

Inspected actual call sites confirm synchronous text/Speech/image generation, async task handles for supported media adapters, RunningHub POST polling, and HC registration side effects. The full per-adapter implementation inventory is still being read; do not treat a protocol capability from the old P0 table as verified upstream idempotency. Only existing documented/implemented stable keys may be retained; other submission windows stay conservative unknown.

### Inspected call boundaries (P6 working tree, 2026-09-17)

This table describes repository code, not independently verified upstream guarantees. Each generation submission still needs explicit named-step integration; HTTP method alone must not classify charges.

| Adapter path | New generation / extra side effect | Recovery and separate finalization |
|---|---|---|
| Worker text, including Ark/HC/RunningHub text | Streaming chat/completions POST. Film Bible uses visual_bible and bound_storyboard, with distinct repair steps if validation fails. Generic storyboard has one possible repair. | Persist complete text before validation; replay completed steps without another POST. Partial stream plus no terminal checkpoint remains unknown. Dynamically reserve repair before calling it. |
| OpenAI-compatible image / Ark image / HC synchronous image | images/generations POST, potentially multiple output units in one request | Persist response list before downloading/decoding/probing/registering; slot identity distinguishes even identical requested images. |
| Volcengine speech | One streaming POST per line/job, audio bytes arrive in events | Persist terminal audio outcome before probe/register. No response does not prove unsent. |
| Ark video | POST contents/generations/tasks; GET original task; DELETE is a cancellation request, not confirmation of free work | Original handle/credential only. Success URL precedes download. Legacy fixed-dialogue mux and pre-submit reference-audio compilation use additional FFmpeg calls that must share local CPU-slot accounting; these currently use subprocess.run and still need integration. |
| HC async image/video / Seedance v3 | Separate generation POST, GET original task, DELETE cancellation request | Existing _post_task retries transport failures with Idempotency-Key. Header presence and its fake test are NOT proof of upstream deduplication; automatic retry must be disabled unless a verified contract is established. Group creation, asset creation and detail polling are distinct from generation. |
| RunningHub image/video | media/upload/binary POST uploads reference; model-specific POST generates; openapi/v2/query POST only polls | Persist original task ID; no second generation after known handle. Upload side effects must not be mistaken for a generation quota unit. |
| MiniMax | video_generation POST; query/video_generation GET; files/retrieve GET | Persist original task ID then file/download descriptor, never replace account or restart generation to redownload. |
| Replicate | Prediction POST; prediction GET; cancel POST | Persist original prediction and terminal output before parsing text/storyboard or registering media. Cancel request is not proof of remote termination. |
| Retained Maestro/Comfy/generic video adapters | Catalogue/defaults/uploads/preparation are distinct from generation submission | Preserve existing capability restrictions; handle writes use the shared guarded helper. No new enabled model/protocol or paid test is implied. |

Unverified upstream submission-idempotency semantics remain conservative unknown. No real Provider was called to establish this inventory.

## Implementation sequence within this one authorized stage

1. Deterministic baseline red tests and new isolated PG resource manifest; task lease/attempt/fencing unit and independent-process integration.
2. Atomic scoped idempotency, planned steps, original-day reservations, queue/concurrency/pause and fair scheduling.
3. Adapter send/query/finalize boundaries; every Worker write guarded; HC mapping DB coordination; fault injection with fake request ledger.
4. Existing admin and task UI with real authorized endpoints, narrow browser verification; complete PG/P4/P5/frontend regressions.
5. Fixed business SHA and independent evidence; external P6 review. Never label steps 1–3 complete P6.

## Development checkpoint 2026-09-17 07:42 local

- Working base remains afd1eb0. P5-R2 original review and P6 prompt downloaded/read; checksum verification uses the downloaded original list. No business commit or push for this unfinished P6 foundation yet.
- New cluster only: `<TEMP>/ovc-p6-pg-20260917`; PostgreSQL 18.6 binaries reused read-only from `<TEMP>/ovc-pg18/pgsql/bin`; listener **127.0.0.1:55436**, postmaster **PID39832** verified. Dedicated local test role `ovc_p6_test`, trust authentication restricted by listener to loopback, no real accounts/data/keys. This is not a production security configuration. Existing 55432/55434 clusters and all historical Web/Worker instances remain untouched. No public listener/firewall change.
- Tests use OVC_TEST_ADMIN_URL for this new cluster's postgres admin database, then existing tests/postgres_test_db.py creates a unique ovc_test_* DB per pytest session and drops only its own exact active DB. No prior databases were deleted. Keep new cluster available for remaining P6 tests; do not bulk kill/drop anything.
- Baseline runtime afd1eb0 + new tests/test_p6_worker_processes.py: UTC23:39:45.6774209–23:39:53.5499671, **1 failed / 4.61s / exit1**. First real Worker PID18776 started, second PID4488 exited2 due to existing exclusive PG Worker lock. Both exact test-owned Popen handles terminated/reaped; logs `<TEMP>/ovc-p6-pg-20260917/baseline-two-workers.txt`. Not a fake lock failure.
- Foundation migration `0007_job_attempts` and backend/job_execution.py added but **not wired to Worker/store/providers yet**. Database readiness head updated; migration only run on new throwaway test databases, not historical running services.
- tests/test_p6_execution_leases.py: **5 passed / 5.89s / exit0**, UTC23:41:09.8507804–23:41:18.3476576; actual PG concurrent connections, live heartbeat, stale lease/token, unknown send and known handle recovery. Log `<TEMP>/ovc-p6-pg-20260917/lease-foundation-first.txt`. These are primitive tests, not finished Worker/fault/quota evidence. Full independent Worker regression remains red until integrated.
- Next: finish reading adapter execution sections, add deterministic staged-write/fake request tests, connect current-attempt context to every Worker-reached state/handle/asset/HC write, add explicit persisted send/finalize steps and quota admission. Only remove database-wide exclusion/startup reset after replacement guards are actually in use. Need complete scheduler/limits/idempotency/admin/UI/browser/full regression before fixed SHA delivery.
- No subagents requested/used. CUA main review tab remains p5Reviewer/tab1; current reply finished PASS, no pending send. Do not resend R2. Prior P5 harness sessions/resources remain preserved.

## Development checkpoint 2026-09-17 07:53 local

- Still uncommitted P6 work on base afd1eb0; no final business SHA or READY_FOR_REVIEW claim. Only the new 55436 cluster is used. Do not apply its changing migration to historical services.
- Store progress/result/handle/cancel-phase writes and common asset registration now validate current attempt inside each write transaction. API control cancellation has a narrowly checked bypass, not a general result-write capability. Tokens are omitted by default from unpacked job/API responses.
- Every Worker-scoped HTTP hop now checks the current lease, including credential-free download/redirect transports. This guard does not claim to revoke an already dispatched request. HC mapping/group writes are guarded, but cross-process HC registration coordination is **not yet implemented**.
- Legacy job_update(handle) now shares the monotonic handle helper: cannot replace an original handle; cancellation racing a received handle retains it. FFmpeg execution uses a unique temporary directory per invocation and reaps only its own Popen child even when lease checking raises. Ark's separate subprocess.run helpers still need the same lifecycle/slot treatment.
- Added job_steps primitives: immutable named units, canonical effective-request hash, persisted submitting/accepted/completed/unknown checkpoints, atomic original-handle checkpoint, and no replay of unknown submissions. They are **not yet wired to admission reservations or production adapter send boundaries**. Real PG tests cover original-handle recovery and completed first step followed by unknown second step.
- Added job_outputs with unique (job_id, output_key) identity and per-output content hash, inserted atomically with the asset. Replaying a current-attempt checkpoint reuses the existing asset; different ordered slots may contain identical bytes. Changed bytes at an existing slot fail rather than replacing the original. Adapter checkpoint replay still needs full runtime integration.
- Regression sequence retained under `<TEMP>/ovc-p6-pg-20260917`: `unguarded-writes-red.txt` 5 failed; `guarded-writes-first.txt` 10 passed; `guarded-writes-expanded.txt` 13 passed; `egress-handles-red.txt` 8 failed; `egress-handles-first.txt` 57 passed/47.40s (P6 + P4 model foundation); `steps-first.txt` 28 passed/25.89s, UTC23:50:08.5914801–23:50:37.6035827; `output-identity-red.txt` 2 failed; `output-hc-export-first.txt` 44 passed/46.71s, UTC23:51:53.2257197–23:52:42.6344861. Red failures were the asserted missing protection/duplicate identity, not environment failures. These working-tree development logs are not final fixed-SHA evidence.
- Broad real-PG backend regression launched UTC23:52:52.5939727: `python -m pytest -q --ignore=tests/test_p6_worker_processes.py`, output `foundation-backend-regression.txt`, exec session39026. The independent two-Worker baseline is explicitly excluded because runtime still owns the P5 global lock; that known red is **not waived**. Check completion before reporting results.
- At UTC23:55, the broad run had reached 14% with no reported failure; this is progress only, not a pass result. Its owned database is `ovc_test_34044_6e5d5e981ef6` on the new cluster. A read-only activity check showed active work, no lock wait; leave it running and resume session39026. `compileall` for backend/new migration/P6 tests and `git diff --check` passed (only repository CRLF conversion warnings). The existing P1 real-process test still expects a second Worker refusal; replace that assertion with the authorized P6 behavior while preserving Web/Worker separation and exact process ownership when scheduler integration is ready.
- Remaining required P6 work: atomic scoped admission/idempotency + quota/reservations; permission checks per new paid step; named adapter send/finalize integration; task-level Worker scheduler/heartbeat/fairness replacing global lock/reset; remote occupancy + HC unique unknown-state coordination; admin/user endpoints and UI; two-process fake fault ledger, browser and full final regressions. Do not enter P7 or request P6 acceptance for the current foundation.
