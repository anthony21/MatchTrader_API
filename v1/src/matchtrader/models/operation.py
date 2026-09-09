from .base import Record


class Operation(Record):
    status: str
    nativeCode: str | int | None = None
    errorMessage: str | None = None
    orderId: str | None = None
