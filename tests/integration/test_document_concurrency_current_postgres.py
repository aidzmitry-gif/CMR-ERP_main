"""The same ERP document race oracles against the registered PostgreSQL schema."""
import pytest

from tests.accounting.test_postgres import pg_factory as pg_factory  # noqa: F401
from tests.test_document_concurrency import (
    test_concurrent_retries_issue_one_document as _same_key,
)
from tests.test_document_concurrency import (
    test_concurrent_revision_and_issue_cannot_duplicate as _replacement,
)
from tests.test_document_concurrency import (
    test_edit_against_issuing_draft_is_serialized as _edit_issue,
)
from tests.test_document_concurrency import (
    test_existing_draft_replay_refreshes_cached_original as _cached_replay,
)
from tests.test_invoice_unreserved_cancellation import (
    registered_api as registered_api,  # noqa: F401
)

pytestmark = [pytest.mark.integration,
              pytest.mark.parametrize('pg_factory', ['registered_head'], indirect=True)]


async def test_pg_concurrent_retries_issue_one_document(registered_api):
    await _same_key(registered_api)


async def test_pg_concurrent_revision_and_issue_cannot_duplicate(registered_api):
    await _replacement(registered_api)


async def test_pg_edit_against_issuing_draft_is_serialized(registered_api):
    await _edit_issue(registered_api)


async def test_pg_existing_draft_replay_refreshes_cached_original(registered_api):
    await _cached_replay(registered_api)
