# SPDX-License-Identifier: GPL-3.0-only
import os

import pytest

# No windows are shown, so tests also run without a display (CI, SSH).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


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
    lasting = {t.ident for t in threading.enumerate() if not t.daemon}
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
                 if not t.daemon and t.ident not in lasting and t.is_alive()]
    QT_PROBLEMS.clear()
    if problems:
        pytest.fail("\n".join(problems), pytrace=False)
