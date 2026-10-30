# SPDX-License-Identifier: GPL-3.0-only
"""A deterministic Windows for tests: a clock that moves only when told, a
display API whose every call can be scripted, and gates that stop a call
part-way so another thread can be let in at an exact point.

With these, a race is a sequence of steps, not a hope: thread A is held
inside SetDeviceGammaRamp, thread B is started and shown to wait, A is let
go, and the outcome is checked. Nothing sleeps, so nothing is flaky, and
"after two minutes" costs nothing.

- FakeClock: monotonic seconds, moved by advance().
- Gate: a point a call stops at until the test opens it. entered() says a
  thread has arrived; open() lets it through.
- FakeWindows: the DisplayApi of hardware/windows.py over a few fake
  displays, with gamma ramps (rejecting ramps too far from neutral, as
  Windows' default GdiIcmGammaRange does), DDC/CI brightness and HDR. Each
  call can be scripted to return a value, raise, or stop at a gate, once or
  every time; every call is logged in order, with the thread that made it.
- run_together: start several functions at the same instant (a Barrier),
  wait for them all, raise what any raised, and fail on a deadlock rather
  than hang.
"""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nightlight.core.colortemp import identity_ramp
from nightlight.hardware import win32

# Longest any test waits for a thread; reached only when the code under test
# deadlocks, so a failure says so instead of hanging the suite.
DEADLOCK_S = 10.0


class FakeClock:
    """monotonic() for the code under test; moves only on advance()."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Gate:
    """Where a scripted call stops until the test opens it."""

    def __init__(self, name: str = "gate") -> None:
        self.name = name
        self._arrived = threading.Event()
        self._open = threading.Event()

    def pass_through(self) -> None:
        """Called by the code under test (through FakeWindows)."""
        self._arrived.set()
        if not self._open.wait(DEADLOCK_S):
            raise AssertionError(f"{self.name} was never opened")

    def entered(self, timeout: float = DEADLOCK_S) -> bool:
        """Wait until a thread has reached the gate."""
        return self._arrived.wait(timeout)

    def open(self) -> None:
        self._open.set()


@dataclass
class FakeDisplay:
    gdi_name: str
    key: str
    hdr: bool = False
    ramp: list[list[int]] = field(default_factory=identity_ramp)
    brightness: int = 50  # DDC/CI VCP 0x10, 0-100
    sdr_white_nits: float = 240.0
    handle: int = 0
    connected: bool = True


@dataclass
class Call:
    method: str
    args: tuple
    thread: str


class FakeWindows:
    """The DisplayApi (hardware/windows.py), scripted. See the module docstring."""

    def __init__(self, *displays: FakeDisplay, min_peak: float = 0.7) -> None:
        self.displays = {d.gdi_name: d for d in displays}
        for number, display in enumerate(displays, start=1):
            display.handle = display.handle or number * 10
        self.min_peak = min_peak  # a ramp whose lowest channel peaks below this share of full is refused
        self.calls: list[Call] = []
        self._lock = threading.Lock()
        self._scripts: dict[tuple[str, str | None], deque] = defaultdict(deque)
        self._always: dict[tuple[str, str | None], Any] = {}
        self._handles_open: set[int] = set()

    # --- Scripting -------------------------------------------------------------------------------

    def script(self, method: str, *outcomes: Any, display: str | None = None) -> None:
        """The next calls of `method` (on `display`, or any) give these
        outcomes in turn, then behave normally again. An outcome is a value
        to return, an exception to raise, a Gate to stop at (then behave
        normally), or a function called with the call's arguments."""
        self._scripts[(method, display)].extend(outcomes)

    def always(self, method: str, outcome: Any, display: str | None = None) -> None:
        """Every call of `method` gives `outcome` until cleared with None."""
        if outcome is None:
            self._always.pop((method, display), None)
        else:
            self._always[(method, display)] = outcome

    def calls_of(self, method: str) -> list[Call]:
        with self._lock:
            return [call for call in self.calls if call.method == method]

    def unplug(self, gdi_name: str) -> None:
        self.displays[gdi_name].connected = False

    def another_program_sets(self, gdi_name: str, ramp: list[list[int]]) -> None:
        """f.lux, a GPU tool or Windows itself changing the ramp."""
        self.displays[gdi_name].ramp = [list(c) for c in ramp]

    def _call(self, method: str, display: str | None, args: tuple, normal: Callable[[], Any]) -> Any:
        with self._lock:
            self.calls.append(Call(method, args, threading.current_thread().name))
            outcome = _NORMAL
            for key in ((method, display), (method, None)):
                if self._scripts[key]:
                    outcome = self._scripts[key].popleft()
                    break
                if key in self._always:
                    outcome = self._always[key]
                    break
        if isinstance(outcome, Gate):
            outcome.pass_through()
            outcome = _NORMAL
        if outcome is _NORMAL:
            return normal()
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return outcome(*args)
        return outcome

    def _display(self, gdi_name: str) -> FakeDisplay:
        display = self.displays.get(gdi_name)
        if display is None or not display.connected:
            raise OSError(f"{gdi_name} is not connected")
        return display

    # --- DisplayApi ------------------------------------------------------------------------------

    def display_targets(self) -> list[win32.DisplayTarget]:
        def normal():
            # The device path as Windows gives it, so that the identity (DisplayTarget.key) is d.key.
            return [win32.DisplayTarget(d.gdi_name, d.key, f"\\\\?\\DISPLAY#{d.key}#5&1a2b3c&0&UID{d.handle}#"
                                        "{e6f07b5f-ee97-4a90-b076-33f57bf4eaa7}", 5, d.hdr)
                    for d in self.displays.values() if d.connected]
        return self._call("display_targets", None, (), normal)

    def attached_display_names(self) -> list[str]:
        return self._call("attached_display_names", None, (),
                          lambda: [d.gdi_name for d in self.displays.values() if d.connected])

    def physical_monitors(self) -> list[win32.PhysicalMonitor]:
        def normal():
            found = [win32.PhysicalMonitor(d.gdi_name, d.handle, "Generic PnP Monitor")
                     for d in self.displays.values() if d.connected]
            self._handles_open.update(m.handle for m in found)
            return found
        return self._call("physical_monitors", None, (), normal)

    def destroy_physical_monitor(self, handle: int) -> None:
        self._call("destroy_physical_monitor", None, (handle,), lambda: self._handles_open.discard(handle))

    def _by_handle(self, handle: int) -> FakeDisplay:
        display = next((d for d in self.displays.values() if d.handle == handle), None)
        if display is None or not display.connected:
            raise win32.DdcError("no such monitor", win32.ERROR_GRAPHICS_MONITOR_NO_LONGER_EXISTS)
        return display

    def get_vcp(self, handle: int, code: int) -> tuple[int, int]:
        return self._call("get_vcp", None, (handle, code), lambda: (self._by_handle(handle).brightness, 100))

    def set_vcp(self, handle: int, code: int, value: int) -> None:
        def normal():
            self._by_handle(handle).brightness = value
        self._call("set_vcp", None, (handle, code, value), normal)

    def get_monitor_brightness(self, handle: int) -> tuple[int, int, int]:
        return self._call("get_monitor_brightness", None, (handle,), lambda: (0, self._by_handle(handle).brightness, 100))

    def set_monitor_brightness(self, handle: int, value: int) -> None:
        self.set_vcp(handle, 0x10, value)

    def get_sdr_white_level(self, target: win32.DisplayTarget) -> float | None:
        return self._call("get_sdr_white_level", target.gdi_name, (target,),
                          lambda: self._display(target.gdi_name).sdr_white_nits)

    def set_sdr_white_level(self, target: win32.DisplayTarget, nits: float) -> bool:
        def normal():
            self._display(target.gdi_name).sdr_white_nits = nits
            return True
        return self._call("set_sdr_white_level", target.gdi_name, (target, nits), normal)

    def get_gamma_ramp(self, gdi_name: str) -> win32.GammaRamp | None:
        return self._call("get_gamma_ramp", gdi_name, (gdi_name,),
                          lambda: [list(c) for c in self._display(gdi_name).ramp])

    def set_gamma_ramp(self, gdi_name: str, ramp: win32.GammaRamp) -> bool:
        def normal():
            display = self._display(gdi_name)
            if min(channel[-1] for channel in ramp) < self.min_peak * 65535:
                return False  # Windows' default limit on how far from neutral a ramp may go
            display.ramp = [list(c) for c in ramp]
            return True
        return self._call("set_gamma_ramp", gdi_name, (gdi_name, ramp), normal)

    def display_profile(self, gdi_name: str) -> str | None:
        return self._call("display_profile", gdi_name, (gdi_name,), lambda: None)

    def windows_loads_calibrations(self) -> bool:
        return self._call("windows_loads_calibrations", None, (), lambda: True)

    @property
    def open_handles(self) -> set[int]:
        """Physical monitor handles handed out and not destroyed yet."""
        return set(self._handles_open)


