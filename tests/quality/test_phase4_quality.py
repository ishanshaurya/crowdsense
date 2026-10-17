"""Phase 4 checks: no logic in the UI (Q-17), dashboard imports (P4-C04), every P4 id tested."""

import ast
import inspect
import re
from pathlib import Path

import pytest

from core import insights
from tests.support import ROOT, decision

DASHBOARD = sorted((ROOT / "dashboard").glob("*.py"))
ALLOWED_CORE = {"core.store", "core.demand", "core.insights", "core.config", "core.catalog"}
ALLOWED_CORE |= {"core.clock", "core.sessions"}  # sign-in cookie token (survives a reload)
ALLOWED_CORE |= {"core.outbound"}  # phase 5: the preview is the text that is sent (#75, P5-U07)
SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|JOIN|WHERE|GROUP BY|ORDER BY|COUNT|SUM)\b")
MATH_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
MATH_CALLS = {
    "sum",
    "min",
    "max",
    "sorted",
    "round",
    "abs",
    "Counter",
    "mean",
    "median",
    "agg",
    "groupby",
    "pivot_table",
    "count",
    "len",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_dashboard_files_exist() -> None:
    assert {p.name for p in DASHBOARD} >= {"app.py", "views.py", "text.py"}


@decision(30, 57)
@pytest.mark.parametrize("path", DASHBOARD, ids=lambda p: p.name)
def test_q17_no_sql_in_dashboard(path: Path) -> None:
    hits = SQL.findall(path.read_text(encoding="utf-8"))
    assert hits == [], f"SQL in {path.name}: {hits}"
    assert not any(name.split(".")[0] in {"psycopg", "psycopg_pool"} for name in _imports(path))


@decision(30, 31)
@pytest.mark.parametrize("path", DASHBOARD, ids=lambda p: p.name)
def test_q17_no_math_on_rows_in_dashboard(path: Path) -> None:
    for node in ast.walk(_tree(path)):
        assert not isinstance(node, ast.AugAssign), f"{path.name}:{node.lineno} augmented math"
        if isinstance(node, ast.BinOp):
            assert not isinstance(node.op, MATH_OPS), f"{path.name}:{node.lineno} arithmetic"
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            assert name not in MATH_CALLS, f"{path.name}:{node.lineno} calls {name}()"


@decision(30, 31)
def test_q17_dashboard_uses_insights_types_not_rules() -> None:
    for path in DASHBOARD:
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom) and node.module == "core.insights":
                for alias in node.names:
                    assert not inspect.isfunction(getattr(insights, alias.name)), alias.name
            if isinstance(node, ast.Import):
                assert all(a.name != "core.insights" for a in node.names)


@decision(30)
@pytest.mark.parametrize("path", DASHBOARD, ids=lambda p: p.name)
def test_p4_c04_dashboard_imports_only_allowed_core_modules(path: Path) -> None:
    for name in _imports(path):
        top = name.split(".")[0]
        assert top not in {"adapters", "api", "scripts"}, name
        if top == "core":
            assert name in ALLOWED_CORE, name


def test_every_phase_4_test_id_has_a_test() -> None:
    spec = (ROOT / "testing" / "phases" / "phase-4-dashboard.md").read_text(encoding="utf-8")
    ids = set(re.findall(r"\bP4-[UC]\d+\b", spec))
    assert len(ids) == 18
    code = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "tests").rglob("*.py"))
    missing = sorted(i for i in ids if i.lower().replace("-", "_") not in code.lower())
    assert missing == []
