# SPDX-License-Identifier: GPL-3.0-only
"""Faults injected where the gamma backend meets the outside world: its
crash-recovery journal on disk, and Windows' answer to "which displays are
there?". Each fault must cost at most that one piece of information, never
night light on the displays, and never an exception out of the backend.
"""

import json
import logging

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from nightlight.core.colortemp import gamma_ramp, identity_ramp, whitepoint
from nightlight.hardware import windows
from tests.fake_windows import FakeClock, FakeDisplay, FakeWindows
from tests.test_concurrency import D1, D2, expected, shows

json_values = st.recursive(
    st.none() | st.booleans() | st.integers(-70000, 70000) | st.floats(allow_nan=False) | st.text(max_size=5),
    lambda inner: st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=6), inner, max_size=4),
    max_leaves=12,
)
entries = st.fixed_dictionaries({}, optional={"dirty": json_values, "base": json_values, "last": json_values})


# --- The journal on disk ---------------------------------------------------------------------------


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture], max_examples=60)
@given(st.dictionaries(st.sampled_from(["KEY1", "KEY2", "other"]), entries | json_values, max_size=3), json_values)
def test_any_journal_contents_never_stop_night_light(tmp_path, displays, calibrations):
    """The journal is a file anyone (or a crash mid-write on an old version)
    could have left in any state. Whatever it holds, night light works."""
    path = tmp_path / "gamma.json"
    path.write_text(json.dumps({"version": 1, "displays": displays, "calibrations": calibrations}), encoding="utf-8")
    fake = FakeWindows(FakeDisplay(D1, "KEY1"), FakeDisplay(D2, "KEY2"), min_peak=0.0)
    gamma = windows.WindowsGammaBackend(api=fake, journal=windows.GammaJournal(path), clock=FakeClock())
    gamma.apply(4000)
    assert shows(fake, D1, expected(4000)) and shows(fake, D2, expected(4000))
    gamma.release()
    assert fake.displays[D1].ramp == identity_ramp()


def test_a_journal_that_cant_be_saved_costs_crash_recovery_only(tmp_path, monkeypatch, caplog):
    def disk_full(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(windows, "write_atomic", disk_full)
    fake = FakeWindows(FakeDisplay(D1, "KEY1"), min_peak=0.0)
    gamma = windows.WindowsGammaBackend(api=fake, journal=windows.GammaJournal(tmp_path / "gamma.json"), clock=FakeClock())
    with caplog.at_level(logging.WARNING):
        gamma.apply(4000)
        gamma.release()
    assert "Could not save" in caplog.text
    assert fake.displays[D1].ramp == identity_ramp()


def test_an_unreadable_journal_file_starts_afresh(tmp_path, caplog):
    path = tmp_path / "gamma.json"
    path.write_bytes(b'{"version": 1, "displays": {"KEY1": {"dirty": tr')  # cut off mid-write
    fake = FakeWindows(FakeDisplay(D1, "KEY1", ramp=gamma_ramp(whitepoint(3000))), min_peak=0.0)
    with caplog.at_level(logging.WARNING):
        gamma = windows.WindowsGammaBackend(api=fake, journal=windows.GammaJournal(path), clock=FakeClock())
        gamma.reset()
    assert "starts afresh" in caplog.text
    assert fake.displays[D1].ramp == identity_ramp()  # the leftover tint is still recognised by its shape


# --- Asking Windows which displays there are -------------------------------------------------------


def test_a_failed_display_query_keeps_what_was_known_about_each_display():
    """QueryDisplayConfig failing for a moment (win32.display_targets then
    gives [], and the names come from a simpler call) mustn't make an HDR
    display look like HDR was turned off, or lose its identity, which the
    journal and the kept calibration are filed under."""
    clock = FakeClock()
    fake = FakeWindows(FakeDisplay(D1, "KEY1", hdr=True), FakeDisplay(D2, "KEY2"), min_peak=0.0)
    gamma = windows.WindowsGammaBackend(api=fake, clock=clock)
    gamma.apply(4000)
    assert gamma.hdr_displays() == {D1}
    known = gamma._displays[D2].key
    assert known
    fake.always("display_targets", [])  # the query fails, for a while
    clock.advance(gamma.DISPLAYS_TTL)
    gamma.apply(3900)
    assert gamma.hdr_displays() == {D1}
    assert gamma._displays[D2].key == known
    assert fake.displays[D1].ramp == identity_ramp() and shows(fake, D2, expected(3900))
    fake.always("display_targets", None)  # answering again


def test_a_display_found_only_while_the_query_fails_is_treated_as_new():
    clock = FakeClock()
    fake = FakeWindows(FakeDisplay(D1, "KEY1"), min_peak=0.0)
    gamma = windows.WindowsGammaBackend(api=fake, clock=clock)
    gamma.apply(4000)
    fake.displays[D2] = FakeDisplay(D2, "KEY2", handle=20)
    fake.always("display_targets", [])
    clock.advance(gamma.DISPLAYS_TTL)
    gamma.apply(4000)
    assert shows(fake, D2, expected(4000)) and gamma._displays[D2].key == ""  # nothing known about it yet


def test_a_ramp_that_cant_be_read_while_listing_doesnt_stop_the_others():
    fake = FakeWindows(FakeDisplay(D1, "KEY1"), FakeDisplay(D2, "KEY2"), min_peak=0.0)
    fake.always("get_gamma_ramp", OSError("the driver said no"), display=D1)
    gamma = windows.WindowsGammaBackend(api=fake, clock=FakeClock())
    gamma.apply(4000)
    assert shows(fake, D2, expected(4000))
