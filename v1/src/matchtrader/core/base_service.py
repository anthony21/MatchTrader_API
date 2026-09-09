from .errors import ConnectionClosedError


class BaseService:
    """Services borrow the facade's singleton lease; they do not own or close it."""

    def __init__(self, owner):
        self.owner = owner

    @property
    def connection(self):
        if self.owner.closed:
            raise ConnectionClosedError("API owner is closed")
        return self.owner.connection
