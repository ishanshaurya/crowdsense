"""Code quality checks Q-04 to Q-08 and Q-10 (testing/quality/architecture-quality.md).

Q-01 (ruff), Q-02 (mypy), Q-03 (detect-secrets) and Q-09 (coverage gate) run as tools in
pre-commit and CI; Q-05 (import-linter) is run here too so `pytest` alone catches it.
"""

import ast
import builtins
import importlib.util
import random
import re
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from core import catalog, flow
from core.decide import decide
from core.types import FanState
from tests.support import (
    ARTIST,
    FULL_FLOW,
    NOW,
    ROOT,
    choose,
    event,
    load_yaml,
    start,
    venue_table,
)

CORE = sorted((ROOT / "core").glob("*.py"))
CODE_DIRS = ["core", "migrations", "scripts", "adapters", "api", "dashboard"]
PURE_MODULES = ["types", "catalog", "flow", "decide", "insights"]
MAX_FILE_LINES = 400
MAX_FUNCTION_LINES = 40
DECISIONS = (ROOT / "docs" / "decisions.md").read_text(encoding="utf-8")


def python_files(*dirs: str) -> list[Path]:
    return sorted(p for d in dirs for p in (ROOT / d).rglob("*.py") if ".venv" not in p.parts)


def decision_numbers() -> set[int]:
    bullets = re.findall(r"\*\*#(\d+)\*\*", DECISIONS)
    rows = re.findall(r"^\|\s*(\d+)\s*\|", DECISIONS, flags=re.MULTILINE)
    return {int(n) for n in [*bullets, *rows]}


def decision_line(number: int) -> str:
    bullet = re.search(rf"\*\*#{number}\*\*(.*)", DECISIONS)
    row = re.search(rf"^\|\s*{number}\s*\|(.*)", DECISIONS, flags=re.MULTILINE)
    match = bullet or row
    assert match, f"decision #{number} not found in docs/decisions.md"
    return match.group(1)


def test_q04_every_env_var_read_in_code_is_declared_with_a_placeholder() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    declared = dict(line.split("=", 1) for line in example if "=" in line)
    pattern = re.compile(
        r"environ(?:\.get)?\s*[(\[]\s*[\"']([A-Z][A-Z0-9_]+)[\"']|getenv\(\s*[\"']([A-Z_]+)"
    )
    read = set()
    for path in python_files(*CODE_DIRS):
        for groups in pattern.findall(path.read_text(encoding="utf-8")):
            read.update(g for g in groups if g)
    assert read, "expected at least DATABASE_URL to be read somewhere"
    assert read <= set(declared), f"undeclared env vars: {read - set(declared)}"
    for name, value in declared.items():
        assert "://" not in value and len(value) <= 40, f"{name} looks like a real value"


def test_q03_env_file_is_ignored_and_secret_baseline_exists() -> None:
    ignored = subprocess.run(["git", "check-ignore", "-q", ".env"], cwd=ROOT, check=False)
    assert ignored.returncode == 0
    assert (ROOT / ".secrets.baseline").exists()
    assert (ROOT / ".pre-commit-config.yaml").read_text().count("detect-secrets") >= 1


def test_q05_import_contracts_hold() -> None:
    code = "from importlinter.cli import lint_imports_command as run; run()"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_q06_decide_does_no_io_and_reads_no_clock_or_randomness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("decide touched the outside world")

    state = start(FanState()).state
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(random, "random", forbidden)
    monkeypatch.setattr(uuid, "uuid4", forbidden)
    monkeypatch.setattr(time, "time", forbidden)
    for _, value in FULL_FLOW:
        state = choose(state, value).state
    assert decide(state, event("text", text="hi"), NOW, artist=ARTIST, can_push=True).replies


@pytest.mark.parametrize("module", PURE_MODULES)
def test_q06_pure_modules_import_nothing_impure_and_never_call_now(module: str) -> None:
    tree = ast.parse((ROOT / "core" / f"{module}.py").read_text(encoding="utf-8"))
    impure = {
        "random",
        "uuid",
        "socket",
        "os",
        "time",
        "subprocess",
        "pathlib",
        "psycopg",
        "asyncio",
    }
    imported = {
        name.split(".")[0]
        for node in ast.walk(tree)
        for name in (
            [a.name for a in node.names]
            if isinstance(node, ast.Import)
            else [node.module or ""]
            if isinstance(node, ast.ImportFrom)
            else []
        )
    }
    assert imported.isdisjoint(impure), imported & impure
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert calls.isdisjoint({"now", "utcnow", "today"})


