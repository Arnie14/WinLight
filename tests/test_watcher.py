# SPDX-License-Identifier: GPL-3.0-only
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from nightlight.system.watcher import DisplayWatcher


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class FakeEvents(QObject):
    """winsystem.SystemEvents' signals (test_the_fake_matches_the_real_events checks)."""

    suspending = Signal()
    resumed = Signal()
    displayOff = Signal()
    displayOn = Signal()
    locked = Signal()
    unlocked = Signal()
    displayChanged = Signal()
    clockChanged = Signal()
    endingSession = Signal()
    panelBrightness = Signal(int)
    powerSourceChanged = Signal(int)
    hotkeyPressed = Signal(int)


def signal_names(cls):
    from PySide6.QtCore import QMetaMethod

    meta = cls.staticMetaObject
    return {bytes(meta.method(i).name()).decode() for i in range(meta.methodOffset(), meta.methodCount())
            if meta.method(i).methodType() == QMetaMethod.MethodType.Signal}


def test_the_fake_matches_the_real_events():
    from nightlight.hardware.winsystem import SystemEvents

    assert signal_names(FakeEvents) == signal_names(SystemEvents)


def watcher(events=None):
    clock = Clock()
    w = DisplayWatcher(QApplication.instance(), clock=clock, events=events)
    seen = []
    for name in ("suspending", "resumed", "displaysOff", "displaysOn", "clockChanged"):
        getattr(w, name).connect(lambda name=name: seen.append(name))
    return w, clock, seen


def test_resume_is_noticed_from_a_clock_jump():
    w, clock, seen = watcher()
    clock.now += 5
    w.check_clock()
    assert seen == []
    clock.now += 600  # slept for ten minutes
    w.check_clock()
    assert seen == ["resumed"]


def test_one_wake_gives_one_resume_even_with_both_sources():
    events = FakeEvents()
    w, clock, seen = watcher(events)
    events.suspending.emit()
    clock.now += 3600
    events.resumed.emit()  # Windows says so...
    clock.now += 5
    w.check_clock()  # ...and the clock jump is the same wake
    assert seen == ["suspending", "resumed"]


def test_the_clock_still_notices_a_wake_windows_did_not_report():
    events = FakeEvents()
    w, clock, seen = watcher(events)
    clock.now += 3600
    w.check_clock()
    assert seen == ["resumed"]


def test_display_changes_are_ignored_while_suspending():
    events = FakeEvents()
    w, clock, seen = watcher(events)
    events.suspending.emit()
    events.displayChanged.emit()
    assert not w._settle.isActive()
    events.resumed.emit()
    events.displayChanged.emit()
    assert w._settle.isActive()


def test_power_and_session_events_pass_through():
    events = FakeEvents()
    w, clock, seen = watcher(events)
    events.displayOff.emit()
    events.displayOn.emit()
    events.unlocked.emit()  # the app puts night light back itself; displays weren't off
    events.locked.emit()
    events.clockChanged.emit()
    assert seen == ["displaysOff", "displaysOn", "clockChanged"]


# --- From the audit: what the watcher must not get stuck on --------------------


def test_a_sleep_that_never_happened_does_not_leave_the_displays_asleep():
    # A sleep that failed or was cancelled sends no resume: the displays stayed
    # "asleep" (nothing sent to them, display changes ignored) for the session.
    events = FakeEvents()
    w, clock, seen = watcher(events)
    events.suspending.emit()
    for _ in range(18):  # the clock checks keep running normally for 90 s: the PC is awake
        clock.now += 5
        w.check_clock()
    assert seen == ["suspending"]  # not yet: Windows may still be on its way to sleep
    clock.now += 5
    w.check_clock()
    assert seen == ["suspending", "resumed"]
    events.displayChanged.emit()
    assert w._settle.isActive()  # display changes count again


def test_changing_the_clock_is_not_taken_for_waking_up():
    events = FakeEvents()
    w, clock, seen = watcher(events)
    clock.now += 3600  # the clock was set an hour forward...
    events.clockChanged.emit()  # ...and Windows said so
    w.check_clock()
    assert seen == ["clockChanged"]


def sleeping_watcher(events):
    """A watcher with both clocks faked: the wall clock and time that counts sleep."""
    wall, ticks = Clock(), Clock()
    w = DisplayWatcher(QApplication.instance(), clock=wall, events=events, ticks=ticks)
    seen = []
    for name in ("suspending", "resumed", "clockChanged"):
        getattr(w, name).connect(lambda name=name: seen.append(name))
    return w, wall, ticks, seen


def sleep(wall, ticks, seconds):
    wall.now += seconds
    ticks.now += seconds


