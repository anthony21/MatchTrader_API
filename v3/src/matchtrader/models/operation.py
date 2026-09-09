from pydantic import model_validator

from .base import Record


class Operation(Record):
    status: str | None = None
    nativeCode: str | int | None = None
    errorMessage: str | None = None
    orderId: str | None = None
    positionId: str | None = None

    @model_validator(mode="after")
    def recognized_response(self):
        if not (self.status or self.orderId or self.positionId):
            raise ValueError("Missing operation status or broker identity")
        return self
