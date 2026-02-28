"""Optimized screen capture using mss with persistent instance and region support."""

from __future__ import annotations

import numpy as np
import mss


class ScreenCapture:
    """Persistent screen capturer — reuses the mss instance across grabs."""

    def __init__(self, monitor_index: int = 1):
        self._sct = mss.mss()
        self._monitor_index = monitor_index
        self._region: dict | None = None

    @property
    def monitor(self) -> dict:
        return self._sct.monitors[self._monitor_index]

    def set_region(self, left: int, top: int, width: int, height: int):
        """Lock captures to a specific screen region (e.g. the game board)."""
        self._region = {"left": left, "top": top, "width": width, "height": height}

    def clear_region(self):
        """Reset to full-monitor capture."""
        self._region = None

    def grab(self) -> np.ndarray:
        """Grab a frame as a BGR numpy array.

        If a region is set, captures only that rectangle.
        Otherwise captures the full monitor.
        """
        area = self._region if self._region else self._sct.monitors[self._monitor_index]
        shot = self._sct.grab(area)
        # mss returns BGRA — slice off alpha, no copy needed for read-only use
        return np.asarray(shot)[:, :, :3]

    def close(self):
        self._sct.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
