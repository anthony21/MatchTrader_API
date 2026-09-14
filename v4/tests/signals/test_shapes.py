import pytest

from matchtrader.signals import BaseSignal, ChainSignal, P01Signal, R01Signal, parse_signal
from tests.signals.helpers import lane, raw


def test_each_source_gets_its_own_shape_on_the_shared_base():
    assert type(parse_signal(raw(source="chain"))) is ChainSignal
    assert type(parse_signal(raw(source="P01_LOG", label="P01RR_1_1"))) is P01Signal
    assert type(parse_signal(raw(source="panel", label="P01RR_1_1"))) is P01Signal
    assert type(parse_signal(raw(source="R01", label="R01_BTCUSD_long_0_1_0_2"))) is R01Signal
    assert type(parse_signal(raw(source="somebody"))) is BaseSignal
    assert all(issubclass(shape, BaseSignal) for shape in (ChainSignal, P01Signal, R01Signal))


def test_base_normalises_side_and_type_and_requires_a_timezone():
    signal = parse_signal(raw(side="long", orderType="stop"))
    assert signal.side == "BUY" and signal.copyOrderType == "STOP"
    assert parse_signal(raw(side=1)).side == "SELL"
    with pytest.raises(ValueError):
        parse_signal(raw(timestampUtc="2026-09-13T10:00:00"))
    assert signal.scope == ("qt", "chain", "", "", "US TECH 100", "box")


def test_r01_states_its_order_type_in_the_detail_text_and_carries_its_grade():
    signal = parse_signal(raw(source="R01", label="R01_X_long_1", detail="resting stop at beyond edge",
                              grade="PRIME", stamp="88.5", rfx="S15+", arm="r5:b8|PRIME|"))
    assert signal.order_type == "STOP" and signal.grade == "PRIME" and signal.rfx == "S15+"
    assert parse_signal(raw(source="R01", label="x", detail="resting limit at range edge")).order_type == "LIMIT"
    assert parse_signal(raw(source="R01", label="x", detail="?")).order_type == ""


def test_attribution_rules_belong_to_the_subclasses():
    with pytest.raises(ValueError, match="X17"):
        parse_signal(raw(detail="somebody else")).check_attribution(lane(x17_only=True))
    parse_signal(raw(detail="x17-spine bar=1")).check_attribution(lane(x17_only=True))
    parse_signal(raw(detail="somebody else")).check_attribution(lane())   # only when the lane requires X17
    with pytest.raises(ValueError, match="manual P01"):
        parse_signal(raw(source="panel", label="L:low@0_1@2")).check_attribution(lane())
    parse_signal(raw(source="P01_LOG", label="L:low@0_1029@6016")).check_attribution(lane())
    parse_signal(raw(source="P01_LOG", label="P01RR_231335_60")).check_attribution(lane())
    with pytest.raises(ValueError, match="recognised"):
        parse_signal(raw(source="P01_LOG", label="box")).check_attribution(lane())
    parse_signal(raw(source="R01", label="anything")).check_attribution(lane())
