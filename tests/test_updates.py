# SPDX-License-Identifier: GPL-3.0-only
"""Checking for updates: off by default, Winlight's only connection to the
internet, and when on, a newer release is found, said once, and never
downloaded."""

import ast
import json
from pathlib import Path

import pytest
from PySide6.QtCore import QUrl

from nightlight.config import AppConfig, GeneralConfig
from nightlight.system import updates
from nightlight.system.updates import UP_TO_DATE, UpdateChecker, newest, version_key
from tests.test_app import start  # noqa: F401  (a fixture)

ROOT = Path(__file__).resolve().parent.parent


def release(tag, draft=False, url=None):
    return {"tag_name": tag, "draft": draft, "prerelease": "beta" in tag,
            "html_url": url or f"https://github.com/Arnie14/WinLight/releases/tag/{tag}"}


def test_versions_sort_with_betas_before_their_release():
    order = ["0.4.0-beta.1", "0.5.0-beta.1", "0.5.0-beta.2", "0.5.0", "0.5.1-beta.1", "v0.6.0-beta.1", "1.0.0"]
    assert sorted(order, key=version_key) == order
    assert version_key("v0.6.0-beta.1") == version_key("0.6.0-beta.1")
    for nonsense in ("", "latest", "0.6", "0.6.0-", "0.6.0.1", "v0.6.0 beta"):
        assert version_key(nonsense) is None, nonsense


def test_the_newest_release_is_picked_and_drafts_and_odd_entries_are_left_out():
    releases = [release("v0.5.0-beta.1"), release("v0.7.0-beta.1", draft=True), release("nightly"),
                release("v0.6.0-beta.2", url="https://example.com/fake"), "junk", {"tag_name": 5},
                release("v0.6.0-beta.1")]
    found = newest(releases)
    assert found.version == "0.6.0-beta.1" and found.url.endswith("/v0.6.0-beta.1")
    assert newest([]) is None and newest({"message": "rate limited"}) is None


class Fetch:
    """GitHub, as the checker reads it: no network in the tests."""

    def __init__(self, body=None, error=""):
        self.body, self.error, self.calls = body, error, 0

    def __call__(self, done):
        self.calls += 1
        done(self.body, self.error)


def checker(body=None, error="", current="0.5.0-beta.1"):
    fetch = Fetch(json.dumps(body).encode() if body is not None else None, error)
    found, checked = [], []
    check = UpdateChecker(fetch=fetch, current=current)
    check.found.connect(lambda version, url: found.append((version, url)))
    check.checked.connect(checked.append)
    return check, fetch, found, checked


def test_a_newer_release_is_reported_with_its_page():
    check, _fetch, found, checked = checker([release("v0.6.0-beta.1"), release("v0.5.0-beta.1")])
    check.check_now()
    assert found == [("0.6.0 Beta 1", "https://github.com/Arnie14/WinLight/releases/tag/v0.6.0-beta.1")]
    assert checked[-1] == "0.6.0 Beta 1 is available"


@pytest.mark.parametrize(("body", "error", "said"), [
    ([release("v0.5.0-beta.1")], "", UP_TO_DATE),
    ([release("v0.4.0-beta.1")], "", UP_TO_DATE),  # older than this one
    (None, "Host not found", "Couldn't check: Host not found"),
    ({"message": "API rate limit exceeded"}, "", "Couldn't check: GitHub's answer had no releases in it"),
])
def test_nothing_newer_or_no_answer_says_so_and_finds_nothing(body, error, said):
    check, _fetch, found, checked = checker(body, error)
    check.check_now()
    assert found == [] and checked[-1] == said


def test_an_unreadable_answer_or_a_failing_fetch_breaks_nothing():
    check = UpdateChecker(fetch=lambda done: done(b"<html>not json", ""), current="0.5.0-beta.1")
    check.check_now()
    assert check.last.startswith("Couldn't check")

    def broken(done):
        raise RuntimeError("no network stack")

    check = UpdateChecker(fetch=broken, current="0.5.0-beta.1")
    check.check_now()
    assert check.last == "Couldn't check: no network stack" and not check._busy  # and the next check can run


