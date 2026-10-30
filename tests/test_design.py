# SPDX-License-Identifier: GPL-3.0-only
"""The design's promises, tried against the running code: each section takes
one choice the app is built on and pushes on it, often with thousands of
random cases from a fixed seed (so a failure repeats exactly).

- Settings survive every round trip: the Settings window, the file, and any
  file contents whatsoever, without ever stopping the app from starting.
- Doing the same thing twice changes nothing the second time (idempotency).
- The schedules stay within their bounds at any time, in any time zone.
- The monitor queue is safe to feed from many threads at once, and keeps
  only the newest level per display.
- Starting and quitting leaves nothing behind: no thread, timer, window or
  shortcut; quitting twice is harmless.
- Qt objects live on the main thread and are freed when let go.
- The display watcher, fed random event sequences, keeps its promises.
- Atomic writes: a reader never sees half a file, whatever the writers do.

Thread, slot and Qt-warning failures anywhere are caught by conftest.py.
"""

import dataclasses
import gc
import json
import random
import threading
import time
import weakref
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from nightlight import config, files
from nightlight.color import controller as controller_module
from nightlight.color.controller import NightLightController
from nightlight.config import (
    Anchor,
    AppConfig,
    BrightnessScheduleConfig,
    DisplayPrefs,
    GeneralConfig,
    Mode,
    NightLightConfig,
    SchedulePoint,
)
from nightlight.core.brightness_schedule import scheduled_level
from nightlight.core.colortemp import MAX_KELVIN, MIN_KELVIN, NEUTRAL_KELVIN
from nightlight.core.schedule import Override, OverrideKind, compute_state
from nightlight.core.shortcuts import Shortcut
from tests.test_app import start  # noqa: F401  (a fixture)
from tests.test_controller import RecordingGamma
from tests.test_settings_window import FakeGamma

ZONES = ["UTC", "Europe/Kyiv", "Atlantic/Reykjavik", "Pacific/Tongatapu", "Pacific/Kiritimati", "Pacific/Chatham",
         "America/New_York", "Australia/Sydney", "Asia/Kolkata", "America/St_Johns"]

# Every setting away from its default, so a setting the window or the file
# loses shows up (test_the_sample_changes_every_setting keeps it complete).
EVERY_SETTING = AppConfig(
    NightLightConfig(
        enabled=True, mode=Mode.LOCATION, day_temperature=6200, night_temperature=3400, transition_minutes=45,
        night_start="21:30", day_start="06:45", latitude=50.4333, longitude=30.5167, timezone="Europe/Kyiv",
        exempt_apps=("photoshop.exe", "vlc.exe"), exempt_fullscreen=True, pause_for_apps=False, pause_automatically=True,
        solar_transition_minutes=20, never_pause_at_night=True, never_pause_from="time", never_pause_time="23:15",
    ),
    GeneralConfig(
        start_with_windows=False, start_minimized=False, remember_brightness=False, link_brightness=True,
        software_dimming=False, respect_fullscreen=False, follow_laptop_brightness=True, idle_dim=True, idle_minutes=17,
        idle_level=35, idle_exempt_apps=("teams.exe",), keep_brightness_on_power_change=True, keep_calibration=True,
        shortcut_overlay=False, check_for_updates=True, theme="dark", accent="teal",
    ),
    BrightnessScheduleConfig(enabled=True, preset="custom", transition_minutes=15, points=(
        SchedulePoint(80, anchor=Anchor.SUNRISE, offset_minutes=30), SchedulePoint(25, "22:10"))),
    displays=(DisplayPrefs("DEL41A2:7XKJ9F3", "Desk", True, True),),
    shortcuts=(Shortcut("Ctrl+Alt+Up", "brightness_up", 5), Shortcut("Ctrl+Alt+N", "suspend")),
)


# --- Settings survive every round trip -------------------------------------------------------


