# SPDX-License-Identifier: GPL-3.0-only
"""DDC/CI retries, layer by layer and end to end.

A DDC/CI message travels over the monitor cable's I2C wires and is often
garbled: Monitorian and Twinkle Tray retry the transient errors. Winlight's
retries come in layers, each tested here:

1. The call: win32._ddc_call tries a transient error up to three times,
   50 ms apart, and spaces messages to one monitor (test_win32.py has the
   property tests of the loop itself).
2. The backend: a "monitor no longer exists" error becomes MonitorGoneError
   (detect again); a read that still fails is "unknown" (None), not a crash.
3. The queue (MonitorService): a failed write is reported, the queue carries
   on, and a gone display triggers one detection.
4. The manager: one failure is shown; a second in a row marks the display
   "failing" and detects again in 5 s; a call that hangs marks it "not
   responding" and detects again at 10 and 30 s; any success clears it.

The end-to-end tests run the real layers 1 to 3 together, with only the
monitor's driver (dxva2) faked.
"""

import types

import pytest

from nightlight.brightness.monitors import (
    Commanded,
    Detected,
    Failed,
    Gone,
    MonitorManager,
    MonitorService,
    Status,
    Write,
)
from nightlight.hardware import win32, windows
from nightlight.hardware.calls import InlineRunner
from tests.test_monitor_service import FakeClock, of
from tests.test_monitors import SlowBackend, ready
from tests.test_windows_backend import with_edid

TRANSIENT = win32.ERROR_GRAPHICS_I2C_ERROR_RECEIVING_DATA
GONE = win32.ERROR_GRAPHICS_MONITOR_NO_LONGER_EXISTS
HANDLE = 7


class Dxva2:
    """The monitor's driver: each read or write answers with the next scripted
    result (True, or an error code), then works. The level it holds is real."""

    def __init__(self, level=40):
        self.level = level
        self.script: list = []
        self.attempts = 0
        self.calls: list[str] = []  # "get" or "set", each attempt
        self.last_error = 0

    def _answer(self) -> bool:
        self.attempts += 1
        answer = self.script.pop(0) if self.script else True
        if answer is True:
            return True
        self.last_error = answer
        return False

    def GetVCPFeatureAndVCPFeatureReply(self, handle, code, _type, current, maximum):
        self.calls.append("get")
        if not self._answer():
            return False
        current._obj.value, maximum._obj.value = self.level, 100
        return True

    def SetVCPFeature(self, handle, code, value):
        self.calls.append("set")
        if not self._answer():
            return False
        self.level = value
        return True


@pytest.fixture
def stack(monkeypatch):
    """The real call, backend and queue over a fake driver, detected once."""
    driver = Dxva2()
    pauses = []
    monkeypatch.setattr(win32, "_dxva2", driver, raising=False)
    monkeypatch.setattr(win32.ctypes, "get_last_error", lambda: driver.last_error)
    monkeypatch.setattr(win32, "time", types.SimpleNamespace(sleep=pauses.append, monotonic=win32.time.monotonic))
    monkeypatch.setattr(win32, "display_targets", lambda: [with_edid(r"\\.\DISPLAY1", "DELL U2720Q", "AAA111")])
    monkeypatch.setattr(win32, "physical_monitors", lambda: [win32.PhysicalMonitor(r"\\.\DISPLAY1", HANDLE, "x")])
    monkeypatch.setattr(win32, "destroy_physical_monitor", lambda handle: None)
    backend = windows.WindowsBrightnessBackend()
    backend._wmi = None
    events, clock = [], FakeClock()
    service = MonitorService(backend, events.append, InlineRunner(), clock=clock)
    service.request_detect()
    service.run_pending()
    [info] = of(events, Detected)[-1].monitors
    assert info.supported and info.channel == "ddc"
    return types.SimpleNamespace(driver=driver, service=service, events=events, key=info.key, pauses=pauses, clock=clock)


def write(stack, value):
    """How many times the change was sent to the monitor."""
    stack.events.clear()
    before = len(stack.driver.calls)
    stack.service.request_write(Write(stack.key, value))
    stack.service.run_pending()
    return stack.driver.calls[before:].count("set")


