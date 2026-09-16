# P5-R2 — OVC-P5-02 late receipt coherence

Status: **READY_FOR_REVIEW**, not external acceptance. P5 remains blocked until its external gate closes. P6, paid Providers and public deployment are not authorized.

Repository: `imherro/OurVideoCreator`, branch `master`; upstream MyVideoCreator not changed.

## Binding

- Actual base: `78fd14f40339e0b71908a685efb2354a0c1045ce` (P5-R1 independent evidence submission).
- Fixed tested business SHA: `aebffe364313601aceb611fbcd0ca2b01a42e29d`.
- Evidence HEAD is the subsequent docs-only commit containing this report; it is supplied in the review request, not fabricated inside a self-referencing commit.
- R1 backend business: `34d646d5c17d5ba12fdc56d4948ab513703731ff`; backend Git diff to R2 is empty, exit 0. No backend execution at R2 is claimed. R1's 473 backend / 10 concurrency results remain in their original evidence directory.

## Minimal chosen behavior: B, explicit conflict

ObjectDrafts keeps the acknowledged r2 body and revision paired. Observed r3 is retained separately for comparison; a later r2 echo cannot replace that cached r3. In-flight user typing is kept. A timer cannot issue a ticket for a conflict, and no automatic rebase/resubmit occurs.

CollaborationClient records the successfully committed r2 rows/baseline, then reports a local 409 conflict if this save's own tickets observed a newer snapshot. This is a client-generated conflict after a successful mock/server write, not a claim that the original HTTP response was 409. Unrelated conflicted objects do not block independent saveOnly on Y. The real host callbacks display 保存冲突; no success callback marks the page fully saved. Explicit discard adopts r3 before the next note save; explicit compare/keep-draft continues to obey server CAS.

The actual host integration also exposed old-scope errors changing a newly opened page's saved/dirty status. main.tsx now checks project ID, client identity and generation before applying success/error or saveObject-finally state. This covers reopening the same ID as well as switching to another ID. No protocol, backend, dependencies, lock scheme or SSE suppression changed.

Business files: `src/objectDrafts.ts`, `src/collaborationClient.ts`, `src/main.tsx`; tests: new `tests/p5_receipt_host.test.mjs`, updated `tests/owned_content_drafts.test.mjs`.

The shared chapter/script state machine now uses the same explicit-conflict choice. Its previous isolated test expected automatic r3 adoption. The replacement assertion is stronger, not deleted: r2 local body retained, r3 remote comparison retained, unsaved=true, automatic retry rejected, and explicit discard loads r3.

## Deterministic baseline red

Runtime was unchanged at base `78fd14f...`; only an untracked regression test was added. `baseline/final-note-baseline-test.mjs` freezes that test (copy it into `tests/p5_receipt_host.test.mjs` in a disposable baseline checkout to reproduce).

The strict test transport validates revision, epoch and ownership for the whole batch before mutation. It commits r2, copies the response, and delays only its delivery. A second actual CollaborationClient reads committed r2 and legally saves r3. First client receives r3 via real mergeRemoteRows and the actual host acceptObjectDocument callback, then receives r2. A note-only edit goes through the actual global save callback. The red log records **expected_revision=3 with action=v2, final server r4/action=v2**, demonstrating silent overwrite, not merely a mismatched draft assertion.

- Baseline runtime SHA above; frozen source SHA256 `18174b6d4d347f1ea8c0681602d3c37ec435daddebe5ca353c37228adb29faad` (raw working-tree bytes).
- UTC 2026-09-16T23:21:20.8193015Z–23:21:21.5639288Z.
- `node --test tests/p5_receipt_host.test.mjs`: **6 failed / 3 passed / 0 skipped**, exit 1.
- Output: `baseline/baseline-final-note-red.txt`; includes host document/status, client rows/baseline/draft, requests and final server state.
- Earlier valid 8-case red: 5 failed / 3 passed, exit 1. Earlier fixture-only failure is explicitly separated in ATTEMPT_HISTORY.md; none of the red results was overwritten.

## Fixed-SHA verification

Capture window UTC **2026-09-16T23:24:05.614Z–23:24:22.138Z**. Every command, start/end and exit code is in `commands-aebffe3/runs.json`; stdout/stderr are adjacent. All six commands exit 0.

| Check | Result |
|---|---|
| Actual host + client + state-machine + owned-content targeted set | 49 passed, 0 failed, 0 skipped |
| All default frontend tests | 195 passed, 0 failed, 0 skipped |
| TypeScript `tsc -b` | exit 0 |
| Vite build | exit 0, 1837 modules; existing large-chunk warning retained |
| Backend equivalence to fixed R1 business | no differences, exit 0 |
| Business diff whitespace check | exit 0 |

The host tests parse and transpile the actual three function declarations in main.tsx (save, saveObject, acceptObjectDocument); only React refs/setters are test substitutes. They execute actual adapter/state-machine/split/compose code, not a rewritten success/error branch. The extraction fails if callbacks are missing/ambiguous. This is **host callback integration with strict in-memory CAS**, not React DOM rendering, browser, HTTP, SSE transport or real PostgreSQL evidence. R2 adds no production debugging hook. Matrix maps all requested cases.

## Boundaries and resources

No R2 backend/full PG rerun, new browser run, real paid Provider, visual rendering, or end-to-end HTTP transport test was performed or claimed. Frontend/build changes are the only runtime changes; the backend equivalence check is the reason for not mechanically repeating R1's backend run. No legacy data migration or resources deleted. User 7868, retained 7895/6313/6185/7028 and prior P5 instances, databases, leases and browser drafts were not operated on by this test suite. Its two clients and server rows exist only in Node memory.

Review the new collaboration repository, close OVC-P5-02 only if verified, then decide the P5 gate. Focus on functional behavior and this minimal repair; do not add speculative architecture.