def test_q07_files_and_functions_stay_small() -> None:
    for path in python_files("core", "tests", "adapters", "api", "scripts", "dashboard"):
        assert len(path.read_text(encoding="utf-8").splitlines()) <= MAX_FILE_LINES, path
    for path in python_files("core", "adapters", "api", "scripts", "dashboard"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                length = (node.end_lineno or node.lineno) - node.lineno + 1
                assert length <= MAX_FUNCTION_LINES, f"{path.name}:{node.name} is {length} lines"


def test_q08_no_todo_without_an_issue_id() -> None:
    marker = "TO" + "DO"
    bare = re.compile(rf"{marker}(?!\(#\d+\))")
    offenders = [
        p.name
        for p in python_files("core", "migrations", "scripts", "tests")
        if p != Path(__file__) and bare.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


def test_q10_venue_table_matches_catalog_and_migration_seed() -> None:
    rows = venue_table()
    assert len(rows) == 14
    assert rows == [(v.city, v.name, v.capacity) for v in catalog.VENUES]
    spec = importlib.util.spec_from_file_location(
        "seed", ROOT / "migrations" / "versions" / "0002_seed_venues.py"
    )
    assert spec and spec.loader
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    assert [(city, name, cap) for _, city, name, cap in seed.VENUES] == rows


def test_q10_venue_names_have_no_type_words() -> None:
    words = re.compile(r"\b(arena|hall|club|stadium)\b", re.IGNORECASE)
    assert [v.name for v in catalog.VENUES if words.search(v.name)] == []


def test_q10_option_lists_match_decisions_20_to_22() -> None:
    cities = decision_line(20).split("Cities:")[1].split("(")[0].strip().split(", ")
    assert cities == list(catalog.CITIES)
    bands = decision_line(21).split("Budget bands:")[1].split("·")[0].strip().split(" / ")
    assert [b.casefold() for b in bands] == [o.label.casefold() for o in catalog.BUDGET_OPTIONS]
    groups = decision_line(22).split("Group size:")[1].split("·")[0].strip().split(" / ")
    assert groups == [o.label for o in catalog.GROUP_OPTIONS]


def test_q10_no_step_asks_timing() -> None:
    assert "timing" in decision_line(23).lower() and "removed" in decision_line(23).lower()
    for step in flow.STEPS:
        assert "timing" not in (step.id + step.prompt + (step.field or "")).lower()


def test_q10_every_decision_tag_exists_in_decisions_md() -> None:
    known = decision_numbers()
    assert {1, 20, 91} <= known
    used: dict[str, set[int]] = {}
    for path in python_files("tests"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and _called_decision(node):
                used.setdefault(path.name, set()).update(
                    a.value for a in node.args if isinstance(a, ast.Constant)
                )
    for scenario in (ROOT / "testing" / "scenarios").glob("*.yaml"):
        data = load_yaml(scenario.name)
        if isinstance(data, dict) and "decisions" in data:
            used[scenario.name] = set(data["decisions"])
    assert sum(len(v) for v in used.values()) > 20
    missing = {name: nums - known for name, nums in used.items() if nums - known}
    assert missing == {}


def _called_decision(node: ast.Call) -> bool:
    func = node.func
    return (isinstance(func, ast.Name) and func.id == "decision") or (
        isinstance(func, ast.Attribute) and func.attr == "decision"
    )


def test_every_phase_1_test_id_has_a_test() -> None:
    spec = (ROOT / "testing" / "phases" / "phase-1-core.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"\bP1-[USC]\d+\b", spec))
    assert len(ids) >= 50
    code = "\n".join(p.read_text(encoding="utf-8") for p in python_files("tests")).lower()
    missing = sorted(i for i in ids if i.lower().replace("-", "_") not in code)
    assert missing == []