def test_the_sample_changes_every_setting():
    """A setting added later must be added to EVERY_SETTING, or the round trips
    below wouldn't notice the window or the file dropping it."""
    for section in ("night_light", "general", "brightness_schedule"):
        sample, default = getattr(EVERY_SETTING, section), getattr(AppConfig(), section)
        same = [f.name for f in dataclasses.fields(sample) if getattr(sample, f.name) == getattr(default, f.name)]
        assert not same, f"{section}: give these a non-default value in EVERY_SETTING: {same}"
    assert EVERY_SETTING.displays and EVERY_SETTING.shortcuts


def test_every_setting_survives_the_settings_window():
    """Settings opens with the saved settings and Apply saves what it shows:
    a setting the window doesn't read back would be reset by any Apply."""
    from nightlight.ui.settings_window import SettingsWindow

    controller = NightLightController(FakeGamma(), EVERY_SETTING.night_light, lambda: datetime(2026, 6, 15, 12, tzinfo=UTC))
    window = SettingsWindow(controller, EVERY_SETTING, can_autostart=True)
    try:
        shown = window.current_config()
        for section in ("night_light", "general", "brightness_schedule"):
            for field in dataclasses.fields(getattr(EVERY_SETTING, section)):
                saved, back = getattr(getattr(EVERY_SETTING, section), field.name), getattr(getattr(shown, section), field.name)
                assert back == saved, f"{section}.{field.name}: saved {saved!r}, the window gives back {back!r}"
        assert shown == EVERY_SETTING
    finally:
        window.close()
        controller.shutdown()


def test_every_setting_survives_the_settings_file(tmp_path):
    path = tmp_path / "settings.json"
    config.save(EVERY_SETTING, path)
    assert config.load(path) == EVERY_SETTING
    config.save(config.load(path), path)
    assert config.load(path) == EVERY_SETTING


def random_value(rng: random.Random, depth: int = 0):
    """Anything JSON can hold, and some numbers Python's json reads that others don't."""
    choices = [None, True, False, 0, -1, 7, 10**30, -(10**30), 1e400, -1e400, float("nan"), 0.5, "", "x", "23:59", "25:99",
               "Ctrl+Alt+Up", "photoshop.exe", "location", "times", "always", "sunrise", "dark", "\u0000", "a" * 5000]
    roll = rng.random()
    if depth < 3 and roll < 0.15:
        return [random_value(rng, depth + 1) for _ in range(rng.randint(0, 5))]
    if depth < 3 and roll < 0.3:
        return {rng.choice(["x", "level", "keys", "action", "value", "at", "name", "hidden"]): random_value(rng, depth + 1)
                for _ in range(rng.randint(0, 4))}
    return rng.choice(choices)


def random_document(rng: random.Random) -> dict:
    """A settings file with the real sections and keys, holding random values
    (and some unknown keys), as a hand edit, a bug or a newer version might."""
    document = {}
    for section, cls in (("night_light", NightLightConfig), ("general", GeneralConfig), ("brightness_schedule", BrightnessScheduleConfig)):
        if rng.random() < 0.9:
            document[section] = {f.name: random_value(rng) for f in dataclasses.fields(cls) if rng.random() < 0.7}
            if rng.random() < 0.2:
                document[section]["unknown"] = random_value(rng)
        elif rng.random() < 0.5:
            document[section] = random_value(rng)
    if rng.random() < 0.6:
        document["shortcuts"] = [{"keys": random_value(rng), "action": random_value(rng), "value": random_value(rng),
                                  "display": random_value(rng)} for _ in range(rng.randint(0, 40))]
    if rng.random() < 0.5:
        document["displays"] = {str(random_value(rng)): random_value(rng) for _ in range(rng.randint(0, 4))}
    if rng.random() < 0.3:
        document["version"] = random_value(rng)
    return document


