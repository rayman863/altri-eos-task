"""The pure-ASGI test client itself: a streaming response that waits for the client to
disconnect (like the Phase 5 SSE stream) must end, not hang the run."""

import asyncio
import time

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from tests.api.conftest import asgi_request


def test_streams_end_when_the_client_disconnects():
    app = FastAPI()

    @app.get("/stream")
    async def stream() -> StreamingResponse:
        async def forever():
            while True:
                yield b"data: tick\n\n"
                await asyncio.sleep(0.05)

        return StreamingResponse(forever(), media_type="text/event-stream")

    started = time.perf_counter()
    resp = asyncio.run(asgi_request(app, "GET", "/stream", disconnect_after=0.3))
    assert resp.status == 200
    assert resp.raw.startswith(b"data: tick")
    assert time.perf_counter() - started < 3
