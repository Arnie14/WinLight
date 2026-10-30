# SPDX-License-Identifier: GPL-3.0-only
"""Races, one at a time, in a fixed order.

Each test here stages one interleaving on purpose: a thread is held at a
gate inside a Windows call (tests/fake_windows.py), another arrives, the gate
opens, and the outcome is checked. Time is a fake clock moved by the test.
Nothing sleeps, so a test either always passes or always fails; the
concurrency marker runs just these (pytest -m concurrency), and
test_architecture.py keeps time.sleep out of them.

The stress tests in test_concurrency_and_soak.py throw random work at the
same code from many threads; these say exactly which order was tried.
"""

import itertools
import logging

import pytest

from nightlight.core.colortemp import dimmed_ramp, gamma_ramp, identity_ramp, ramps_match, whitepoint
from nightlight.hardware import windows
from nightlight.hardware.gamma import GammaBusy
from tests.fake_windows import FakeClock, FakeDisplay, FakeWindows, Gate, start_together

pytestmark = pytest.mark.concurrency

D1, D2 = r"\\.\DISPLAY1", r"\\.\DISPLAY2"
BLOCKED_S = 0.2  # how long a thread must stay blocked to count as waiting; never slept, only waited for at most


def expected(kelvin: int, dim: int = 100, base=None):
    under = dimmed_ramp(dim, 256, base) if dim < 100 else (base or identity_ramp())
    return gamma_ramp(whitepoint(kelvin), 256, under)


def shows(fake: FakeWindows, name: str, ramp) -> bool:
    """The same ramp, but for the nudge each tinted ramp gets (windows.NUDGE_STEPS)."""
    return ramps_match(fake.displays[name].ramp, ramp, tolerance=windows.NUDGE_STEPS)


def backend(*names, clock=None, journal=None):
    fake = FakeWindows(*(FakeDisplay(name, f"KEY{i}") for i, name in enumerate(names, start=1)), min_peak=0.0)
    gamma = windows.WindowsGammaBackend(api=fake, journal=journal, clock=clock or FakeClock())
    gamma.reset()  # lists the displays
    return fake, gamma


# --- Several owners of one gamma ramp -------------------------------------------------------------


def test_night_light_arriving_while_dimming_is_inside_the_driver_waits_and_both_end_on_screen():
    """Dimming runs on the monitor thread, night light on the UI thread; they
    share one ramp. Night light arriving mid-change must wait, not write a
    ramp of its own over the half-made one, and the ramp on screen at the end
    has both: tinted and dimmed."""
    fake, gamma = backend(D1)
    inside = Gate("dimming's SetDeviceGammaRamp")
    fake.script("set_gamma_ramp", inside, display=D1)
    dimming = start_together(lambda: gamma.set_dimming(D1, 50), names=("monitor thread",))
    assert inside.entered()
    night_light = start_together(lambda: gamma.apply(3000), names=("UI thread",))
    night_light.threads[0].join(BLOCKED_S)
    assert night_light.alive() == ["UI thread"], "night light didn't wait for the change in progress"
    assert not [c for c in fake.calls_of("set_gamma_ramp") if c.thread == "UI thread"]
    inside.open()
    dimming.join()
    night_light.join()
    assert shows(fake, D1, expected(3000, 50))


@pytest.mark.parametrize("first", ["night light", "dimming", "idle dimming", "pause"])
def test_every_owner_of_a_ramp_at_once_ends_with_all_of_them_on_screen(first):
    """Whichever change gets into the driver first, and in whatever order the
    others follow it, each change composes the whole ramp again: the result
    is the same, every layer present."""
    fake, gamma = backend(D1, D2)
    changes = {
        "night light": lambda: gamma.apply(3500),
        "dimming": lambda: gamma.set_dimming(D1, 60),
        "idle dimming": lambda: gamma.set_idle_dim({D1: 40}),
        "pause": lambda: gamma.set_override(D2, 6500),  # night light paused on D2 for an app
    }
    inside = Gate(f"{first}'s SetDeviceGammaRamp")
    fake.script("set_gamma_ramp", inside)
    leader = start_together(changes.pop(first), names=(first,))
    assert inside.entered()
    others = start_together(*changes.values(), names=tuple(changes))
    inside.open()
    leader.join()
    others.join()
    # D1: night light over the darker of its two dimmings; D2: paused, so neutral, and not dimmed.
    assert shows(fake, D1, expected(3500, 40))
    assert shows(fake, D2, identity_ramp())


