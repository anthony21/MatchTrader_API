def test_refresh_token_http_contract(check_endpoint):
    check_endpoint("refresh_token")


def test_json_refresh_result_does_not_expose_tokens(api_factory):
    import httpx

    api, _ = api_factory(
        lambda r: (
            httpx.Response(200, json={"token": "private-new-session"})
            if r.url.path.endswith("refresh-token")
            else None
        )
    )
    api.login()
    response = api.refresh_token()
    assert response.token.get_secret_value() == "private-new-session"
    assert "private-new-session" not in response.model_dump_json()
