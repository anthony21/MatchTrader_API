from matchtrader.models.instrument import Instrument

from .base import BaseEndpoint


class GetInstruments(BaseEndpoint):
    """GET /mtr-api/SYSTEM_UUID/effective-instruments."""

    method = "GET"
    path = "mtr-api/SYSTEM_UUID/effective-instruments"
    scope = "trading"
    write = False
    safe_read = True
    action = ""
    collection = "instruments"
    response_model = Instrument
    single_as_list = True
