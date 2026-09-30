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
