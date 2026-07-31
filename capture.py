"""Interactive region screenshot via macOS screencapture."""
from __future__ import annotations

import base64
import os
import subprocess
import tempfile


class CaptureError(Exception):
    """screencapture failed for a real reason (e.g. missing Screen Recording permission)."""


# screencapture can hang (observed with a wedged window server). Without a bound
# the worker thread blocks forever and app.py's _busy lock is never released,
# which silently blocks every later analysis.
CAPTURE_TIMEOUT = 15.0


def _tmp_png() -> str:
    fd, path = tempfile.mkstemp(suffix=".png", prefix="screen-coach-")
    os.close(fd)
    os.unlink(path)  # screencapture recreates it; we only want the path
    return path


def capture_region(runner=subprocess.run) -> str | None:
    """Prompt an interactive region capture.

    Returns the PNG path on success, None on a clean Esc-cancel, and raises
    CaptureError on a genuine failure (non-zero exit, e.g. permission denied) —
    so the caller can tell "user cancelled" apart from "it's broken".
    """
    path = _tmp_png()
    try:
        result = runner(["screencapture", "-i", "-o", path],
                        capture_output=True, text=True, timeout=CAPTURE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise CaptureError(f"screencapture 超时（{CAPTURE_TIMEOUT:g}s）") from None
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    rc = getattr(result, "returncode", 0)
    if rc:
        stderr = (getattr(result, "stderr", "") or "").strip()
        raise CaptureError(stderr or f"screencapture exited with code {rc}")
    return None  # no file + clean exit = user pressed Esc


def capture_rect(x: float, y: float, w: float, h: float,
                 runner=subprocess.run) -> str:
    """Capture a fixed rectangle. x/y/w/h are already in screencapture's
    top-left-origin space — the caller owns the AppKit→screencapture conversion
    (see region.py: rects come from an AppKit window frame).

    Unlike capture_region there is no user involved, so there is no cancel
    case: anything other than a written file is a CaptureError.
    """
    path = _tmp_png()
    spec = f"{int(round(x))},{int(round(y))},{int(round(w))},{int(round(h))}"
    try:
        result = runner(["screencapture", "-x", "-o", "-R", spec, path],
                        capture_output=True, text=True, timeout=CAPTURE_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise CaptureError(f"screencapture 超时（{CAPTURE_TIMEOUT:g}s）") from None
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return path
    stderr = (getattr(result, "stderr", "") or "").strip()
    rc = getattr(result, "returncode", 0)
    raise CaptureError(stderr or f"截取区域 {spec} 失败（exit {rc}）")


def to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")
