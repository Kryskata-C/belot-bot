"""Belot Bot dashboard window — PyQt6 custom-painted overlay."""

from __future__ import annotations

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PyQt6.QtWidgets import QWidget, QPushButton

from game_state import GameState, Card, TableCard, Suit, Rank, BidType, Phase, ALL_CARDS

# ── colours ─────────────────────────────────────────────────────────
BG = QColor(30, 30, 34)
PANEL_BG = QColor(42, 42, 48)
TEXT = QColor(220, 220, 220)
DIM = QColor(100, 100, 100)
RED = QColor(220, 50, 50)
BLACK = QColor(230, 230, 230)
GREEN = QColor(60, 180, 80)
GOLD = QColor(230, 190, 60)
CARD_BG = QColor(255, 255, 255)
CARD_BORDER = QColor(80, 80, 80)
ACTIVE_BID = QColor(70, 130, 220)
INACTIVE_BID = QColor(60, 60, 65)
REC_PLAY_BG = QColor(30, 100, 40)
REC_BID_BG = QColor(120, 100, 20)
REC_PASS_BG = QColor(60, 60, 65)
VOID_BG = QColor(50, 40, 40)

SUIT_SYMBOL = {Suit.CLUBS: "♣", Suit.DIAMONDS: "♦", Suit.HEARTS: "♥", Suit.SPADES: "♠"}
SUIT_COLOR = {Suit.CLUBS: BLACK, Suit.DIAMONDS: RED, Suit.HEARTS: RED, Suit.SPADES: BLACK}
RANK_LABEL = {
    Rank.SEVEN: "7", Rank.EIGHT: "8", Rank.NINE: "9", Rank.TEN: "10",
    Rank.JACK: "J", Rank.QUEEN: "Q", Rank.KING: "K", Rank.ACE: "A",
}
BID_LABEL = {
    BidType.CLUBS: "♣", BidType.DIAMONDS: "♦", BidType.HEARTS: "♥",
    BidType.SPADES: "♠", BidType.NO_TRUMPS: "БК", BidType.ALL_TRUMPS: "ВК",
    BidType.CONTRA: "К", BidType.RECONTRA: "РК", BidType.PASS: "ПАС",
}
BID_ORDER = [
    BidType.CLUBS, BidType.DIAMONDS, BidType.HEARTS, BidType.SPADES,
    BidType.NO_TRUMPS, BidType.ALL_TRUMPS,
    BidType.CONTRA, BidType.RECONTRA, BidType.PASS,
]
RANK_ORDER = [Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.TEN,
              Rank.JACK, Rank.QUEEN, Rank.KING, Rank.ACE]
SUIT_ORDER = [Suit.CLUBS, Suit.DIAMONDS, Suit.HEARTS, Suit.SPADES]

WIN_W, WIN_H = 580, 860


