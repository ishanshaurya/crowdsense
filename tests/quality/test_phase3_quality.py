"""Phase 3 checks: no core change (P3-C03), plugin cost (Q-15, #101), adapter protocol (Q-11).

Before the `phase-3` tag exists the diff is tag `phase-2` → working tree (untracked files too);
after it, `phase-2` → `phase-3`, so later phases can change `core/` again.
"""

import re
import shutil
import subprocess

import pytest

from adapters.base import Adapter
from adapters.web_sim import WebSimAdapter
from tests.support import ROOT, decision

FROZEN = ("core/", "migrations/")
ALLOWED = (  # #101
    "adapters/web_sim.py",
    "api/chat.py",
    "api/ratelimit.py",
    "api/static/",
    "api/webhooks.py",
    "scripts/",
    "tests/",
    "testing/",
    "docs/",
    "notes/",
    "README.md",
    "CONTEXT.md",
    ".github/workflows/ci.yml",
)


def _git(*args: str) -> str:
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    result = subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _has_tag(tag: str) -> bool:
    return bool(_git("tag", "--list", tag).strip())


def changed_paths() -> set[str]:
    assert _has_tag("phase-2"), "tag phase-2 missing (CI: checkout with fetch-depth 0)"
    if _has_tag("phase-3"):
        return set(_git("diff", "--name-only", "phase-2", "phase-3").split())
    tracked = set(_git("diff", "--name-only", "phase-2").split())
    untracked = set(_git("ls-files", "--others", "--exclude-standard").split())
    return tracked | untracked


def webhooks_diff() -> str:
    end = ["phase-3"] if _has_tag("phase-3") else []
    return _git("diff", "-U0", "phase-2", *end, "--", "api/webhooks.py")


@decision(4, 16)
def test_p3_c03_no_change_in_core_or_migrations_since_phase_2() -> None:
    frozen = sorted(p for p in changed_paths() if p.startswith(FROZEN))
    assert frozen == [], f"core/migrations changed: fix the contract first and record it: {frozen}"


@decision(101)
def test_q15_plugin_cost_only_allowed_paths_changed() -> None:
    outside = sorted(p for p in changed_paths() if not p.startswith(ALLOWED))
    assert outside == [], f"phase 3 touched paths outside #101: {outside}"


@decision(101)
def test_q15_webhooks_change_is_only_the_wiring_line() -> None:
    lines = [
        line[1:].strip()
        for line in webhooks_diff().splitlines()
        if line[:1] in "+-" and not line.startswith(("+++", "---"))
    ]
    allowed = re.compile(r"(from api\.chat import mount_chat|.*create_app\(.*|.*mount_chat\(.*)")
    assert all(allowed.fullmatch(line) for line in lines if line), lines
    assert len(lines) <= 4


@decision(4)
def test_q11_web_chat_adapter_implements_the_protocol() -> None:
    members = [n for n in vars(Adapter) if not n.startswith("_")] + ["channel", "capabilities"]
    for name in members:
        assert hasattr(WebSimAdapter, name), f"WebSimAdapter lacks {name}"
    for name in ("parse", "render", "send", "authorized", "answer_tap", "confirm_tap"):
        assert callable(getattr(WebSimAdapter, name))


def test_every_phase_3_test_id_has_a_test() -> None:
    spec = (ROOT / "testing" / "phases" / "phase-3-plugin-and-seed.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"\bP3-[UC]\d+\b", spec))
    assert len(ids) >= 12
    code = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").rglob("*.py")).lower()
    missing = sorted(i for i in ids if i.lower().replace("-", "_") not in code)
    assert missing == []
