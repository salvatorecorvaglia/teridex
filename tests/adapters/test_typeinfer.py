"""Tests for driver-native type-name inference."""

from __future__ import annotations

import pytest

from teridex_adapters._typeinfer import infer_column_type
from teridex_core.models.result import ColumnType


@pytest.mark.parametrize(
    ("native", "expected"),
    [
        ("integer", ColumnType.INTEGER),
        ("BIGINT", ColumnType.INTEGER),
        ("int4", ColumnType.INTEGER),
        ("serial", ColumnType.INTEGER),
        ("real", ColumnType.FLOAT),
        ("double precision", ColumnType.FLOAT),
        ("numeric", ColumnType.DECIMAL),
        ("decimal", ColumnType.DECIMAL),
        ("boolean", ColumnType.BOOL),
        ("date", ColumnType.DATE),
        ("time", ColumnType.TIME),
        ("timestamptz", ColumnType.DATETIME),
        ("datetime", ColumnType.DATETIME),
        ("text", ColumnType.STRING),
        ("varchar", ColumnType.STRING),
        ("jsonb", ColumnType.JSON),
        ("bytea", ColumnType.BINARY),
        ("uuid", ColumnType.UUID),
    ],
)
def test_infer_known_types(native: str, expected: ColumnType) -> None:
    assert infer_column_type(native) is expected


def test_infer_strips_parametric_suffix() -> None:
    assert infer_column_type("VARCHAR(255)") is ColumnType.STRING
    assert infer_column_type("numeric(10, 2)") is ColumnType.DECIMAL
    assert infer_column_type("char (10)") is ColumnType.STRING


def test_infer_is_case_and_whitespace_insensitive() -> None:
    assert infer_column_type("  Integer  ") is ColumnType.INTEGER


@pytest.mark.parametrize("native", [None, "", "   ", "geometry", "wibble"])
def test_infer_unknown_types(native: str | None) -> None:
    assert infer_column_type(native) is ColumnType.UNKNOWN
