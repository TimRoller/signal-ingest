from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import polars as pl
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HAPPY_DIR = PROJECT_ROOT / "evals" / "datasets" / "happy"
FAILURE_DIR = PROJECT_ROOT / "evals" / "datasets" / "failure_modes"


def _requires_anthropic() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set; skipping live-eval suite")


@dataclass(frozen=True)
class HappyDataset:
    name: str
    csv_path: Path
    expected: pl.DataFrame


@dataclass(frozen=True)
class FailureDataset:
    name: str
    csv_path: Path


def _load_expected(module_path: Path) -> pl.DataFrame:
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.expected()  # type: ignore[no-any-return]


def discover_happy() -> Iterable[HappyDataset]:
    for csv in sorted(HAPPY_DIR.glob("*.csv")):
        expected_path = csv.with_suffix(".py")
        if not expected_path.exists():
            raise FileNotFoundError(f"missing expected module for {csv.name}")
        yield HappyDataset(name=csv.stem, csv_path=csv, expected=_load_expected(expected_path))


def discover_failures() -> Iterable[FailureDataset]:
    for csv in sorted(FAILURE_DIR.glob("*.csv")):
        yield FailureDataset(name=csv.stem, csv_path=csv)


@pytest.fixture(scope="session", autouse=True)
def require_api_key() -> None:
    _requires_anthropic()
