def test_public_shadow_facade():
    from matchtrader.bridge import OrderEvent, ShadowBridge

    assert OrderEvent.__name__ == "OrderEvent"
    assert ShadowBridge.__name__ == "ShadowBridge"
