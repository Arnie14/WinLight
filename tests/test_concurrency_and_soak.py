# SPDX-License-Identifier: GPL-3.0-only
"""Many things at once, and many things for a long time.

- The gamma backend called from several threads at once (the UI, the call
  runner's threads, a stuck call coming back late): no deadlock, no torn
  ramp, and the last tint asked for is the one on screen.
- Several launches knocking on the single-instance pipe at the same moment.
- Soaks of the night light controller and the brightness scheduler: random
  settings, overrides, time jumps (forwards, backwards, across daylight
  saving), displays coming and going, users taking over; their invariants
  hold at every step.
- Signals from the monitor thread arrive on the main thread.
- The atomic writer cleans up after itself even when it fails.
- The suite passes in reverse order too: no test depends on another's leftovers.
"""

import os
import random
import subprocess
import sys
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QCoreApplication, QThread
from PySide6.QtTest import QTest

from nightlight import files
from nightlight.brightness.monitors import Status
from nightlight.color import controller as controller_module
from nightlight.color.controller import NightLightController
from nightlight.config import Anchor, BrightnessScheduleConfig, Mode, NightLightConfig, SchedulePoint
from nightlight.core.colortemp import MAX_KELVIN, MIN_KELVIN, identity_ramp, whitepoint
from nightlight.core.schedule import OverrideKind
from nightlight.hardware import win32, windows
from tests.test_controller import RecordingGamma

ROOT = Path(__file__).resolve().parent.parent


# --- The gamma backend from several threads -----------------------------------------------------


def test_the_gamma_backend_from_many_threads_at_once_ends_on_the_last_tint(monkeypatch):
    """Six threads tint, check, re-apply, pause, dim and reset two displays
    as fast as they can for a second: nothing deadlocks or raises, every
    ramp written is a whole ramp, and the tint asked for last is on screen."""
    from tests.test_windows_backend import FakeGdi, same, target

    names = (r"\\.\DISPLAY1", r"\\.\DISPLAY2")
    gdi = FakeGdi({name: identity_ramp() for name in names}, min_peak=0.0)
    written_lock, torn = threading.Lock(), []
    real_set = gdi.set

    def checked_set(name, ramp):
        if len(ramp) != 3 or any(len(channel) != 256 for channel in ramp):
            with written_lock:
                torn.append(name)
        return real_set(name, ramp)

    gdi.install(monkeypatch, [target(names[0], "A"), target(names[1], "B")])
    monkeypatch.setattr(win32, "set_gamma_ramp", checked_set)
    gamma = windows.WindowsGammaBackend()
    stop, errors = threading.Event(), []

    def work(seed):
        rng = random.Random(seed)
        actions = [lambda: gamma.apply(rng.randint(1900, 6500)), gamma.verify, gamma.reapply,
                   lambda: gamma.set_override(rng.choice(names), rng.choice([6500, None])),
                   lambda: gamma.set_idle_dim(rng.choice([{}, {names[0]: 40}, {names[1]: 60}])), gamma.reset]
        while not stop.is_set():
            try:
                rng.choice(actions)()
            except Exception as exc:  # collected: the test fails on any
                errors.append(repr(exc))

    threads = [threading.Thread(target=work, args=(seed,), name=f"gamma {seed}", daemon=True) for seed in range(6)]
    for thread in threads:
        thread.start()
    QTest.qWait(1000)
    stop.set()
    for thread in threads:
        thread.join(10)
    assert not any(thread.is_alive() for thread in threads), "a thread is stuck in the gamma backend: a deadlock"
    assert not errors and not torn
    gamma.set_override(names[0], None)
    gamma.set_override(names[1], None)
    gamma.set_idle_dim({})
    gamma.apply(4500)
    for name in names:
        assert gdi.ramps[name][2][-1] / 65535 == pytest.approx(whitepoint(4500)[2], abs=0.01)
    gamma.reset()
    assert all(same(gdi.ramps[name], identity_ramp()) for name in names)


# --- The single-instance pipe, many launches at once ------------------------------------------------


