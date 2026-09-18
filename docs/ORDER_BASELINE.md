# Verified pending-order baseline

The baseline is the existing `MatchTraderAPI` facade and its account-scoped REST
connection, request models, and individual endpoint modules. Keep future callers
on this path rather than introducing a separate broker HTTP implementation.

## Live verification, September 18, 2026

The v3-base SDK submitted a GooeyTrade demo XAUUSD BUY LIMIT for 1 lot at 4340,
with stop loss 4330 and take profit 4350. The broker returned `status: OK` and
an order ID. A cancellation targeting that exact ID was sent 5.000745 seconds
after receipt of the create response. The cancellation response reported `OK`.
Subsequent active-order and open-position reads showed the test order absent,
no new position, and all pre-existing pending order IDs still present.

Private execution evidence, timestamps, account and broker identities are retained
locally in `data/verification/gooey-one-lot-20260918.json`; they are not part of a
source handoff. The script used this branch's SDK with its own Python environment.
It did not submit through the dashboard's native capture router.

The cancel reply also carried `errorCode: UNKNOWN_ERROR` despite `status: OK`.
Preserve that evidence; confirmation relies on the response together with broker
read-back, not the errorCode field alone. This observation is not permission to
ignore all error fields on other responses.

## Contract to preserve

1. Load credentials privately, name the destination account explicitly, and open
   one `MatchTraderAPI(settings)` context. Keep the explicit SDK User-Agent.
2. Log in and verify that the connection selected the requested account. Tokens,
   system UUID and session cookies come from that account's broker login response.
3. Read the instrument, lot limits, quote and existing orders/positions. Check the
   requested quantity, direction, order type and prices before a mutation.
4. Record the intended request before calling `create_pending_order()` once.
   Send numeric `volume`, `price`, `slPrice` and `tpPrice` through the SDK's models.
5. Preserve the returned broker ID. An accepted pending order is not a fill.
6. For the authorized test only, wait five seconds from receipt of acceptance,
   then call `cancel_pending_order()` for that exact instrument, ID, side and type.
   Place cancellation in cleanup so an intervening local failure cannot skip it.
7. Read active orders and positions after cancellation. Report uncertain results
   explicitly. Never cancel unrelated orders or automatically retry an uncertain
   create. If an order fills, cancelling a pending ID is not equivalent to closing
   the resulting position; that requires its own exact identity and authorization.
8. Close the SDK context. Do not persist a globally armed dashboard as part of a test.

Canonical broker calls (schematic; not an automatically runnable trading script):

```python
created = api.create_pending_order(
    instrument="XAUUSD", orderSide="BUY", type="LIMIT",
    volume=Decimal("1"), price=Decimal("4340"),
    slPrice=Decimal("4330"), tpPrice=Decimal("4350"),
)
# Retain created.orderId; perform the authorized wait/cleanup and reconciliation.
cancelled = api.cancel_pending_order(
    instrument="XAUUSD", id=created.orderId, orderSide="BUY", type="LIMIT",
)
remaining_orders = api.active_orders()
remaining_positions = api.open_positions()
```

## What this establishes

This specific demo-account login, pending-create, timed-cancel and read-back path
worked end to end. It does not establish a 100% success rate, fills or cash P/L,
market orders, stop orders, modifications, partial closes, all brokers, all account
types, renewal during a mutation, or recovery after a network failure.

`tests/test_order_baseline.py` protects the observed request/response contract and
exact-ID cancellation offline. Existing core tests cover other transport behavior;
mocked checks do not expand the live-validation claim.
