"""P4-C03, P4-C05, P4-C06, P4-U09, P4-U11: the Streamlit app on Postgres, as the read-only role.

`AppTest` runs the script in this process; caches are cleared around every test so each test reads
its own database (and the reader's pool is closed, `on_release`).
"""

import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from types import SimpleNamespace
from urllib.parse import urlsplit

import psycopg
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from core.clock import SystemClock
from core.engine import Engine
from core.outbound import today_ist
from core.store_postgres import PostgresStore
from dashboard import text as dashboard_text
from scripts import dashboard_role
from tests.component.helpers import flow, talk
from tests.component.test_dashboard_role import PASSWORD, role_url  # noqa: F401 (fixture)
from tests.conftest import url_of
from tests.support import ARTIST, ROOT, decision

APP = str(ROOT / "dashboard" / "app.py")
GATE = "gate-password-123"  # pragma: allowlist secret
VIEW_TITLES = {
    "Recommendations by city",
    "Top cities",
    "Top venues",
    "Budget bands",
    "Group sizes",
    "City × venue",
    "Response funnel",
    "Growth per city (IST weeks)",
    "Sources",
    "Latest fans",
}


def _clear() -> None:
    st.cache_data.clear()
    st.cache_resource.clear()


@pytest.fixture
def app(role_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[AppTest]:  # noqa: F811
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", role_url)
    monkeypatch.setenv("DASHBOARD_PASSWORD", GATE)
    _clear()
    yield AppTest.from_file(APP, default_timeout=30)
    _clear()


def sign_in(app: AppTest) -> AppTest:
    app.run()
    app.text_input[0].input(GATE)
    app.button[0].click().run()
    assert not app.exception, app.exception
    return app


def markdown(app: AppTest) -> str:
    return "\n".join(m.value for m in app.markdown)


@decision(60)
def test_gate_shows_nothing_until_the_password(app: AppTest) -> None:
    app.run()
    assert not app.subheader and not app.table and not app.sidebar.radio
    app.text_input[0].input("wrong-password-1")
    app.button[0].click().run()
    assert [e.value for e in app.error] == ["Wrong password."]
    assert not app.subheader


def test_missing_settings_name_the_variable_only(app: AppTest, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DASHBOARD_PASSWORD", "short")
    app.run()
    assert [e.value for e in app.error] == ["DASHBOARD_PASSWORD must be at least 12 characters"]


@decision(28, 106)
def test_p4_c05_every_view_renders(app: AppTest) -> None:
    sign_in(app)
    assert {s.value for s in app.subheader} == VIEW_TITLES
    assert "Play **Pune** first, at **Koregaon Park Lawns**" in markdown(app)
    assert "About **13 people** want to come" in markdown(app)
    assert not app.error


@decision(18, 73, 107)
def test_p4_u09_switch_defaults_to_simulated_and_changes_numbers(app: AppTest) -> None:
    sign_in(app)
    assert app.sidebar.radio[0].value == "simulated"
    assert ":orange-badge[Simulated data] **9 counted fans** (11 started)" in markdown(app)
    app.sidebar.radio[0].set_value("real").run()
    assert ":green-badge[Real] **1 counted fan** (2 started)" in markdown(app)
    assert "Simulated data" not in markdown(app)


@decision(18)
def test_p4_c06_simulated_badge_only_on_simulated_data(app: AppTest) -> None:
    sign_in(app)
    assert ":orange-badge[Simulated data]" in markdown(app)
    app.sidebar.radio[0].set_value("real").run()
    assert ":orange-badge" not in markdown(app) and ":green-badge[Real]" in markdown(app)


@decision(60)
def test_p4_u11_email_column_hidden_until_toggled(app: AppTest) -> None:
    sign_in(app)
    latest = app.table[0].value
    assert "Email" not in latest.columns
    app.sidebar.toggle[0].set_value(True).run()
    emails = list(app.table[0].value["Email"])
    assert emails.count("s1@example.com") == 1 and emails.count("") == 8  # blank, not "None"


@decision(28, 106)
async def test_p4_c03_new_fan_appears_after_refresh(app: AppTest, pg_migrated_url: str) -> None:
    sign_in(app)
    app.sidebar.radio[0].set_value("real").run()
    assert "**1 counted fan**" in markdown(app)
    store = PostgresStore(pg_migrated_url)
    await talk(
        Engine(store, SystemClock(), artist_name=ARTIST),
        "newfan01",
        flow("Indore", "14", "lt_1500", "2"),
    )
    await store.close()
    committed = time.monotonic()
    st.cache_data.clear()  # stands in for the 4 s cache expiring
    app.run()
    assert "**2 counted fans** (3 started)" in markdown(app)
    assert time.monotonic() - committed < 10


@decision(31)
def test_p4_u10_empty_database_shows_captions_not_blank_charts(
    pg_migrated_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with psycopg.connect(pg_migrated_url, autocommit=True) as admin:
        dashboard_role.apply(admin, PASSWORD)
    parts = urlsplit(pg_migrated_url)
    empty = url_of(
        parts.hostname or "",
        parts.port or 5432,
        "crowdsense_dashboard",
        PASSWORD,
        parts.path.lstrip("/"),
    )
    monkeypatch.setenv("DASHBOARD_DATABASE_URL", empty)
    monkeypatch.setenv("DASHBOARD_PASSWORD", GATE)
    _clear()
    app = sign_in(AppTest.from_file(APP, default_timeout=30))
    _clear()
    assert {s.value for s in app.subheader} == VIEW_TITLES
    assert [c.value for c in app.caption].count("Nothing in this view yet.") == len(VIEW_TITLES)
    assert "**0 counted fans** (0 started)" in markdown(app)


def _eligible_fan(url: str, user: str, city: str = "Indore") -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        fan_id = conn.execute(
            "INSERT INTO fans (city, completed_at, created_at, last_seen) "
            "VALUES (%s, now(), now(), now()) RETURNING id",
            (city,),
        ).fetchone()[0]  # type: ignore[index]
        conn.execute(
            "INSERT INTO identities (channel, external_user_id, fan_id, consent) "
            "VALUES ('telegram', %s, %s, true)",
            (user, fan_id),
        )


def _requests(url: str) -> list[tuple[object, ...]]:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT city, status FROM announcement_requests").fetchall()


def _announce_form(app: AppTest, city: str) -> AppTest:
    sign_in(app)
    app.selectbox(key="announce_city").set_value(city).run()
    assert not app.exception, app.exception
    return app


@decision(75, 80, 110)
def test_p5_u07_u08_preview_and_count_then_queue(app: AppTest, pg_migrated_url: str) -> None:
    _eligible_fan(pg_migrated_url, "a1")
    _eligible_fan(pg_migrated_url, "a2")
    _announce_form(app, "Indore")
    assert any("Will send to 2 fans" in m.value for m in app.markdown)
    assert any(t.value.startswith(f"{ARTIST} is coming to Indore.") for t in app.text)
    app.button(key="announce").click().run()
    assert [s.value for s in app.success] == [dashboard_text.QUEUED]
    assert _requests(pg_migrated_url) == [("Indore", "pending")]


@decision(41, 75, 112)
def test_p5_c03_double_click_is_refused_twice(app: AppTest, pg_migrated_url: str) -> None:
    _eligible_fan(pg_migrated_url, "a1")
    _announce_form(app, "Indore")
    app.button(key="announce").click().run()
    assert app.button(key="announce").disabled  # same session: the button locks
    with psycopg.connect(pg_migrated_url, autocommit=True) as conn:  # another session got in first
        conn.execute("DELETE FROM announcement_requests")
        conn.execute(
            "INSERT INTO announcement_requests (city, event_date) "
            "VALUES ('Indore', (now() AT TIME ZONE 'Asia/Kolkata')::date)"
        )
    app.session_state["announced"] = set()
    app.run()
    app.button(key="announce").click().run()
    assert [i.value for i in app.info] == [dashboard_text.ALREADY_QUEUED]
    assert len(_requests(pg_migrated_url)) == 1


@decision(15, 75)
def test_p5_c04_nobody_to_notify_disables_the_button(app: AppTest) -> None:
    _announce_form(app, "Jaipur")
    assert any(c.value == dashboard_text.NOBODY for c in app.caption)
    assert app.button(key="announce").disabled


@decision(75, 113)
def test_p5_u09_past_date_never_reaches_the_form(app: AppTest, pg_migrated_url: str) -> None:
    """Streamlit drops a value under `min_value`; the fan-out refuses past dates as well."""
    _eligible_fan(pg_migrated_url, "a1")
    _announce_form(app, "Indore")
    app.date_input(key="announce_date").set_value(date(2020, 1, 1)).run()
    today = today_ist(datetime.now(UTC))
    assert app.date_input(key="announce_date").value == today
    assert not any(e.value == dashboard_text.PAST_DATE for e in app.error)


@decision(60)
def test_a_reload_keeps_the_signed_in_browser_signed_in(
    app: AppTest, monkeypatch: pytest.MonkeyPatch
) -> None:
    sign_in(app)
    token = app.session_state["session_token"]
    assert app.sidebar.radio  # signed in
    # A reload is a new Streamlit session: no session_state, but the browser sends the cookie back.
    monkeypatch.setattr(st, "context", SimpleNamespace(cookies={"crowdsense_session": token}))
    reloaded = AppTest.from_file(APP, default_timeout=30).run()
    assert not reloaded.exception and reloaded.sidebar.radio and not reloaded.text_input
    monkeypatch.setattr(st, "context", SimpleNamespace(cookies={"crowdsense_session": "forged"}))
    forged = AppTest.from_file(APP, default_timeout=30).run()
    assert forged.text_input and not forged.sidebar.radio


@decision(60)
def test_sign_out_revokes_the_token(app: AppTest, monkeypatch: pytest.MonkeyPatch) -> None:
    sign_in(app)
    token = app.session_state["session_token"]
    next(b for b in app.sidebar.button if b.label == "Sign out").click().run()
    assert app.text_input  # back at the gate
    monkeypatch.setattr(st, "context", SimpleNamespace(cookies={"crowdsense_session": token}))
    again = AppTest.from_file(APP, default_timeout=30).run()
    assert again.text_input and not again.sidebar.radio