def test_several_launches_at_the_same_moment_each_get_through():
    """Six second launches start together (double-clicks, a script): each
    reaches the running copy and is told to exit."""
    import uuid

    from nightlight.system.single_instance import SingleInstance
    from tests.test_single_instance import second_launch

    instance = SingleInstance(f"night-light-test-{uuid.uuid4().hex}")
    assert instance.notify_running() is False
    shown = []
    instance.activated.connect(lambda: shown.append(True))
    try:
        launches = [second_launch(instance._name, "launch") for _ in range(6)]
        for _ in range(750):
            if len(shown) == 6 and all(p.poll() is not None for p in launches):
                break
            QTest.qWait(20)
        assert len(shown) == 6
        assert [p.wait(10) for p in launches] == [0] * 6
    finally:
        instance.close()
        QTest.qWait(50)


# --- Soaks ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(3))
def test_night_light_soak(monkeypatch, seed):
    """1500 random steps: settings changed, overrides set and ended, previews,
    the clock jumping forwards and back, the timers firing. At every step the
    target stays a temperature the screen can show and the state agrees with
    the override; after quitting, nothing touches the screen."""
    monkeypatch.setattr(controller_module, "QUICK_ADJUST_MS", 20)
    rng = random.Random(seed)
    zone = ZoneInfo(rng.choice(["Europe/Kyiv", "America/New_York", "Pacific/Chatham"]))
    now = {"t": datetime(2026, 3, 27, 12, tzinfo=zone)}  # two days before Europe's spring change
    gamma = RecordingGamma()
    controller = NightLightController(gamma, NightLightConfig(enabled=True), clock=lambda: now["t"], zone=zone)
    for step in range(1500):
        roll = rng.random()
        if roll < 0.3:
            now["t"] += timedelta(minutes=rng.choice([1, 7, 59, 61, 600, -3, -90]))
            controller.update()
        elif roll < 0.45:
            controller.set_config(NightLightConfig(
                enabled=rng.random() < 0.85, mode=rng.choice(list(Mode)), night_temperature=rng.randint(MIN_KELVIN, 6500),
                transition_minutes=rng.choice([0, 15, 120, 600]), latitude=50.45, longitude=30.52,
                night_start=f"{rng.randint(0, 23):02d}:00", day_start=f"{rng.randint(0, 23):02d}:30").normalized())
        elif roll < 0.6:
            until = rng.choice([None, now["t"] + timedelta(minutes=rng.randint(-30, 120))])
            controller.set_override(rng.choice(list(OverrideKind)), until)
        elif roll < 0.7:
            controller.clear_override()
        elif roll < 0.8:
            controller.preview(rng.choice([None, rng.randint(MIN_KELVIN, MAX_KELVIN)]))
        else:
            QCoreApplication.processEvents()  # let the fade's timer run
        target = controller.target_temperature
        assert MIN_KELVIN <= target <= MAX_KELVIN, (step, target)
        assert 0.0 <= controller.state.night_factor <= 1.0, step
        override = controller.override
        if override is not None and not override.active_at(now["t"]):
            controller.update()  # an override past its end is dropped at the next update
            assert controller.override is None, step
    controller.preview(None)
    for _ in range(100):
        if controller.current_temperature == controller.target_temperature:
            break
        QTest.qWait(10)
    assert all(MIN_KELVIN <= k <= MAX_KELVIN for k in gamma.applied)
    controller.shutdown()
    written = len(gamma.applied)
    controller.update()
    controller.set_override(OverrideKind.ACTIVATE)
    controller.preview(3000)
    QTest.qWait(100)
    assert len(gamma.applied) == written, "the screen was touched after quitting"


