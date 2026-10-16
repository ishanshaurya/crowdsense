"""Crowdsense dashboard (#28): password gate (#60), Simulated / Real (#73), live refresh (#106).

    uv run --env-file .env python -m streamlit run dashboard/app.py

Reads only through `core.demand` with the read-only role (#105). Streamlit only draws (Q-17).
"""

import hmac
import os
import time
from datetime import UTC, datetime

import streamlit as st

from core.config import ConfigError, DashboardSettings, load_dashboard_settings
from core.demand import DEFAULT_VIEW, VIEWS, DemandReader, DemandReport, View
from core.store import StoreUnavailable
from dashboard import views
from dashboard.text import VIEW_LABEL

REFRESH_SECONDS = 5
CACHE_SECONDS = 4  # shared by every open tab: about one query batch per 5 s per view (#106)
FAILED_LOGIN_DELAY = 1.0


@st.cache_resource
def _settings() -> DashboardSettings:
    return load_dashboard_settings(os.environ)


@st.cache_resource(on_release=DemandReader.close)  # pool closed when the cache clears
def _reader() -> DemandReader:
    return DemandReader(_settings().database_url)


@st.cache_data(ttl=CACHE_SECONDS, show_spinner=False)
def _report(view: View, with_email: bool) -> DemandReport:
    return _reader().report(view, datetime.now(UTC), with_email=with_email)


def _gate(password: str) -> bool:
    if st.session_state.get("signed_in"):
        return True
    with st.form("gate"):
        typed = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")
    if submitted:
        if hmac.compare_digest(typed.encode(), password.encode()):
            st.session_state.signed_in = True
            st.rerun()
        time.sleep(FAILED_LOGIN_DELAY)  # slows guessing
        st.error("Wrong password.")
    return False


@st.fragment(run_every=REFRESH_SECONDS)
def _live(view: View, show_emails: bool) -> None:
    try:
        report = _report(view, show_emails)
    except StoreUnavailable:
        st.error("The database cannot be reached. Retrying every few seconds.")
        return
    views.draw_all(report, show_emails)


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
    with st.sidebar:
        view = st.radio(
            "Data", VIEWS, index=VIEWS.index(DEFAULT_VIEW), format_func=VIEW_LABEL.get, key="view"
        )
        show_emails = st.toggle("Show emails (this session only)", value=False, key="emails")
    _live(view, show_emails)


main()