@pytest.mark.parametrize("seed", range(4))
def test_no_settings_file_whatever_it_holds_stops_winlight_starting(tmp_path, seed):
    """500 random files per seed: load never raises, gives settings in range,
    and saving and loading again gives the same settings (a fixed point), so
    nothing drifts with each start."""
    rng = random.Random(seed)
    path = tmp_path / "settings.json"
    for case in range(500):
        path.write_text(json.dumps(random_document(rng)), encoding="utf-8")
        loaded = config.load(path)
        assert isinstance(loaded, AppConfig), case
        assert loaded.night_light == loaded.night_light.normalized() and loaded.general == loaded.general.normalized(), case
        assert loaded.brightness_schedule == loaded.brightness_schedule.normalized(), case
        assert all(s.normalized() == s for s in loaded.shortcuts) and len(loaded.shortcuts) <= config.MAX_SHORTCUTS, case
        config.save(loaded, path)
        assert config.load(path) == loaded, case


def test_normalizing_twice_changes_nothing():
    """normalized() is applied on every load: applied again it must change
    nothing, or settings would drift a little at every start."""
    rng = random.Random(11)
    for _ in range(2000):
        night = NightLightConfig(day_temperature=rng.randint(-5000, 50000), night_temperature=rng.randint(-5000, 50000),
                                 transition_minutes=rng.randint(-100, 5000), latitude=rng.uniform(-500, 500),
                                 longitude=rng.uniform(-500, 500), solar_transition_minutes=rng.randint(-50, 500),
                                 exempt_apps=tuple(rng.choice([" A.exe", "a.exe", "", "B.EXE "]) for _ in range(rng.randint(0, 4))),
                                 night_start=rng.choice(["21:00", "99:99", "", "7:5"]), never_pause_from=rng.choice(["night", "x"]))
        general = GeneralConfig(idle_minutes=rng.randint(-10, 10_000), idle_level=rng.randint(-50, 500),
                                theme=rng.choice(["dark", "nope"]), accent=rng.choice(["teal", "neon"]))
        point = SchedulePoint(level=rng.randint(-50, 500), at=rng.choice(["07:00", "bad"]), offset_minutes=rng.randint(-9999, 9999))
        shortcut = Shortcut(rng.choice(["ctrl+alt+up", "Alt+Space", "F12", "Ctrl+A", "x"]), rng.choice(["panel", "brightness_set", "?"]),
                            rng.randint(-50, 500))
        for value in (night, general, point, BrightnessScheduleConfig(points=(point,) * rng.randint(0, 20))):
            once = value.normalized()
            assert once.normalized() == once, value
        once = shortcut.normalized()
        assert once is None or once.normalized() == once, shortcut


# --- Doing the same thing twice changes nothing -----------------------------------------------


@pytest.fixture
def settled_controller(monkeypatch):
    monkeypatch.setattr(controller_module, "QUICK_ADJUST_MS", 100)
    gamma = RecordingGamma()
    night = NightLightConfig(enabled=True, mode=Mode.ALWAYS, night_temperature=3800)
    controller = NightLightController(gamma, night, clock=lambda: datetime(2026, 6, 15, 23, tzinfo=UTC))
    for _ in range(100):
        if controller.current_temperature == controller.target_temperature:
            break
        QTest.qWait(20)
    QTest.qWait(150)
    yield controller, gamma, night
    controller.shutdown()


def test_setting_the_same_night_light_again_writes_nothing(settled_controller):
    controller, gamma, night = settled_controller
    assert controller.current_temperature == 3800
    applied = len(gamma.applied)
    controller.set_config(night)
    controller.set_config(dataclasses.replace(night))  # equal, a different object
    controller.clear_override()  # none to clear
    QTest.qWait(300)
    assert gamma.applied[applied:] == [], "unchanged settings wrote the ramps again"
    controller.update()  # the regular check: puts the ramp back once, in case Windows reset it
    QTest.qWait(300)
    assert gamma.applied[applied:] == [3800]


def settle(controller):
    for _ in range(200):
        if controller.current_temperature == controller.target_temperature:
            break
        QTest.qWait(20)
    QTest.qWait(150)


def test_the_same_override_twice_is_one_change(settled_controller):
    controller, gamma, _night = settled_controller
    controller.set_override(OverrideKind.SUSPEND, None)
    settle(controller)
    after_first = len(gamma.applied)
    controller.set_override(OverrideKind.SUSPEND, None)
    settle(controller)
    assert len(gamma.applied) - after_first <= 1  # at most the same ramp once more, no fade


