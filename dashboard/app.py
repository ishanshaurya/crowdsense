"""Crowdsense dashboard (#28): password gate (#60), Simulated / Real (#73), live refresh (#106).

Four pages (Dashboard, Analytics, Cities & Venues, Announcements) behind one sidebar. A page
refreshes itself; "Announce a show" opens one dialog from the header or from a ranked row.

    uv run --env-file .env python -m streamlit run dashboard/app.py

Reads only through `core.demand` with the read-only role (#105). Streamlit only draws (Q-17).
"""

import hmac
import os
import time
from collections.abc import Callable
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path

import streamlit as st

from core.catalog import CITIES
from core.clock import SystemClock
from core.config import ConfigError, DashboardSettings, load_dashboard_settings
from core.demand import DEFAULT_VIEW, VIEWS, DemandReader, DemandReport, View
from core.outbound import (
    announcement_history,
    announcement_reply,
    audience_count,
    request_announcement,
    today_ist,
)
from core.sessions import SESSION_SECONDS, SessionTokens
from core.store import StoreUnavailable
from dashboard import views
from dashboard.text import (
    ALREADY_QUEUED,
    ANNOUNCE_TITLE,
    NOBODY,
    PAST_DATE,
    QUEUED,
    STATUS_LABEL,
    VIEW_LABEL,
    will_send,
)

REFRESH_SECONDS = 5
CACHE_SECONDS = 4  # shared by every open tab: about one query batch per 5 s per view (#106)
FAILED_LOGIN_DELAY = 1.0
COOKIE = "crowdsense_session"
STYLE = Path(__file__).with_name("style.css")


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
def _live(view: View, show_emails: bool, draw: Callable[[DemandReport, bool], None]) -> None:
    try:
        report = _report(view, show_emails)
    except StoreUnavailable:
        st.error("The database cannot be reached. Retrying every few seconds.")
        return
    views.draw_banner(report)
    draw(report, show_emails)


def _announce_form(settings: DashboardSettings) -> None:
    """#75: the form only asks; the webhook service builds the audience and sends (#80).

    The database refuses a second request for a city and date; the button is also disabled for
    that pair once clicked in this session.
    """
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


@st.dialog(ANNOUNCE_TITLE)
def _announce_dialog(settings: DashboardSettings) -> None:
    _announce_form(settings)


def _plan_show(city: str) -> None:
    """A ranked row's button: remember the city, then redraw the whole page to open the dialog."""
    st.session_state.plan_city = city
    st.rerun()


def _top_city() -> str | None:
    try:
        ranked = _report(st.session_state.view, st.session_state.emails).overview.ranked
    except StoreUnavailable:
        return None
    return ranked[0].city if ranked else None


def _header(title: str, subtitle: str, *, announce: bool) -> None:
    text, action = st.columns([5, 2], vertical_alignment="center")
    text.markdown(f"# {title}\n{subtitle}")
    if announce and action.button("Announce a show", key="open_announce", type="tertiary"):
        st.session_state.plan_city = _top_city() or CITIES[0]  # the hero's pick, editable


def _open_dialog(settings: DashboardSettings) -> None:
    city = st.session_state.pop("plan_city", None)
    if city is not None:
        st.session_state.announce_city = city
        _announce_dialog(settings)


def _page(title: str, subtitle: str, draw: Callable[[DemandReport, bool], None]) -> None:
    settings = _settings()
    _header(title, subtitle, announce=True)
    _live(st.session_state.view, st.session_state.emails, draw)
    _open_dialog(settings)


def _dashboard() -> None:
    settings = _settings()
    _page(settings.artist_name, "Fan demand overview", _draw_dashboard)


def _draw_dashboard(report: DemandReport, _show_emails: bool) -> None:
    views.draw_dashboard(report, _plan_show, CITIES_PAGE)


def _analytics() -> None:
    _page(
        "Analytics",
        "Who your fans are, where they drop off and how demand grows.",
        views.draw_analytics,
    )


def _cities_venues() -> None:
    _page("Cities & Venues", "Where fans are and which rooms fit them.", _draw_cities_venues)


def _draw_cities_venues(report: DemandReport, _show_emails: bool) -> None:
    views.draw_cities_venues(report)


def _announcements() -> None:
    settings = _settings()
    _header("Announcements", "Tell fans in one city when tickets open.", announce=False)
    _, centre, _ = st.columns([1, 2, 1])
    with centre:
        with st.container(border=True):
            st.subheader(ANNOUNCE_TITLE)
            _announce_form(settings)
        with st.container(border=True):
            st.subheader("Sent and queued")
            _history()


def _history() -> None:
    try:
        with _reader().snapshot() as conn:
            rows = announcement_history(conn)
    except StoreUnavailable:
        st.error("The database cannot be reached. Try again in a moment.")
        return
    if not rows:
        st.caption("Nothing sent yet.")
        return
    st.dataframe(
        [
            {
                "City": r.city,
                "Tickets open": r.event_date,
                "Status": STATUS_LABEL.get(r.status, r.status),
                "Fans": r.recipients,
            }
            for r in rows
        ],
        hide_index=True,
    )


CITIES_PAGE = st.Page(
    _cities_venues, title="Cities & Venues", icon=":material/location_on:", url_path="cities-venues"
)
PAGES = [
    st.Page(
        _dashboard,
        title="Dashboard",
        icon=":material/space_dashboard:",
        url_path="dashboard",
        default=True,
    ),
    st.Page(_analytics, title="Analytics", icon=":material/bar_chart:", url_path="analytics"),
    CITIES_PAGE,
    st.Page(
        _announcements, title="Announcements", icon=":material/campaign:", url_path="announcements"
    ),
]


def _sidebar(settings: DashboardSettings) -> None:
    with st.sidebar:
        st.markdown(
            '<div class="brand"><b>CrowdSense</b><br><span>Fan demand intelligence</span></div>',
            unsafe_allow_html=True,
        )
        for page in PAGES:
            st.page_link(page)
        st.divider()
        st.radio(
            "Data", VIEWS, index=VIEWS.index(DEFAULT_VIEW), format_func=VIEW_LABEL.get, key="view"
        )
        st.toggle("Show emails (this session only)", value=False, key="emails")
        name = escape(settings.artist_name)
        st.markdown(
            f'<div class="artist-card"><b>{name}</b><br><span>Artist account</span></div>',
            unsafe_allow_html=True,
        )
        st.button("Sign out", on_click=_sign_out)


def main() -> None:
    st.set_page_config(page_title="Crowdsense", page_icon=":material/graphic_eq:", layout="wide")
    st.html(f"<style>{STYLE.read_text(encoding='utf-8')}</style>")
    try:
        settings = _settings()
    except ConfigError as error:
        st.error(str(error))  # names the variable, never its value
        st.stop()
    if not _gate(settings.password):
        st.stop()
    _remember_browser()
    _sidebar(settings)
    st.navigation(PAGES, position="hidden").run()


main()
