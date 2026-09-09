"""Stable exceptions; messages never include request bodies or authentication tokens."""


class MatchTraderError(Exception):
    """Base client error."""


class ConfigurationError(MatchTraderError):
    pass


class AuthenticationError(MatchTraderError):
    pass


class ConnectionClosedError(MatchTraderError):
    pass


class APIError(MatchTraderError):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class UnknownOutcomeError(APIError):
    """A mutation failed in transit; reconcile server state before retrying."""


class WritesDisabledError(MatchTraderError):
    pass


class ProtocolError(MatchTraderError):
    pass
