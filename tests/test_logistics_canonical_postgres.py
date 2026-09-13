"""Real PostgreSQL consumer/storage integration; source adapter remains a pinned boundary."""
import pytest

from tests.accounting.test_postgres import pg_factory  # noqa: F401
from tests.test_logistics_canonical_intakes import (
    test_two_producers_share_execution_and_terminal_exact_replay as canonical_flow,
)
from tests.test_logistics_relay_postgres import pg  # noqa: F401


@pytest.mark.parametrize("mode", ["spot", "contract"])
async def test_pg_canonical_two_sources_one_execution_terminal_replay(pg, mode):  # noqa: F811
    async with pg.factory() as session:
        # Synthetic release fixture tests terminal revalidation, not a cancellation act.
        await canonical_flow(session, None, pg.exact, mode, terminal_field="reserve_status")
