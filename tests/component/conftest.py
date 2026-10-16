"""Seeded rows shared by phase 3 (seed) and phase 4 (dashboard at 20k) tests: one engine run."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from scripts.seed import rows_of, run_engine
from scripts.seed_plan import plan_fans

Rows = dict[str, list[Any]]


def _rows(count: int) -> Rows:
    async def go() -> Rows:
        return await rows_of(await run_engine(plan_fans(count, 42, datetime.now(UTC))))

    return asyncio.run(go())


@pytest.fixture(scope="session")
def full_rows() -> Rows:
    return _rows(20_000)


@pytest.fixture(scope="session")
def small_rows() -> Rows:
    return _rows(1_000)
