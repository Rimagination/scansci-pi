from scansci_html.credentials import (
    credential_status,
    delete_credential,
    get_credential,
    set_credential,
)


class FakeKeyring:
    def __init__(self) -> None:
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service_name: str, username: str) -> str | None:
        return self.store.get((service_name, username))

    def set_password(self, service_name: str, username: str, password: str) -> None:
        self.store[(service_name, username)] = password

    def delete_password(self, service_name: str, username: str) -> None:
        del self.store[(service_name, username)]


def test_get_credential_reads_environment_before_keyring():
    backend = FakeKeyring()
    set_credential("elsevier-api-key", "from-keyring", backend=backend)

    value = get_credential(
        "elsevier-api-key",
        backend=backend,
        env={"ELSEVIER_API_KEY": "from-env"},
    )

    assert value == "from-env"


def test_set_get_delete_credential_uses_keyring_service_name():
    backend = FakeKeyring()

    set_credential("springer-nature-api-key", "springer-secret", backend=backend)

    assert get_credential("springer-nature-api-key", backend=backend, env={}) == "springer-secret"
    assert backend.store[("scansci-html", "springer_nature_api_key")] == "springer-secret"

    delete_credential("springer-nature-api-key", backend=backend)

    assert get_credential("springer-nature-api-key", backend=backend, env={}) == ""


def test_credential_status_is_redacted_and_reports_source():
    backend = FakeKeyring()
    set_credential("elsevier-inst-token", "institution-token", backend=backend)

    rows = credential_status(backend=backend, env={"ELSEVIER_API_KEY": "api-key"})

    by_name = {row["name"]: row for row in rows}
    assert by_name["elsevier-api-key"]["status"] == "present"
    assert by_name["elsevier-api-key"]["source"] == "environment"
    assert by_name["elsevier-api-key"]["value"] == "***"
    assert by_name["elsevier-inst-token"]["status"] == "present"
    assert by_name["elsevier-inst-token"]["source"] == "keyring"
    assert by_name["springer-nature-api-key"]["status"] == "missing"


def test_credential_status_teaches_elsevier_api_application_and_configuration():
    backend = FakeKeyring()

    rows = credential_status(backend=backend, env={})

    by_name = {row["name"]: row for row in rows}
    elsevier = by_name["elsevier-api-key"]
    assert elsevier["status"] == "missing"
    assert elsevier["setup_url"] == "https://dev.elsevier.com/apikey/manage"
    assert elsevier["configure_command"] == "scansci credentials set elsevier-api-key"
    assert any("Developer Portal" in step for step in elsevier["setup_steps"])
    assert any("subscription" in step.lower() for step in elsevier["setup_steps"])


def test_wiley_tdm_client_token_can_be_stored_in_keyring():
    backend = FakeKeyring()

    set_credential("wiley-tdm-client-token", "wiley-token", backend=backend)

    assert get_credential("wiley-tdm-client-token", backend=backend, env={}) == "wiley-token"
    assert backend.store[("scansci-html", "wiley_tdm_client_token")] == "wiley-token"
