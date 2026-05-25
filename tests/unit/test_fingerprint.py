from __future__ import annotations

from shared.llm.fingerprint import PLAN_VERSION, fingerprint


def test_same_schema_different_order_produces_same_fingerprint() -> None:
    a = fingerprint(
        source="demo", columns=["id", "name", "value"], dtypes=["Int64", "String", "Int64"]
    )
    b = fingerprint(
        source="demo", columns=["value", "id", "name"], dtypes=["Int64", "Int64", "String"]
    )
    assert a == b


def test_different_dtype_changes_fingerprint() -> None:
    a = fingerprint(source="demo", columns=["id"], dtypes=["Int64"])
    b = fingerprint(source="demo", columns=["id"], dtypes=["String"])
    assert a != b


def test_different_source_changes_fingerprint() -> None:
    a = fingerprint(source="demo", columns=["id"], dtypes=["Int64"])
    b = fingerprint(source="vendor_a", columns=["id"], dtypes=["Int64"])
    assert a != b


def test_plan_version_bump_changes_fingerprint() -> None:
    a = fingerprint(source="demo", columns=["id"], dtypes=["Int64"], plan_version=PLAN_VERSION)
    b = fingerprint(source="demo", columns=["id"], dtypes=["Int64"], plan_version="9999-12-31")
    assert a != b


def test_fingerprint_is_64_hex_chars() -> None:
    fp = fingerprint(source="demo", columns=["id"], dtypes=["Int64"])
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)
