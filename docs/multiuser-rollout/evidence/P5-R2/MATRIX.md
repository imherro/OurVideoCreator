# P5-R2 verification mapping

All rows refer to fixed aebffe364313601aceb611fbcd0ca2b01a42e29d; tests are strict mock CAS + actual callbacks, not browser/HTTP.

| Required behavior | Executable evidence |
|---|---|
| r2 committed, r3 remote, late r2; note-only cannot overwrite | `p5_receipt_host`: final note test logs all state and requests; four full/only × typing/no-typing cases |
| In-flight input remains available for compare | Four cases assert host note and draft.remote r3, status conflict; no additional request |
| Own r2 echo is normal | Own echo test: saved, no conflict, exactly one request |
| Receipt before remote, old reads monotonic | Own echo test then normal r3; older-echo cached-r3 test; existing client late-full-read regression |
| Save X plus remote Y | Actual second client modifies Y, actual host receives it; baseline Y retained, no echo write |
| Independent saveOnly Y despite X conflict | Actual host saveObject('shot-y') succeeds and X conflict stays |
| Scope isolation | Full/only × different/same ID generation: late receipt cannot change new host status/body/draft |
| Assignment epoch | Reassignment management event increments rev+epoch; late ack conflict, keep rejected, discard then former-owner save rejected |
| Explicit accept/discard | r3 adopted, then note-only r4 retains v3 action |
| Explicit compare/reapply | Additional real second-client r4 defeats stale r3 CAS; typed draft retained |
| Shared owned-content consumer | Chapter test retains r2 body+r3 compare, no timer resend, explicit discard r3 |
| Existing features | Entire default suite 195 passed: structural adapter, lease, candidate and existing editor tests retained |

No tests skipped. Original R1 backend and browser evidence remains untouched.
