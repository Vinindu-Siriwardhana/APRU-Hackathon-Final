"""One process-wide lock and atomic file writes.

Endpoints and WhatsApp background tasks run in a thread pool, so two requests can
load the same submission (or the GN workbook), change it and save it at the same
moment: one change is lost, or a reader sees a half-written file. Every
load → change → save of a submission, the conversation logs and the workbook happens
while holding `lock`, and every file is replaced atomically (write a temp file in the
same folder, then os.replace), so a reader sees either the old file or the new one.

Slow work (reading the handwriting) runs OUTSIDE the lock; see Pipeline.process.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from pathlib import Path

lock = threading.RLock()


def replace(src: Path, dst: Path, attempts: int = 20) -> None:
    """os.replace, retried briefly: on Windows a reader (antivirus, a download in
    progress) can hold the target open for a moment."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        tmp.write_bytes(data)
        replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))
