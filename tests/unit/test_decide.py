import pytest

from core import flow
from core.catalog import BUDGET_OPTIONS, GROUP_OPTIONS
from core.decide import decide
from core.insights import PEOPLE_PER_GROUP
from core.types import (
    DeleteFan,
    FanState,
    MarkCompleted,
    SaveAnswer,
    SetConsent,
    SetOptedOut,
)
from tests.support import (
    ARTIST,
    FULL_FLOW,
    NOW,
    choose,
    decision,
    event,
    finished_fan,
    say,
    start,
    step,
    walk,
)

BAND_IDS = [o.id for o in BUDGET_OPTIONS]


def labels(decision_) -> list[str]:  # type: ignore[no-untyped-def]
    return [o.label for o in decision_.replies[-1].options or ()]


def at(step_id: str) -> FanState:
    """A fan sitting on `step_id`, reached through the real flow."""
    state = start(FanState()).state
    for _, value in FULL_FLOW:
        if state.step_id == step_id:
            return state
        state = choose(state, value).state
    return state


@decision(36)
def test_p1_u01_consent_yes_moves_to_city() -> None:
    first = start(FanState())
    assert first.replies[0].step_id == "consent"
    assert "Get updates when Artist X plays near you" in first.replies[0].text
    result = choose(first.state, "yes")
    assert result.state.step_id == "city"
    assert result.state.consent is True
    assert result.writes == (SetConsent(True),)
    assert len(result.replies[0].options or ()) == 10


@decision(36)
def test_p1_u02_consent_no_saves_only_the_decline() -> None:
    result = choose(start(FanState()).state, "no")
    assert result.replies[0].step_id == "declined"
    assert result.writes == (SetConsent(False),)
    assert result.state.consent is False
    assert result.state.answers == {}


@decision(36)
def test_p1_u03_text_at_consent_re_asks_consent() -> None:
    state = start(FanState()).state
    result = say(state, "hello there")
    assert result.replies[0].is_error
    assert result.replies[0].step_id == "consent"
    assert [o.id for o in result.replies[0].options or ()] == ["yes", "no"]
    assert result.state == state
    assert result.writes == ()


@decision(24, 25)
def test_p1_u04_venue_step_lists_only_the_cities_venues() -> None:
    state = at("city")
    pune = choose(state, "Pune")
    assert labels(pune) == ["Baner Greens", "Koregaon Park Lawns", "Other / not listed"]
    mumbai = choose(state, "Mumbai")
    assert labels(mumbai) == ["Mahalaxmi Maidan", "Bandra Waterfront", "Other / not listed"]


@decision(27)
def test_p1_u05_other_venue_stores_note_and_leaves_venue_empty() -> None:
    other = choose(at("venue"), flow.OTHER)
    assert other.replies[0].step_id == "venue_note"
    assert other.writes == ()
    noted = say(other.state, "near the airport")
    assert noted.writes == (SaveAnswer("venue_note", "near the airport"),)
    assert "venue" not in noted.state.answers
    assert noted.state.step_id == "budget"


@decision(13)
def test_p1_u06_unknown_choice_re_asks_and_saves_nothing() -> None:
    state = at("city")
    for result in (choose(state, "Atlantis"), say(state, "Atlantis")):
        assert result.replies[0].is_error
        assert result.replies[0].step_id == "city"
        assert result.writes == ()
        assert result.state == state


@decision(33)
@pytest.mark.parametrize(("code", "people"), [("1", 1), ("2", 2), ("3_5", 4), ("6_plus", 6)])
def test_p1_u07_group_codes_map_to_people(code: str, people: int) -> None:
    result = choose(at("group"), code)
    assert result.writes == (SaveAnswer("group_size", code),)
    assert PEOPLE_PER_GROUP[code] == people
    assert [o.id for o in GROUP_OPTIONS] == list(PEOPLE_PER_GROUP)


