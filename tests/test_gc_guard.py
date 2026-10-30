# SPDX-License-Identifier: GPL-3.0-only
"""Garbage is collected on the main thread only (nightlight/gc_guard.py)."""

import gc
import threading
from pathlib import Path

from PySide6.QtCore import QObject

from nightlight import gc_guard


class Cycle:
    def __init__(self):
        self.me = self
        self.qt = QObject()  # a Qt object in reference cycle garbage


def test_a_busy_worker_thread_never_collects_garbage_holding_qt_objects():
    collector = gc_guard.MainThreadGarbageCollector()
    threads = []

    def note(phase, info):
        if phase == "start":
            threads.append(threading.current_thread().name)

    gc.callbacks.append(note)
    try:
        for _ in range(50):
            Cycle()  # garbage, waiting for a collection
        worker = threading.Thread(target=lambda: [[{}] for _ in range(200_000)], name="monitor-service")
        worker.start()  # allocates far past every threshold
        worker.join()
        assert "monitor-service" not in threads
        collector._checks = gc_guard.FULL_EVERY - 1
        collector.check()  # the main thread's timer
        assert threads and set(threads) == {threading.current_thread().name}
    finally:
        gc.callbacks.remove(note)
        collector.stop()
        gc.disable()  # as the test session keeps it (conftest)


# --- From the 0.2.0 audit -------------------------------------------------------


def test_only_the_guard_collects():
    """A collection anywhere else (a worker thread) frees every cycle in the
    process, Qt objects included: the crash the guard exists for. WMI's
    release used to collect on the monitor thread."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = [
        str(path.relative_to(root))
        for path in [*root.joinpath("nightlight").rglob("*.py"), root / "main.py"]
        if path.name != "gc_guard.py" and re.search(r"\bgc\.(collect|enable)\(", path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


class _Com:
    """Stands in for a wmi / win32com wrapper: in a cycle, holding a resource."""

    def __init__(self, released):
        self.peer = None
        self.resource = _Resource(released)


class _Resource:
    def __init__(self, released):
        self._released = released

    def __del__(self):
        self._released.append(True)


_Com.__module__ = "fakecom.client"


def test_release_cycles_frees_tied_objects_now_without_a_collection():
    import gc

    from nightlight.gc_guard import release_cycles

    released = []
    a, b = _Com(released), _Com(released)
    a.peer, b.peer = b, a  # the cycle that kept them for the collector
    unrelated = {"keep": [1, 2, 3]}
    a.shared = unrelated
    enabled = gc.isenabled()
    gc.disable()
    try:
        assert release_cycles(a, ("fakecom",)) == 2
        del a, b
        assert released == [True, True]  # freed by reference counting, on this thread
    finally:
        if enabled:
            gc.enable()
    assert unrelated == {"keep": [1, 2, 3]}  # containers are followed, never cleared


def test_release_cycles_leaves_other_modules_alone():
    from nightlight.gc_guard import release_cycles

    class Plain:
        pass

    root = Plain()
    root.child = Plain()
    root.child.value = 5
    assert release_cycles(root, ("fakecom",)) == 0
    assert root.child.value == 5


def test_no_connected_lambda_holds_self():
    """A lambda using self, connected to a signal, makes a reference cycle
    (self -> widget -> connection -> lambda -> self). Collected, PySide
    deleted such widgets twice and the process crashed as it exited (the
    first 0.5.0 build). Connect a bound method instead: PySide holds those
    without keeping self alive."""
    import ast

    root = Path(__file__).resolve().parent.parent / "nightlight"
    # The pipe's sockets belong to Qt (the server's children, deleted with
    # deleteLater on hang-up), so collecting their wrappers deletes nothing;
    # the lambdas keep each socket's wrapper, and so its buffer's key, stable.
    allowed = {"system/single_instance.py"}
    found = []
    for path in sorted(root.rglob("*.py")):
        if path.relative_to(root).as_posix() in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "connect"):
                continue
            for argument in node.args:
                if isinstance(argument, ast.Lambda) and any(
                        isinstance(name, ast.Name) and name.id == "self" for name in ast.walk(argument.body)):
                    found.append(f"{path.relative_to(root.parent)}:{node.lineno}")
    assert not found, found
