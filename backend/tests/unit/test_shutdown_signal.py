"""SIGTERM closes live streams at once, and still reaches the server's own handler."""

import asyncio
import os
import signal

from app.realtime import on_shutdown_signal


def test_sigterm_runs_the_callback_and_the_previous_handler():
    original = signal.getsignal(signal.SIGTERM)
    server_saw: list[int] = []
    signal.signal(signal.SIGTERM, lambda signum, frame: server_saw.append(signum))
    try:

        async def scenario() -> list[str]:
            closed: list[str] = []
            restore = on_shutdown_signal(lambda: closed.append("streams closed"))
            os.kill(os.getpid(), signal.SIGTERM)
            await asyncio.sleep(0.05)  # let call_soon_threadsafe run
            restore()
            return closed

        closed = asyncio.run(scenario())
        assert closed == ["streams closed"]
        assert server_saw == [signal.SIGTERM]
        assert signal.getsignal(signal.SIGTERM) is not None  # restored to the "server" one
    finally:
        signal.signal(signal.SIGTERM, original)


def test_nothing_is_installed_without_a_server_handler():
    original = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    try:

        async def scenario():
            restore = on_shutdown_signal(lambda: None)
            installed = signal.getsignal(signal.SIGTERM)
            restore()
            return installed

        assert asyncio.run(scenario()) is signal.SIG_DFL
    finally:
        signal.signal(signal.SIGTERM, original)