def test_off_means_no_check_and_no_network_at_all():
    check = UpdateChecker(current="0.5.0-beta.1")  # the real fetch, which would use Qt's network
    check.set_enabled(False)
    assert not check._timer.isActive() and check._network is None


def test_on_it_checks_a_minute_after_starting_then_once_a_day():
    check, fetch, _found, _checked = checker([release("v0.5.0-beta.1")])
    check.set_enabled(True)
    assert check._timer.isActive() and check._timer.remainingTime() <= updates.FIRST_CHECK_MS and fetch.calls == 0
    check._timer.timeout.emit()
    assert fetch.calls == 1 and check._timer.interval() == updates.CHECK_EVERY_MS
    check.set_enabled(False)
    assert not check._timer.isActive()


def test_it_is_off_by_default():
    assert GeneralConfig().check_for_updates is False and AppConfig().general.check_for_updates is False


def test_nothing_else_in_winlight_connects_to_the_internet():
    """The docs and Settings say the update check is Winlight's only
    connection to the internet: no other module may use a network API."""
    network = {"QNetworkAccessManager", "QTcpSocket", "QUdpSocket", "QSslSocket", "urllib", "http", "requests",
               "socket", "httpx", "aiohttp", "ftplib", "smtplib", "webbrowser"}
    found = []
    for path in sorted(ROOT.joinpath("nightlight").rglob("*.py")):
        if path.name == "updates.py":
            continue
        text = path.read_text(encoding="utf-8")
        if path.name == "privacy.py":  # socket only for the computer's name, to scrub it from reports
            assert [line.strip() for line in text.splitlines() if "socket." in line] == [
                'return os.environ.get("COMPUTERNAME") or socket.gethostname()']
            text = text.replace("import socket\n", "")
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [(node.module or "").split(".")[0], *(alias.name for alias in node.names)]
            else:
                continue
            found += [f"{path.relative_to(ROOT)}:{node.lineno} {name}" for name in names if name in network]
    assert not found, found


# --- In the app -----------------------------------------------------------------------------


def test_the_settings_page_explains_it_and_saves_it(start):  # noqa: F811
    night_light, _ = start(GeneralConfig())
    night_light.show_settings()
    window = night_light._settings
    assert not window.check_for_updates.isChecked()
    texts = " ".join(label.text() for label in window.findChildren(type(window.update_status)))
    assert "only time Winlight connects to the internet" in texts and "recommended" in texts
    window.check_for_updates.setChecked(True)
    assert window.current_config().general.check_for_updates is True
    window._apply()
    assert night_light._config.general.check_for_updates and night_light.updates._timer.isActive()
    window.close()


def test_a_newer_version_is_announced_once_and_its_page_opens_on_click(start, monkeypatch):  # noqa: F811
    from nightlight import app as app_module

    night_light, _ = start(GeneralConfig())
    assert night_light.updates._network is None  # off: nothing network-related made
    shown, opened = [], []
    monkeypatch.setattr(night_light.tray, "showMessage", lambda title, *rest: shown.append(title))
    monkeypatch.setattr(app_module.QDesktopServices, "openUrl", lambda url: opened.append(url))
    url = "https://github.com/Arnie14/WinLight/releases/tag/v0.6.0-beta.1"
    night_light._on_update_found("0.6.0 Beta 1", url)
    night_light._on_update_found("0.6.0 Beta 1", url)  # the next day's check: not again
    assert shown == ["Winlight 0.6.0 Beta 1 is available"]
    night_light._on_tray_message_clicked()
    assert opened == [QUrl(url)]
    night_light._message_url = ""  # another notice (a hint) since: clicking it opens nothing
    night_light._on_tray_message_clicked()
    assert opened == [QUrl(url)]
    night_light.show_settings()
    assert url in night_light._settings.update_status.text()
    night_light._settings.close()