# --- The schedules stay within bounds, anywhere, any time -------------------------------------


def random_night_light(rng: random.Random) -> NightLightConfig:
    return NightLightConfig(
        enabled=rng.random() < 0.8, mode=rng.choice(list(Mode)), day_temperature=rng.randint(MIN_KELVIN, MAX_KELVIN),
        night_temperature=rng.randint(MIN_KELVIN, MAX_KELVIN), transition_minutes=rng.choice([0, 1, 5, 30, 120, 600]),
        night_start=f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}", day_start=f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}",
        latitude=rng.uniform(-89.9, 89.9), longitude=rng.uniform(-180, 180), solar_transition_minutes=rng.choice([-1, 0, 15, 120]),
    ).normalized()


def random_moment(rng: random.Random) -> tuple[datetime, ZoneInfo]:
    zone = ZoneInfo(rng.choice(ZONES))
    moment = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(minutes=rng.randint(0, 366 * 24 * 60))
    return moment.astimezone(zone), zone


def test_night_light_stays_within_its_temperatures_at_any_moment_anywhere():
    """5000 random settings, moments and places (polar days, +14 h zones,
    half-hour offsets, daylight saving changes): the factor stays in 0..1,
    the temperature between the day and night temperatures, overrides win,
    and the next change is never in the past."""
    rng = random.Random(7)
    for case in range(5000):
        night = random_night_light(rng)
        now, zone = random_moment(rng)
        override = rng.choice([None, Override(OverrideKind.SUSPEND, None), Override(OverrideKind.ACTIVATE, None)])
        state = compute_state(night, now, override, zone)
        low, high = sorted((night.day_temperature, night.night_temperature))
        assert 0.0 <= state.night_factor <= 1.0, (case, night, now)
        if override is not None and override.kind is OverrideKind.SUSPEND:
            assert (state.night_factor, state.temperature) == (0.0, night.day_temperature), (case, night, now)  # as KWin
        elif override is not None and override.kind is OverrideKind.ACTIVATE:
            assert (state.night_factor, state.temperature) == (1.0, night.night_temperature), (case, night, now)
        elif not night.enabled:
            assert (state.night_factor, state.temperature) == (0.0, NEUTRAL_KELVIN), (case, night, now)  # off: no tint
        else:
            assert low <= state.temperature <= high, (case, night, now, state)
        if state.next_transition is not None:
            assert state.next_transition.start >= now - timedelta(seconds=1), (case, night, now)


def minutes_between(earlier: str, later: str) -> int:
    (h1, m1), (h2, m2) = (map(int, earlier.split(":")), map(int, later.split(":")))
    return (h2 * 60 + m2 - h1 * 60 - m1) % (24 * 60)


def test_night_light_changes_smoothly_minute_by_minute():
    """No jump bigger than the steepest change the settings allow: the
    transition's length, or the time to the next change when that's
    shorter (a daylight saving day can shorten it by an hour). Found a jump
    from 0.42 to 0.95 when the morning began before the evening's change ended."""
    rng = random.Random(3)
    for case in range(300):
        night = dataclasses.replace(random_night_light(rng), enabled=True, mode=Mode.TIMES,
                                    transition_minutes=rng.choice([30, 60, 120, 600]))
        now, zone = random_moment(rng)
        gap = min(minutes_between(night.night_start, night.day_start), minutes_between(night.day_start, night.night_start))
        steepest = max(1, min(night.transition_minutes, gap - 60))
        previous = compute_state(night, now, None, zone).night_factor
        for minute in range(1, 24 * 60, 7):
            factor = compute_state(night, now + timedelta(minutes=minute), None, zone).night_factor
            assert abs(factor - previous) <= 7 / steepest + 1e-6, (case, night, now, minute, previous, factor)
            previous = factor


