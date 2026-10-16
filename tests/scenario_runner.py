"""Runs the YAML conversation scenarios (testing/README.md "Scenario format") against an engine."""

from typing import Any

from core.engine import Engine, TurnResult
from core.store import Store
from core.types import EventKind, Option
from tests.support import event, load_yaml

COMMANDS: dict[str, EventKind] = {
    "/start": "start",
    "/stop": "stop",
    "/delete": "delete",
    "/help": "help",
}
SPECIAL_KEYS = {"count", "count_for_field", "count_for_msg_id"}


class Chat:
    """One fan talking to the engine; remembers the last buttons so labels map to choice ids."""

    def __init__(self, engine: Engine, *, channel: str = "telegram", user: str = "u1") -> None:
        self.engine = engine
        self.channel = channel
        self.user = user
        self.options: tuple[Option, ...] = ()
        self.options_step: str | None = None
        self._sent = 0

    async def send(self, spec: dict[str, Any]) -> TurnResult:
        self._sent += 1
        msg_id = spec.get("msg_id", f"auto{self._sent}")
        result = await self.engine.handle(self._event(spec, msg_id))
        for out in result.replies:
            if out.reply.options is not None:
                self.options, self.options_step = out.reply.options, out.reply.step_id
        await self.engine.mark_sent(result.replies)
        return result

    def _event(self, spec: dict[str, Any], msg_id: str):  # type: ignore[no-untyped-def]
        common = {"msg_id": msg_id, "user": self.user, "channel": self.channel}
        kind, value = spec["kind"], spec.get("value")
        if kind == "start":
            return event("start", source_tag=spec.get("source_tag"), **common)
        if kind == "command":
            return event(COMMANDS[value], **common)
        if kind == "text":
            return event("text", text=value, **common)
        label_to_id = {o.label: o.id for o in self.options}
        return event(
            "choice",
            choice_id=label_to_id.get(value, value),
            choice_step=self.options_step,
            **common,
        )


def check_expect(result: TurnResult, expect: dict[str, Any]) -> None:
    if expect.get("no_reply"):
        assert result.replies == ()
    else:
        last = result.replies[-1].reply
        assert last.step_id == expect["step"]
        assert last.is_error == bool(expect.get("error")), last
        labels = [o.label for o in last.options or ()]
        if "options" in expect:
            assert labels == expect["options"]
        if "options_count" in expect:
            assert len(labels) == expect["options_count"]
        if "text_contains" in expect:
            assert expect["text_contains"] in last.text
    assert result.duplicate == bool(expect.get("duplicate"))


async def play(chat: Chat, scenario_id: str, *, stop_before: str | None = None) -> None:
    scenario = load_yaml(f"{scenario_id}.yaml")
    if "setup" in scenario:
        setup = scenario["setup"]
        await play(chat, setup["scenario"], stop_before=setup.get("stop_before"))
    for turn in scenario["steps"]:
        result = await chat.send(turn["send"])
        check_expect(result, turn["expect"])
        if stop_before and turn["expect"].get("step") == stop_before:
            return


async def tables(store: Store) -> dict[str, list[dict[str, Any]]]:
    fans, identities = await store.fans(), await store.identities()
    consent_of = {i.fan_id: i.consent for i in identities}
    venue_of = {v.id: v.name for v in await store.venues()}
    return {
        "fans": [
            {**vars(f), "venue": venue_of.get(f.venue_id), "consent": consent_of.get(f.id)}
            for f in fans
        ],
        "identities": [vars(i) for i in identities],
        "sessions": [vars(s) for s in await store.sessions()],
        "answers": [vars(a) for a in await store.answers()],
        "events": [vars(e) for e in await store.events()],
        "replies": [vars(r) for r in await store.replies()],
    }


async def check_final_db(store: Store, final_db: dict[str, Any]) -> None:
    rows_by_table = await tables(store)
    for name, expected in final_db.items():
        rows = rows_by_table[name]
        if expected == "none":
            assert rows == [], name
            continue
        _check_counts(name, rows, expected)
        columns = {k: v for k, v in expected.items() if k not in SPECIAL_KEYS}
        if columns:
            assert len(rows) == 1, f"{name}: expected one row, got {len(rows)}"
            for column, value in columns.items():
                assert rows[0][column] == value, (
                    f"{name}.{column}: {rows[0][column]!r} != {value!r}"
                )


def _check_counts(name: str, rows: list[dict[str, Any]], expected: dict[str, Any]) -> None:
    if "count" in expected:
        assert len(rows) == expected["count"], name
    for field, count in expected.get("count_for_field", {}).items():
        assert sum(1 for r in rows if r["field"] == field) == count, field
    for msg_id, count in expected.get("count_for_msg_id", {}).items():
        assert sum(1 for r in rows if r["external_msg_id"] == msg_id) == count, msg_id


async def run_scenario(engine: Engine, store: Store, scenario_id: str) -> Chat:
    chat = Chat(engine)
    await play(chat, scenario_id)
    await check_final_db(store, load_yaml(f"{scenario_id}.yaml")["final_db"])
    return chat
