"""Screen detector for Belot game elements: cards, bidding panel, score."""

from __future__ import annotations

import os
import cv2
import numpy as np
import pytesseract

from game_state import (
    GameState, Card, Rank, Suit, BidType, Phase, ALL_CARDS,
)

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
CARD_TEMPLATE_DIR = os.path.join(TEMPLATE_DIR, "cards")
BID_TEMPLATE_DIR = os.path.join(TEMPLATE_DIR, "bids")

CARD_MATCH_THRESHOLD = 0.80
BID_MATCH_THRESHOLD = 0.85

_RANK_MAP: dict[str, Rank] = {
    "7": Rank.SEVEN, "8": Rank.EIGHT, "9": Rank.NINE,
    "10": Rank.TEN, "J": Rank.JACK, "Q": Rank.QUEEN,
    "K": Rank.KING, "A": Rank.ACE,
}


# ---------------------------------------------------------------------------
# Visual card detector — finds rank/suit text on card faces, no templates
# ---------------------------------------------------------------------------

class VisualCardDetector:
    """Detects cards by finding rank+suit characters on white card faces."""

    def detect(self, region: np.ndarray) -> list[Card]:
        if region.size == 0:
            return []

        # Step 1: mask white card area
        hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        card_mask = cv2.inRange(hsv, (0, 0, 140), (180, 100, 255))

        # Step 2: within white card area, find dark/red ink (rank+suit text)
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        _, dark_text = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY_INV)
        # Red ink: also counts as "text" on cards
        red1 = cv2.inRange(hsv, (0, 100, 80), (10, 255, 255))
        red2 = cv2.inRange(hsv, (160, 100, 80), (180, 255, 255))
        red_mask = red1 | red2
        # Combine: dark text + red text, but only on card faces
        text_mask = cv2.bitwise_and(dark_text | red_mask, card_mask)

        # Clean small noise
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        text_mask = cv2.morphologyEx(text_mask, cv2.MORPH_OPEN, kernel)

        # Step 3: find connected components of text on cards
        contours, _ = cv2.findContours(text_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        # Step 4: group text blobs into rank+suit clusters by proximity
        blobs = []
        img_h = region.shape[0]
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < 30:  # noise
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            # Filter: rank text is in upper portion of hand region, reasonably sized
            if h < 8 or h > img_h * 0.6:
                continue
            if w > region.shape[1] * 0.3:  # too wide = not a single rank
                continue
            blobs.append((x, y, w, h, area))

        if not blobs:
            return []

        # Group blobs into columns (each card's rank+suit is roughly vertical)
        blobs.sort(key=lambda b: b[0])
        groups = self._group_blobs_into_cards(blobs)

        # Step 5: for each group, classify the card
        found: list[tuple[int, Card]] = []
        seen = set()
        for group in groups:
            card = self._classify_group(region, group)
            if card and card not in seen:
                seen.add(card)
                min_x = min(b[0] for b in group)
                found.append((min_x, card))

        found.sort(key=lambda t: t[0])
        return [c for _, c in found]

    def _group_blobs_into_cards(self, blobs: list) -> list[list]:
        """Group nearby text blobs into per-card clusters."""
        if not blobs:
            return []

        groups = [[blobs[0]]]
        for blob in blobs[1:]:
            last_group = groups[-1]
            # Check if this blob is close to the last group (same card)
            last_x = max(b[0] + b[2] for b in last_group)
            first_x = min(b[0] for b in last_group)
            blob_x = blob[0]

            # Same card if x-overlap or very close
            if blob_x < last_x + 20 and blob_x >= first_x - 20:
                last_group.append(blob)
            else:
                groups.append([blob])

        return groups

    def _classify_group(self, img: np.ndarray, group: list) -> Card | None:
        """Classify a group of text blobs as a card (rank + suit)."""
        # Get bounding box of the whole group
        x1 = min(b[0] for b in group)
        y1 = min(b[1] for b in group)
        x2 = max(b[0] + b[2] for b in group)
        y2 = max(b[1] + b[3] for b in group)

        # Pad a bit
        pad = 5
        x1 = max(0, x1 - pad)
        y1 = max(0, y1 - pad)
        x2 = min(img.shape[1], x2 + pad)
        y2 = min(img.shape[0], y2 + pad)

        crop = img[y1:y2, x1:x2]
        if crop.size == 0:
            return None

        rank = self._read_rank(crop)
        suit = self._read_suit(crop)
        if rank and suit:
            return Card(rank, suit)
        return None

    def _read_rank(self, crop: np.ndarray) -> Rank | None:
        """OCR the rank from a card corner crop."""
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 140, 255, cv2.THRESH_BINARY_INV)

        # Scale up for OCR
        h, w = binary.shape
        scale = max(1, 50 // max(h, 1))
        if scale > 1:
            binary = cv2.resize(binary, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST)

        binary = cv2.copyMakeBorder(binary, 15, 15, 15, 15, cv2.BORDER_CONSTANT, value=0)

        text = pytesseract.image_to_string(
            binary, config="--psm 7 -c tessedit_char_whitelist=78910JQKA"
        ).strip().upper().replace(" ", "").replace("\n", "")

        if not text:
            return None

        # Try full match first, then prefix
        for length in [min(2, len(text)), 1]:
            candidate = text[:length]
            if candidate in _RANK_MAP:
                return _RANK_MAP[candidate]

        return None

    def _read_suit(self, crop: np.ndarray) -> Suit | None:
        """Determine suit by color analysis."""
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

        # Count red pixels
        red1 = cv2.inRange(hsv, (0, 100, 80), (10, 255, 255))
        red2 = cv2.inRange(hsv, (160, 100, 80), (180, 255, 255))
        red_count = cv2.countNonZero(red1) + cv2.countNonZero(red2)

        # Count dark pixels (black ink on card)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        _, dark = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY_INV)
        black_count = cv2.countNonZero(dark)

        is_red = red_count > 20 and red_count > black_count * 0.2

        if is_red:
            return self._red_suit(crop, hsv)
        else:
            return self._black_suit(crop, gray)

    def _red_suit(self, crop: np.ndarray, hsv: np.ndarray) -> Suit:
        """Hearts vs diamonds by shape."""
        red1 = cv2.inRange(hsv, (0, 100, 80), (10, 255, 255))
        red2 = cv2.inRange(hsv, (160, 100, 80), (180, 255, 255))
        mask = red1 | red2

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return Suit.HEARTS

        largest = max(contours, key=cv2.contourArea)
        hull = cv2.convexHull(largest)
        hull_area = cv2.contourArea(hull)
        if hull_area == 0:
            return Suit.HEARTS

        solidity = cv2.contourArea(largest) / hull_area
        # Diamond is more angular (lower solidity)
        return Suit.DIAMONDS if solidity < 0.80 else Suit.HEARTS

    def _black_suit(self, crop: np.ndarray, gray: np.ndarray) -> Suit:
        """Clubs vs spades by shape."""
        _, binary = cv2.threshold(gray, 80, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return Suit.SPADES

        # Find largest black blob (suit symbol)
        largest = max(contours, key=cv2.contourArea)
        hull = cv2.convexHull(largest)
        hull_area = cv2.contourArea(hull)
        if hull_area == 0:
            return Suit.SPADES

        solidity = cv2.contourArea(largest) / hull_area
        # Club trefoil → lower solidity; spade is more solid
        return Suit.CLUBS if solidity < 0.75 else Suit.SPADES


# ---------------------------------------------------------------------------
# Template-based card detector (when templates exist)
# ---------------------------------------------------------------------------

class CardDetector:
    def __init__(self):
        self.templates: dict[Card, np.ndarray] = {}
        self._load_templates()

    def _load_templates(self):
        if not os.path.isdir(CARD_TEMPLATE_DIR):
            return
        rank_map = {r.value: r for r in Rank}
        suit_map = {s.value: s for s in Suit}
        for fname in os.listdir(CARD_TEMPLATE_DIR):
            if not fname.endswith(".png"):
                continue
            name = fname[:-4]
            parts = name.split("_", 1)
            if len(parts) != 2:
                continue
            rank_str, suit_str = parts
            rank = rank_map.get(rank_str)
            suit = suit_map.get(suit_str)
            if rank and suit:
                img = cv2.imread(os.path.join(CARD_TEMPLATE_DIR, fname))
                if img is not None:
                    self.templates[Card(rank, suit)] = img

    @property
    def is_calibrated(self) -> bool:
        return len(self.templates) > 0

    def reload(self):
        self.templates.clear()
        self._load_templates()

    def detect(self, region: np.ndarray) -> list[Card]:
        if not self.templates:
            return []
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        found: list[tuple[int, Card]] = []
        seen = set()
        for card, tmpl in self.templates.items():
            tmpl_gray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
            if tmpl_gray.shape[0] > gray.shape[0] or tmpl_gray.shape[1] > gray.shape[1]:
                continue
            result = cv2.matchTemplate(gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= CARD_MATCH_THRESHOLD)
            for y, x in zip(*locations):
                if card not in seen:
                    seen.add(card)
                    found.append((int(x), card))
        found.sort(key=lambda t: t[0])
        return [card for _, card in found]


# ---------------------------------------------------------------------------
# Bid detection
# ---------------------------------------------------------------------------

BID_LABELS = {
    BidType.CLUBS: "СПАТИЯ", BidType.NO_TRUMPS: "БЕЗ КОЗ",
    BidType.DIAMONDS: "КАРО", BidType.ALL_TRUMPS: "ВСИЧКО КОЗ",
    BidType.HEARTS: "КУПА", BidType.CONTRA: "КОНТРА",
    BidType.SPADES: "ПИКА", BidType.RECONTRA: "РЕКОНТРА",
    BidType.PASS: "ПАС",
}


class BidDetector:
    def __init__(self):
        self.templates: dict[BidType, np.ndarray] = {}
        self._load_templates()

    def _load_templates(self):
        if not os.path.isdir(BID_TEMPLATE_DIR):
            return
        bid_map = {b.value: b for b in BidType}
        for fname in os.listdir(BID_TEMPLATE_DIR):
            if not fname.endswith(".png"):
                continue
            name = fname[:-4]
            bid = bid_map.get(name)
            if bid:
                img = cv2.imread(os.path.join(BID_TEMPLATE_DIR, fname))
                if img is not None:
                    self.templates[bid] = img

    def reload(self):
        self.templates.clear()
        self._load_templates()

    def detect_available(self, region: np.ndarray) -> list[BidType]:
        if not self.templates:
            return self._detect_by_brightness(region)
        return self._detect_by_template(region)

    def _detect_by_template(self, region: np.ndarray) -> list[BidType]:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        available = []
        for bid, tmpl in self.templates.items():
            tmpl_gray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
            if tmpl_gray.shape[0] > gray.shape[0] or tmpl_gray.shape[1] > gray.shape[1]:
                continue
            result = cv2.matchTemplate(gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
            if result.max() >= BID_MATCH_THRESHOLD:
                available.append(bid)
        return available

    def _detect_by_brightness(self, region: np.ndarray) -> list[BidType]:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        bright_ratio = np.mean(gray > 200)
        if bright_ratio > 0.15:
            return list(BidType)
        return []


# ---------------------------------------------------------------------------
# Score detection — OCR when no digit templates
# ---------------------------------------------------------------------------

class ScoreDetector:
    def __init__(self):
        self.digit_templates: dict[int, np.ndarray] = {}
        self._load_digit_templates()

    def _load_digit_templates(self):
        digit_dir = os.path.join(TEMPLATE_DIR, "digits")
        if not os.path.isdir(digit_dir):
            return
        for i in range(10):
            path = os.path.join(digit_dir, f"{i}.png")
            if os.path.exists(path):
                img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
                if img is not None:
                    self.digit_templates[i] = img

    def detect(self, region: np.ndarray) -> tuple[int | None, int | None]:
        if self.digit_templates:
            return self._detect_by_template(region)
        return self._detect_by_ocr(region)

    def _detect_by_template(self, region: np.ndarray) -> tuple[int | None, int | None]:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        mid = w // 2
        return self._read_number(gray[:, :mid]), self._read_number(gray[:, mid:])

    def _read_number(self, region: np.ndarray) -> int | None:
        if not self.digit_templates:
            return None
        found: list[tuple[int, int]] = []
        for digit, tmpl in self.digit_templates.items():
            if tmpl.shape[0] > region.shape[0] or tmpl.shape[1] > region.shape[1]:
                continue
            result = cv2.matchTemplate(region, tmpl, cv2.TM_CCOEFF_NORMED)
            locations = np.where(result >= 0.80)
            for y, x in zip(*locations):
                if not any(abs(x - fx) < tmpl.shape[1] for fx, _ in found):
                    found.append((int(x), digit))
        if not found:
            return None
        found.sort(key=lambda t: t[0])
        try:
            return int("".join(str(d) for _, d in found))
        except ValueError:
            return None

    def _detect_by_ocr(self, region: np.ndarray) -> tuple[int | None, int | None]:
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
        h, w = binary.shape
        mid = w // 2
        bottom = binary[h // 2:, :]
        return self._ocr_number(bottom[:, :mid]), self._ocr_number(bottom[:, mid:])

    def _ocr_number(self, region: np.ndarray) -> int | None:
        if region.size == 0 or np.mean(region) < 5:
            return None
        scaled = cv2.resize(region, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
        scaled = cv2.copyMakeBorder(scaled, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=0)
        text = pytesseract.image_to_string(
            scaled, config="--psm 7 -c tessedit_char_whitelist=0123456789"
        ).strip()
        try:
            return int(text)
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Main detector
# ---------------------------------------------------------------------------

class GameDetector:
    def __init__(self):
        self.card_detector = CardDetector()
        self.visual_detector = VisualCardDetector()
        self.bid_detector = BidDetector()
        self.score_detector = ScoreDetector()

        self.hand_region: dict | None = None
        self.table_region: dict | None = None
        self.bid_region: dict | None = None
        self.score_region: dict | None = None

        self._seen_cards: set[Card] = set()
        self._last_hand: list[Card] = []

    def set_regions(self, hand=None, table=None, bid=None, score=None):
        if hand:
            self.hand_region = hand
        if table:
            self.table_region = table
        if bid:
            self.bid_region = bid
        if score:
            self.score_region = score

    @property
    def has_regions(self) -> bool:
        return self.hand_region is not None

    def _crop(self, frame: np.ndarray, region: dict) -> np.ndarray:
        x, y, w, h = region["x"], region["y"], region["w"], region["h"]
        return frame[y:y + h, x:x + w]

    def _detect_cards(self, region_img: np.ndarray) -> list[Card]:
        if self.card_detector.is_calibrated:
            return self.card_detector.detect(region_img)
        return self.visual_detector.detect(region_img)

    def detect(self, frame: np.ndarray) -> GameState:
        state = GameState()

        if self.hand_region:
            hand_img = self._crop(frame, self.hand_region)
            state.hand = self._detect_cards(hand_img)
            if state.hand:
                self._last_hand = state.hand

        if self.table_region:
            table_img = self._crop(frame, self.table_region)
            state.table_cards = self._detect_cards(table_img)
            for c in state.table_cards:
                self._seen_cards.add(c)

        state.seen_cards = set(self._seen_cards)

        if self.bid_region:
            bid_img = self._crop(frame, self.bid_region)
            state.available_bids = self.bid_detector.detect_available(bid_img)
            state.phase = Phase.BIDDING if state.available_bids else Phase.PLAYING
        elif state.hand:
            state.phase = Phase.PLAYING

        if self.score_region:
            score_img = self._crop(frame, self.score_region)
            our, their = self.score_detector.detect(score_img)
            if our is not None:
                state.our_score = our
            if their is not None:
                state.their_score = their

        return state

    def reset_round(self):
        self._seen_cards.clear()
        self._last_hand.clear()
