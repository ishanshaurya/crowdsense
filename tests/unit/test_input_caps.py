import pytest

from core.clock import ScriptedClock
from core.engine import MAX_TEXT, Engine, cap_inbound
from core.store_memory import InMemoryStore
from tests.support import ARTIST, NOW, decision, event


@decision(95)
def test_text_is_cut_to_1000_characters_and_short_text_is_untouched() -> None:
    assert cap_inbound(event("text", text="x" * 5000)).text == "x" * MAX_TEXT
    assert cap_inbound(event("text", text="Pune")).text == "Pune"
    assert cap_inbound(event("start")).text is None


@decision(3, 95)
@pytest.mark.parametrize(
    ("tag", "kept"),
    [
        ("ig_story", "ig_story"),
        ("A-z_09", "A-z_09"),
        ("x" * 64, "x" * 64),
        ("x" * 65, None),
        ("ig story", None),
        ("ig_story\n", None),
        ("🎤", None),
        ("<script>", None),
        ("", None),
    ],
)
async def test_p2_u12_source_tag_check(tag: str, kept: str | None) -> None:
    store = InMemoryStore()
    engine = Engine(store, ScriptedClock(NOW), artist_name=ARTIST)
    result = await engine.handle(event("start", source_tag=tag))
    (identity,) = await store.identities()
    assert identity.source_tag == kept
    assert [o.reply.step_id for o in result.replies] == ["consent"]
    assert not result.replies[0].reply.is_error
