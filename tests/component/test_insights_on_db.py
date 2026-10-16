from core import insights
from core.clock import ScriptedClock
from core.engine import Engine
from core.store import Store
from core.store_memory import InMemoryStore
from core.store_postgres import PostgresStore
from tests.component.helpers import flow, talk
from tests.support import ARTIST, NOW, decision

FANS = [
    ("Pune", "8", "1500_3000", "3_5"),
    ("Pune", "9", "1500_3000", "6_plus"),
    ("Pune", "8", "lt_1500", "2"),
    ("Mumbai", "2", "3000_6000", "1"),
    ("Jaipur", "13", "gte_6000", "2"),
]


async def seed(store: Store) -> None:
    engine = Engine(store, ScriptedClock(NOW), artist_name=ARTIST)
    for i, spec in enumerate(FANS):
        await talk(engine, f"fan{i}", flow(*spec))
    await talk(engine, "partial", [("start", ""), ("choice", "yes"), ("choice", "Delhi NCR")])


@decision(41)
async def test_p1_c12_insights_over_postgres_rows_match_the_fake(pg_migrated_url: str) -> None:
    memory, postgres = InMemoryStore(), PostgresStore(pg_migrated_url)
    await seed(memory)
    await seed(postgres)
    results = []
    for store in (memory, postgres):
        fans, venues = await store.fans(), await store.venues()
        results.append(
            (
                insights.recommend(fans, venues, NOW),
                insights.venue_demand(fans),
                insights.funnel(fans),
            )
        )
    assert results[0] == results[1]
    recommendations = results[0][0]
    assert [r.city for r in recommendations] == ["Pune", "Jaipur", "Mumbai"]
    assert recommendations[0].attendance == 12 and recommendations[0].venue is not None
    assert recommendations[0].venue.name == "Koregaon Park Lawns"
    funnel = results[0][2]
    assert (funnel.started, funnel.completed) == (6, 5)
