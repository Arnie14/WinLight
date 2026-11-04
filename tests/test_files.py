# SPDX-License-Identifier: GPL-3.0-only
import os

import pytest

from nightlight import files


def test_writes_and_replaces(tmp_path):
    path = tmp_path / "sub" / "state.json"
    files.write_atomic(path, "one")
    files.write_atomic(path, "two")
    assert path.read_text(encoding="utf-8") == "two"
    assert [p.name for p in path.parent.iterdir()] == ["state.json"]  # no temporary file left behind


def test_a_file_held_open_for_a_moment_is_retried(tmp_path, monkeypatch):
    # Antivirus or the search indexer holding the file: "Access is denied" for a moment.
    path = tmp_path / "state.json"
    path.write_text("old", encoding="utf-8")
    real_replace, refusals = os.replace, [2]

    def busy_replace(src, dst):
        if refusals[0]:
            refusals[0] -= 1
            raise PermissionError(13, "Access is denied")
        real_replace(src, dst)

    monkeypatch.setattr(files.os, "replace", busy_replace)
    monkeypatch.setattr(files, "RETRY_DELAY_S", 0)
    files.write_atomic(path, "new")
    assert path.read_text(encoding="utf-8") == "new"


def test_a_file_that_stays_locked_keeps_its_old_contents(tmp_path, monkeypatch):
    path = tmp_path / "state.json"
    path.write_text("old", encoding="utf-8")

    def locked(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(files.os, "replace", locked)
    monkeypatch.setattr(files, "RETRY_DELAY_S", 0)
    with pytest.raises(PermissionError):
        files.write_atomic(path, "new")
    assert path.read_text(encoding="utf-8") == "old"  # never half-written


def test_the_new_contents_reach_the_disk_before_the_rename(tmp_path, monkeypatch):
    """Renaming over the old file is journaled by NTFS, the new file's
    contents aren't: after a power cut, a rename that got to the disk before
    the data left the file empty or zeroed, and settings.json then read as
    damaged, so Winlight started with default settings."""
    import os

    from nightlight import files

    order = []
    real_fsync, real_replace = os.fsync, os.replace
    monkeypatch.setattr(files.os, "fsync", lambda fd: (order.append("fsync"), real_fsync(fd))[1])
    monkeypatch.setattr(files.os, "replace", lambda src, dst: (order.append("replace"), real_replace(src, dst))[1])
    files.write_atomic(tmp_path / "settings.json", "{}")
    assert order == ["fsync", "replace"]
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == "{}"
