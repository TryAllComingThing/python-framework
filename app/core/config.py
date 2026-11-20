from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_origin(value: str) -> str:
    """Normalize one HTTP origin and reject values with no unambiguous origin."""
    raw = value.strip()
    if not raw or raw == "*":
        raise ValueError("Explicit HTTP origins are required")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Invalid HTTP origin: {value!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Origins must not contain credentials")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("Origins must not contain a path, query or fragment")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid HTTP origin port: {value!r}") from exc
    hostname = parsed.hostname.lower()
    host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 80 if parsed.scheme == "http" else 443
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme}://{host}{port_suffix}"


class Settings(BaseSettings):
    app_env: Literal["local", "test", "staging", "production"] = "local"
    database_url: str | None = None
    log_level: str = "INFO"
    default_locale: Literal["zh-CN", "en-US"] = "zh-CN"
    cors_origins: list[str] = Field(default_factory=list)
    cookie_auth_enabled: bool = False
    csrf_origins: list[str] = Field(default_factory=list)
    trusted_hosts: list[str] = Field(default_factory=list)
    file_storage_root: str = "./var/uploads"
    file_malware_scan_enabled: bool = False
    file_clamd_socket: str = "/run/clamav/clamd.ctl"
    max_request_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    file_max_bytes: int = Field(default=5_000_000, ge=1)
    session_ttl_hours: int = Field(default=8, ge=1, le=24 * 30)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("cors_origins", "csrf_origins")
    @classmethod
    def normalize_http_origins(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for origin in value:
            item = _normalize_origin(origin)
            if item not in normalized:
                normalized.append(item)
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
