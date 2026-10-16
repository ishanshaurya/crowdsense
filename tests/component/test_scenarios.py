import pytest

from core.engine import Engine
from core.store import Store
from tests.scenario_runner import run_scenario
from tests.support import decision, load_yaml

OTHER_SCENARIOS = [
    "decline_consent",
    "stop_command",
    "delete_command",
    "bad_input_then_ok",
    "other_venue",
    "returning_fan_edit",
    "email_validation",
    "edit_city_clears_venue",
]


def with_decisions(name: str) -> object:
    return pytest.param(name, id=name, marks=decision(*load_yaml(f"{name}.yaml")["decisions"]))


@decision(4, 11, 12)
async def test_p1_c01_happy_path_pune(engine: Engine, store: Store) -> None:
    await run_scenario(engine, store, "happy_path_pune")


@decision(41)
async def test_p1_c02_duplicate_message(engine: Engine, store: Store) -> None:
    await run_scenario(engine, store, "duplicate_message")


@pytest.mark.parametrize("name", [with_decisions(n) for n in OTHER_SCENARIOS])
async def test_p1_c13_scenarios(engine: Engine, store: Store, name: str) -> None:
    await run_scenario(engine, store, name)
