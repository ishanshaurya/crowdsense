"""Seed plan: deterministic (P3-U03), distribution rules (P3-U04), content rules (Q-16)."""

import os
import re
import subprocess
import sys
from collections import Counter
from datetime import timedelta

from core import flow
from core.catalog import CITIES, VENUES
from scripts import seed_plan
from scripts.seed_plan import CITY_SHARE, WEEKS, plan_fans
from tests.support import NOW, ROOT, decision

PLANS = plan_fans(20_000, 42, NOW)


@decision(40)
def test_p3_u03_same_seed_gives_the_same_fans() -> None:
    assert plan_fans(500, 7, NOW) == plan_fans(500, 7, NOW)
    assert plan_fans(500, 7, NOW) != plan_fans(500, 8, NOW)


@decision(40)
def test_p3_u03_same_seed_is_reproducible_across_processes() -> None:
    """Hash randomisation differs per process; the plan must not depend on it."""
    code = (
        "from scripts.seed_plan import plan_fans; from tests.support import NOW; "
        "print(repr(plan_fans(300, 42, NOW)))"
    )
    outputs = {
        subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, "PYTHONHASHSEED": str(salt)},
        ).stdout
        for salt in (1, 2)
    }
    assert len(outputs) == 1


@decision(40, 78)
def test_p3_u04_every_city_present_and_the_big_three_lead() -> None:
    counts = Counter(p.city for p in PLANS)
    assert set(counts) == set(CITIES) == set(CITY_SHARE)
    top = [city for city, _ in counts.most_common(3)]
    assert sorted(top) == sorted(["Mumbai", "Delhi NCR", "Bengaluru"])


@decision(40)
def test_p3_u04_jaipur_and_indore_rise_week_over_week() -> None:
    for city in ("Jaipur", "Indore"):
        weekly = Counter(p.week for p in PLANS if p.city == city)
        series = [weekly[w] for w in range(WEEKS)]
        assert series == sorted(series) and len(set(series)) == WEEKS, (city, series)


@decision(56)
def test_seeded_dates_fall_in_the_six_weeks_before_now() -> None:
    for plan in PLANS:
        assert NOW - timedelta(days=7 * WEEKS) <= plan.start < NOW - timedelta(minutes=30)
        last_turn = plan.start + timedelta(seconds=40 * len(plan.moves))
        assert last_turn < NOW


@decision(24, 39)
def test_p3_u04_venue_choices_belong_to_the_fans_city() -> None:
    city_of = {str(v.id): v.city for v in VENUES}
    for plan in PLANS:
        for _, step, value in plan.moves:
            if step == "venue" and value != "other":
                assert city_of[str(value)] == plan.city


def test_seed_outcomes_match_the_approved_rates() -> None:
    declined = sum(1 for p in PLANS if p.moves[0][2] == "no") / len(PLANS)
    finished = sum(1 for p in PLANS if p.moves[-1][1] in ("email", None)) / len(PLANS)
    assert 0.04 < declined < 0.06
    assert 0.80 < finished < 0.90


@decision(23, 24, 1)
def test_q16_seed_and_user_facing_text_follow_the_content_rules() -> None:
    type_words = re.compile(r"\b(arena|hall|club|stadium|auditorium|pub|bar)\b", re.IGNORECASE)
    timing = re.compile(r"\b(when|timing|date|weekend|weekday|evening|morning)\b", re.IGNORECASE)
    seed_text = list(seed_plan.VENUE_NOTES) + list(seed_plan.SOURCE_TAGS)
    assert [t for t in seed_text if type_words.search(t) or timing.search(t)] == []
    prompts = [s.prompt for s in flow.STEPS if s.id not in ("consent", "done")]
    assert [p for p in prompts if timing.search(p) or type_words.search(p)] == []
    script = (ROOT / "docs" / "message-script.md").read_text(encoding="utf-8")
    approved = re.search(r"\*\*#1\*\* Consent · _Bot text: (.+?)_ ·", script)
    assert approved is not None
    assert flow.CONSENT_TEXT.format(artist="Artist X") == approved.group(1)
