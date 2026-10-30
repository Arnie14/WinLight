# SPDX-License-Identifier: GPL-3.0-only
"""The design's rules, checked in the source itself.

Each rule reads every module's syntax tree and fails, naming the file and
line, when code breaks a rule the app relies on. A code review can miss
these; this can't. Where a rule has a justified exception, it is listed
with its reason, so adding another needs a reason too. And each rule is fed
the mistake it exists for (test_each_rule_catches_the_mistake_it_is_for),
so a rule that silently stopped working fails too.

The rules come from bugs this project (or LightBulb and Twinkle Tray) had:
signals emitted under a lock froze the UI; a lambda holding self crashed
the 0.5.0 build at exit; a ctypes call without declared types truncates
64-bit handles; a timer or thread without an owner dies or keeps the app
alive; a blocking call on the main thread freezes the panel. Others are
checked elsewhere: layers in test_imports.py, garbage collection and
lambdas in test_gc_guard.py, ruff's bugbear for lambdas in loops (B023)
and mutable default arguments (B006).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EVERYTHING = [*sorted(ROOT.joinpath("nightlight").rglob("*.py")), ROOT / "main.py"]


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def with_parents(tree: ast.Module) -> ast.Module:
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node  # type: ignore[attr-defined]
    return tree


TREES = {path: with_parents(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))) for path in EVERYTHING}


def calls(trees, attribute: str | None = None, name: str | None = None):
    """(path, call node) for every call of `x.attribute(...)` or `name(...)`."""
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (attribute and isinstance(func, ast.Attribute) and func.attr == attribute) or (
                    name and isinstance(func, ast.Name) and func.id == name):
                yield path, node


def where(path: Path, node: ast.AST) -> str:
    return f"{rel(path)}:{node.lineno}"


def enclosing_function(node: ast.AST) -> ast.AST | None:
    while (node := getattr(node, "parent", None)) is not None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return node
    return None


# --- Windows calls (ctypes) ------------------------------------------------------------------


def dll_variables(tree: ast.AST) -> dict[str, bool]:
    """Names bound to ctypes.WinDLL(...) -> whether loaded with use_last_error=True."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            if (func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")) == "WinDLL":
                last_error = any(k.arg == "use_last_error" and getattr(k.value, "value", False) is True for k in node.value.keywords)
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        found[target.id] = last_error
    return found


def dll_calls(tree: ast.AST, dlls: dict[str, bool]):
    """(dll, function, node) for each `dll.Function(...)` call."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id in dlls and node.func.attr[:1].isupper()):
            yield node.func.value.id, node.func.attr, node


def declared(tree: ast.AST, what: str) -> set[tuple[str, str]]:
    """(dll, function) pairs given `.argtypes =` or `.restype =` (what)."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (isinstance(target, ast.Attribute) and target.attr == what and isinstance(target.value, ast.Attribute)
                        and isinstance(target.value.value, ast.Name)):
                    found.add((target.value.value.id, target.value.attr))
    return found


def rule_ctypes_types(trees) -> list[str]:
    missing = []
    for path, tree in trees.items():
        dlls = dll_variables(tree)
        args, results = declared(tree, "argtypes"), declared(tree, "restype")
        for dll, function, node in dll_calls(tree, dlls):
            for kind, table in (("argtypes", args), ("restype", results)):
                if (dll, function) not in table:
                    missing.append(f"{where(path, node)} {dll}.{function} has no {kind}")
    return missing


def test_every_windows_function_declares_its_argument_and_return_types():
    """Without argtypes, ctypes passes Python ints as 32-bit C ints: a 64-bit
    handle (HWND, HMONITOR, a pointer) is cut in half, which works until a
    handle above 4 GB comes along. Without restype, a returned handle is cut
    the same way."""
    seen = sum(1 for tree in TREES.values() for _ in dll_calls(tree, dll_variables(tree)))
    assert seen > 50, "the check found too few calls: the way DLLs are loaded changed"
    assert not rule_ctypes_types(TREES)


def rule_shared_dlls(trees) -> list[str]:
    return [where(path, node) for path, tree in trees.items() for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in ("windll", "oledll", "cdll", "pydll")
            and isinstance(node.value, ast.Name) and node.value.id == "ctypes"]


