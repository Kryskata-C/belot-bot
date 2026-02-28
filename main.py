"""Belot Bot — main entry point.

Uses JavaScript injection into Safari to read game state directly from
the Phaser engine, runs AI strategy analysis, then displays recommendations
on a PyQt6 overlay.
"""

from __future__ import annotations

import signal
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QShortcut, QKeySequence
from PyQt6.QtWidgets import QApplication

from js_detector import JSDetector
from strategy import BelotBrain
from gui import BelotBotWindow

SCAN_INTERVAL_MS = 500


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    app = QApplication(sys.argv)
    detector = JSDetector()
    brain = BelotBrain()

    window = BelotBotWindow()
    window.show()

    timer = QTimer()

    def scan():
        try:
            state = detector.detect()
            state.recommendation = brain.update(state)
            window.update_state(state)
        except Exception as e:
            print(f"Scan error: {e}")

    timer.timeout.connect(scan)

    def on_start():
        """Called when user clicks Start — begin scanning."""
        # Reset round state but keep learned layout (trick center etc)
        detector.reset_round()
        brain.reset_round()
        timer.start(SCAN_INTERVAL_MS)
        window.set_running(True)
        print("Scanning started!")

    def on_stop():
        """Called when user clicks Stop — pause scanning."""
        timer.stop()
        window.set_running(False)
        print("Scanning stopped.")

    window.start_clicked.connect(on_start)
    window.stop_clicked.connect(on_stop)

    QShortcut(QKeySequence("Ctrl+Q"), window).activated.connect(app.quit)

    print("Belot Bot ready — click START when in a match")

    exit_code = app.exec()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