@decision(36)
def test_p1_u09_email_skip_invalid_valid() -> None:
    state = at("email")
    skipped = choose(state, flow.SKIP)
    assert skipped.replies[0].step_id == "done"
    assert skipped.writes == (MarkCompleted(NOW),)
    for bad in ("not-an-email", "a@b", "two words@x.com", ""):
        assert say(state, bad).replies[0].is_error
    valid = say(state, " fan@example.com ")
    assert valid.writes == (SaveAnswer("email", "fan@example.com"), MarkCompleted(NOW))
    assert valid.replies[0].step_id == "done"


@decision(36)
def test_p1_u10_stop_works_at_every_step_then_goes_quiet() -> None:
    states = [FanState(), start(FanState()).state]
    state = states[1]
    for _, value in FULL_FLOW:
        state = choose(state, value).state
        states.append(state)
    for state in states:
        stopped = step(state, "stop")
        assert stopped.writes == (SetOptedOut(True),)
        assert [r.step_id for r in stopped.replies] == ["stopped"]
        assert stopped.state.opted_out
        assert say(stopped.state, "Pune").replies == ()
        assert step(stopped.state, "stop").replies == ()


@decision(36)
def test_p1_u11_delete_and_help() -> None:
    state = at("budget")
    deleted = step(state, "delete")
    assert deleted.writes == (DeleteFan(),)
    assert deleted.replies[0].step_id == "deleted"
    helped = step(state, "help")
    assert helped.writes == ()
    assert "/stop" in helped.replies[0].text and "/delete" in helped.replies[0].text
    assert ARTIST in helped.replies[0].text


@decision(23, 94)
def test_p1_u12_flow_is_complete() -> None:
    reachable, queue = set(), ["consent"]
    while queue:
        step_id = queue.pop()
        if step_id in reachable or step_id not in flow.STEP_BY_ID:
            continue
        reachable.add(step_id)
        current = flow.STEP_BY_ID[step_id]
        queue += [current.next, current.edit_next, *current.branches.values()]
    assert reachable == set(flow.STEP_BY_ID)
    from core.store import SNAPSHOT_COLUMNS
    from core.types import ANSWER_FIELDS

    fields = {s.field for s in flow.STEPS if s.field}
    assert fields <= set(ANSWER_FIELDS) == set(SNAPSHOT_COLUMNS)
    assert not any("timing" in (s.id + s.prompt + (s.field or "")).lower() for s in flow.STEPS)
    assert not any("interest" in (s.id + (s.field or "")).lower() for s in flow.STEPS)
    assert "Would you actually come?" not in {s.prompt for s in flow.STEPS}
    assert len(flow._city_options({})) == 10
    assert (len(BUDGET_OPTIONS), len(GROUP_OPTIONS)) == (4, 4)


@decision(41)
def test_p1_u13_decide_is_deterministic() -> None:
    state = at("group")
    moves = [event("choice", choice_id="3_5", choice_step="group"), event("text", text="x")]
    for move in moves:
        first = decide(state, move, NOW, artist=ARTIST, can_push=True)
        assert first == decide(state, move, NOW, artist=ARTIST, can_push=True)


@decision(36)
def test_p1_u14_returning_fan_sees_menu_and_edit_returns_to_done() -> None:
    fan = finished_fan()
    menu = start(fan)
    assert labels(menu) == ["City", "Venue", "Budget", "Group", "All good"]
    assert "Baner Greens" in menu.replies[0].text
    asked = choose(menu.state, "budget")
    assert asked.replies[0].step_id == "budget"
    edited = choose(asked.state, "3000_6000")
    assert edited.writes == (SaveAnswer("budget_band", "3000_6000"),)
    assert edited.replies[0].step_id == "done"
    assert choose(menu.state, "done").replies[0].step_id == "done"


