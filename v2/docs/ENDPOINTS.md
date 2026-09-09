# Endpoint inventory

Each operation has its own endpoint and request-model file. Only writes are gated by MTR_ENABLE_WRITES.

| API method | HTTP | Path | Writes |
|---|---|---|---|
| `api.platform_details(...)` | GET | `/manager/platform-details` | False |
| `api.register(...)` | POST | `/manager/user` | True |
| `api.login(...)` | POST | `/manager/mtr-login` | False |
| `api.refresh_token(...)` | POST | `/manager/refresh-token` | False |
| `api.login_with_token(...)` | POST | `/manager/login/co/with-token` | False |
| `api.quotes(...)` | GET | `/mtr-api/SYSTEM_UUID/quotations` | False |
| `api.balance(...)` | GET | `/mtr-api/SYSTEM_UUID/balance` | False |
| `api.instruments(...)` | GET | `/mtr-api/SYSTEM_UUID/effective-instruments` | False |
| `api.candles(...)` | GET | `/mtr-api/SYSTEM_UUID/candles` | False |
| `api.open_positions(...)` | GET | `/mtr-api/SYSTEM_UUID/open-positions` | False |
| `api.open_position(...)` | POST | `/mtr-api/SYSTEM_UUID/position/open` | True |
| `api.edit_position(...)` | POST | `/mtr-api/SYSTEM_UUID/position/edit` | True |
| `api.partial_close(...)` | POST | `/mtr-api/SYSTEM_UUID/position/close-partially` | True |
| `api.close_position(...)` | POST | `/mtr-api/SYSTEM_UUID/position/close` | True |
| `api.closed_positions(...)` | POST | `/mtr-api/SYSTEM_UUID/closed-positions` | False |
| `api.active_orders(...)` | GET | `/mtr-api/SYSTEM_UUID/active-orders` | False |
| `api.create_pending_order(...)` | POST | `/mtr-api/SYSTEM_UUID/pending-order/create` | True |
| `api.edit_pending_order(...)` | POST | `/mtr-api/SYSTEM_UUID/pending-order/edit` | True |
| `api.cancel_pending_order(...)` | POST | `/mtr-api/SYSTEM_UUID/pending-order/cancel` | True |
