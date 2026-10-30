# SPDX-License-Identifier: GPL-3.0-only
"""The tests that guard the most important mechanisms, checked to fail
when the mechanism breaks.

A test that passes whatever the code does proves nothing. Each case below
breaks one safeguard on purpose (a mutation, as mutation-testing tools make
them, but chosen by hand for what matters most), in a copy of the source,
and runs the tests written to guard it: at least one must fail. A control
run shows the same tests pass on the unbroken copy, so a failure means the
break was noticed, not that the copy doesn't run. The working tree is never
touched.

When a safeguard's code is rewritten, its mutation stops matching and the
test says so: write the break again for the new code.

(mutmut and similar tools need fork(), which Windows doesn't have, and
mutate everything blindly; these few run anywhere, in about a minute.)
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# (what breaks, file, code as it is, code broken, tests that must notice)
MUTATIONS = [
    ("the gamma lock never locks", "nightlight/hardware/windows.py",
     "        if not self._lock.acquire(timeout=LOCK_WAIT_STUCK_S if self._stuck else LOCK_WAIT_S):",
     "        if not (self._lock.acquire(blocking=False) or True):",
     ["tests/test_concurrency.py::test_night_light_arriving_while_dimming_is_inside_the_driver_waits_and_both_end_on_screen"]),
    ("backing off from another program never takes longer", "nightlight/hardware/windows.py",
     "display.backoff = min(CONTEST_BACKOFF_MAX_S, display.backoff * 2) if display.backoff else CONTEST_BACKOFF_S",
     "display.backoff = CONTEST_BACKOFF_S",
     ["tests/test_concurrency.py::test_another_program_fighting_is_backed_off_from_for_longer_each_time"]),
    ("one display's error stops the others", "nightlight/hardware/windows.py",
     '''        try:
            step(display)
        except Exception:
            log.exception("Changing the gamma ramp of %s failed", display.name)''',
     "        step(display)",
     ["tests/test_concurrency.py::test_an_unexpected_error_on_one_display_doesnt_stop_the_others"]),
    ("a failed display query forgets HDR and identity", "nightlight/hardware/windows.py",
     '''            sources = {name: (self._displays[name].hdr, self._displays[name].key) if name in self._displays else (False, "")
                       for name in self._api.attached_display_names()}''',
     '''            sources = dict.fromkeys(self._api.attached_display_names(), (False, ""))''',
     ["tests/test_fault_injection.py::test_a_failed_display_query_keeps_what_was_known_about_each_display"]),
    ("a call returning while given up on stays listed as stuck", "nightlight/hardware/calls.py",
     '''            if not job.done.is_set():
                job.abandoned = True
                # Listed under the same lock: _finish takes it off the list
                # under it too, so a call returning right now can't leave
                # itself listed as stuck forever.
                stuck.add(job)
        if job.abandoned:''',
     '''            if not job.done.is_set():
                job.abandoned = True
        if job.abandoned:
            stuck.add(job)''',
     ["tests/test_calls.py::test_a_call_returning_while_it_is_being_given_up_on_is_not_left_stuck"]),
    ("DDC/CI errors are never retried", "nightlight/hardware/win32.py",
     "        if code not in _TRANSIENT_ERRORS or attempt == _DDC_ATTEMPTS - 1:",
     "        if True:",
     ["tests/test_ddc_retries.py::test_a_garbled_message_is_sent_again_and_the_change_goes_through"]),
    ("repeated failures never mark a display failing", "nightlight/brightness/monitors.py",
     "        elif state.failures >= 2:",
     "        elif state.failures >= 3:",
     ["tests/test_ddc_retries.py::test_a_second_failure_in_a_row_marks_it_failing_and_looks_again_in_5_s"]),
    ("SDR brightness is sent outside Windows' range", "nightlight/hardware/win32.py",
     "    nits = max(SDR_MIN_NITS, min(SDR_MAX_NITS, round(nits / 4) * 4))",
     "    nits = round(nits / 4) * 4",
     ["tests/test_win32.py::test_any_sdr_brightness_asked_for_is_sent_inside_windows_own_range"]),
    ("structure offsets aren't checked", "nightlight/hardware/win32.py",
     "    return sizes + offset_problems(offsets)",
     "    return sizes",
     ["tests/test_win32.py::test_a_field_in_the_wrong_place_is_found"]),
    ("a calibration with an impossible gamma is read", "nightlight/core/icc.py",
     "        if not GAMMA_RANGE[0] <= gamma <= GAMMA_RANGE[1]:  # also nan and inf",
     "        if gamma <= 0:",
     ["tests/test_icc.py::test_a_windows_calibration_with_an_impossible_gamma_is_refused"]),
    ("Winlight's own dimming is kept as a calibration", "nightlight/core/colortemp.py",
     "    return not looks_like_tint(ramp) and not looks_like_own_dimming(ramp)",
     "    return not looks_like_tint(ramp)",
     ["tests/test_gamma_properties.py::test_winlights_own_dimming_left_over_is_never_kept_as_a_calibration"]),
    ("a ramp falling by more than noise is kept", "nightlight/core/colortemp.py",
     "value < highest - DIP_TOLERANCE",
     "value < highest - 65535",
     ["tests/test_gamma_properties.py::test_a_ramp_that_falls_by_more_than_noise_is_never_kept"]),
    ("Settings controls get no name for screen readers", "nightlight/ui/settings_parts.py",
     "                target.setAccessibleName(title)",
     "                pass",
     ["tests/test_frontend_audit.py::test_every_settings_control_has_a_name_a_screen_reader_can_say"]),
]


@pytest.fixture(scope="module")
def copy(tmp_path_factory):
    """The source and tests, copied once; each mutation changes one file and puts it back."""
    target = tmp_path_factory.mktemp("mutant")
    shutil.copytree(ROOT / "nightlight", target / "nightlight", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT / "tests", target / "tests", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "pyproject.toml", target)
    return target


def run(copy: Path, tests: list[str]) -> subprocess.CompletedProcess:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONDONTWRITEBYTECODE": "1",
           "WINLIGHT_HYPOTHESIS_PROFILE": "mutation"}  # no shrinking: whether it fails is enough
    # The copy's tests import the copy's nightlight: pytest puts the copy's
    # root first on the path (tests/ is a package). Checked by the control run.
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *tests], cwd=copy, env=env,
                          capture_output=True, text=True, timeout=300, check=False)


def test_the_guarding_tests_pass_on_the_unbroken_copy(copy):
    tests = sorted({test for *_, guards in MUTATIONS for test in guards})
    result = run(copy, tests)
    assert result.returncode == 0, result.stdout[-3000:]


@pytest.mark.parametrize(("what", "path", "original", "broken", "guards"), MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_breaking_a_safeguard_is_noticed(copy, what, path, original, broken, guards):
    source = (ROOT / path).read_text(encoding="utf-8")
    assert source.count(original) == 1, f"the code for '{what}' changed: write its mutation again for the new code"
    target = copy / path
    try:
        target.write_text(source.replace(original, broken), encoding="utf-8")
        result = run(copy, guards)
    finally:
        target.write_text(source, encoding="utf-8")
    assert result.returncode == 1, f"'{what}' went unnoticed by {guards}:\n{result.stdout[-3000:]}"
