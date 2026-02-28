"""Calibration tool — capture templates and define screen regions.

Run this to:
1. Take a screenshot
2. Let you draw rectangles around: hand, table, bid panel, score
3. Crop card/bid templates from those regions

Usage:
    python calibrate.py
"""

from __future__ import annotations

import json
import os
import cv2
import numpy as np

from capture import ScreenCapture

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "regions.json")
CARD_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "cards")
BID_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "bids")
DIGIT_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "digits")

from game_state import Rank, Suit

# All 32 belot cards
RANKS = list(Rank)
SUITS = list(Suit)


class RegionSelector:
    """Interactive rectangle selector on a screenshot."""

    def __init__(self, image: np.ndarray, window_name: str = "Select Region"):
        self.image = image
        self.window_name = window_name
        self.start = None
        self.end = None
        self.drawing = False
        self.done = False

    def _mouse_cb(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.start = (x, y)
            self.drawing = True
        elif event == cv2.EVENT_MOUSEMOVE and self.drawing:
            self.end = (x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            self.end = (x, y)
            self.drawing = False
            self.done = True

    def select(self, prompt: str = "Draw a rectangle, press ENTER to confirm, ESC to skip") -> dict | None:
        print(f"\n>>> {prompt}")
        clone = self.image.copy()
        cv2.namedWindow(self.window_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.window_name, min(1400, self.image.shape[1]), min(900, self.image.shape[0]))
        cv2.setMouseCallback(self.window_name, self._mouse_cb)

        self.start = self.end = None
        self.done = False

        while True:
            display = clone.copy()
            if self.start and self.end:
                cv2.rectangle(display, self.start, self.end, (0, 255, 0), 2)
            cv2.putText(display, prompt, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.imshow(self.window_name, display)

            key = cv2.waitKey(30) & 0xFF
            if key == 27:  # ESC
                cv2.destroyWindow(self.window_name)
                return None
            if key == 13 and self.done:  # ENTER
                break

        cv2.destroyWindow(self.window_name)

        if self.start and self.end:
            x1, y1 = min(self.start[0], self.end[0]), min(self.start[1], self.end[1])
            x2, y2 = max(self.start[0], self.end[0]), max(self.start[1], self.end[1])
            return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
        return None


def calibrate_regions(screenshot: np.ndarray) -> dict:
    """Let user select the 4 key regions on screen."""
    selector = RegionSelector(screenshot)

    regions = {}
    for name, prompt in [
        ("hand", "Select your HAND region (cards at the bottom)"),
        ("bid", "Select the BIDDING PANEL region"),
        ("score", "Select the SCORE region (НИЕ / ВИЕ)"),
    ]:
        region = selector.select(prompt)
        if region:
            regions[name] = region
            print(f"  {name}: {region}")
        else:
            print(f"  {name}: skipped")

    # Table region last — take a fresh screenshot so user can have cards on table
    print("\nTaking new screenshot in 3 seconds for TABLE region...")
    print("Make sure cards are visible on the table!")
    import time
    time.sleep(3)
    cap = ScreenCapture()
    table_shot = cap.grab()
    cap.close()
    table_selector = RegionSelector(table_shot)
    region = table_selector.select("Select the TABLE region (center where tricks are played)")
    if region:
        regions["table"] = region
        print(f"  table: {region}")
    else:
        print(f"  table: skipped")

    return regions


def calibrate_cards(screenshot: np.ndarray, hand_region: dict):
    """Interactive card template capture from the hand region.

    Shows the hand region and lets you click individual cards,
    then label each one with rank + suit.
    """
    os.makedirs(CARD_TEMPLATE_DIR, exist_ok=True)

    x, y, w, h = hand_region["x"], hand_region["y"], hand_region["w"], hand_region["h"]
    hand_img = screenshot[y:y+h, x:x+w]

    suit_names = {s.value: s for s in Suit}
    rank_names = {r.value: r for r in Rank}

    print("\n--- Card Template Capture ---")
    print("Click on each card's top-left corner area, then type its identity.")
    print("Format: rank_suit (e.g., '7_diamonds', 'A_spades', 'J_hearts')")
    print("Type 'done' to finish.\n")

    saved = 0
    while True:
        label = input("Card label (e.g. '7_diamonds') or 'done': ").strip()
        if label.lower() == "done":
            break

        parts = label.split("_", 1)
        if len(parts) != 2 or parts[0] not in rank_names or parts[1] not in suit_names:
            print(f"  Invalid. Use format: rank_suit. Ranks: {list(rank_names.keys())}, Suits: {list(suit_names.keys())}")
            continue

        print("  Click on the card in the window, then press ENTER...")
        selector = RegionSelector(hand_img, "Click card region")
        region = selector.select(f"Draw rectangle around {label}")
        if region is None:
            print("  Skipped.")
            continue

        cx, cy, cw, ch = region["x"], region["y"], region["w"], region["h"]
        card_img = hand_img[cy:cy+ch, cx:cx+cw]
        if card_img.size == 0:
            print("  Empty region, try again.")
            continue

        path = os.path.join(CARD_TEMPLATE_DIR, f"{label}.png")
        cv2.imwrite(path, card_img)
        saved += 1
        print(f"  Saved: {path}")

    print(f"\nSaved {saved} card templates.")


def main():
    print("=== Belot Bot Calibration ===\n")
    print("Taking screenshot in 3 seconds... make sure the game is visible!")

    import time
    time.sleep(3)

    cap = ScreenCapture()
    screenshot = cap.grab()
    cap.close()

    print(f"Screenshot captured: {screenshot.shape[1]}x{screenshot.shape[0]}")

    # Step 1: Region selection
    print("\n--- Step 1: Select screen regions ---")
    regions = calibrate_regions(screenshot)

    if regions:
        with open(CONFIG_PATH, "w") as f:
            json.dump(regions, f, indent=2)
        print(f"\nRegions saved to {CONFIG_PATH}")

    # Step 2: Card template capture
    if "hand" in regions:
        do_cards = input("\nCapture card templates now? (y/n): ").strip().lower()
        if do_cards == "y":
            calibrate_cards(screenshot, regions["hand"])

    print("\nCalibration complete!")
    print(f"  Regions config: {CONFIG_PATH}")
    print(f"  Card templates: {CARD_TEMPLATE_DIR}/")
    print(f"  Bid templates:  {BID_TEMPLATE_DIR}/")
    print(f"  Digit templates: {DIGIT_TEMPLATE_DIR}/")


if __name__ == "__main__":
    main()
