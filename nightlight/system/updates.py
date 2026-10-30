# SPDX-License-Identifier: GPL-3.0-only
"""Checking for a newer version, when the user turns it on (it's off by default).

Winlight's only connection to the internet. Once a day (and a minute after
starting, and when asked) it reads GitHub's public list of releases and,
if one is newer than this version, says so. It downloads and installs
nothing: the release page opens when asked, and installing stays the
user's step. The request carries nothing but Winlight's version in its
User-Agent; GitHub sees the address it comes from, as with any page.

Betas are offered too, since Winlight is in beta. Drafts never are.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, QUrl, Signal

from nightlight import __version__, display_version

log = logging.getLogger(__name__)

RELEASES_API = "https://api.github.com/repos/Arnie14/WinLight/releases?per_page=10"
FIRST_CHECK_MS = 60_000  # after starting: never part of start-up
CHECK_EVERY_MS = 24 * 60 * 60_000
TIMEOUT_MS = 15_000
MAX_REPLY_BYTES = 2_000_000

_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-([a-z]+)(?:\.(\d+))?)?$")


def version_key(text: str) -> tuple[int, int, int, int, int] | None:
    """"0.6.0-beta.1" or "v0.6.0" -> a key that sorts versions; None if it isn't one.
    A release sorts after its betas: 0.6.0-beta.2 < 0.6.0 < 0.6.1-beta.1."""
    match = _VERSION.match(text.strip())
    if match is None:
        return None
    major, minor, patch, stage, number = match.groups()
    final = stage is None
    return int(major), int(minor), int(patch), 1 if final else 0, 0 if final else int(number or 0)


@dataclass(frozen=True)
class Release:
    version: str  # as tagged, without the "v": "0.6.0-beta.1"
    url: str  # its page on GitHub


def newest(releases: object) -> Release | None:
    """The newest release in GitHub's list (drafts left out); None if there's none."""
    best: tuple[tuple, Release] | None = None
    if not isinstance(releases, list):
        return None
    for item in releases:
        if not isinstance(item, dict) or item.get("draft"):
            continue
        tag, url = item.get("tag_name"), item.get("html_url")
        if not isinstance(tag, str) or not isinstance(url, str) or not url.startswith("https://github.com/"):
            continue
        key = version_key(tag)
        if key is not None and (best is None or key > best[0]):
            best = (key, Release(tag.strip().removeprefix("v"), url))
    return best[1] if best else None


# Each check's outcome, as Settings shows it.
UP_TO_DATE = "You have the newest version"
CHECKING = "Checking…"


class UpdateChecker(QObject):
    found = Signal(str, str)  # a newer version (as shown: "0.6.1 Beta 1"), its release page
    checked = Signal(str)  # how the last check went, for Settings

    def __init__(self, fetch: Callable[[Callable[[bytes | None, str], None]], None] | None = None,
                 current: str = __version__, parent: QObject | None = None) -> None:
        """`fetch(done)` reads the releases and calls done(body, error); the
        default uses Qt's network, created only when a check runs (so with
        the setting off, nothing network-related exists at all)."""
        super().__init__(parent)
        self._fetch = fetch or self._fetch_with_qt
        self._current = version_key(current)
        self._network = None
        self._busy = False
        self.last = ""  # the last check's outcome
        self._timer = QTimer(self, singleShot=True)
        self._timer.timeout.connect(self._scheduled)

    def set_enabled(self, enabled: bool) -> None:
        if enabled and not self._timer.isActive():
            self._timer.start(FIRST_CHECK_MS)
        elif not enabled:
            self._timer.stop()

    def check_now(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._report(CHECKING)
        try:
            self._fetch(self._done)
        except Exception as exc:  # never let a check break anything else
            log.warning("Checking for updates failed: %s", exc)
            self._done(None, str(exc))

    def _scheduled(self) -> None:
        self._timer.start(CHECK_EVERY_MS)
        self.check_now()

    def _done(self, body: bytes | None, error: str) -> None:
        self._busy = False
        if body is None:
            log.info("Couldn't check for updates: %s", error)
            self._report(f"Couldn't check: {error}" if error else "Couldn't check")
            return
        try:
            release = newest(json.loads(body))
        except ValueError:
            release = None
        if release is None:
            log.info("Checking for updates: GitHub's answer had no releases in it")
            self._report("Couldn't check: GitHub's answer had no releases in it")
            return
        key = version_key(release.version)
        if self._current is not None and key is not None and key > self._current:
            shown = display_version(release.version)
            log.info("Checking for updates: %s is out", shown)
            self._report(f"{shown} is available")
            self.found.emit(shown, release.url)
        else:
            self._report(UP_TO_DATE)

    def _report(self, text: str) -> None:
        self.last = text
        self.checked.emit(text)

    def _fetch_with_qt(self, done: Callable[[bytes | None, str], None]) -> None:
        from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

        if self._network is None:
            self._network = QNetworkAccessManager(self)
        request = QNetworkRequest(QUrl(RELEASES_API))
        request.setRawHeader(b"User-Agent", f"Winlight/{__version__}".encode())
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setTransferTimeout(TIMEOUT_MS)
        reply = self._network.get(request)

        def finished() -> None:
            reply.deleteLater()
            if reply.error() != QNetworkReply.NetworkError.NoError:
                done(None, reply.errorString())
                return
            body = bytes(reply.read(MAX_REPLY_BYTES).data())
            done(body, "")

        reply.finished.connect(finished)
