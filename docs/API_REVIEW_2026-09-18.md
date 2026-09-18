# Background API review — September 18, 2026

Scope: v3-base facade, REST transport, endpoint/request/response contracts, and their
capture-router consumers. An independent background agent reviewed the code and
used offline MockTransport reproductions. No new broker request or mutation was
made during this review. Production code remains unchanged.

## Findings

### High: successful pending-order edits become uncertain in the capture router

`src/matchtrader/endpoints/edit_pending_order.py:16` has no response model.
A successful empty response returns `None`; a JSON response remains a dictionary.
`src/matchtrader/capture/router.py:156` accesses `result.status` unconditionally.
That raises an exception, marking the trade uncertain and blocking subsequent
managed actions even when the broker accepted the edit.

The capture tests mock edit responses as `Operation(status="OK")`, unlike the
real SDK contract. Add an SDK-to-router integration regression covering empty
success, then normalize the contract and use read-back to resolve the edited state.

### Medium: implicit account selection can change during refresh

`src/matchtrader/core/rest_connection.py:125` accepts the only account in a login
response when no account ID was configured. Refresh calls that same adoption path
at line 201 without pinning the previously resolved account.

Offline reproduction: initial login with sole account 123, followed by refresh
with sole account 456, changed the connection's selected account and credentials.
Pin the resolved account for the connection's lifetime and add a refresh mismatch
test. The verified GooeyTrade test specified its account explicitly, so its exact
account check already protects it from this implicit-selection case.

### Medium: ambiguous writes do not consistently raise UnknownOutcomeError

`src/matchtrader/core/rest_connection.py:96` uses ordinary `APIError` for HTTP 5xx;
line 99 returns `None` for an empty body. `src/matchtrader/endpoints/base.py:54`
turns invalid modeled responses into `ProtocolError`, including write responses.

Offline reproduction: pending creation receiving 502 raised `APIError`; HTTP 200
with `{}` or no body raised `ProtocolError`. These outcomes do not establish that
the broker failed to execute the order. Consumers that reconcile only when they
catch `UnknownOutcomeError` could handle them incorrectly.

Classify post-submission ambiguity consistently, preserving endpoint-specific
documented empty-success contracts. Add tests for 5xx, unusable acknowledgements,
one transmission only, and reconciliation requirements. The SDK currently does
not automatically replay writes; the capture router also treats post-send
exceptions conservatively, limiting the immediate effect.

## Strengths and validation boundary

Explicit account matching, account-scoped leases, write gates, bounded read
renewal, no automatic mutation replay, positive/finite request quantities,
exact-ID cancellation, and sanitized transport errors are already present.

The successful demo create/cancel/readback path is documented in
[ORDER_BASELINE.md](ORDER_BASELINE.md). Its cancellation response included both
`status: OK` and `errorCode: UNKNOWN_ERROR`; the broker read-back supported the
successful cancellation result. That observation does not generalize to every
response, broker, endpoint, fill or position lifecycle.

Baseline verification: 114 offline API/core/model/endpoint/CLI tests passed,
including the added submit/cancel/readback regression. Ruff passed across
`src`, `tests`, and `scripts`. These findings are documented, not fixed in this
baseline checkpoint.
