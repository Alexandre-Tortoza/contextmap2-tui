from contextmap_tui.client import ClientStatus, ContextMapClient, FakeContextMapClient


def test_fake_client_satisfies_gateway_contract() -> None:
    client = FakeContextMapClient(backend_name="fixture", detail="ready")

    assert isinstance(client, ContextMapClient)
    assert client.status() == ClientStatus(name="fixture", connected=True, detail="ready")