def test_the_order_of_owners_never_changes_the_result():
    """The same four changes in all 24 orders, one after another."""
    results = set()
    for order in itertools.permutations(range(4)):
        fake, gamma = backend(D1)
        changes = [(gamma.apply, 4000), (gamma.set_dimming, D1, 70), (gamma.set_idle_dim, {D1: 50}), (gamma.set_override, D1, 5000)]
        for index in order:
            method, *args = changes[index]
            method(*args)
        assert shows(fake, D1, expected(5000, 50))  # its pause temperature, the darker dimming
        results.add(tuple(fake.displays[D1].ramp[2][:-1]))  # the nudge aside
    assert len(results) == 1


# --- A driver that doesn't return -----------------------------------------------------------------


def test_a_ramp_change_stuck_in_the_driver_puts_the_rest_on_hold_without_freezing_the_app(monkeypatch, caplog):
    """The stuck change holds the lock. The UI thread's changes give up after
    a moment and are skipped (the next tick repeats them) instead of
    freezing the app; dimming is told it didn't happen. When the driver
    returns, everything carries on."""
    monkeypatch.setattr(windows, "LOCK_WAIT_S", 0.05)
    fake, gamma = backend(D1)
    stuck = Gate("a driver that doesn't return")
    fake.script("set_gamma_ramp", stuck, display=D1)
    dimming = start_together(lambda: gamma.set_dimming(D1, 50), names=("monitor thread",))
    assert stuck.entered()
    with caplog.at_level(logging.INFO):
        assert gamma.apply(3000) is None  # skipped, not waited for
        assert gamma.verify() is False and gamma.hdr_displays() == set()
        with pytest.raises(GammaBusy):
            gamma.set_dimming(D1, 30)
        assert "stuck" in caplog.text
        assert len(fake.calls_of("set_gamma_ramp")) == 1  # only the stuck one reached the driver
        stuck.open()
        dimming.join()
        gamma.apply(3000)
        assert "carry on" in caplog.text
    assert shows(fake, D1, expected(3000, 50))


def test_quitting_while_a_change_is_stuck_doesnt_wait_and_the_journal_restores_it_next_time(monkeypatch, tmp_path):
    """Quitting can't wait for the driver forever: the displays are left as
    they are, and the journal, saved as soon as a display was tinted, gives
    the next start what to put back."""
    monkeypatch.setattr(windows, "LOCK_WAIT_S", 0.05)
    journal_path = tmp_path / "gamma.json"
    fake, gamma = backend(D1, journal=windows.GammaJournal(journal_path))
    gamma.apply(3000)
    stuck = Gate("a driver that doesn't return")
    fake.script("set_gamma_ramp", stuck, display=D1)
    dimming = start_together(lambda: gamma.set_dimming(D1, 50), names=("monitor thread",))
    assert stuck.entered()
    gamma.release()  # skipped: returns instead of hanging
    stuck.open()
    dimming.join()
    tinted = fake.displays[D1].ramp
    assert not ramps_match(tinted, identity_ramp())
    next_start = windows.WindowsGammaBackend(api=fake, journal=windows.GammaJournal(journal_path), clock=FakeClock())
    next_start.reset()
    assert fake.displays[D1].ramp == identity_ramp()  # recognised as ours, and put back


# --- Another program, at the worst moment ---------------------------------------------------------


def test_another_program_changing_the_ramp_between_ours_and_its_read_back():
    """SetDeviceGammaRamp, then another program's change, then our read-back:
    it looks like a driver that ignored ours. That's taken as what the
    display shows, so checking doesn't fight it at once; the next night
    light tick (every 10 s) sets ours again."""
    fake, gamma = backend(D1)
    theirs = gamma_ramp(whitepoint(2500))

    def ours_then_theirs(name, ramp):
        fake.displays[name].ramp = [list(c) for c in ramp]
        fake.another_program_sets(name, theirs)
        return True

    fake.script("set_gamma_ramp", ours_then_theirs, display=D1)
    gamma.apply(4000)
    assert fake.displays[D1].ramp == theirs
    assert gamma.verify() is False  # what it last saw: nothing to put back
    gamma.apply(4000)  # the next tick
    assert shows(fake, D1, expected(4000))


