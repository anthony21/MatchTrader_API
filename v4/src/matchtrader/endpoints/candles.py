from matchtrader.models.candle import Candle
from matchtrader.models.candles_request import CandlesRequest

from .base import BaseEndpoint


class GetCandles(BaseEndpoint):
    """GET /mtr-api/SYSTEM_UUID/candles."""

    method = "GET"
    path = "mtr-api/SYSTEM_UUID/candles"
    scope = "trading"
    write = False
    safe_read = True
    action = ""
    collection = "candles"
    request_model = CandlesRequest
    response_model = Candle
