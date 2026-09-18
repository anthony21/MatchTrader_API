from .base import Record


class Platform(Record):
    partnerId: str
    platformUrl: str
    brokerName: str = ""
