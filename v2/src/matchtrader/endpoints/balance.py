from matchtrader.models.balance import Balance

from .base import BaseEndpoint


class GetBalance(BaseEndpoint):
    """GET /mtr-api/SYSTEM_UUID/balance."""

    method = "GET"
    path = "mtr-api/SYSTEM_UUID/balance"
    scope = "trading"
    write = False
    safe_read = True
    action = ""
    collection = None
    response_model = Balance