@pytest.mark.parametrize("seed", range(3))
def test_brightness_schedule_soak(tmp_path, seed):
    """1000 random steps: hours passing (and the clock going back), displays
    plugged and unplugged, asleep and awake, the user setting levels, idle
    dimming holding. Every level the schedule sends is one of its points'
    (or between two of them), only to a display that's there and can take
    it, never to an unsupported one."""
    from nightlight.brightness.scheduler import BrightnessScheduler
    from tests.test_brightness_schedule import DELL, LG, PANEL, TV, Clock, FakeMonitors

    rng = random.Random(seed)
    zone = ZoneInfo("Europe/Kyiv")
    points = (SchedulePoint(90, "07:00"), SchedulePoint(60, anchor=Anchor.SUNSET, offset_minutes=-30), SchedulePoint(25, "23:30"))
    config = BrightnessScheduleConfig(enabled=True, preset="custom", points=points, transition_minutes=rng.choice([0, 30]))
    monitors, clock = FakeMonitors(), Clock(datetime(2026, 10, 24, 6, tzinfo=zone))  # a day before Europe's autumn change
    scheduler = BrightnessScheduler(monitors, config, tmp_path / "schedule.json", clock=clock, zone=zone, location=lambda: (50.45, 30.52))
    displays = [DELL, LG, PANEL, TV]
    present: list = []
    try:
        for _ in range(1000):
            roll = rng.random()
            if roll < 0.35:
                clock.now += timedelta(minutes=rng.choice([1, 5, 30, 61, 300, -20]))
                scheduler.evaluate("tick")
            elif roll < 0.5:
                present = rng.sample(displays, rng.randint(0, len(displays)))
                monitors.detect(*present, status=rng.choice([Status.OK, Status.READING]))
            elif roll < 0.6 and present:
                key = rng.choice(present).key
                if monitors.states[key].status is not Status.UNSUPPORTED:
                    monitors.set_status(key, rng.choice([Status.OK, Status.ASLEEP, Status.NOT_RESPONDING]))
            elif roll < 0.7 and present:
                display = rng.choice(present)
                monitors.set_brightness(display.key, rng.randint(0, 100))  # the user's own
            elif roll < 0.8:
                scheduler.set_held(rng.random() < 0.5)  # idle dimming holds the displays down
            else:
                scheduler.evaluate("timer")
        levels = [p.level for p in points]
        for key, value, source in monitors.sent:
            if source == "user":
                continue
            assert key != TV.key, "the schedule wrote to a display without brightness control"
            assert min(levels) <= value <= max(levels), (key, value)
    finally:
        scheduler.shutdown()


# --- Threads ----------------------------------------------------------------------------------------


def test_the_monitor_threads_events_arrive_on_the_main_thread():
    """The monitor service works on its own thread; everything it reports
    reaches the app through queued signals, on the main thread, where the
    UI can be touched."""
    from nightlight.brightness.monitors import MonitorManager
    from nightlight.hardware import create_backends

    brightness, _gamma = create_backends("fake")
    manager = MonitorManager(brightness)
    threads = []
    manager.monitorsChanged.connect(lambda _monitors: threads.append(QThread.currentThread()))
    manager.displayChanged.connect(lambda _key: threads.append(QThread.currentThread()))
    try:
        manager.refresh(force=True)
        for _ in range(200):
            if threads:
                break
            QTest.qWait(20)
        assert threads and all(thread is QCoreApplication.instance().thread() for thread in threads)
    finally:
        manager.shutdown()


# --- Files ------------------------------------------------------------------------------------------


def test_a_write_that_fails_leaves_the_old_file_and_no_temporary_one(tmp_path, monkeypatch):
    path = tmp_path / "settings.json"
    files.write_atomic(path, '{"old": true}')

    def locked(_source, _target):
        raise PermissionError("held open by another program")

    monkeypatch.setattr(files.os, "replace", locked)
    monkeypatch.setattr(files, "RETRY_DELAY_S", 0.001)
    with pytest.raises(PermissionError):
        files.write_atomic(path, '{"new": true}')
    assert path.read_text(encoding="utf-8") == '{"old": true}'
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


# --- Order ------------------------------------------------------------------------------------------

REVERSED = ["tests/test_shortcuts.py", "tests/test_shortcut_safeguards.py", "tests/test_updates.py", "tests/test_config.py",
            "tests/test_controller.py", "tests/test_watcher.py", "tests/test_monitor_service.py", "tests/test_schedule.py",
            "tests/test_commands.py", "tests/test_settings_window.py"]


@pytest.mark.skipif(bool(os.environ.get("WINLIGHT_INNER_RUN")), reason="the run inside this test")
def test_the_tests_pass_in_reverse_order_too():
    """A test that only passes after another (shared state, a leftover window,
    a patched module) passes in the usual order and hides a bug. Ten modules
    with the most shared state run here backwards, test by test."""
    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *REVERSED],
                               cwd=ROOT, capture_output=True, text=True, timeout=300)
    ids = [line for line in collected.stdout.splitlines() if "::" in line]
    assert len(ids) > 300, collected.stdout[-2000:]
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *reversed(ids)], cwd=ROOT,
                            capture_output=True, text=True, timeout=900, env={**os.environ, "WINLIGHT_INNER_RUN": "1"})
    assert result.returncode == 0, result.stdout[-4000:]
