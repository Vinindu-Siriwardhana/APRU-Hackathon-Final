"""Image read/write that works on every OS. cv2.imread/imwrite can't open paths with
non-ASCII characters on Windows, so go through bytes instead."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import cv2
import numpy as np


def read_image(path: str | Path) -> Optional[np.ndarray]:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None


def write_image(path: str | Path, img: np.ndarray, quality: int = 90) -> None:
    ext = Path(path).suffix.lower() or ".jpg"
    params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext in (".jpg", ".jpeg") else []
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise ValueError(f"could not encode image as {ext}")
    Path(path).write_bytes(buf.tobytes())
