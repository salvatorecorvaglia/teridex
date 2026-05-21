"""Connection / DSN models."""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote, unquote, urlparse
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from teridex_core.errors import ConfigError

Scheme = Literal["duckdb", "sqlite", "postgres", "postgresql", "mysql"]
_VALID_SCHEMES = {"duckdb", "sqlite", "postgres", "postgresql", "mysql"}


class Dsn(BaseModel):
    """Parsed DSN. Use :meth:`parse` to build from a URL string."""

    model_config = ConfigDict(frozen=True)

    scheme: str
    username: str | None = None
    password: str | None = None
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
    def parse(cls, url: str) -> "Dsn":
        try:
            parsed = urlparse(url)
        except ValueError as exc:
            raise ConfigError(f"invalid DSN: {url}", context={"error": str(exc)}) from exc
        if not parsed.scheme:
            raise ConfigError(f"DSN missing scheme: {url}")
        # path: "/dbname" or "/path/to/file.db" or ":memory:"
        database: str | None
        if parsed.path in ("", "/"):
            database = None
        elif parsed.scheme in {"sqlite", "duckdb"}:
            # File-based; preserve full path
            database = parsed.path.lstrip("/") if parsed.path.startswith("/:") is False else parsed.path
            if database == "" or database == ":memory:":
                database = ":memory:"
        else:
            database = parsed.path.lstrip("/")
        params: dict[str, str] = {}
        if parsed.query:
            for chunk in parsed.query.split("&"):
                if not chunk:
                    continue
                k, _, v = chunk.partition("=")
                params[unquote(k)] = unquote(v)
        return cls(
            scheme=parsed.scheme.lower(),
            username=unquote(parsed.username) if parsed.username else None,
            password=unquote(parsed.password) if parsed.password else None,
            host=parsed.hostname,
            port=parsed.port,
            database=database,
            params=params,
        )

    def render(self, *, mask_password: bool = True) -> str:
        userinfo = ""
        if self.username:
            userinfo = quote(self.username, safe="")
            if self.password:
                userinfo += ":" + ("***" if mask_password else quote(self.password, safe=""))
            userinfo += "@"
        host = self.host or ""
        port = f":{self.port}" if self.port else ""
        db = self.database or ""
        if db and not db.startswith("/") and self.scheme in {"sqlite", "duckdb"} and db != ":memory:":
            db = "/" + db
        elif db and self.scheme not in {"sqlite", "duckdb"}:
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