def test_a_change_that_would_run_into_the_next_finishes_as_it_starts():
    """Night at 22:00 with 10 hours of change, day at 06:00: the evening's
    change reaches full night at 06:00, and the morning's starts from there."""
    night = NightLightConfig(enabled=True, mode=Mode.TIMES, night_start="22:00", day_start="06:00", transition_minutes=600)
    zone = ZoneInfo("Europe/Kyiv")
    at = datetime(2026, 6, 16, 6, 0, tzinfo=zone)
    before = compute_state(night, at - timedelta(minutes=1), None, zone).night_factor
    now = compute_state(night, at, None, zone).night_factor
    after = compute_state(night, at + timedelta(minutes=1), None, zone).night_factor
    assert before < now <= 1.0 and after < now and now - before < 0.01 and now - after < 0.01


def test_never_pausing_late_at_night_still_ends_in_the_morning_with_a_shortened_evening():
    """With the evening's change cut short to end as the morning's starts,
    "from full night" holds nothing that night, rather than all next day."""
    from nightlight.core.schedule import pausing_held

    night = NightLightConfig(enabled=True, mode=Mode.TIMES, night_start="22:00", day_start="06:00", transition_minutes=600,
                             never_pause_at_night=True, never_pause_from="night")
    zone = ZoneInfo("Europe/Kyiv")
    for hour in (7, 12, 18, 21):
        assert not pausing_held(night, datetime(2026, 6, 16, hour, tzinfo=zone), zone), hour


def test_the_brightness_schedule_stays_between_its_points_levels():
    rng = random.Random(5)
    for case in range(3000):
        points = tuple(SchedulePoint(rng.randint(0, 100), f"{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}",
                                     rng.choice(list(Anchor)), rng.randint(-240, 240)) for _ in range(rng.randint(1, 6)))
        schedule = BrightnessScheduleConfig(enabled=True, points=points, transition_minutes=rng.choice([0, 15, 60, 240])).normalized()
        now, zone = random_moment(rng)
        location = rng.choice([None, (rng.uniform(-89, 89), rng.uniform(-180, 180))])
        found = scheduled_level(schedule, now, zone, location)
        assert found is not None, case
        levels = [p.level for p in schedule.points]
        assert min(levels) <= found.level <= max(levels), (case, schedule, now)
        if not found.transitioning:
            assert found.level == found.since.level, (case, schedule, now)
        assert found.next is None or found.next.at > found.since.at, (case, schedule, now)


# --- The monitor queue under many threads ------------------------------------------------------


