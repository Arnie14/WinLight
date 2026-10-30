# SPDX-License-Identifier: GPL-3.0-only
"""Writing the app's small state files safely.

Each file is written to a temporary file next to it and then renamed over
it, so a crash or power cut mid-write leaves the old file, never half a new
one. On Windows the rename fails with "Access is denied" while another
program briefly holds the file open (antivirus scanning it, the search
indexer, a sync client), so it is tried again a few times before giving up.

Each write has a temporary file of its own. With one shared name, two
threads writing the same file at once (the gamma journal, written by a call
abandoned as stuck and by the next one) each renamed the other's
half-written file into place: a reader then found half a file.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

ATTEMPTS = 5
RETRY_DELAY_S = 0.05


def write_atomic(path: Path, text: str) -> None:
    """Replace `path`'s contents with `text`; raises OSError if it can't."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f"{path.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        for attempt in range(ATTEMPTS):
            try:
                os.replace(tmp, path)  # noqa: PTH105 (the tests stand in for os.replace to simulate a locked file)
                return
            except PermissionError:
                if attempt == ATTEMPTS - 1:
                    raise
                time.sleep(RETRY_DELAY_S * (attempt + 1))
    finally:
        tmp.unlink(missing_ok=True)  # gone already once it replaced the file; left over only on failure