def test_another_program_fighting_is_backed_off_from_for_longer_each_time():
    """Three changes within CONTEST_WINDOW_S is a fight: hands off for
    CONTEST_BACKOFF_S, doubling each time, at most CONTEST_BACKOFF_MAX_S.
    On the fake clock, with the real constants."""
    clock = FakeClock()
    fake, gamma = backend(D1, clock=clock)
    gamma.apply(4500)
    theirs = gamma_ramp(whitepoint(2500))
    backoffs = []
    for _ in range(6):
        for _ in range(windows.CONTEST_CHANGES):
            fake.another_program_sets(D1, theirs)
            gamma.verify()
            clock.advance(1)
        backoffs.append(gamma._displays[D1].backoff)
        sets = len(fake.calls_of("set_gamma_ramp"))
        gamma.apply(4400)  # night light moving on meanwhile leaves it alone
        clock.advance(gamma._displays[D1].contested_until - clock() - 1)
        assert gamma.verify() is False and fake.displays[D1].ramp == theirs  # a second before the end: still hands off
        assert len(fake.calls_of("set_gamma_ramp")) == sets
        clock.advance(2)
        assert gamma.verify() is True and shows(fake, D1, expected(4400))  # then night light is back
        clock.advance(windows.CONTEST_WINDOW_S + 1)
    assert backoffs == [120, 240, 480, 960, 1800, 1800]


def test_resets_while_the_desktop_comes_back_dont_count_as_a_fight_but_later_ones_do():
    clock = FakeClock()
    fake, gamma = backend(D1, clock=clock)
    gamma.apply(4500)
    gamma.reapply()  # waking
    for _ in range(windows.CONTEST_CHANGES + 2):  # Windows resetting it again and again, within SETTLING_S
        fake.another_program_sets(D1, identity_ramp())
        assert gamma.verify() is True
        clock.advance(1)
    assert not gamma._displays[D1].contested
    clock.advance(windows.SETTLING_S)
    for _ in range(windows.CONTEST_CHANGES):
        fake.another_program_sets(D1, gamma_ramp(whitepoint(2500)))
        gamma.verify()
    assert gamma._displays[D1].contested


def test_a_reset_every_few_minutes_is_never_a_fight():
    clock = FakeClock()
    fake, gamma = backend(D1, clock=clock)
    gamma.apply(4500)
    for _ in range(10):  # the lock screen, now and then
        clock.advance(windows.CONTEST_WINDOW_S / 2 + 1)
        fake.another_program_sets(D1, identity_ramp())
        assert gamma.verify() is True and shows(fake, D1, expected(4500))
    assert not gamma._displays[D1].contested


# --- Displays coming and going mid-change ---------------------------------------------------------


def test_a_display_unplugged_after_the_list_was_made_doesnt_stop_the_others(caplog):
    clock = FakeClock()
    fake, gamma = backend(D1, D2, clock=clock)
    fake.unplug(D1)  # the list is still trusted for DISPLAYS_TTL
    with caplog.at_level(logging.WARNING):
        gamma.apply(4000)
    assert shows(fake, D2, expected(4000))
    clock.advance(gamma.DISPLAYS_TTL)
    gamma.apply(3900)
    assert D1 not in gamma._displays
    fake.displays[D1].connected = True  # plugged back in
    fake.displays[D1].ramp = identity_ramp()
    gamma.displays_changed()
    gamma.apply(3800)
    assert shows(fake, D1, expected(3800)) and shows(fake, D2, expected(3800))


def test_a_display_unplugged_while_its_change_is_inside_the_driver(monkeypatch):
    """The change fails for that display only; the next display in the same
    call is still set."""
    fake, gamma = backend(D1, D2)
    inside = Gate("D1's SetDeviceGammaRamp")
    fake.script("set_gamma_ramp", inside, display=D1)
    change = start_together(lambda: gamma.apply(4200), names=("UI thread",))
    assert inside.entered()
    fake.unplug(D1)
    fake.script("get_gamma_ramp", OSError("gone"), display=D1)  # its read-back fails too
    inside.open()
    change.join()
    assert shows(fake, D2, expected(4200))


def test_an_unexpected_error_on_one_display_doesnt_stop_the_others():
    """Not an OSError (those are expected and handled where the call is
    made): a bug, or ctypes failing in a way nobody foresaw. Found by
    breaking the per-display guard on purpose: no test noticed."""
    fake, gamma = backend(D1, D2)
    fake.always("set_gamma_ramp", RuntimeError("unforeseen"), display=D1)
    gamma.apply(4100)
    assert shows(fake, D2, expected(4100))