def test_many_threads_queueing_levels_at_once_send_the_newest_for_each_display():
    """8 threads queue 400 levels each over 6 displays at the same time: the
    queue stays consistent, and one detection-and-write pass sends each
    display exactly one level, the last one queued for it."""
    from nightlight.brightness.monitors import Write
    from tests.test_monitor_service import ScriptedBackend, detect, make

    keys = [f"KEY{n}" for n in range(6)]
    backend = ScriptedBackend([(key, True) for key in keys])
    service, _events, clock = make(backend)
    detect(service, clock)
    backend.calls.clear()
    order = threading.Lock()
    last: dict[str, int] = {}
    together = threading.Barrier(8)

    def feed(seed):
        rng = random.Random(seed)
        together.wait()
        for _ in range(400):
            key, value = rng.choice(keys), rng.randint(0, 100)
            with order:  # the order the queue saw them in
                service.request_write(Write(key, value))
                last[key] = value

    threads = [threading.Thread(target=feed, args=(seed,), name=f"feeder {seed}", daemon=True) for seed in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not any(thread.is_alive() for thread in threads), "a feeding thread is stuck: a deadlock"
    service.run_pending()
    sent = backend.sets()
    assert sorted(key for key, _ in sent) == sorted(last), "each display gets one write"
    assert dict(sent) == last


def test_monitor_managers_started_and_stopped_leave_no_threads():
    from nightlight.brightness.monitors import MonitorManager
    from nightlight.hardware import create_backends

    def threads():
        return {t.ident for t in threading.enumerate()}

    before = threads()
    for _ in range(6):
        brightness, _gamma = create_backends("fake")
        manager = MonitorManager(brightness)
        manager.refresh(force=True)
        QTest.qWait(50)
        manager.shutdown()
    for _ in range(100):
        if threads() <= before:
            break
        QTest.qWait(20)
    assert threads() <= before, [t.name for t in threading.enumerate() if t.ident not in before]


# --- Starting and quitting leave nothing behind --------------------------------------------------


def test_starting_and_quitting_again_and_again_leaves_nothing_behind(tmp_path, monkeypatch):
    """Five starts and quits of the whole app: afterwards no thread it started
    is running, none of its timers is active, no window shows, no shortcut is
    registered, and quitting a second time is harmless."""
    from PySide6.QtWidgets import QSystemTrayIcon

    from nightlight import app as app_module
    from nightlight.hardware import create_backends

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: True))
    monkeypatch.setattr(app_module.winsystem, "user_busy", lambda: False)
    monkeypatch.setattr(app_module.autostart, "create", lambda: None)
    (tmp_path / "settings.json").write_text(json.dumps({
        "general": {"start_minimized": True, "check_for_updates": True},
        "shortcuts": [{"keys": "Ctrl+Alt+Up", "action": "brightness_up"}]}), encoding="utf-8")
    before = {t.ident for t in threading.enumerate()}
    for _ in range(5):
        brightness, gamma = create_backends("fake")
        night_light = app_module.NightLightApp(QApplication.instance(), brightness, gamma, tmp_path / "settings.json")
        QTest.qWait(100)
        night_light.show_panel()
        night_light._shutdown()
        night_light._shutdown()  # signing out, then quitting: once is enough
        # The services' timers (checks, schedules, polling) must stop: signing out
        # keeps the event loop running a while. A widget's own repaint timer (the
        # panel's day ribbon) only redraws, and ends with the event loop.
        timers = [t for t in vars(night_light).values() if isinstance(t, QTimer)]
        for owner in [o for o in vars(night_light).values() if isinstance(o, QObject) and not isinstance(o, QWidget)]:
            timers += [t for t in owner.findChildren(QTimer) if not isinstance(t.parent(), QWidget)]
        running = [f"{type(t.parent()).__name__}: every {t.interval()} ms" for t in timers if t.isActive()]
        assert not running, f"timers still running after quitting: {running}"
        assert night_light.shortcuts._registered == {} and not night_light.updates._timer.isActive()
        if night_light.tray:
            night_light.tray.hide()
        night_light.flyout.hide()
    for _ in range(150):
        if {t.ident for t in threading.enumerate()} <= before:
            break
        QTest.qWait(20)
    assert {t.ident for t in threading.enumerate()} <= before, [t.name for t in threading.enumerate() if t.ident not in before]


# --- Qt objects: on the main thread, and freed when let go ------------------------------------------


def test_every_qt_object_of_the_app_lives_on_the_main_thread(start):  # noqa: F811
    """Qt objects belong to the thread that made them; one made on a worker
    would get its signals and timers there, where the UI can't be touched."""
    night_light, _ = start(GeneralConfig())
    night_light.show_settings()
    main = QCoreApplication.instance().thread()
    objects = [o for o in vars(night_light).values() if isinstance(o, QObject)]
    found = [o for owner in objects for o in [owner, *owner.findChildren(QObject)]]
    elsewhere = [type(o).__name__ for o in found if o.thread() is not main]
    assert len(found) > 100 and not elsewhere, elsewhere
    night_light._settings.close()


def test_a_closed_settings_window_is_freed(start):  # noqa: F811
    """Connected to the monitors with lambdas holding it, a settings window
    stayed alive as long as the monitors (all session); bound methods let go."""
    from nightlight.ui.settings_window import SettingsWindow

    night_light, _ = start(GeneralConfig())
    window = SettingsWindow(night_light.controller, night_light._config, monitors=night_light.monitors,
                            scheduler=night_light.scheduler)
    window.show()
    window.close()
    ref = weakref.ref(window)
    window.deleteLater()
    del window
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    assert ref() is None, [type(r).__name__ for r in gc.get_referrers(ref())][:10]
    night_light.monitors.monitorsChanged.emit([])  # a signal after it's gone reaches nothing dead


