def test_public_session_owner():
    from matchtrader.sessions import SessionManager

    assert callable(SessionManager)
