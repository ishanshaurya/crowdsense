import os
import shutil
from collections.abc import AsyncIterator
from urllib.parse import quote

import pytest
from alembic import command
from alembic.config import Config
from pytest_postgresql import factories

from core.clock import ScriptedClock
from core.engine import Engine
from core.store import Store
from core.store_memory import InMemoryStore
from core.store_postgres import PostgresStore
from tests.support import ARTIST, NOW, ROOT

# CI uses a Postgres service (#44); locally pytest-postgresql starts the Homebrew server.
if os.environ.get("CI"):
    pg_server = factories.postgresql_noproc()
else:
    pg_server = factories.postgresql_proc(executable=shutil.which("pg_ctl"))
postgresql = factories.postgresql("pg_server")


def url_of(host: str, port: int | str, user: str, password: str | None, dbname: str) -> str:
    auth = quote(user) + (f":{quote(password)}" if password else "")
    return f"postgresql://{auth}@{host}:{port}/{dbname}"


def migrate(url: str, revision: str = "head", *, down: bool = False) -> None:
    config = Config(str(ROOT / "alembic.ini"))
    os.environ["DATABASE_URL"] = url
    try:
        (command.downgrade if down else command.upgrade)(config, revision)
    finally:
        del os.environ["DATABASE_URL"]


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        marker = "component" if "/tests/component/" in str(item.path) else "unit"
        item.add_marker(getattr(pytest.mark, marker))


@pytest.fixture(autouse=True)
def _never_touch_real_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)


@pytest.fixture
def pg_url(postgresql) -> str:  # type: ignore[no-untyped-def]
    info = postgresql.info
    return url_of(info.host, info.port, info.user, info.password, info.dbname)


@pytest.fixture
def pg_migrated_url(pg_url: str) -> str:
    migrate(pg_url)
    return pg_url


@pytest.fixture(params=["memory", "postgres"])
async def store(request: pytest.FixtureRequest) -> AsyncIterator[Store]:
    if request.param == "memory":
        backend: Store = InMemoryStore()
    else:
        backend = PostgresStore(request.getfixturevalue("pg_migrated_url"))
    yield backend
    await backend.close()


@pytest.fixture
def clock() -> ScriptedClock:
    return ScriptedClock(NOW)


@pytest.fixture
def engine(store: Store, clock: ScriptedClock) -> Engine:
    return Engine(store, clock, artist_name=ARTIST)
