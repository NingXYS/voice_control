"""Shared validation for service base URLs and plaintext-network exceptions."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit


def is_loopback_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def validate_service_origin(
    value: str,
    *,
    setting: str,
    allow_insecure_remote: bool = False,
) -> str:
    """Return a normalized HTTP(S) origin, rejecting credentials and URL tails."""
    candidate = str(value).strip().rstrip("/")
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"{setting} must be a valid HTTP(S) origin") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{setting} must be an HTTP(S) origin without credentials or a path")
    if parsed.scheme == "http" and not is_loopback_host(parsed.hostname) and not allow_insecure_remote:
        raise ValueError(
            f"non-loopback {setting} must use HTTPS; explicitly enable the insecure override "
            "only for an accepted isolated-LAN risk"
        )
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}{f':{port}' if port is not None else ''}"
