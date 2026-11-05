# SPDX-License-Identifier: GPL-3.0-only
import os

import pytest

# No windows are shown, so tests also run without a display (CI, SSH).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from hypothesis import Phase, settings
from PySide6.QtWidgets import QApplication

# Property-based tests (hypothesis) run the same cases every time, as the
# suite's seeded random tests do, so a failure repeats exactly; and keep no
# example database (no .hypothesis folder). No deadline: a slow CI machine
# isn't a failure.
settings.register_profile("winlight", derandomize=True, database=None, deadline=None, print_blob=True)
# test_mutations.py only needs to know a property fails, not its smallest case.
settings.register_profile("mutation", settings.get_profile("winlight"),
                          phases=[Phase.explicit, Phase.reuse, Phase.generate])
settings.load_profile(os.environ.get("WINLIGHT_HYPOTHESIS_PROFILE", "winlight"))


@pytest.fixture(scope="session", autouse=True)
def qapp():
    # One application for the whole run: Qt allows only one per process, and
    # some tests need widgets (the settings window) or screens.
    app = QApplication.instance() or QApplication([])
    # As in the app (nightlight/gc_guard.py): garbage is collected on the main
    # thread only, here after each test, never on a monitor or call thread.
    import gc

    gc.disable()
    yield app
    gc.enable()


# Tests that use something there is one of per desktop, not per process: real
# hotkeys (RegisterHotKey) and real key presses (SendInput), in child
# processes. Run in parallel (pytest -n auto --dist loadgroup, as CI does),
# they go to one worker, one after another, so two never hold the same keys.
DESKTOP_WIDE = {"test_shortcuts.py", "test_shortcut_safeguards.py"}
# The slow tier: soaks, random properties, mutation checks, and runs of the
# suite inside a test; together about half the run's time in a tenth of its
# tests. `pytest -n auto -m "not slow"` leaves them out while iterating; CI,
# and every run before a commit or a release, runs everything.
SLOW = {"test_mutations.py", "test_concurrency_and_soak.py", "test_settings_properties.py", "test_chaos.py",
        "test_gamma_properties.py", "test_design.py"}


def pytest_collection_modifyitems(config, items):
    parallel = config.pluginmanager.hasplugin("xdist")
    for item in items:
        if item.path.name in SLOW:
            item.add_marker(pytest.mark.slow)
        if parallel and item.path.name in DESKTOP_WIDE:
            item.add_marker(pytest.mark.xdist_group("desktop"))


def pytest_collection_finish(session):
    """Everything that exists once the tests are collected (modules, Qt's and
    the test modules' classes, hypothesis) stays for the whole run: frozen,
    the collections after each test look only at what tests made since, which
    is what they are for. Each looked through every object in the process
    otherwise: 166 ms a collection, two per test, about half the run."""
    import gc

    gc.collect()
    gc.freeze()


@pytest.fixture(autouse=True)
def collect_qt_garbage():
    """After each test, delete its leftover Qt objects here, on the main thread
    with no event loop running. Left to Python's garbage collector, they were
    destroyed at a random later moment (a test's widgets and timers sit in
    reference cycles), sometimes mid-event-loop in another test, which crashed
    Qt with an access violation about one full run in two."""
    yield
    import gc

    from PySide6.QtCore import QCoreApplication, QEvent

    gc.collect()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()


# --- Guards for every test ------------------------------------------------------------------------
#
# Failures that otherwise pass unnoticed: an exception inside a Qt slot (PySide
# prints it and carries on, so the test still passes), a Qt warning about
# threads, timers or connections, a test that hangs, and a thread left running.
# Uncaught exceptions in threads and in __del__ fail tests through
# pyproject.toml's filterwarnings. tests/test_suite_guards.py checks each guard.

import faulthandler  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import traceback  # noqa: E402

from PySide6.QtCore import QtMsgType, qInstallMessageHandler  # noqa: E402

# Longer than the slowest test by far: a test past it is hung (a deadlock),
# and the run ends with every thread's stack instead of waiting for CI's limit.
WATCHDOG_S = float(os.environ.get("WINLIGHT_TEST_WATCHDOG_S", "300"))
# Qt's offscreen platform, used for the tests, can't do these; they aren't bugs.
QT_NOISE = re.compile(r"This plugin does not support|QFontDatabase: Cannot find font directory")


class QtProblems:
    """What Qt reported during the current test."""

    def __init__(self):
        self.messages: list[str] = []
        self.exceptions: list[str] = []

    def clear(self):
        self.messages.clear()
        self.exceptions.clear()


QT_PROBLEMS = QtProblems()


def _qt_message(kind, _context, message):
    if kind in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg) and not QT_NOISE.search(message):
        QT_PROBLEMS.messages.append(f"{kind.name}: {message}")


qInstallMessageHandler(_qt_message)


def _real_stderr(config):
    """Where a hung test's stacks go: pytest's own copy of the real stderr
    (the test's stderr is captured, and lost when the run is ended)."""
    try:
        from _pytest.faulthandler import fault_handler_stderr_fd_key

        return config.stash[fault_handler_stderr_fd_key]
    except (ImportError, KeyError):
        return sys.__stderr__


def _slot_exception(kind, value, tb):
    QT_PROBLEMS.exceptions.append("".join(traceback.format_exception(kind, value, tb)))


@pytest.fixture(autouse=True)
def fail_on_hidden_problems(request):
    QT_PROBLEMS.clear()
    hook = sys.excepthook
    sys.excepthook = _slot_exception  # where PySide sends an exception raised in a slot
    # Thread objects, not their idents: a thread started but not yet running
    # has no ident (None) and gets one moment later, and an ident can be
    # reused once its thread ends (see test_architecture's rule).
    lasting = {t for t in threading.enumerate() if not t.daemon}
    faulthandler.dump_traceback_later(WATCHDOG_S, exit=True, file=_real_stderr(request.config))
    yield QT_PROBLEMS
    faulthandler.cancel_dump_traceback_later()
    sys.excepthook = hook
    # Windows a test left open are hidden: the next test starts with none showing.
    for widget in QApplication.topLevelWidgets():
        if widget.isVisible():
            widget.hide()
    problems = [f"an exception in a Qt slot:\n{text}" for text in QT_PROBLEMS.exceptions]
    problems += [f"Qt said: {text}" for text in QT_PROBLEMS.messages]
    problems += [f"a thread left running (not a daemon): {t.name}" for t in threading.enumerate()
                 if not t.daemon and t not in lasting and t.is_alive()]
    QT_PROBLEMS.clear()
    if problems:
        pytest.fail("\n".join(problems), pytrace=False)
