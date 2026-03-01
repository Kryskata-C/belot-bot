"""Game state model for Belot."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Suit(Enum):
    CLUBS = "clubs"       # СПАТИЯ ♣
    DIAMONDS = "diamonds" # КАРО ♦
    HEARTS = "hearts"     # КУПА ♥
    SPADES = "spades"     # ПИКА ♠


class Rank(Enum):
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "10"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"


class BidType(Enum):
    PASS = "pass"               # ПАС
    CLUBS = "clubs"             # СПАТИЯ
    DIAMONDS = "diamonds"       # КАРО
    HEARTS = "hearts"           # КУПА
    SPADES = "spades"           # ПИКА
    NO_TRUMPS = "no_trumps"     # БЕЗ КОЗ
    ALL_TRUMPS = "all_trumps"   # ВСИЧКО КОЗ
    CONTRA = "contra"           # КОНТРА x2
    RECONTRA = "recontra"       # РЕКОНТРА x4


@dataclass
class Card:
    rank: Rank
    suit: Suit

    def __hash__(self):
        return hash((self.rank, self.suit))

    def __eq__(self, other):
        return self.rank == other.rank and self.suit == other.suit

    def __repr__(self):
        symbols = {"clubs": "♣", "diamonds": "♦", "hearts": "♥", "spades": "♠"}
        return f"{self.rank.value}{symbols[self.suit.value]}"


# Full 32-card belot deck
ALL_CARDS: set[Card] = {
    Card(rank, suit) for rank in Rank for suit in Suit
}


class DeclarationType(Enum):
    TERZA = "terza"       # 3 consecutive = 20 pts
    QUARTA = "quarta"     # 4 consecutive = 50 pts
    KENTA = "kenta"       # 5 consecutive = 100 pts
    BELOT = "belot"       # K+Q of trump = 20 pts
    CARE_9 = "care_9"     # four 9s = 150 pts
    CARE_J = "care_j"     # four Js = 200 pts
    CARE = "care"         # four of other rank = 100 pts


@dataclass
class Declaration:
    type: DeclarationType
    seat: int             # 0-3
    points: int


class Phase(Enum):
    BIDDING = "bidding"
    PLAYING = "playing"
    BETWEEN_ROUNDS = "between_rounds"
    UNKNOWN = "unknown"


@dataclass
class TableCard:
    """A card on the table with who played it."""
    card: Card
    player_name: str  # e.g. "Christ8634", "Bot1"
    seat: int         # 0-3


@dataclass
class TrickRecord:
    """A completed trick."""
    cards: list[TableCard]   # 4 cards in play order
    winner_seat: int
    trump: BidType | None


@dataclass
class Recommendation:
    """AI recommendation for the player."""
    action: str              # "play" or "bid"
    card: Card | None        # recommended card to play
    bid: BidType | None      # recommended bid
    reasoning: str           # explanation shown on GUI
    confidence: float        # 0.0-1.0


@dataclass
class GameState:
    phase: Phase = Phase.UNKNOWN

    # Cards
    hand: list[Card] = field(default_factory=list)
    table_cards: list[TableCard] = field(default_factory=list)  # cards on table this trick
    seen_cards: set[Card] = field(default_factory=set)          # all cards seen so far

    # Bidding
    current_bid: BidType | None = None
    available_bids: list[BidType] = field(default_factory=list)

    # Score
    our_score: int = 0   # НИЕ
    their_score: int = 0  # ВИЕ

    # Trump & round info
    trump: BidType | None = None               # current trump suit/type
    seat_bids: dict = field(default_factory=lambda: {0: None, 1: None, 2: None, 3: None})
    trick_history: list[TrickRecord] = field(default_factory=list)
    suit_voids: dict = field(default_factory=dict)  # {seat: set(Suit)}
    recommendation: Recommendation | None = None
    our_points: int = 0      # points won this round
    their_points: int = 0    # opponent points this round
    announcer_seat: int = -1  # who made the winning bid
    dealer_seat: int = -1
    declarations: list[Declaration] = field(default_factory=list)

    @property
    def unseen_cards(self) -> set[Card]:
        """Cards not yet seen (not in hand, not played)."""
        return ALL_CARDS - self.seen_cards - set(self.hand)

    def __repr__(self):
        hand_str = ", ".join(str(c) for c in self.hand) if self.hand else "none"
        table_str = ", ".join(f"{tc.card}({tc.player_name})" for tc in self.table_cards) if self.table_cards else "none"
        return (
            f"Phase: {self.phase.value}\n"
            f"Hand: [{hand_str}]\n"
            f"Table: [{table_str}]\n"
            f"Seen: {len(self.seen_cards)}/32  Unseen: {len(self.unseen_cards)}\n"
            f"Bid: {self.current_bid}  Trump: {self.trump}\n"
            f"Score: НИЕ {self.our_score} — ВИЕ {self.their_score}\n"
            f"Round pts: Us {self.our_points} / Them {self.their_points}"
        )
