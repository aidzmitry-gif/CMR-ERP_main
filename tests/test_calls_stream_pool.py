"""A live call stream must leave the database pool available to other requests."""
import asyncio
import json
import socket
from types import SimpleNamespace

import httpx
import uvicorn
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.domain.models import User
from core.runtime.deps import get_session
from modules.sales import calls
from modules.sales.models import CallLog
from modules.sales.routes import router


async def test_live_calls_stream_does_not_pin_the_authorization_connection(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'synthetic-stream.db').as_posix()}",
        pool_size=1, max_overflow=0, pool_timeout=0.2,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    employee_id = 990001
    async with engine.begin() as connection:
        await connection.run_sync(User.__table__.create)
    async with factory() as session:
        session.add(User(username="synthetic-stream-owner", full_name="Synthetic stream owner",
            role="sales", department="Продажи", status="active", deal_visibility="own",
            employee_id=employee_id))
        await session.commit()

    app = FastAPI()
    app.state.core = SimpleNamespace(
        services=SimpleNamespace(db=SimpleNamespace(session_factory=factory)),
        roles=[SimpleNamespace(name="sales", permissions=["sales.deal.read"])],
    )
    # Include the actual global scope guard as well as the actual stream endpoint.
    app.include_router(router, prefix="/sales")

    @app.get("/__synthetic_pool_probe")
    async def probe(session: AsyncSession = Depends(get_session, scope="function")):
        return {"value": await session.scalar(text("SELECT 1"))}

    @app.exception_handler(PoolTimeout)
    async def pool_timeout(_request, _error):
        return JSONResponse({"code": "synthetic_pool_timeout"}, status_code=503)

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app, log_level="error", access_log=False, lifespan="off", timeout_graceful_shutdown=1,
    ))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if serving.done():
                    await serving
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=3) as client:
            assert (await client.get("/__synthetic_pool_probe")).json() == {"value": 1}
            async with client.stream("GET", "/sales/calls/stream", headers={
                "X-User": "synthetic-stream-owner", "X-User-Roles": "sales",
            }) as stream:
                assert stream.status_code == 200
                lines = stream.aiter_lines()
                assert await asyncio.wait_for(anext(lines), timeout=2) == ": connected"
                assert await asyncio.wait_for(anext(lines), timeout=2) == ""
                assert calls.has_subscriber(employee_id)

                before_probe = engine.pool.checkedout()
                available = await client.get("/__synthetic_pool_probe")
                assert available.status_code == 200, available.text
                assert available.json() == {"value": 1}
                assert before_probe == 0
                assert engine.pool.checkedout() == 0
                assert calls.has_subscriber(employee_id)

                # A probe must succeed while the stream remains live, not after it closes.
                assert calls._push_card(CallLog(id=990001, call_id="SYN-POOL-CALL", direction="in",
                    owner_id=employee_id, status="ringing"))
                event = await asyncio.wait_for(anext(lines), timeout=2)
                assert event.startswith("data: ")
                assert json.loads(event[6:])["call_id"] == "SYN-POOL-CALL"
            async with asyncio.timeout(2):
                while calls.has_subscriber(employee_id):
                    await asyncio.sleep(0.01)
            assert engine.pool.checkedout() == 0
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(serving, timeout=5)
        finally:
            listener.close()
            await engine.dispose()