# --- End to end: the real call, backend and queue ------------------------------------------------


def test_a_garbled_message_is_sent_again_and_the_change_goes_through(stack):
    stack.driver.script = [TRANSIENT, TRANSIENT]
    assert write(stack, 70) == 3
    assert of(stack.events, Commanded) == [Commanded(stack.key, 70, "user")] and not of(stack.events, Failed)
    assert stack.driver.level == 70
    assert stack.pauses.count(win32._DDC_RETRY_DELAY) == 2


def test_a_monitor_garbling_every_try_fails_that_change_only(stack):
    stack.driver.script = [TRANSIENT] * win32._DDC_ATTEMPTS
    assert write(stack, 70) == win32._DDC_ATTEMPTS  # three tries, no more
    [failed] = of(stack.events, Failed)
    assert failed.key == stack.key and not failed.timeout and "0xC0262583" in failed.message
    assert stack.driver.level == 40
    assert write(stack, 75) == 1 and stack.driver.level == 75  # the next change works: the queue carried on


def test_an_unplugged_monitor_is_not_retried_and_is_detected_again(stack):
    stack.driver.script = [GONE]
    assert write(stack, 70) == 1  # "gone" is never retried
    assert of(stack.events, Gone) == [Gone(stack.key)] and not of(stack.events, Commanded)
    kinds = [type(event) for event in stack.events]
    assert Detected in kinds[kinds.index(Gone):]  # looked for again, at once


def test_a_read_that_keeps_failing_is_unknown_not_an_error(stack):
    stack.driver.script = [TRANSIENT] * win32._DDC_ATTEMPTS
    level = stack.service._backend.get_brightness(0)
    assert level is None


# --- The manager: how failures add up --------------------------------------------------------------


@pytest.fixture
def display(manager):
    monitors = manager(SlowBackend(delay=0))
    state = ready(monitors)
    scheduled = len(monitors._scheduled)
    return monitors, state, scheduled


@pytest.fixture
def manager():
    managers = []

    def make(backend):
        managers.append(MonitorManager(backend))
        return managers[-1]

    yield make
    for m in managers:
        m.shutdown()


def due_in(monitors, after):
    return sorted(round(timer.interval() / 1000) for _due, timer in monitors._scheduled[after:])


def test_one_failed_change_is_shown_but_the_display_stays_usable(display):
    monitors, state, scheduled = display
    monitors._on_event(Failed("A", "Setting VCP 0x10 failed (0xC0262583)"))
    assert state.status is Status.OK and state.message == "The last change failed"
    assert due_in(monitors, scheduled) == []


def test_a_second_failure_in_a_row_marks_it_failing_and_looks_again_in_5_s(display):
    monitors, state, scheduled = display
    for _ in range(2):
        monitors._on_event(Failed("A", "Setting VCP 0x10 failed"))
    assert state.status is Status.FAILING
    assert due_in(monitors, scheduled) == [5]


def test_a_success_in_between_starts_the_count_again(display):
    monitors, state, scheduled = display
    monitors._on_event(Failed("A", "garbled"))
    monitors._on_event(Commanded("A", 60, "user"))
    monitors._on_event(Failed("A", "garbled"))
    assert state.status is Status.OK and state.failures == 1


def test_a_success_after_failing_clears_it(display):
    monitors, state, _scheduled = display
    for _ in range(2):
        monitors._on_event(Failed("A", "garbled"))
    monitors._on_event(Commanded("A", 60, "user"))
    assert state.status is Status.OK and state.failures == 0 and state.message == ""


def test_a_call_that_hangs_marks_it_not_responding_and_looks_again_at_10_and_30_s(display):
    monitors, state, scheduled = display
    monitors._on_event(Failed("A", "setting the brightness didn't return within 5 s", timeout=True))
    assert state.status is Status.NOT_RESPONDING
    assert due_in(monitors, scheduled) == [10, 30]


def test_a_fresh_detection_forgets_old_failures(display):
    monitors, state, _scheduled = display
    monitors._on_event(Failed("A", "garbled"))
    monitors._on_event(Detected(monitors.generation + 1, [monitors.state("A").info]))
    assert monitors.state("A").failures == 0