def test_windows_syncing_the_clock_as_it_wakes_doesnt_hide_the_wake(caplog):
    """A tester's log: Modern Standby sends no suspend or resume, and Windows
    synced the clock before the next check; the jump was put down to the
    clock change, and the wake went unnoticed."""
    events = FakeEvents()
    w, wall, ticks, seen = sleeping_watcher(events)
    sleep(wall, ticks, 29100)
    events.clockChanged.emit()
    with caplog.at_level("INFO"):
        w.check_clock()
    assert seen == ["clockChanged", "resumed"]
    assert "Woke up after 29100 s" in caplog.text


def test_a_sleep_windows_announced_isnt_taken_for_one_that_never_happened(caplog):
    """The same log: "going to sleep 23499 s ago, but it is still running",
    after a 6-hour sleep whose wake came with a clock change first."""
    events = FakeEvents()
    w, wall, ticks, seen = sleeping_watcher(events)
    events.suspending.emit()
    sleep(wall, ticks, 23499)
    events.clockChanged.emit()
    with caplog.at_level("INFO"):
        w.check_clock()
    assert seen == ["suspending", "clockChanged", "resumed"]
    assert "Woke up after 23499 s" in caplog.text and "still running" not in caplog.text


def test_setting_the_clock_forward_is_still_not_a_wake():
    events = FakeEvents()
    w, wall, ticks, seen = sleeping_watcher(events)
    wall.now += 3600  # set an hour forward: time that counts sleep doesn't move
    ticks.now += 5
    events.clockChanged.emit()
    w.check_clock()
    assert seen == ["clockChanged"]


def test_the_wall_clock_still_notices_a_wake_where_the_other_clock_misses_it():
    w, wall, ticks, seen = sleeping_watcher(FakeEvents())
    wall.now += 600  # a clock that stopped while asleep: the wall clock tells
    ticks.now += 5
    w.check_clock()
    assert seen == ["resumed"]


def test_time_with_sleep_is_a_steady_clock():
    from nightlight.system.watcher import time_with_sleep

    first = time_with_sleep()
    assert time_with_sleep() >= first


def test_input_while_the_displays_are_reported_off_means_they_are_on():
    # A missed "display on" notification left them "off" until the next sleep.
    events = FakeEvents()
    idle = {"s": 300.0}
    clock = Clock()
    w = DisplayWatcher(QApplication.instance(), clock=clock, events=events, idle_seconds=lambda: idle["s"])
    seen = []
    for name in ("displaysOff", "displaysOn"):
        getattr(w, name).connect(lambda name=name: seen.append(name))
    events.displayOff.emit()
    clock.now += 5
    w.check_clock()
    assert seen == ["displaysOff"]  # no input: still off
    idle["s"] = 1.0  # a key was pressed
    clock.now += 5
    w.check_clock()
    assert seen == ["displaysOff", "displaysOn"]
    clock.now += 5
    w.check_clock()
    assert seen == ["displaysOff", "displaysOn"]  # once


# --- From the 0.2.0 audit -------------------------------------------------------


def test_the_input_that_turned_the_displays_off_does_not_turn_them_on():
    """A hotkey or a click on "turn off display" is input just before the
    "off": it used to read as the displays being back on at the next check,
    and the app sent DDC/CI to monitors that were asleep."""
    events = FakeEvents()
    idle = {"s": 0.5}
    clock = Clock()
    w = DisplayWatcher(QApplication.instance(), clock=clock, events=events, idle_seconds=lambda: idle["s"])
    seen = []
    w.displaysOn.connect(lambda: seen.append("on"))
    events.displayOff.emit()  # half a second after the key that did it
    clock.now += 5
    idle["s"] += 5
    w.check_clock()
    assert seen == []
    idle["s"] = 0.3  # a real key press, well after the displays went off
    clock.now += 5
    w.check_clock()
    assert seen == ["on"]


def test_a_display_that_keeps_changing_is_still_acted_on():
    """A loose cable sends a change every second: the settle timer kept
    restarting, so detection never ran."""
    w, clock, _seen = watcher()
    changed = []
    w.displaysChanged.connect(lambda: changed.append(True))
    for _ in range(5):
        w._changed("flapping")
        clock.now += 1
        assert not changed
    w._changed("flapping")  # 5 s since the first change
    assert changed == [True]
    w._changed("flapping again")
    assert changed == [True] and w._settle.isActive()  # a new burst starts over


def test_a_stopped_watcher_signals_nothing():
    events = FakeEvents()
    w, clock, seen = watcher(events)
    changed = []
    w.displaysChanged.connect(lambda: changed.append(True))
    w.stop()
    events.displayChanged.emit()
    clock.now += 600
    w.check_clock()
    w._settle.timeout.emit()
    assert not w._settle.isActive() and changed == [] and seen == []


def test_screen_signals_reach_methods_not_lambdas():
    """Lambdas connected to the application's signals outlive the watcher
    and would call into a deleted object; methods are disconnected with it."""
    import inspect

    from nightlight.system import watcher as module

    source = inspect.getsource(module.DisplayWatcher.__init__) + inspect.getsource(module.DisplayWatcher._watch)
    assert "connect(lambda" not in source