@decision(25)
def test_p1_u15_edit_city_clears_venue_and_re_asks() -> None:
    fan = start(finished_fan()).state
    asked = choose(fan, "city").state
    changed = choose(asked, "Mumbai")
    assert changed.writes == (SaveAnswer("city", "Mumbai"), SaveAnswer("venue", None))
    assert changed.replies[0].step_id == "venue"
    assert labels(changed) == ["Mahalaxmi Maidan", "Bandra Waterfront", "Other / not listed"]
    same = choose(asked, "Pune")
    assert same.writes == ()
    assert same.replies[0].step_id == "done"


@decision(70)
def test_p1_u31_edit_never_uncounts_a_completed_fan() -> None:
    fan = finished_fan()
    state = fan
    for kind, value in (("start", ""), ("choice", "city"), ("choice", "Mumbai")):
        result = start(state) if kind == "start" else choose(state, value)
        assert not any(isinstance(w, MarkCompleted) for w in result.writes)
        state = result.state
        assert state.completed


@decision(84)
def test_p1_u33_furthest_step_never_moves_back() -> None:
    fan = finished_fan()
    assert fan.furthest_step == "done"
    state = choose(start(fan).state, "city").state
    assert state.step_id == "city"
    assert state.furthest_step == "done"
    assert choose(state, "Mumbai").state.furthest_step == "done"
    assert at("budget").furthest_step == "budget"
    assert choose(start(FanState()).state, "no").state.furthest_step == "consent"


@decision(91)
def test_p1_u34_stale_tap_changes_nothing() -> None:
    state = at("budget")
    result = step(state, "choice", choice_id="Mumbai", choice_step="city")
    assert result.state == state
    assert result.writes == ()
    assert result.replies[0].is_error
    assert result.replies[0].text == flow.STALE_TEXT


@decision(36)
def test_declined_fan_is_asked_again_on_start() -> None:
    declined = choose(start(FanState()).state, "no").state
    assert say(declined, "hi").replies[0].step_id == "declined"
    again = start(declined)
    assert again.replies[0].step_id == "consent"
    assert again.writes == (SetConsent(None),)
    assert again.state.consent is None


@decision(36)
def test_start_after_stop_resubscribes_and_resumes() -> None:
    state = step(at("budget"), "stop").state
    resumed = start(state)
    assert resumed.writes == (SetOptedOut(False),)
    assert resumed.replies[0].step_id == "budget"
    assert not resumed.state.opted_out


@decision(13)
def test_free_text_step_rejects_a_tap_and_choice_step_rejects_odd_text() -> None:
    note_state = choose(at("venue"), flow.OTHER).state
    tapped = choose(note_state, "anything")
    assert tapped.replies[0].is_error and tapped.replies[0].step_id == "venue_note"
    assert say(note_state, "   ").replies[0].is_error
    assert say(at("budget"), "cheap").replies[0].is_error


@decision(36)
def test_typed_label_works_like_a_tap_for_text_only_channels() -> None:
    state = at("city")
    assert say(state, "pune").state.answers == {"city": "Pune"}
    assert say(at("email"), "Skip").replies[0].step_id == "done"
    assert say(start(FanState()).state, "Count me in").state.consent is True


@decision(87)
def test_done_message_depends_on_push_capability() -> None:
    state = at("email")
    pushed = step(state, "choice", choice_id="skip", choice_step="email", can_push=True)
    quiet = step(state, "choice", choice_id="skip", choice_step="email", can_push=False)
    assert "We'll message you" in pushed.replies[0].text
    assert "We'll message you" not in quiet.replies[0].text


@decision(36)
def test_completed_fan_is_marked_completed_once() -> None:
    fan = finished_fan()
    assert fan.completed
    again = choose(start(fan).state, "done")
    assert again.writes == ()


@decision(36)
def test_walk_full_flow_collects_every_answer() -> None:
    assert walk(start(FanState()).state, *FULL_FLOW).answers == {
        "city": "Pune",
        "venue": "8",
        "budget_band": "1500_3000",
        "group_size": "3_5",
    }
