from matchtrader import signals


def test_package_exposes_the_three_steps_and_the_shapes():
    for name in ("parse_signal", "SignalEngine", "BrokerDispatcher", "OrderPlan", "Refusal", "Context",
                 "SymbolMap", "SymbolMapping", "BaseSignal", "P01Signal", "ChainSignal", "R01Signal", "Outcome"):
        assert hasattr(signals, name), name
    assert set(signals.__all__) >= {"parse_signal", "SignalEngine", "BrokerDispatcher"}
