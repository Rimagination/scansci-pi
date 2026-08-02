from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Mapping


SERVICE_NAME = "scansci-html"


class CredentialStoreError(RuntimeError):
    """Raised when the system credential store cannot be used."""


@dataclass(frozen=True)
class CredentialSpec:
    name: str
    keyring_username: str
    env_vars: tuple[str, ...]
    description: str
    setup_url: str = ""
    setup_steps: tuple[str, ...] = ()


CREDENTIAL_SPECS: tuple[CredentialSpec, ...] = (
    CredentialSpec(
        name="elsevier-api-key",
        keyring_username="elsevier_api_key",
        env_vars=("ELSEVIER_API_KEY",),
        description="Elsevier Developer Portal API key.",
        setup_url="https://dev.elsevier.com/apikey/manage",
        setup_steps=(
            "Request an Elsevier API key from the Elsevier Developer Portal.",
            "Store it locally with: scansci credentials set elsevier-api-key",
            "Closed full text still requires subscription entitlement through the API account, institution, or network route.",
        ),
    ),
    CredentialSpec(
        name="elsevier-inst-token",
        keyring_username="elsevier_inst_token",
        env_vars=("ELSEVIER_INST_TOKEN", "ELSEVIER_INSTITUTION_TOKEN"),
        description="Elsevier institution token for entitled institutional API access.",
    ),
    CredentialSpec(
        name="springer-nature-api-key",
        keyring_username="springer_nature_api_key",
        env_vars=("SPRINGER_NATURE_API_KEY", "SPRINGER_API_KEY"),
        description="Springer Nature Developer Portal API key.",
    ),
    CredentialSpec(
        name="wiley-tdm-client-token",
        keyring_username="wiley_tdm_client_token",
        env_vars=("WILEY_TDM_CLIENT_TOKEN", "TDM_API_TOKEN"),
        description="Wiley Online Library TDM client token.",
    ),
)


def credential_names() -> list[str]:
    return [spec.name for spec in CREDENTIAL_SPECS]


def get_credential(
    name: str,
    *,
    backend: object | None = None,
    env: Mapping[str, str] | None = None,
) -> str:
    spec = _credential_spec(name)
    environment = os.environ if env is None else env
    for env_var in spec.env_vars:
        value = str(environment.get(env_var) or "").strip()
        if value:
            return value
    try:
        keyring_backend = backend or _load_keyring()
        value = keyring_backend.get_password(SERVICE_NAME, spec.keyring_username)
    except CredentialStoreError:
        return ""
    return str(value or "").strip()


def set_credential(name: str, value: str, *, backend: object | None = None) -> None:
    spec = _credential_spec(name)
    secret = str(value or "").strip()
    if not secret:
        raise CredentialStoreError("empty credential value")
    keyring_backend = backend or _load_keyring()
    keyring_backend.set_password(SERVICE_NAME, spec.keyring_username, secret)


def delete_credential(name: str, *, backend: object | None = None) -> None:
    spec = _credential_spec(name)
    keyring_backend = backend or _load_keyring()
    try:
        keyring_backend.delete_password(SERVICE_NAME, spec.keyring_username)
    except Exception:
        pass


def credential_status(
    *,
    backend: object | None = None,
    env: Mapping[str, str] | None = None,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    environment = os.environ if env is None else env
    keyring_backend = backend
    if keyring_backend is None:
        try:
            keyring_backend = _load_keyring()
        except CredentialStoreError:
            keyring_backend = None

    for spec in CREDENTIAL_SPECS:
        env_value = next((environment.get(env_var) for env_var in spec.env_vars if environment.get(env_var)), "")
        keyring_value = ""
        if keyring_backend is not None:
            try:
                keyring_value = keyring_backend.get_password(SERVICE_NAME, spec.keyring_username) or ""
            except Exception:
                keyring_value = ""
        source = "environment" if env_value else "keyring" if keyring_value else ""
        rows.append(
            {
                "name": spec.name,
                "status": "present" if source else "missing",
                "source": source or "missing",
                "value": "***" if source else "",
                "env_vars": list(spec.env_vars),
                "description": spec.description,
                "setup_url": spec.setup_url,
                "setup_steps": list(spec.setup_steps),
                "configure_command": f"scansci credentials set {spec.name}",
            }
        )
    return rows


def credential_setup_message(name: str) -> str:
    spec = _credential_spec(name)
    parts = []
    if spec.setup_url:
        parts.append(f"apply/request at {spec.setup_url}")
    parts.append(f"configure with `scansci credentials set {spec.name}`")
    if spec.env_vars:
        parts.append(f"or set {spec.env_vars[0]}")
    if spec.setup_steps:
        parts.append("note: " + " ".join(spec.setup_steps))
    return "; ".join(parts)


def _credential_spec(name: str) -> CredentialSpec:
    normalized = _normalize_name(name)
    for spec in CREDENTIAL_SPECS:
        if normalized in {_normalize_name(spec.name), _normalize_name(spec.keyring_username)}:
            return spec
    allowed = ", ".join(credential_names())
    raise CredentialStoreError(f"unknown credential {name!r}; allowed: {allowed}")


def _normalize_name(name: str) -> str:
    return str(name or "").strip().lower().replace("_", "-")


def _load_keyring() -> object:
    try:
        import keyring
    except Exception as exc:  # pragma: no cover - depends on environment packaging
        raise CredentialStoreError(
            "Python keyring is not installed; install scansci-html with keyring support"
        ) from exc
    return keyring