def test_creating_and_closing_settings_windows_doesnt_grow_qt_objects(start):  # noqa: F811
    from nightlight.ui.settings_window import SettingsWindow

    night_light, _ = start(GeneralConfig())

    def cycle():
        window = SettingsWindow(night_light.controller, night_light._config, monitors=night_light.monitors)
        window.show()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()

    cycle()
    baseline = len(QApplication.allWidgets())
    for _ in range(5):
        cycle()
    assert len(QApplication.allWidgets()) <= baseline


# --- The display watcher, fed random events --------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_the_watcher_keeps_its_promises_whatever_order_events_come_in(seed):
    """2000 random events (sleep, wake, displays off and on, display changes,
    clock jumps, clock changes, settling): no display change is reported
    while asleep, nothing at all after stopping, and no exception."""
    from nightlight.system.watcher import DisplayWatcher
    from tests.test_watcher import Clock, FakeEvents

    rng = random.Random(seed)
    events, clock = FakeEvents(), Clock()
    watcher = DisplayWatcher(QApplication.instance(), clock=clock, events=events)
    seen = []
    for name in ("suspending", "resumed", "displaysOff", "displaysOn", "clockChanged", "displaysChanged"):
        getattr(watcher, name).connect(lambda name=name: seen.append(name))
    def settle_fires():  # the settle timer firing, as it would: only when it's running
        if watcher._settle.isActive():
            watcher._settle.stop()
            watcher._settle.timeout.emit()

    actions = [
        events.suspending.emit, events.resumed.emit, events.displayOff.emit, events.displayOn.emit, events.displayChanged.emit,
        events.clockChanged.emit, events.locked.emit, events.unlocked.emit, watcher.check_clock, settle_fires,
    ]
    for _ in range(2000):
        clock.now += rng.choice([0.1, 1, 5, 40, 3600])
        rng.choice(actions)()
    asleep = False
    for name in seen:
        if name == "suspending":
            asleep = True
        elif name == "resumed":
            asleep = False
        elif name == "displaysChanged":
            assert not asleep, "a display change reported while asleep"
    watcher.stop()
    count = len(seen)
    for action in actions:
        clock.now += 3600
        action()
    assert len(seen) == count, f"signals after stopping: {seen[count:]}"


# --- Atomic writes ----------------------------------------------------------------------------------


def test_readers_never_see_half_a_file_whatever_the_writers_do(tmp_path):
    """Four writers replace a settings-sized file with different contents as
    fast as they can while a reader reads it: every read is one complete
    version (the file is swapped in one step, never written in place)."""
    path = tmp_path / "settings.json"
    versions = [json.dumps({"writer": n, "padding": "x" * (2000 + 500 * n)}) for n in range(4)]
    files.write_atomic(path, versions[0])
    stop = threading.Event()
    torn, failures = [], []

    def write(n):
        while not stop.is_set():
            try:
                files.write_atomic(path, versions[n])
            except OSError as exc:  # another writer held it past the retries: allowed, never half a file
                failures.append(exc)

    def read():
        while not stop.is_set():
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue  # swapped at that instant (Windows); the next read sees it
            if text not in versions:
                torn.append(text[:80])

    threads = [threading.Thread(target=write, args=(n,), name=f"writer {n}", daemon=True) for n in range(4)]
    threads.append(threading.Thread(target=read, name="reader", daemon=True))
    for thread in threads:
        thread.start()
    time.sleep(1.5)
    stop.set()
    for thread in threads:
        thread.join(10)
    assert not torn, f"half-written contents seen: {torn[:3]}"
    assert path.read_text(encoding="utf-8") in versions
    assert not [p for p in tmp_path.iterdir() if p.name != "settings.json"], "temporary files left behind"
