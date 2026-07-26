"""Connection / DSN models."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import parse_qsl, quote, unquote, urlparse, urlsplit, urlunsplit
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from teridex_core.errors import ConfigError

Scheme = Literal["duckdb", "sqlite", "postgres", "postgresql", "mysql"]
_VALID_SCHEMES = {"duckdb", "sqlite", "postgres", "postgresql", "mysql"}


def mask_dsn_password(url: str) -> str:
    """Mask credentials in a DSN URL to prevent password leaks in logs/errors."""
    try:
        parsed = urlsplit(url)
        if parsed.password:
            user = quote(unquote(parsed.username), safe="") if parsed.username else ""
            host = parsed.hostname or ""
            port = f":{parsed.port}" if parsed.port is not None else ""
            netloc = f"{user}:***@{host}{port}"
            return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
    except Exception:
        pass
    return re.sub(r"([^:]+://[^:]+:)[^@]+(@)", r"\1***\2", url)


class Dsn(BaseModel):
    """Parsed DSN. Use :meth:`parse` to build from a URL string."""

    model_config = ConfigDict(frozen=True)

    scheme: str
    username: str | None = None
    password: SecretStr | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    params: dict[str, str] = Field(default_factory=dict)

    @field_validator("scheme")
    @classmethod
    def _check_scheme(cls, v: str) -> str:
        v = v.lower()
        if v not in _VALID_SCHEMES:
            raise ValueError(f"unsupported scheme: {v}; valid: {sorted(_VALID_SCHEMES)}")
        return v

    @classmethod
    def parse(cls, url: str) -> Dsn:
        masked = mask_dsn_password(url)
        try:
            parsed = urlparse(url)
        except ValueError as exc:
            raise ConfigError(f"invalid DSN: {masked}", context={"error": str(exc)}) from exc
        if not parsed.scheme:
            raise ConfigError(f"DSN missing scheme: {masked}")
        # path: "/dbname" or "/path/to/file.db" or "/:memory:"
        database: str | None
        if parsed.path in ("", "/"):
            database = None
        else:
            # Strip exactly one leading slash. ``sqlite:///foo.db`` → ``foo.db``;
            # ``sqlite:////abs/foo.db`` → ``/abs/foo.db``. The literal
            # ``/:memory:`` collapses to ``:memory:``.
            database = parsed.path[1:] if parsed.path.startswith("/") else parsed.path
        params: dict[str, str] = {}
        if parsed.query:
            params = dict(parse_qsl(parsed.query))
        return cls(
            scheme=parsed.scheme.lower(),
            username=unquote(parsed.username) if parsed.username else None,
            password=SecretStr(unquote(parsed.password)) if parsed.password else None,
            host=parsed.hostname,
            port=parsed.port,
            database=database,
            params=params,
        )

    def render(self, *, mask_password: bool = True) -> str:
        userinfo = ""
        if self.username or self.password:
            if self.username:
                userinfo = quote(self.username, safe="")
            if self.password:
                userinfo += ":" + (
                    "***" if mask_password else quote(self.password.get_secret_value(), safe="")
                )
            userinfo += "@"
        host = self.host or ""
        port = f":{self.port}" if self.port else ""
        db = self.database or ""
        if (
            db
            and not db.startswith("/")
            and self.scheme in {"sqlite", "duckdb"}
            and db != ":memory:"
        ) or (db and self.scheme not in {"sqlite", "duckdb"}):
            db = "/" + db
        elif db == ":memory:":
            db = "/:memory:"
        query = ""
        if self.params:
            query = "?" + "&".join(f"{quote(k)}={quote(v)}" for k, v in self.params.items())
        return f"{self.scheme}://{userinfo}{host}{port}{db}{query}"


class ConnectionInfo(BaseModel):
    """Runtime info about an active connection."""

    model_config = ConfigDict(frozen=True)

    connection_id: str = Field(default_factory=lambda: uuid4().hex)
    dsn: Dsn
    label: str | None = None

    @property
    def display_name(self) -> str:
        return self.label or self.dsn.render(mask_password=True)
