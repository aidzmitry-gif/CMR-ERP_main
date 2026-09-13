"""Explicit constraint boundary for a multi-statement reopening command."""
from contextlib import asynccontextmanager

from sqlalchemy import text


@asynccontextmanager
async def reopening_checks(session):
    """Validate the complete transaction, then leave constraints deferred.

    Caller owns commit/rollback and must not bring unrelated incomplete work.
    Subsequent ledger packages may be assembled; commit still validates them.
    This does not restore an unknown caller constraint mode.
    """
    postgres = session.get_bind().dialect.name == 'postgresql'
    if postgres:
        with session.no_autoflush:
            await session.execute(text('SET CONSTRAINTS ALL DEFERRED'))
    yield
    await session.flush()
    if postgres:
        await session.execute(text('SET CONSTRAINTS ALL IMMEDIATE'))
        await session.execute(text('SET CONSTRAINTS ALL DEFERRED'))
