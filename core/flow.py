"""The conversation as data (docs/architecture.md §5, docs/message-script.md).

Wording of #2 to #17 is draft (#38).
"""

import dataclasses
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from core.catalog import BUDGET_OPTIONS, CITIES, GROUP_OPTIONS, VENUES
from core.types import Expects, Option

FLOW_ID = "main"
OTHER = "other"
SKIP = "skip"

CONSENT_TEXT = (
    "Hi! Get updates when {artist} plays near you. Answer a few quick questions so we can "
    "plan the right shows. Reply /stop any time to opt out."
)
DECLINED_TEXT = "No problem. Message me any time."
DONE_PUSH_TEXT = "You're in! We'll message you when {artist} announces a show near you."
DONE_NO_PUSH_TEXT = "You're in! Thanks for telling us."
EDIT_MENU_TEXT = "Welcome back! Want to update anything?"
INVALID_CHOICE_TEXT = "Please tap one of the options."
STALE_TEXT = "That question has passed."
STOPPED_TEXT = "You're unsubscribed."
DELETED_TEXT = "Your data is deleted."
APOLOGY_TEXT = "Something went wrong, please tap again"  # sent directly, never stored (#71)
HELP_TEXT = (
    "I ask a few questions so {artist} can plan shows near you. "
    "/stop unsubscribes you, /delete erases everything I stored about you, "
    "/start picks up where you left off."
)

CONSENT_OPTIONS = (Option("yes", "Count me in"), Option("no", "No thanks"))
EDIT_OPTIONS = (
    Option("city", "City"),
    Option("venue", "Venue"),
    Option("budget", "Budget"),
    Option("group", "Group"),
    Option("done", "All good"),
)

OptionsFn = Callable[[Mapping[str, str]], tuple[Option, ...]]
Validator = Callable[[str], str | None]

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_TEXT = 200


def _city_options(_: Mapping[str, str]) -> tuple[Option, ...]:
    return tuple(Option(city, city) for city in CITIES)


def _venue_options(answers: Mapping[str, str]) -> tuple[Option, ...]:
    city = answers.get("city")
    listed = tuple(Option(str(v.id), v.name) for v in VENUES if v.city == city)
    return (*listed, Option(OTHER, "Other / not listed"))


def _static(options: tuple[Option, ...]) -> OptionsFn:
    return lambda _: options


def valid_email(text: str) -> str | None:
    value = text.strip()
    return value if len(value) <= _MAX_TEXT and _EMAIL.match(value) else None


def valid_note(text: str) -> str | None:
    value = text.strip()
    return value if value and len(value) <= _MAX_TEXT else None


@dataclass(frozen=True)
class Step:
    id: str
    prompt: str
    expects: Expects
    field: str | None = None
    options: OptionsFn | None = None
    next: str = "done"
    edit_next: str = "done"
    branches: Mapping[str, str] = dataclasses.field(default_factory=dict)
    clears: tuple[str, ...] = ()
    null_choice: str | None = None
    validate: Validator | None = None
    invalid: str = INVALID_CHOICE_TEXT


STEPS = (
    Step(
        "consent",
        CONSENT_TEXT,
        "choice",
        options=_static(CONSENT_OPTIONS),
        next="city",
        branches={"no": "declined"},
    ),
    Step(
        "city",
        "Which city are you in?",
        "choice",
        field="city",
        options=_city_options,
        next="venue",
        edit_next="venue",
        clears=("venue", "venue_note"),
    ),
    Step(
        "venue",
        "Where would you want to see the show?",
        "choice",
        field="venue",
        options=_venue_options,
        next="budget",
        branches={OTHER: "venue_note"},
        clears=("venue_note",),
        null_choice=OTHER,
    ),
    Step(
        "venue_note",
        "Tell us the place.",
        "free_text",
        field="venue_note",
        next="budget",
        validate=valid_note,
        invalid="Please type the place name in a few words.",
    ),
    Step(
        "budget",
        "What ticket price feels comfortable?",
        "choice",
        field="budget_band",
        options=_static(BUDGET_OPTIONS),
        next="group",
    ),
    Step(
        "group",
        "How many people are coming?",
        "choice",
        field="group_size",
        options=_static(GROUP_OPTIONS),
        next="email",
    ),
    Step(
        "email",
        "Shows near you can sell out fast. Drop your email and we'll tell you the moment "
        "{artist} tickets open. Or tap Skip.",
        "free_text",
        field="email",
        options=_static((Option(SKIP, "Skip"),)),
        validate=valid_email,
        null_choice=SKIP,
        invalid="That doesn't look like an email. Send it again, or tap Skip.",
    ),
    Step("done", DONE_PUSH_TEXT, "none"),
)
STEP_BY_ID = {step.id: step for step in STEPS}

# Furthest-step ranking (#84). `venue_note` sits where its detour happens.
FUNNEL_ORDER = tuple(step.id for step in STEPS)

# Step ids a session can rest on besides the question steps.
SESSION_ONLY_STEPS = ("declined", "edit_menu")
MENU_TARGETS = {
    "city": "city",
    "venue": "venue",
    "budget": "budget",
    "group": "group",
    "done": "done",
}


def step_options(step: Step, answers: Mapping[str, str]) -> tuple[Option, ...] | None:
    return step.options(answers) if step.options else None


def funnel_rank(step_id: str | None) -> int:
    return FUNNEL_ORDER.index(step_id) if step_id in FUNNEL_ORDER else -1


def edit_menu_text(answers: Mapping[str, str]) -> str:
    venue = next((v.name for v in VENUES if str(v.id) == answers.get("venue")), None)
    shown = {
        "City": answers.get("city"),
        "Venue": venue or answers.get("venue_note"),
        "Budget": _label(BUDGET_OPTIONS, answers.get("budget_band")),
        "Group": _label(GROUP_OPTIONS, answers.get("group_size")),
    }
    lines = [f"{name}: {value}" for name, value in shown.items() if value]
    return "\n".join([EDIT_MENU_TEXT, "", *lines])


def _label(options: tuple[Option, ...], option_id: str | None) -> str | None:
    return next((o.label for o in options if o.id == option_id), None)