def test_no_shared_ctypes_dll_objects():
    """ctypes.windll.user32 is one object for the whole process: argtypes set
    on it in one module change every other module's calls. Each module loads
    its own WinDLL."""
    assert not rule_shared_dlls(TREES)


def rule_last_error(trees) -> list[str]:
    wrong = []
    for path, tree in trees.items():
        dlls = dll_variables(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if ast.unparse(node.func) in ("ctypes.get_last_error", "get_last_error"):
                for dll, name, call in dll_calls(enclosing_function(node) or tree, dlls):
                    if not dlls[dll]:
                        wrong.append(f"{where(path, node)} reads the last error near {dll}.{name} (line {call.lineno}), "
                                     "loaded without use_last_error")
            elif ast.unparse(node.func).endswith(".GetLastError"):
                wrong.append(f"{where(path, node)} calls GetLastError() directly: use ctypes.get_last_error()")
    return wrong


def test_windows_errors_are_read_from_dlls_that_keep_them():
    """ctypes.get_last_error() is only right after a call through a DLL
    loaded with use_last_error=True; otherwise it reads a stale value (and
    GetLastError() itself can be overwritten by Python in between)."""
    assert not rule_last_error(TREES)


# --- Threads, locks and the main thread --------------------------------------------------------


def rule_emit_under_lock(trees) -> list[str]:
    found = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.With):
                continue
            guards = [ast.unparse(item.context_expr) for item in node.items]
            if not any(word in guard.lower() for guard in guards for word in ("lock", "cond", "mutex")):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute) and inner.func.attr in ("emit", "_emit"):
                    found.append(f"{where(path, inner)} {ast.unparse(inner)[:60]} inside `with {', '.join(guards)}`")
    return found


def test_no_signal_is_emitted_while_holding_a_lock():
    """A signal's slots run at once on the emitting thread (the UI thread for
    most): emitted under a lock, a slot that takes another lock (the gamma
    backend's) can deadlock, or freeze the UI behind a slow display call.
    Events are collected under the lock and emitted after letting go."""
    assert not rule_emit_under_lock(TREES)


def rule_threads(trees) -> list[str]:
    wrong = []
    for path, node in calls(trees, attribute="Thread"):
        keywords = {k.arg: k.value for k in node.keywords}
        if not (isinstance(keywords.get("daemon"), ast.Constant) and keywords["daemon"].value is True):
            wrong.append(f"{where(path, node)} isn't daemon=True")
        if "name" not in keywords:
            wrong.append(f"{where(path, node)} has no name=")
    return wrong


def test_every_thread_is_a_named_daemon():
    """A thread that isn't a daemon keeps the process alive after quitting
    (a hung DDC/CI call would then never let Winlight exit); a name makes it
    findable in logs and in a stuck process's dump."""
    assert not rule_threads(TREES)


# Where sleeping is right: worker threads, and the deliberate blocking fade
# when quitting (the event loop has ended by then).
SLEEP_ALLOWED = {
    "nightlight/brightness/monitors.py": "the monitor service's worker thread (and the stuck-detection watcher)",
    "nightlight/hardware/win32.py": "DDC/CI timing, on the monitor worker thread",
    "nightlight/hardware/brightness.py": "the fake backend's simulated latency",
    "nightlight/files.py": "retrying a replace another program holds open, a few short waits",
    "nightlight/color/controller.py": "the fade to neutral when quitting, after the event loop ends",
}


def rule_sleep(trees) -> list[str]:
    return [where(path, node) for path, node in [*calls(trees, attribute="sleep"), *calls(trees, name="sleep")]
            if rel(path) not in SLEEP_ALLOWED]


def test_nothing_sleeps_on_the_main_thread():
    """time.sleep on the UI thread freezes the panel, the tray and shortcuts.
    Waiting on the main thread is a QTimer; blocking work goes to a worker."""
    assert not rule_sleep(TREES)


NESTED_LOOPS_ALLOWED = {
    ("main.py", "exec"): "the application's own event loop",
    ("nightlight/app.py", "exec"): "Report a Problem's message box, opened from a menu",
}


def rule_nested_loops(trees) -> list[str]:
    return [f"{where(path, node)} {ast.unparse(node.func)}()" for attribute in ("exec", "exec_", "processEvents")
            for path, node in calls(trees, attribute=attribute) if (rel(path), attribute) not in NESTED_LOOPS_ALLOWED]


