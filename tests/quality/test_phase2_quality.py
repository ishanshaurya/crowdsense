"""Quality checks Q-11 to Q-14 (testing/quality/architecture-quality.md) and phase 2 test ids.

Q-13's pip-audit needs the network, so it runs in pre-commit and CI; the lockfile check runs here.
"""

import ast
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from adapters.base import Adapter
from adapters.telegram import TelegramAdapter
from api.logs import configure_logging
from core.clock import ScriptedClock
from core.store_memory import InMemoryStore
from tests.component.telegram_fake import FIXTURES, SECRET, TOKEN, Fan, build_rig, error
from tests.support import NOW, ROOT, decision

ADAPTER_FILES = sorted((ROOT / "adapters").glob("*.py"))
FORBIDDEN_FOR_ADAPTERS = (
    "core.flow",
    "core.engine",
    "core.decide",
    "core.store",
    "api",
    "dashboard",
)


@decision(4, 5)
def test_q11_every_adapter_implements_the_protocol() -> None:
    members = [n for n in vars(Adapter) if not n.startswith("_")] + ["channel", "capabilities"]
    for name in ("parse", "render", "send", "capabilities", "authorized", "answer_tap"):
        assert name in members
    for cls in (TelegramAdapter,):
        for name in members:
            assert hasattr(cls, name), f"{cls.__name__} lacks {name}"
        for name in ("parse", "render", "send", "authorized", "answer_tap", "confirm_tap"):
            assert callable(getattr(cls, name))


@decision(4)
@pytest.mark.parametrize("path", ADAPTER_FILES, ids=lambda p: p.name)
def test_q11_adapters_import_no_flow_engine_or_store(path: Path) -> None:
    imported: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    bad = {m for m in imported for f in FORBIDDEN_FOR_ADAPTERS if m == f or m.startswith(f + ".")}
    assert bad == set()


@decision(66)
async def test_q12_secret_header_is_required_and_no_secret_reaches_the_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    configure_logging()  # no redaction: the code itself must not log secrets
    assert logging.getLogger("httpx").level >= logging.WARNING
    assert logging.getLogger("httpcore").level >= logging.WARNING
    caplog.set_level(logging.DEBUG)
    rig = build_rig(InMemoryStore(), ScriptedClock(NOW))
    rig.telegram.script["sendMessage"] = [error(500, "boom"), error(429, "slow", retry_after=1)]
    rig.telegram.script["answerCallbackQuery"] = [error(400, "query is too old")]
    fan = Fan(rig)
    assert await rig.post({"update_id": 1}, headers={"X-Telegram-Bot-Api-Secret-Token": "x"}) == 401
    await fan.say("/start ig_story")
    await fan.say("/start")
    await fan.tap("Count me in")
    await rig.sweeper.sweep_once()
    await rig.close()
    text = caplog.text + "".join(str(r.args) for r in caplog.records)
    assert len(caplog.records) >= 3  # the failures above did log something
    assert TOKEN not in text and TOKEN.split(":")[1] not in text and SECRET not in text
    assert "api.telegram.org" not in text


SAFE_IDS = re.compile(r"^-?10+\d{1,2}$")  # placeholders: 1000000001, -1000000009, ...
SAFE_NAMES = {"first_name": {"Test", "Crowdsense"}, "last_name": {"User"}, "title": {"Test Group"}}
SAFE_USERNAMES = {"test_user", "crowdsense_live_bot"}
TOKEN_SHAPE = re.compile(r"\d{6,}:[A-Za-z0-9_-]{30,}")


def _walk(node: Any, parent: str = "") -> list[tuple[str, str, Any]]:
    found = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.append((parent, key, value))
            found += _walk(value, key)
    elif isinstance(node, list):
        for item in node:
            found += _walk(item, parent)
    return found


def test_q14_fixtures_are_scrubbed() -> None:
    files = sorted(FIXTURES.glob("*.json"))
    assert len(files) >= 10
    update_ids = []
    for path in files:
        raw = path.read_text(encoding="utf-8")
        assert not TOKEN_SHAPE.search(raw), path.name
        assert "secret" not in raw.lower() and "x-telegram" not in raw.lower(), path.name
        data = json.loads(raw)
        update_ids.append(data["update_id"])
        for parent, key, value in _walk(data):
            where = f"{path.name}: {parent}.{key}"
            if key == "id" and parent in ("from", "chat"):
                assert SAFE_IDS.match(str(value)), where
            if key in SAFE_NAMES:
                assert value in SAFE_NAMES[key], where
            if key == "username":
                assert value in SAFE_USERNAMES, where
            if key in ("file_id", "file_unique_id"):
                assert str(value).startswith("FILE"), where
            if key in ("phone_number", "email", "contact", "location"):
                raise AssertionError(where)
    assert len(set(update_ids)) == len(update_ids)


@decision(41)
def test_q13_lockfile_is_current() -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not installed")
    result = subprocess.run(
        [uv, "lock", "--check", "--offline"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_every_phase_2_test_id_has_a_test() -> None:
    spec = (ROOT / "testing" / "phases" / "phase-2-telegram.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"\bP2-[UC]\d+\b", spec))
    assert len(ids) >= 28
    code = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").rglob("*.py")).lower()
    missing = sorted(i for i in ids if i.lower().replace("-", "_") not in code)
    assert missing == []
