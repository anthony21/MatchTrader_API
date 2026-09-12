"""Application-scoped broker connection injected into the dashboard and its routes."""


class BrokerSession:
    def __init__(self):
        self.api = None

    def require(self, account_id):
        api = self.api
        if api is None or api.connection.account_id != account_id:
            raise ValueError('Connect the selected broker account first')
        return api