class BelotBotWindow(QWidget):
    """Frameless always-on-top overlay that paints the bot dashboard."""

    start_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setFixedSize(WIN_W, WIN_H)
        self.setWindowTitle("Belot Bot")
        self._drag_pos: QPoint | None = None
        self._state = GameState()
        self._running = False

        # Start button — shown when not running
        self._start_btn = QPushButton("START", self)
        self._start_btn.setGeometry(WIN_W // 2 - 100, WIN_H // 2 - 30, 200, 60)
        self._start_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #2ecc40; color: white; font-size: 22px;"
            "  font-weight: bold; border-radius: 10px; border: 2px solid #27ae60;"
            "}"
            "QPushButton:hover { background-color: #27ae60; }"
        )
        self._start_btn.clicked.connect(self._on_start)

        # Stop button — shown when running
        self._stop_btn = QPushButton("STOP", self)
        self._stop_btn.setGeometry(WIN_W - 80, 5, 70, 28)
        self._stop_btn.setStyleSheet(
            "QPushButton {"
            "  background-color: #e74c3c; color: white; font-size: 11px;"
            "  font-weight: bold; border-radius: 5px; border: 1px solid #c0392b;"
            "}"
            "QPushButton:hover { background-color: #c0392b; }"
        )
        self._stop_btn.clicked.connect(self._on_stop)
        self._stop_btn.hide()

    def _on_start(self):
        self.start_clicked.emit()

    def _on_stop(self):
        self.stop_clicked.emit()

    def set_running(self, running: bool):
        self._running = running
        self._start_btn.setVisible(not running)
        self._stop_btn.setVisible(running)
        self.update()

    # ── public API ──────────────────────────────────────────────────
    def update_state(self, state: GameState) -> None:
        self._state = state
        self.update()

    # ── dragging ────────────────────────────────────────────────────
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag_pos and ev.buttons() & Qt.MouseButton.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, ev):
        self._drag_pos = None

    # ── painting ────────────────────────────────────────────────────
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = self._state
        y = 0

        # background
        p.fillRect(self.rect(), BG)

        # If not running, show waiting screen
        if not self._running:
            font = QFont("Arial", 16, QFont.Weight.Bold)
            p.setFont(font)
            p.setPen(QPen(TEXT))
            p.drawText(0, WIN_H // 2 - 80, WIN_W, 40,
                       Qt.AlignmentFlag.AlignCenter, "Belot Bot")
            font2 = QFont("Arial", 11)
            p.setFont(font2)
            p.setPen(QPen(DIM))
            p.drawText(0, WIN_H // 2 + 40, WIN_W, 30,
                       Qt.AlignmentFlag.AlignCenter,
                       "Enter a match, then click START")
            p.end()
            return

        # ── score bar ───────────────────────────────────────────────
        y = self._draw_score(p, y, s)

        # ── phase status ────────────────────────────────────────────
        y = self._draw_phase(p, y, s)

        # ── bid history (who bid what) ────────────────────────────
        y = self._draw_bid_history(p, y, s)

        # ── table cards ─────────────────────────────────────────────
        y = self._draw_table(p, y, s.table_cards)

        # ── hand cards ──────────────────────────────────────────────
        y = self._draw_section(p, y, "Your Hand", s.hand, s)

        # ── recommendation bar ──────────────────────────────────────
        y = self._draw_recommendation(p, y, s)

        # ── point tracker ───────────────────────────────────────────
        y = self._draw_points(p, y, s)

        # ── bidding bar ─────────────────────────────────────────────
        y = self._draw_bids(p, y, s)

        # ── void tracker ────────────────────────────────────────────
        y = self._draw_voids(p, y, s)

        # ── card tracker ────────────────────────────────────────────
        self._draw_tracker(p, y, s)

        p.end()

    # ── drawing helpers ─────────────────────────────────────────────
    def _draw_score(self, p: QPainter, y: int, s: GameState) -> int:
        h = 50
        p.fillRect(0, y, WIN_W, h, PANEL_BG)
        font = QFont("Arial", 18, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(TEXT))
        p.drawText(20, y, 200, h, Qt.AlignmentFlag.AlignVCenter, f"НИЕ: {s.our_score}")
        p.setPen(QPen(GOLD))
        p.drawText(0, y, WIN_W, h, Qt.AlignmentFlag.AlignCenter, "Score")
        p.setPen(QPen(TEXT))
        p.drawText(WIN_W - 220, y, 200, h, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, f"ВИЕ: {s.their_score}")
        return y + h + 1

    def _draw_phase(self, p: QPainter, y: int, s: GameState) -> int:
        h = 34
        p.fillRect(0, y, WIN_W, h, PANEL_BG)
        font = QFont("Arial", 12)
        p.setFont(font)

        # Left side: phase
        phase_text = s.phase.name.replace("_", " ")
        p.setPen(QPen(GREEN if s.phase == Phase.PLAYING else GOLD))
        p.drawText(15, y, 180, h, Qt.AlignmentFlag.AlignVCenter, f"Phase: {phase_text}")

        # Right side: current contract/trump (big and clear)
        contract = ""
        if s.phase == Phase.PLAYING and s.trump:
            contract = f"Contract: {BID_LABEL.get(s.trump, '?')}"
        elif s.phase == Phase.BIDDING and s.current_bid:
            contract = f"Bid: {BID_LABEL.get(s.current_bid, '?')}"

        if contract:
            bold = QFont("Arial", 14, QFont.Weight.Bold)
            p.setFont(bold)
            p.setPen(QPen(QColor(255, 255, 255)))
            p.drawText(200, y, WIN_W - 215, h,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       contract)

        return y + h + 1

    def _draw_bid_history(self, p: QPainter, y: int, s: GameState) -> int:
        """Show what each player bid — visible during BIDDING and PLAYING."""
        # Only show if there are any actual bids
        has_bids = any(b is not None for b in s.seat_bids.values())
        if not has_bids:
            return y

        h = 34
        p.fillRect(0, y, WIN_W, h, QColor(38, 38, 45))

        seat_labels = {0: "You", 1: "East", 2: "Ptnr", 3: "West"}
        seat_colors = {
            0: GREEN,
            1: RED,
            2: QColor(100, 180, 255),
            3: RED,
        }

        label_font = QFont("Arial", 10)
        bid_font = QFont("Arial", 14, QFont.Weight.Bold)

        # Calculate total width for centering
        entries = [(seat, s.seat_bids[seat]) for seat in [0, 1, 2, 3]
                   if s.seat_bids.get(seat) is not None]
        if not entries:
            return y

        entry_w = 100
        total_w = len(entries) * entry_w
        x = (WIN_W - total_w) // 2

        for seat, bid in entries:
            # Seat label
            p.setFont(label_font)
            p.setPen(QPen(DIM))
            p.drawText(x, y, entry_w, h // 2,
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
                       seat_labels[seat])

            # Bid value — pass is dim, real bids are colored
            p.setFont(bid_font)
            bid_text = BID_LABEL.get(bid, "?")
            if bid == BidType.PASS:
                p.setPen(QPen(DIM))
            else:
                p.setPen(QPen(seat_colors.get(seat, TEXT)))
            p.drawText(x, y + h // 2, entry_w, h // 2,
                       Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop,
                       bid_text)

            x += entry_w

        return y + h + 1

    def _draw_table(self, p: QPainter, y: int, table_cards: list[TableCard]) -> int:
        header_h = 26
        card_area_h = 70
        name_h = 20
        total = header_h + card_area_h + name_h + 6

        p.fillRect(0, y, WIN_W, total, BG)

        # title
        font = QFont("Arial", 11)
        p.setFont(font)
        p.setPen(QPen(DIM))
        p.drawText(15, y, WIN_W, header_h, Qt.AlignmentFlag.AlignVCenter, "Table")

        if table_cards:
            card_w, card_h = 56, 66
            gap = 18
            total_w = len(table_cards) * (card_w + gap) - gap
            x0 = (WIN_W - total_w) // 2
            cy = y + header_h + 2

            seat_labels = {0: "You", 1: "East", 2: "Partner", 3: "West"}
            seat_colors = {0: GREEN, 1: RED, 2: QColor(100, 180, 255), 3: RED}

            for i, tc in enumerate(table_cards):
                cx = x0 + i * (card_w + gap)
                self._draw_card(p, cx, cy, card_w, card_h, tc.card)

                # Seat label below the card
                name_font = QFont("Arial", 9, QFont.Weight.Bold)
                p.setFont(name_font)
                color = seat_colors.get(tc.seat, DIM)
                p.setPen(QPen(color))
                label = seat_labels.get(tc.seat, tc.player_name[:8])
                p.drawText(cx - 3, cy + card_h, card_w + 6, name_h,
                           Qt.AlignmentFlag.AlignCenter, label)
        else:
            p.setPen(QPen(DIM))
            small = QFont("Arial", 10)
            p.setFont(small)
            p.drawText(0, y + header_h, WIN_W, card_area_h, Qt.AlignmentFlag.AlignCenter, "—")

        return y + total

    def _draw_section(self, p: QPainter, y: int, title: str, cards: list[Card], s: GameState) -> int:
        header_h = 26
        card_area_h = 70
        total = header_h + card_area_h + 6

        p.fillRect(0, y, WIN_W, total, BG)

        # title
        font = QFont("Arial", 11)
        p.setFont(font)
        p.setPen(QPen(DIM))
        p.drawText(15, y, WIN_W, header_h, Qt.AlignmentFlag.AlignVCenter, title)

        # cards
        if cards:
            card_w, card_h = 56, 66
            gap = 6
            total_w = len(cards) * (card_w + gap) - gap
            x0 = (WIN_W - total_w) // 2
            cy = y + header_h + 2

            # Check which card is recommended
            rec_card = None
            if s.recommendation and s.recommendation.card:
                rec_card = s.recommendation.card

            for i, card in enumerate(cards):
                cx = x0 + i * (card_w + gap)
                highlight = rec_card and card == rec_card
                self._draw_card(p, cx, cy, card_w, card_h, card, highlight=highlight)
        else:
            p.setPen(QPen(DIM))
            small = QFont("Arial", 10)
            p.setFont(small)
            p.drawText(0, y + header_h, WIN_W, card_area_h, Qt.AlignmentFlag.AlignCenter, "—")

        return y + total

    def _draw_card(self, p: QPainter, x: int, y: int, w: int, h: int, card: Card, highlight: bool = False):
        # rounded rect background
        if highlight:
            p.setPen(QPen(GREEN, 3))
            p.setBrush(QBrush(QColor(220, 255, 220)))
        else:
            p.setPen(QPen(CARD_BORDER, 1))
            p.setBrush(QBrush(CARD_BG))
        p.drawRoundedRect(x, y, w, h, 6, 6)

        color = SUIT_COLOR[card.suit]
        suit_sym = SUIT_SYMBOL[card.suit]
        rank_lbl = RANK_LABEL[card.rank]

        # rank
        font = QFont("Arial", 16, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(color))
        p.drawText(x, y + 4, w, 28, Qt.AlignmentFlag.AlignCenter, rank_lbl)

        # suit
        font_suit = QFont("Arial", 20)
        p.setFont(font_suit)
        p.drawText(x, y + 30, w, 32, Qt.AlignmentFlag.AlignCenter, suit_sym)

    def _draw_recommendation(self, p: QPainter, y: int, s: GameState) -> int:
        h = 40
        rec = s.recommendation
        if not rec:
            p.fillRect(0, y, WIN_W, h, PANEL_BG)
            p.setFont(QFont("Arial", 12))
            p.setPen(QPen(DIM))
            p.drawText(15, y, WIN_W - 30, h, Qt.AlignmentFlag.AlignVCenter, "Waiting for game...")
            return y + h + 1

        # Background color based on action type
        if rec.action == "bid":
            if rec.bid == BidType.PASS:
                bg = REC_PASS_BG
            else:
                bg = REC_BID_BG
        else:
            bg = REC_PLAY_BG

        p.fillRect(0, y, WIN_W, h, bg)

        font = QFont("Arial", 13, QFont.Weight.Bold)
        p.setFont(font)
        p.setPen(QPen(QColor(255, 255, 255)))

        if rec.action == "bid":
            bid_label = BID_LABEL.get(rec.bid, "?") if rec.bid else "?"
            text = f"BID: {bid_label}  —  {rec.reasoning}"
        elif rec.action == "play" and rec.card:
            text = f"PLAY: {rec.card}  —  {rec.reasoning}"
        else:
            text = rec.reasoning

        p.drawText(15, y, WIN_W - 30, h, Qt.AlignmentFlag.AlignVCenter, text)

        # Confidence indicator
        if rec.confidence > 0:
            bar_w = int(80 * rec.confidence)
            bar_h = 5
            bar_x = WIN_W - 95
            bar_y = y + h - 10
            p.fillRect(bar_x, bar_y, 80, bar_h, QColor(60, 60, 60))
            conf_color = GREEN if rec.confidence >= 0.6 else GOLD if rec.confidence >= 0.3 else RED
            p.fillRect(bar_x, bar_y, bar_w, bar_h, conf_color)

        return y + h + 1

    def _draw_points(self, p: QPainter, y: int, s: GameState) -> int:
        if s.phase != Phase.PLAYING:
            return y

        h = 28
        p.fillRect(0, y, WIN_W, h, PANEL_BG)
        font = QFont("Arial", 12)
        p.setFont(font)
        p.setPen(QPen(TEXT))

        total = s.our_points + s.their_points
        remaining = max(0, 162 - total) if s.trump and s.trump not in (BidType.ALL_TRUMPS, BidType.NO_TRUMPS) else max(0, 258 - total)

        text = f"Points:  Us {s.our_points}  /  Them {s.their_points}  /  Left ~{remaining}"
        p.drawText(15, y, WIN_W - 30, h, Qt.AlignmentFlag.AlignVCenter, text)
        return y + h + 1

    def _draw_bids(self, p: QPainter, y: int, s: GameState) -> int:
        h = 42
        p.fillRect(0, y, WIN_W, h, PANEL_BG)

        chip_w, chip_h = 48, 30
        gap = 8
        total_w = len(BID_ORDER) * (chip_w + gap) - gap
        x0 = (WIN_W - total_w) // 2
        cy = y + (h - chip_h) // 2

        available = set(s.available_bids)
        font = QFont("Arial", 11, QFont.Weight.Bold)
        p.setFont(font)

        # Determine current contract (trump) and recommended bid
        rec_bid = None
        if s.recommendation and s.recommendation.action == "bid" and s.recommendation.bid:
            rec_bid = s.recommendation.bid

        # The active contract/trump — highlight it bright
        current_contract = s.trump if s.phase == Phase.PLAYING else None
        current_bid = s.current_bid if s.phase == Phase.BIDDING else None

        for i, bid in enumerate(BID_ORDER):
            cx = x0 + i * (chip_w + gap)
            active = bid in available
            is_recommended = bid == rec_bid and rec_bid != BidType.PASS
            is_current_contract = bid == current_contract
            is_current_bid = bid == current_bid and current_bid not in (
                BidType.PASS, BidType.CONTRA, BidType.RECONTRA, None)

            if is_current_contract:
                # Bright yellow/orange border — THIS is what we're playing
                bg = QColor(200, 140, 20)
            elif is_recommended:
                bg = QColor(60, 160, 60)
            elif is_current_bid:
                # During bidding, show what's been bid so far
                bg = QColor(160, 100, 20)
            elif active:
                bg = ACTIVE_BID
            else:
                bg = INACTIVE_BID

            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(bg))
            p.drawRoundedRect(cx, cy, chip_w, chip_h, 4, 4)

            # Border for current contract
            if is_current_contract:
                p.setPen(QPen(QColor(255, 220, 50), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(cx, cy, chip_w, chip_h, 4, 4)

            lbl = BID_LABEL[bid]
            p.setFont(font)
            if is_current_contract or is_recommended:
                p.setPen(QPen(QColor(255, 255, 255)))
            elif is_current_bid:
                p.setPen(QPen(QColor(255, 230, 150)))
            elif active:
                p.setPen(QPen(TEXT))
            else:
                p.setPen(QPen(DIM))
            p.drawText(cx, cy, chip_w, chip_h, Qt.AlignmentFlag.AlignCenter, lbl)

        return y + h + 1

    def _draw_voids(self, p: QPainter, y: int, s: GameState) -> int:
        if not s.suit_voids or s.phase != Phase.PLAYING:
            return y

        # Check if there are any actual voids to show
        has_voids = any(
            voids for seat, voids in s.suit_voids.items()
            if seat != 0 and voids
        )
        if not has_voids:
            return y

        h = 26
        p.fillRect(0, y, WIN_W, h, VOID_BG)
        font = QFont("Arial", 11)
        p.setFont(font)
        p.setPen(QPen(TEXT))

        seat_labels = {1: "E", 2: "N", 3: "W"}
        parts = []
        for seat in [1, 2, 3]:
            voids = s.suit_voids.get(seat, set())
            if voids:
                void_str = "".join(SUIT_SYMBOL[s] for s in sorted(voids, key=lambda x: x.value))
                parts.append(f"{seat_labels[seat]}:{void_str}")

        text = "Voids: " + "  ".join(parts)
        p.drawText(15, y, WIN_W - 30, h, Qt.AlignmentFlag.AlignVCenter, text)
        return y + h + 1

    def _draw_tracker(self, p: QPainter, y: int, s: GameState):
        # header
        header_h = 26
        p.fillRect(0, y, WIN_W, WIN_H - y, BG)

        seen_count = len(s.seen_cards)
        total = len(ALL_CARDS)
        unseen_count = total - seen_count

        font = QFont("Arial", 12)
        p.setFont(font)
        p.setPen(QPen(DIM))
        p.drawText(15, y, WIN_W - 30, header_h, Qt.AlignmentFlag.AlignVCenter,
                   f"Card Tracker: seen {seen_count}/{total}, unseen {unseen_count}")
        y += header_h

        hand_set = set(s.hand)
        seen_set = s.seen_cards

        row_h = 28
        font_rank = QFont("Arial", 13, QFont.Weight.Bold)
        font_sym = QFont("Arial", 16, QFont.Weight.Bold)

        for suit in SUIT_ORDER:
            sym = SUIT_SYMBOL[suit]
            sc = SUIT_COLOR[suit]

            # suit symbol
            p.setFont(font_sym)
            p.setPen(QPen(sc))
            p.drawText(15, y, 30, row_h, Qt.AlignmentFlag.AlignVCenter, sym)

            # ranks
            p.setFont(font_rank)
            rx = 50
            col_w = (WIN_W - 60) // 8
            for rank in RANK_ORDER:
                card = Card(rank, suit)
                lbl = RANK_LABEL[rank]
                if card in hand_set:
                    p.setPen(QPen(GREEN))
                elif card in seen_set:
                    p.setPen(QPen(DIM))
                else:
                    p.setPen(QPen(TEXT))
                p.drawText(rx, y, col_w, row_h, Qt.AlignmentFlag.AlignCenter, lbl)
                rx += col_w

            y += row_h