def test_no_nested_event_loops_or_manual_event_processing():
    """processEvents() and modal exec() run other events in the middle of a
    function: a slot can then run again inside itself (re-entrancy), with
    half-updated state. Only the listed places may."""
    assert not rule_nested_loops(TREES)


def rule_connections(trees) -> list[str]:
    return [where(path, node) for path, tree in trees.items() for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr in ("DirectConnection", "BlockingQueuedConnection")]


def test_no_direct_or_blocking_connections():
    """A direct connection runs a slot on the emitting thread, a worker's,
    where Qt objects mustn't be touched; a blocking queued one can deadlock.
    Worker threads reach the UI through queued signals only."""
    assert not rule_connections(TREES)


def rule_timers(trees) -> list[str]:
    orphans = []
    for path, node in calls(trees, name="QTimer"):
        if node.args or any(k.arg == "parent" for k in node.keywords):
            continue
        owner = node.parent  # type: ignore[attr-defined]
        kept = isinstance(owner, ast.Assign) and all(
            isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self" for t in owner.targets)
        if not kept:
            orphans.append(where(path, node))
    return orphans


def test_every_timer_has_an_owner():
    """A QTimer with neither a parent nor a reference to it is collected by
    Python, and then never fires (a schedule that silently stops). Each is
    made with a parent, or kept on self."""
    assert not rule_timers(TREES)


# --- Files, processes and output -----------------------------------------------------------------

WRITES_ALLOWED = {
    "nightlight/files.py": "write_atomic itself: the temporary file it then swaps in",
    "nightlight/config.py": "a copy of an unreadable settings file, kept aside for recovering by hand",
    "nightlight/hardware/safe_mode.py": "the DDC/CI marker: a torn marker reads as none, the safe outcome",
    "nightlight/support/diagnostics.py": "the Report a Problem zip, a new file each time",
    "nightlight/support/probe.py": "--probe's report, a new file the user asked for",
    "nightlight/system/autostart.py": "Linux's autostart .desktop file (development only)",
    "nightlight/ui/settings_window.py": "the compatibility report, saved where the user picked",
    "main.py": "--report's file, a new file the user asked for",
}


def rule_writes(trees) -> list[str]:
    wrong = []
    for path, tree in trees.items():
        if rel(path) in WRITES_ALLOWED:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            mode = next((a.value for a in node.args[1:2] if isinstance(a, ast.Constant)), None)
            mode = next((k.value.value for k in node.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)), mode)
            if name in ("write_text", "write_bytes") or (name == "open" and isinstance(mode, str) and set(mode) & set("wax+")):
                wrong.append(where(path, node))
    return wrong


def test_files_the_app_keeps_are_written_atomically():
    """Settings, state and journals are replaced in one step (files.write_atomic):
    a crash or power cut mid-write can't leave half a file that would then
    reset someone's settings. Direct writes are listed with their reason."""
    assert not rule_writes(TREES), "use files.write_atomic"


POPEN_ALLOWED = {"nightlight/app.py": "Explorer showing the Report a Problem zip; not waited for"}


def rule_processes(trees) -> list[str]:
    wrong = []
    for attribute in ("run", "call", "check_call", "check_output"):
        for path, node in calls(trees, attribute=attribute):
            if ast.unparse(node.func) == f"subprocess.{attribute}" and not any(k.arg == "timeout" for k in node.keywords):
                wrong.append(f"{where(path, node)} waits without a timeout")
    wrong += [f"{where(path, node)} a new Popen" for path, node in calls(trees, attribute="Popen")
              if ast.unparse(node.func) == "subprocess.Popen" and rel(path) not in POPEN_ALLOWED]
    return wrong


def test_child_processes_never_hang_the_app():
    """subprocess.run/call/check_* wait for the child: without a timeout a hung
    child freezes the caller for good. Only the listed fire-and-forget Popen."""
    assert not rule_processes(TREES)


PRINT_ALLOWED = {"main.py", "nightlight/cli/client.py", "nightlight/support/probe.py"}


def rule_print(trees) -> list[str]:
    return [where(path, node) for path, node in calls(trees, name="print") if rel(path) not in PRINT_ALLOWED]


def test_only_the_command_line_parts_print():
    """The app is a windowed program: print() has nowhere to go (and in a
    frozen build without a console, writing to a missing stdout can raise).
    Everything else logs."""
    assert not rule_print(TREES)


