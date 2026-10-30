# SPDX-License-Identifier: GPL-3.0-only
"""The suite's own guards (conftest.py, pyproject.toml) catch what they're for.

Each runs a small pytest session in a folder of its own, with copies of this
suite's conftest.py and pytest settings, and a test that does the wrong
thing on purpose: that test must fail there, and a clean one pass. A guard
that silently stopped working would otherwise go unnoticed until the bug it
was for came back.
"""

import os
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

INNER_TESTS = '''
import threading, time
from PySide6.QtCore import QObject, Signal, qWarning

class Emitter(QObject):
    fired = Signal()

def test_clean():
    assert True

def test_an_exception_in_a_slot():
    emitter = Emitter()
    def slot():
        raise RuntimeError("a bug inside a slot")
    emitter.fired.connect(slot)
    emitter.fired.emit()  # PySide prints the error and carries on

def test_a_qt_warning():
    qWarning("QObject::startTimer: Timers cannot be started from another thread")

def test_offscreen_noise_is_fine():
    qWarning("This plugin does not support raise()")

def test_an_exception_in_a_thread():
    thread = threading.Thread(target=lambda: 1 / 0, daemon=True)
    thread.start()
    thread.join()

def test_an_exception_in_a_finalizer():
    class Broken:
        def __del__(self):
            raise RuntimeError("in __del__")
    Broken()

def test_a_thread_left_running():
    stop = threading.Event()
    threading.Thread(target=stop.wait, args=(3,), daemon=False).start()
'''

HANGS = '''
import time

def test_hangs():
    time.sleep(60)
'''


def session(tmp_path: Path, tests: str, env: dict | None = None):
    """Run `tests` with this suite's conftest and settings; outcome per test."""
    settings = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["pytest"]["ini_options"]
    ini = "[pytest]\naddopts = -p no:cacheprovider\nfilterwarnings =\n" + "".join(f"    {w}\n" for w in settings["filterwarnings"])
    (tmp_path / "pytest.ini").write_text(ini, encoding="utf-8")
    (tmp_path / "conftest.py").write_text((ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "test_inner.py").write_text(tests, encoding="utf-8")
    report = tmp_path / "report.xml"
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", f"--junitxml={report}", "test_inner.py"], cwd=tmp_path,
                            capture_output=True, text=True, timeout=180, env={**os.environ, **(env or {})})
    outcomes = {}
    if report.exists():
        for case in ElementTree.parse(report).iter("testcase"):
            failed = case.find("failure") is not None or case.find("error") is not None
            outcomes[case.get("name")] = "failed" if failed else "passed"
    return outcomes, result


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory):
    found, result = session(tmp_path_factory.mktemp("guards"), INNER_TESTS)
    assert found, result.stdout[-3000:] + result.stderr[-3000:]
    return found


def test_a_clean_test_passes_and_offscreen_noise_is_ignored(outcomes):
    assert outcomes["test_clean"] == "passed"
    assert outcomes["test_offscreen_noise_is_fine"] == "passed"


@pytest.mark.parametrize("test", ["test_an_exception_in_a_slot", "test_a_qt_warning", "test_an_exception_in_a_thread",
                                  "test_an_exception_in_a_finalizer", "test_a_thread_left_running"])
def test_hidden_problems_fail_the_test_that_caused_them(outcomes, test):
    assert outcomes[test] == "failed"


def test_a_hung_test_ends_the_run_with_every_threads_stack(tmp_path):
    outcomes, result = session(tmp_path, HANGS, env={"WINLIGHT_TEST_WATCHDOG_S": "2"})
    assert result.returncode != 0
    assert "Timeout" in result.stderr and "test_hangs" in result.stderr  # faulthandler's dump of the stuck test
