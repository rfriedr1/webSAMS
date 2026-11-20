from __future__ import annotations

from sams_web.main import _is_client_hangup_noise, _quiet_loop_exception_handler


class _FakeLoop:
    def __init__(self) -> None:
        self.reported: list[dict] = []

    def default_exception_handler(self, context: dict) -> None:
        self.reported.append(context)


_HANGUP = {
    "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
    "exception": ConnectionResetError(10054, "connection closed by remote host"),
}


def test_client_hangup_is_recognised():
    assert _is_client_hangup_noise(_HANGUP)


def test_other_errors_are_not_swallowed():
    # Same exception type from somewhere else, and a different error from
    # the same callback, must both still be reported.
    assert not _is_client_hangup_noise(
        {"message": "Task exception was never retrieved", "exception": ConnectionResetError()}
    )
    assert not _is_client_hangup_noise(
        {"message": _HANGUP["message"], "exception": RuntimeError("boom")}
    )
    assert not _is_client_hangup_noise({"message": "no exception attached"})


def test_handler_drops_noise_and_forwards_the_rest():
    loop = _FakeLoop()
    _quiet_loop_exception_handler(loop, _HANGUP)
    assert loop.reported == []
    other = {"message": "Task exception was never retrieved", "exception": ValueError("x")}
    _quiet_loop_exception_handler(loop, other)
    assert loop.reported == [other]


class _FakeSock:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeServer:
    def __init__(self) -> None:
        self.active = 1

    def _detach(self, item) -> None:
        self.active -= 1


class _FakeTransport:
    """The state a Proactor transport is left in when `_call_connection_lost`
    raised at its `sock.shutdown()`: not closed, not detached."""

    def __init__(self) -> None:
        self._sock = _FakeSock()
        self._server = _FakeServer()
        self._called_connection_lost = False

    def _call_connection_lost(self, exc) -> None:  # stands in for the real callback
        raise ConnectionResetError(10054, "connection closed by remote host")


class _FakeHandle:
    def __init__(self, callback) -> None:
        self._callback = callback


def test_hangup_finishes_the_skipped_cleanup():
    # Without the detach, Server.wait_closed() never returns and Ctrl+C
    # hangs after "Shutting down".
    transport = _FakeTransport()
    sock, server = transport._sock, transport._server
    loop = _FakeLoop()
    _quiet_loop_exception_handler(loop, {**_HANGUP, "handle": _FakeHandle(transport._call_connection_lost)})
    assert loop.reported == []
    assert sock.closed
    assert server.active == 0
    assert transport._sock is None and transport._server is None
    assert transport._called_connection_lost


def test_cleanup_runs_once_and_tolerates_odd_handles():
    transport = _FakeTransport()
    server = transport._server
    context = {**_HANGUP, "handle": _FakeHandle(transport._call_connection_lost)}
    _quiet_loop_exception_handler(_FakeLoop(), context)
    _quiet_loop_exception_handler(_FakeLoop(), context)
    assert server.active == 0
    # No handle, or a handle without a bound transport: just dropped.
    _quiet_loop_exception_handler(_FakeLoop(), _HANGUP)
    _quiet_loop_exception_handler(_FakeLoop(), {**_HANGUP, "handle": _FakeHandle(print)})