_NORMAL = object()


class Together:
    """Threads started by run_together, for waiting on them part-way."""

    def __init__(self, threads: list[threading.Thread], results: dict[int, Any], errors: list[BaseException]) -> None:
        self.threads = threads
        self.results = results
        self.errors = errors

    def join(self, timeout: float = DEADLOCK_S) -> list[Any]:
        for thread in self.threads:
            thread.join(timeout)
        stuck = [thread.name for thread in self.threads if thread.is_alive()]
        if stuck:
            raise AssertionError(f"deadlock: {', '.join(stuck)} still running after {timeout:g} s")
        if self.errors:
            raise self.errors[0]
        return [self.results[i] for i in range(len(self.threads))]

    def alive(self) -> list[str]:
        return [thread.name for thread in self.threads if thread.is_alive()]


def start_together(*fns: Callable[[], Any], names: tuple[str, ...] = ()) -> Together:
    """Start every function on its own thread, all released at the same
    instant by a Barrier; join() the result."""
    barrier = threading.Barrier(len(fns))
    results: dict[int, Any] = {}
    errors: list[BaseException] = []

    def run(index: int, fn: Callable[[], Any]) -> None:
        barrier.wait(DEADLOCK_S)
        try:
            results[index] = fn()
        except BaseException as exc:  # handed to join()
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(i, fn), name=names[i] if i < len(names) else f"together-{i}", daemon=True)
               for i, fn in enumerate(fns)]
    for thread in threads:
        thread.start()
    return Together(threads, results, errors)


def run_together(*fns: Callable[[], Any], names: tuple[str, ...] = ()) -> list[Any]:
    """Run the functions at the same instant on threads of their own; their results in order."""
    return start_together(*fns, names=names).join()


def started(thread_name: str, fake: FakeWindows, method: str) -> bool:
    """Whether `thread_name` has made a `method` call yet."""
    return any(call.thread == thread_name for call in fake.calls_of(method))
