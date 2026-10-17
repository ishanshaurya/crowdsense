"""Crowdsense dashboard (#28): password gate (#60), Simulated / Real (#73), live refresh (#106).

    uv run --env-file .env python -m streamlit run dashboard/app.py

Reads only through `core.demand` with the read-only role (#105). Streamlit only draws (Q-17).
"""

import hmac
import os
import time
from datetime import UTC, date, datetime

import streamlit as st

from core.catalog import CITIES
from core.clock import SystemClock
from core.config import ConfigError, DashboardSettings, load_dashboard_settings
from core.demand import DEFAULT_VIEW, VIEWS, DemandReader, DemandReport, View
from core.outbound import announcement_reply, audience_count, request_announcement, today_ist
from core.sessions import SESSION_SECONDS, SessionTokens
from core.store import StoreUnavailable
from dashboard import views
from dashboard.text import (
    ALREADY_QUEUED,
    ANNOUNCE_TITLE,
    NOBODY,
    PAST_DATE,
    QUEUED,
    VIEW_LABEL,
    will_send,
)

REFRESH_SECONDS = 5
CACHE_SECONDS = 4  # shared by every open tab: about one query batch per 5 s per view (#106)
FAILED_LOGIN_DELAY = 1.0
COOKIE = "crowdsense_session"


@st.cache_resource
def _settings() -> DashboardSettings:
    return load_dashboard_settings(os.environ)


@st.cache_resource(on_release=DemandReader.close)  # pool closed when the cache clears
def _reader() -> DemandReader:
    return DemandReader(_settings().database_url)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def _report(view: View, with_email: bool) -> DemandReport:
    return _reader().report(view, datetime.now(UTC), with_email=with_email)


@st.cache_resource
def _tokens() -> SessionTokens:
    return SessionTokens(SystemClock())


def _gate(password: str) -> bool:
    if st.session_state.get("signed_in"):
        return True
    cookie = st.context.cookies.get(COOKIE)
    if _tokens().valid(cookie):  # a reload or new tab starts a new session; the cookie bridges it
        st.session_state.signed_in = True
        st.session_state.session_token = cookie
        return True
    with st.form("gate"):
        typed = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if hmac.compare_digest(typed.encode(), password.encode()):
            st.session_state.signed_in = True
            st.session_state.session_token = _tokens().issue()
            st.rerun()
        time.sleep(FAILED_LOGIN_DELAY)  # slows guessing
        st.error("Wrong password.")
    return False


def _remember_browser() -> None:
    """Gives the browser its token (SameSite=Strict, Secure on https); never the password."""
    token = st.session_state.get("session_token")
    if token:
        st.html(
            f"<script>document.cookie = '{COOKIE}={token}; path=/; max-age={SESSION_SECONDS}; "
            "SameSite=Strict' + (location.protocol === 'https:' ? '; Secure' : '');</script>",
            unsafe_allow_javascript=True,
        )


def _sign_out() -> None:
    _tokens().revoke(st.session_state.get("session_token"))
    st.session_state.clear()
    st.html(
        f"<script>document.cookie = '{COOKIE}=; path=/; max-age=0';</script>",
        unsafe_allow_javascript=True,
    )


@st.fragment(run_every=REFRESH_SECONDS)
def _live(view: View, show_emails: bool) -> None:
    try:
        report = _report(view, show_emails)
    except StoreUnavailable:
        st.error("The database cannot be reached. Retrying every few seconds.")
        return
    views.draw_all(report, show_emails)


def _announce(settings: DashboardSettings) -> None:
    """#75: the form only asks; the webhook service builds the audience and sends (#80).

    The database refuses a second request for a city and date; the button is also disabled for
    that pair once clicked in this session.
    """
    with st.expander(ANNOUNCE_TITLE):
        today = today_ist(datetime.now(UTC))
        city = st.selectbox("City", CITIES, key="announce_city")
        day = st.date_input("Tickets open", value=today, min_value=today, key="announce_date")
        if not isinstance(day, date):
            return
        try:
            with _reader().snapshot() as conn:
                count = audience_count(conn, city)
        except StoreUnavailable:
            st.error("The database cannot be reached. Try again in a moment.")
            return
        st.text(announcement_reply(settings.artist_name, city, day).text)  # plain, not markdown
        st.write(will_send(count))
        if count == 0:
            st.caption(NOBODY)
        if day < today:
            st.error(PAST_DATE)
        asked: set[tuple[str, date]] = st.session_state.setdefault("announced", set())
        blocked = count == 0 or day < today or (city, day) in asked
        st.button(
            "Send announcement", disabled=blocked, key="announce", on_click=_send, args=(city, day)
        )
        queued = st.session_state.pop("announce_queued", None)
        if queued is True:
            st.success(QUEUED)
        elif queued is False:
            st.info(ALREADY_QUEUED)


def _send(city: str, day: date) -> None:
    """Runs before the rerun, so the button is already disabled when the page redraws."""
    st.session_state.setdefault("announced", set()).add((city, day))
    try:
        with _reader().snapshot() as conn:
            st.session_state.announce_queued = request_announcement(conn, city, day)
    except StoreUnavailable:
        st.session_state.announced.discard((city, day))  # nothing was queued: allow a retry
        st.toast("The database cannot be reached. Try again in a moment.")


def main() -> None:
    st.set_page_config(page_title="Crowdsense", page_icon="🎤", layout="wide")
    st.title("Crowdsense")
    try:
        settings = _settings()
    except ConfigError as error:
        st.error(str(error))  # names the variable, never its value
        st.stop()
    if not _gate(settings.password):
        st.stop()
    _remember_browser()
    with st.sidebar:
        view = st.radio(
            "Data", VIEWS, index=VIEWS.index(DEFAULT_VIEW), format_func=VIEW_LABEL.get, key="view"
        )
        show_emails = st.toggle("Show emails (this session only)", value=False, key="emails")
        st.button("Sign out", on_click=_sign_out)
    _live(view, show_emails)
    _announce(settings)


main()