# --- Errors ----------------------------------------------------------------------------------------


def rule_swallowed(trees) -> list[str]:
    wrong = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            caught = ast.unparse(node.type) if node.type else "everything"
            silent = len(node.body) == 1 and (isinstance(node.body[0], ast.Pass) or (
                isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)))
            if silent and caught in ("everything", "Exception", "BaseException"):
                wrong.append(f"{where(path, node)} swallows {caught}")
            if caught == "BaseException":
                hands_on = any(isinstance(n, ast.Raise) for n in ast.walk(node)) or (
                    node.name is not None and any(isinstance(n, ast.Name) and n.id == node.name for n in ast.walk(node)))
                if not hands_on:
                    wrong.append(f"{where(path, node)} catches BaseException without re-raising or keeping it")
    return wrong


def test_broad_exceptions_are_never_swallowed_silently():
    """`except Exception: pass` hides the bug that matters. A handler that
    does nothing must name the specific error it expects; catching
    BaseException must re-raise it or hand it on."""
    assert not rule_swallowed(TREES)


# --- The settings model --------------------------------------------------------------------------


def rule_frozen(trees) -> list[str]:
    unfrozen = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for decorator in node.decorator_list:
                    if "dataclass" in ast.unparse(decorator) and "frozen=True" not in ast.unparse(decorator):
                        unfrozen.append(f"{where(path, node)} {node.name}")
    return unfrozen


def test_settings_and_shortcuts_are_immutable():
    """Frozen dataclasses: the settings a part of the app holds can't change
    under it; a change is a new object, compared with == to see what moved."""
    model = {path: tree for path, tree in TREES.items() if rel(path) in ("nightlight/core/settings.py", "nightlight/core/shortcuts.py")}
    assert len(model) == 2 and not rule_frozen(model)


@pytest.mark.parametrize("path", [*EVERYTHING, *sorted(ROOT.joinpath("tests").glob("*.py")), *sorted(ROOT.joinpath("tools").glob("*.py"))],
                         ids=rel)
def test_every_source_file_says_its_license(path):
    text = path.read_text(encoding="utf-8")
    if path.name == "__init__.py" and not text.strip():
        return
    assert text.startswith("# SPDX-License-Identifier: GPL-3.0-only"), rel(path)


# --- The rules catch what they should ----------------------------------------------------------

BAD = {
    rule_ctypes_types: 'import ctypes\nuser32 = ctypes.WinDLL("user32")\nuser32.GetForegroundWindow()\n',
    rule_shared_dlls: "import ctypes\nctypes.windll.user32.MessageBeep(0)\n",
    rule_last_error: ('import ctypes\nk = ctypes.WinDLL("kernel32")\nk.F.argtypes = []\nk.F.restype = None\n'
                      "def f():\n    k.F()\n    return ctypes.get_last_error()\n"),
    rule_emit_under_lock: "def f(self):\n    with self._lock:\n        self.changed.emit()\n",
    rule_threads: "import threading\nthreading.Thread(target=print).start()\n",
    rule_sleep: "import time\ndef slot():\n    time.sleep(1)\n",
    rule_nested_loops: "def f(app):\n    app.processEvents()\n",
    rule_connections: "def f(s, slot):\n    s.connect(slot, Qt.ConnectionType.DirectConnection)\n",
    rule_timers: "from PySide6.QtCore import QTimer\ndef f():\n    timer = QTimer()\n    timer.start(10)\n",
    rule_writes: "def save(path):\n    path.write_text('{}')\n",
    rule_processes: "import subprocess\nsubprocess.run(['x'])\nsubprocess.Popen(['y'])\n",
    rule_print: "print('hello')\n",
    rule_swallowed: "try:\n    pass\nexcept Exception:\n    pass\n",
    rule_frozen: "from dataclasses import dataclass\n@dataclass\nclass Settings:\n    x: int = 1\n",
}


@pytest.mark.parametrize("rule", list(BAD), ids=lambda rule: rule.__name__)
def test_each_rule_catches_the_mistake_it_is_for(rule):
    """A rule that never fails proves nothing: each is fed the mistake it
    exists for, in a module of its own, and must report it."""
    path = ROOT / "nightlight" / "_example.py"
    assert rule({path: with_parents(ast.parse(BAD[rule]))}), f"{rule.__name__} missed:\n{BAD[rule]}"
