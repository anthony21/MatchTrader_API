from matchtrader.orders import Route, StopLimitPlan, StopLimitWatcher, decide


def test_orders_public_contract():
    assert {"stopPrice", "limitPrice"} <= set(StopLimitPlan.model_fields)
    assert Route.REST_LIMIT.value == "rest_limit"
    assert callable(decide) and callable(StopLimitWatcher.poll)
