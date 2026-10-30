# SPDX-License-Identifier: GPL-3.0-only
"""Gamma ramps, tried as properties over every input hypothesis can find:
any temperature, any dimming level, any calibration to tint. A failure is
shrunk to the smallest case that breaks it, and repeats (conftest.py's
profile is derandomized).

What a ramp must always be, whatever it's built from: three channels of
16-bit values, never falling (a falling ramp inverts tones, and Windows
rejects it), never brighter than what it tints, and exactly the base when
nothing is asked of it.
"""

import itertools

from hypothesis import assume, given
from hypothesis import strategies as st

from nightlight.core.colortemp import (
    DRIVER_SAFE_PEAK,
    MAX_KELVIN,
    MIN_KELVIN,
    PLAUSIBLE_BASE_PEAK,
    SOFTWARE_DIM_MIN,
    dimmed_ramp,
    gamma_ramp,
    identity_ramp,
    looks_like_tint,
    plausible_base,
    ramps_match,
    whitepoint,
)

WORD = 65535
kelvins = st.floats(min_value=MIN_KELVIN - 500, max_value=MAX_KELVIN + 500, allow_nan=False)
percents = st.floats(min_value=0, max_value=100, allow_nan=False)
sizes = st.sampled_from([2, 16, 256, 1024])  # Windows uses 256; others are calibration tables resampled


@st.composite
def rising_channels(draw, size=256):
    """A calibration-like channel: rising from 0 (or near it) to near full,
    in steps of any size, flat stretches included."""
    steps = draw(st.lists(st.integers(0, 600), min_size=size - 1, max_size=size - 1))
    start = draw(st.integers(0, 2000))
    channel = list(itertools.accumulate(steps, initial=start))
    return [min(WORD, value) for value in channel]


calibrations = st.lists(rising_channels(), min_size=3, max_size=3)


def rising(channel) -> bool:
    return all(b >= a for a, b in itertools.pairwise(channel))


def well_formed(ramp, size) -> bool:
    return len(ramp) == 3 and all(len(c) == size and all(0 <= v <= WORD for v in c) for c in ramp)


@given(kelvins)
def test_a_whitepoint_is_three_shares_of_full_output_red_always_full(kelvin):
    wp = whitepoint(kelvin)
    assert all(0 <= share <= 1 for share in wp) and wp[0] == 1
    assert wp[1] >= wp[2]  # warming takes more blue than green


@given(kelvins, kelvins)
def test_warmer_never_has_more_blue_or_green(a, b):
    warm, cool = sorted((a, b))
    assert all(w <= c + 1e-12 for w, c in zip(whitepoint(warm), whitepoint(cool)))


@given(kelvins, sizes)
def test_a_tint_is_a_well_formed_rising_ramp(kelvin, size):
    ramp = gamma_ramp(whitepoint(kelvin), size)
    assert well_formed(ramp, size) and all(rising(c) for c in ramp)
    assert ramp[0] == identity_ramp(size)[0]  # red untouched


@given(kelvins, calibrations)
def test_tinting_a_calibration_keeps_it_rising_and_never_brightens_it(kelvin, base):
    ramp = gamma_ramp(whitepoint(kelvin), base=base)
    assert well_formed(ramp, 256)
    for tinted, original in zip(ramp, base):
        assert rising(tinted)
        assert all(t <= o for t, o in zip(tinted, original))


@given(calibrations)
def test_neutral_returns_the_calibration_exactly(base):
    assert gamma_ramp(whitepoint(MAX_KELVIN), base=base) == base


@given(percents, sizes)
def test_dimming_is_a_well_formed_rising_ramp_that_never_goes_below_the_drivers_floor(percent, size):
    ramp = dimmed_ramp(percent, size)
    assert well_formed(ramp, size) and all(rising(c) for c in ramp)
    # Windows refuses ramps whose top is too far from full: the peak stays at DRIVER_SAFE_PEAK or above.
    assert all(c[-1] >= round(DRIVER_SAFE_PEAK * WORD) - 1 for c in ramp)


@given(percents, percents, calibrations)
def test_dimmer_is_never_brighter_anywhere(a, b, base):
    low, high = sorted((a, b))
    darker, lighter = dimmed_ramp(low, base=base), dimmed_ramp(high, base=base)
    assert all(d <= li for dc, lc in zip(darker, lighter) for d, li in zip(dc, lc))


@given(st.floats(min_value=100, max_value=1000, allow_nan=False), calibrations)
def test_full_brightness_returns_the_calibration_exactly(percent, base):
    assert dimmed_ramp(percent, base=base) == base


@given(st.floats(min_value=-1000, max_value=SOFTWARE_DIM_MIN, allow_nan=False))
def test_below_the_lowest_level_dims_as_the_lowest_level(percent):
    assert dimmed_ramp(percent) == dimmed_ramp(SOFTWARE_DIM_MIN)


@given(kelvins)
def test_winlights_own_tints_are_never_kept_as_a_calibration(kelvin):
    """A ramp left by a crash must not be tinted again (it compounds). Every
    tint whose blue falls below the plausible peak is recognised as one."""
    ramp = gamma_ramp(whitepoint(kelvin))
    assert looks_like_tint(ramp)
    if min(c[-1] for c in ramp) < PLAUSIBLE_BASE_PEAK * WORD:
        assert not plausible_base(ramp)


@given(calibrations)
def test_a_rising_calibration_reaching_near_full_is_always_kept(base):
    assume(all(c[-1] >= PLAUSIBLE_BASE_PEAK * WORD for c in base))
    assert plausible_base(base)


@given(calibrations, st.integers(0, 2), st.integers(1, 254))
def test_a_ramp_that_falls_anywhere_is_never_kept(base, channel, at):
    broken = [list(c) for c in base]
    assume(broken[channel][at] > 0)
    broken[channel][at + 1] = broken[channel][at] - 1
    assert not plausible_base(broken)


@given(calibrations, st.integers(-256, 256))
def test_a_ramp_read_back_within_the_drivers_rounding_matches(base, error):
    read_back = [[min(WORD, max(0, v + error)) for v in c] for c in base]
    assert ramps_match(base, read_back)
