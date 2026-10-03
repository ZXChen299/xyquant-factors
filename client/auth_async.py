"""Wait for a shared credential operation without joining asyncio's executor.

The original AuthClient owns the credentials mutex and atomic save. Timing out a
wait never cancels or replays the operation. No token or exception is logged here.
"""
import asyncio
from concurrent.futures import Future
import os
from pathlib import Path
import threading

_guard = threading.Lock()
_inflight = {}


def _key(auth):
    root = getattr(auth, 'root', None)
    if isinstance(root, (str, Path)):
        return ('root', os.path.normcase(os.path.abspath(os.fspath(root))))
    return ('instance', id(auth))


def _start_or_share(auth):
    identity = _key(auth)
    with _guard:
        if identity in _inflight:
            return _inflight[identity]
        future = Future()
        _inflight[identity] = future

        def run():
            value, failure = None, None
            try:
                value = auth.access()
            except BaseException as error:
                failure = error
            finally:
                with _guard:
                    if _inflight.get(identity) is future:
                        del _inflight[identity]
            if failure is None:
                future.set_result(value)
            else:
                future.set_exception(failure)

        try:
            threading.Thread(target=run, name='xyquant-auth-access', daemon=True).start()
        except BaseException:
            del _inflight[identity]
            raise
        return future


def _observe(future):
    # A timed-out waiter may never retrieve the eventual exception. Consume it
    # to prevent asyncio's default exception logger exposing transport details.
    if not future.cancelled():
        future.exception()


async def access(auth, timeout):
    if timeout <= 0:
        raise TimeoutError()
    shared = _start_or_share(auth)
    wrapped = asyncio.wrap_future(shared)
    wrapped.add_done_callback(_observe)
    return await asyncio.wait_for(asyncio.shield(wrapped), timeout)


def drain(auth):
    """Worker shutdown only: wait for this root's existing operation, never start one.

    Call after the job outcome is persisted. This is not part of a tool's request
    budget; it gives an already-sent refresh a chance to save before process exit.
    """
    with _guard:
        future = _inflight.get(_key(auth))
    if future is not None:
        try:
            future.result()
        except BaseException:
            pass
