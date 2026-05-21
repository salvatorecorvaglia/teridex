"""Map driver-native type names to Teridex ``ColumnType``."""

from __future__ import annotations

from teridex_core.models.result import ColumnType

_INTEGER = {
    "int",
    "int2",
    "int4",
    "int8",
    "integer",
    "smallint",
    "bigint",
    "tinyint",
    "mediumint",
    "serial",
    "bigserial",
}
_FLOAT = {"real", "float", "float4", "float8", "double", "double precision"}
_DECIMAL = {"decimal", "numeric"}
_BOOL = {"bool", "boolean", "bit"}
_DATE = {"date"}
_TIME = {"time", "timetz"}
_DATETIME = {"timestamp", "timestamptz", "datetime"}
_STRING = {
    "text",
    "varchar",
    "char",
    "character",
    "character varying",
    "string",
    "name",
    "citext",
    "enum",
    "set",
}
_JSON = {"json", "jsonb"}
_BINARY = {"bytea", "blob", "binary", "varbinary"}
_UUID = {"uuid"}


def infer_column_type(native: str | None) -> ColumnType:
    if not native:
        return ColumnType.UNKNOWN
    n = native.strip().lower()
    # Drop parametric suffix: VARCHAR(255) -> varchar
    if "(" in n:
        n = n.split("(", 1)[0].strip()
    if n in _INTEGER:
        return ColumnType.INTEGER
    if n in _FLOAT:
        return ColumnType.FLOAT
    if n in _DECIMAL:
        return ColumnType.DECIMAL
    if n in _BOOL:
        return ColumnType.BOOL
    if n in _DATE:
        return ColumnType.DATE
    if n in _TIME:
        return ColumnType.TIME
    if n in _DATETIME:
        return ColumnType.DATETIME
    if n in _STRING:
        return ColumnType.STRING
    if n in _JSON:
        return ColumnType.JSON
    if n in _BINARY:
        return ColumnType.BINARY
    if n in _UUID:
        return ColumnType.UUID
    return ColumnType.UNKNOWN
