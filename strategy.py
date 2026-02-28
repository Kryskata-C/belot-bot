"""Belot AI strategy engine.

Provides bidding and play recommendations based on card tracking,
hand evaluation, and positional play logic.

Seat layout: 0=Us(South), 1=RightOpp(East), 2=Partner(North), 3=LeftOpp(West)
Teams: team1={0,2}, team2={1,3}
"""

from __future__ import annotations

from game_state import (
    GameState, Card, TableCard, TrickRecord, Recommendation,
    Rank, Suit, BidType, Phase, ALL_CARDS,
)

# ── Card value tables ────────────────────────────────────────────────

TRUMP_VALUES = {
    Rank.JACK: 20, Rank.NINE: 14, Rank.ACE: 11, Rank.TEN: 10,
    Rank.KING: 4, Rank.QUEEN: 3, Rank.EIGHT: 0, Rank.SEVEN: 0,
}
PLAIN_VALUES = {
    Rank.ACE: 11, Rank.TEN: 10, Rank.KING: 4, Rank.QUEEN: 3,
    Rank.JACK: 2, Rank.NINE: 0, Rank.EIGHT: 0, Rank.SEVEN: 0,
}
NO_TRUMP_VALUES = PLAIN_VALUES  # same point values, different rank order
ALL_TRUMP_VALUES = TRUMP_VALUES

# Strongest → weakest
TRUMP_RANK_ORDER = [
    Rank.JACK, Rank.NINE, Rank.ACE, Rank.TEN,
    Rank.KING, Rank.QUEEN, Rank.EIGHT, Rank.SEVEN,
]
PLAIN_RANK_ORDER = [
    Rank.ACE, Rank.TEN, Rank.KING, Rank.QUEEN,
    Rank.JACK, Rank.NINE, Rank.EIGHT, Rank.SEVEN,
]

LAST_TRICK_BONUS = 10
TOTAL_GAME_POINTS = 162  # all card values in a suit-trump game (excl bonus)
TOTAL_ALL_TRUMPS = 248   # 4 * 62
TOTAL_NO_TRUMPS = 120    # 4 * 30

TEAM1 = {0, 2}  # us + partner
TEAM2 = {1, 3}  # opponents

BID_SUITS = {
    BidType.CLUBS: Suit.CLUBS, BidType.DIAMONDS: Suit.DIAMONDS,
    BidType.HEARTS: Suit.HEARTS, BidType.SPADES: Suit.SPADES,
}

SUIT_SYMBOL = {
    Suit.CLUBS: "♣", Suit.DIAMONDS: "♦",
    Suit.HEARTS: "♥", Suit.SPADES: "♠",
}


def _card_value(card: Card, trump: BidType | None) -> int:
    """Point value of a card given the current contract."""
    if trump == BidType.ALL_TRUMPS:
        return ALL_TRUMP_VALUES[card.rank]
    if trump == BidType.NO_TRUMPS:
        return NO_TRUMP_VALUES[card.rank]
    trump_suit = BID_SUITS.get(trump)
    if trump_suit and card.suit == trump_suit:
        return TRUMP_VALUES[card.rank]
    return PLAIN_VALUES[card.rank]


def _is_trump_card(card: Card, trump: BidType | None) -> bool:
    if trump == BidType.ALL_TRUMPS:
        return True
    if trump == BidType.NO_TRUMPS:
        return False
    trump_suit = BID_SUITS.get(trump)
    return trump_suit is not None and card.suit == trump_suit


def _rank_strength(card: Card, trump: BidType | None) -> int:
    """Higher = stronger. Used for comparison."""
    if _is_trump_card(card, trump):
        order = TRUMP_RANK_ORDER
    else:
        order = PLAIN_RANK_ORDER
    # Reverse index: Jack(0 in list) → strength 7, Seven(7 in list) → strength 0
    try:
        return len(order) - 1 - order.index(card.rank)
    except ValueError:
        return -1


# ── Card Tracker ─────────────────────────────────────────────────────

class CardTracker:
    """Tracks played cards, remaining cards, and suit voids."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.played: dict[Card, int] = {}        # card → seat who played it
        self.suit_voids: dict[int, set[Suit]] = {i: set() for i in range(4)}
        self._hand: set[Card] = set()

    def update_hand(self, hand: list[Card]):
        self._hand = set(hand)

    def card_played(self, card: Card, seat: int):
        self.played[card] = seat

    def record_void(self, seat: int, suit: Suit):
        self.suit_voids[seat].add(suit)

    def infer_voids_from_trick(self, trick_cards: list[TableCard], trump: BidType | None):
        """If a player didn't follow the led suit, they're void in it."""
        if not trick_cards:
            return
        led_suit = trick_cards[0].card.suit
        for tc in trick_cards[1:]:
            if tc.card.suit != led_suit:
                # Player didn't follow suit → void in led_suit
                # (unless it's all trumps where all suits are "trump")
                if trump != BidType.ALL_TRUMPS:
                    self.record_void(tc.seat, led_suit)

    @property
    def played_cards(self) -> set[Card]:
        return set(self.played.keys())

    @property
    def remaining(self) -> set[Card]:
        """Cards not yet played and not in our hand."""
        return ALL_CARDS - self.played_cards - self._hand

    def remaining_in_suit(self, suit: Suit) -> list[Card]:
        return [c for c in self.remaining if c.suit == suit]

    def hand_in_suit(self, suit: Suit) -> list[Card]:
        return [c for c in self._hand if c.suit == suit]

    def is_master(self, card: Card, trump: BidType | None) -> bool:
        """Is this card the highest remaining in its suit?"""
        for c in self.remaining:
            if c.suit == card.suit and _rank_strength(c, trump) > _rank_strength(card, trump):
                return False
        # Also check our own hand
        for c in self._hand:
            if c != card and c.suit == card.suit and _rank_strength(c, trump) > _rank_strength(card, trump):
                return False
        return True

    def highest_remaining_in_suit(self, suit: Suit, trump: BidType | None) -> Card | None:
        cards = self.remaining_in_suit(suit)
        if not cards:
            return None
        return max(cards, key=lambda c: _rank_strength(c, trump))

    def count_remaining_points(self, suit: Suit, trump: BidType | None) -> int:
        return sum(_card_value(c, trump) for c in self.remaining_in_suit(suit))

    def sync_from_state(self, state: GameState):
        """Sync tracker with full game state (seen cards, table, tricks)."""
        self.update_hand(state.hand)
        # Record all seen cards that aren't in hand as played
        for card in state.seen_cards:
            if card not in self._hand and card not in self.played:
                self.played[card] = -1  # seat unknown for historically seen

        # Update from table cards (we know the seat)
        for tc in state.table_cards:
            self.played[tc.card] = tc.seat

        # Update from trick history
        for trick in state.trick_history:
            for tc in trick.cards:
                self.played[tc.card] = tc.seat
            self.infer_voids_from_trick(trick.cards, trick.trump)

        # Infer voids from current trick too
        if state.table_cards:
            self.infer_voids_from_trick(state.table_cards, state.trump)


# ── Bidding Advisor ──────────────────────────────────────────────────

# Bidding strength thresholds
BID_THRESHOLD = 42  # minimum score to recommend bidding

def _evaluate_suit_trump(hand: list[Card], trump_suit: Suit) -> tuple[float, str]:
    """Evaluate hand strength for a suit-trump contract. Returns (score, reasoning)."""
    trumps = [c for c in hand if c.suit == trump_suit]
    non_trumps = [c for c in hand if c.suit != trump_suit]
    reasons = []

    score = 0.0

    # Trump strength: J=+8, 9=+6, A=+5, 10=+3, K=+2, Q=+1
    trump_strength_map = {
        Rank.JACK: 8, Rank.NINE: 6, Rank.ACE: 5, Rank.TEN: 3,
        Rank.KING: 2, Rank.QUEEN: 1, Rank.EIGHT: 0, Rank.SEVEN: 0,
    }
    trump_strength = sum(trump_strength_map[c.rank] for c in trumps)
    score += trump_strength

    # Trump length bonus (more trumps = better control)
    trump_len = len(trumps)
    if trump_len >= 5:
        score += 15
        reasons.append(f"{trump_len} trumps")
    elif trump_len >= 4:
        score += 8
        reasons.append(f"{trump_len} trumps")
    elif trump_len >= 3:
        score += 3
        reasons.append(f"{trump_len} trumps")
    elif trump_len <= 1:
        score -= 15  # too few trumps

    # Trump honors
    trump_ranks = {c.rank for c in trumps}
    if Rank.JACK in trump_ranks:
        reasons.append("J козов")
    if Rank.NINE in trump_ranks:
        reasons.append("9 козов")
    if Rank.JACK in trump_ranks and Rank.NINE in trump_ranks:
        score += 5  # J+9 combo

    # Belot bonus (K+Q of trump)
    if Rank.KING in trump_ranks and Rank.QUEEN in trump_ranks:
        score += 10
        reasons.append("Белот")

    # Side aces
    side_aces = sum(1 for c in non_trumps if c.rank == Rank.ACE)
    score += side_aces * 6
    if side_aces:
        reasons.append(f"{side_aces} side A")

    # Side A-10 combos
    side_suits: dict[Suit, set[Rank]] = {}
    for c in non_trumps:
        side_suits.setdefault(c.suit, set()).add(c.rank)
    for suit, ranks in side_suits.items():
        if Rank.ACE in ranks and Rank.TEN in ranks:
            score += 5
            reasons.append(f"A-10{SUIT_SYMBOL[suit]}")

    # Void suits (can trump opponents' winners)
    all_suits = {Suit.CLUBS, Suit.DIAMONDS, Suit.HEARTS, Suit.SPADES}
    hand_suits = {c.suit for c in hand}
    void_suits = all_suits - hand_suits
    for vs in void_suits:
        if vs != trump_suit:
            score += 4
            reasons.append(f"void {SUIT_SYMBOL[vs]}")

    sym = SUIT_SYMBOL[trump_suit]
    reason_str = f"{sym}: " + ", ".join(reasons) if reasons else f"{sym}: weak"
    return score, reason_str


def _evaluate_all_trumps(hand: list[Card]) -> tuple[float, str]:
    """Evaluate hand strength for all-trumps contract."""
    score = 0.0
    reasons = []

    jacks = [c for c in hand if c.rank == Rank.JACK]
    nines = [c for c in hand if c.rank == Rank.NINE]

    jack_count = len(jacks)
    nine_count = len(nines)

    # Jacks are king in all trumps
    score += jack_count * 12
    score += nine_count * 7

    if jack_count >= 4:
        score += 40  # Карета of Jacks = 200 points!
        reasons.append("4 Jacks! Карета")
    elif jack_count >= 3:
        score += 20
        reasons.append(f"{jack_count} Jacks")
    elif jack_count >= 2:
        score += 5
        reasons.append(f"{jack_count} Jacks")

    if nine_count >= 3:
        score += 10
        reasons.append(f"{nine_count} Nines")
    elif nine_count >= 2:
        score += 3
        reasons.append(f"{nine_count} Nines")

    # Aces still useful
    aces = sum(1 for c in hand if c.rank == Rank.ACE)
    score += aces * 3

    # Long suits help in all trumps
    suit_counts: dict[Suit, int] = {}
    for c in hand:
        suit_counts[c.suit] = suit_counts.get(c.suit, 0) + 1
    for suit, count in suit_counts.items():
        if count >= 4:
            score += 4
        if count >= 5:
            score += 6

    # Belot bonuses (K+Q of any suit = 20 each)
    for suit in [Suit.CLUBS, Suit.DIAMONDS, Suit.HEARTS, Suit.SPADES]:
        suit_cards = {c.rank for c in hand if c.suit == suit}
        if Rank.KING in suit_cards and Rank.QUEEN in suit_cards:
            score += 5
            reasons.append(f"Белот{SUIT_SYMBOL[suit]}")

    reason_str = "ВК: " + ", ".join(reasons) if reasons else "ВК: weak"
    return score, reason_str


def _evaluate_no_trumps(hand: list[Card]) -> tuple[float, str]:
    """Evaluate hand strength for no-trumps contract."""
    score = 0.0
    reasons = []

    aces = [c for c in hand if c.rank == Rank.ACE]
    ace_count = len(aces)
    score += ace_count * 10

    if ace_count >= 4:
        score += 20
        reasons.append("4 Aces!")
    elif ace_count >= 3:
        score += 10
        reasons.append(f"{ace_count} Aces")
    elif ace_count >= 2:
        reasons.append(f"{ace_count} Aces")

    # A-10 combos are very strong in no-trump
    suit_ranks: dict[Suit, set[Rank]] = {}
    for c in hand:
        suit_ranks.setdefault(c.suit, set()).add(c.rank)
    for suit, ranks in suit_ranks.items():
        if Rank.ACE in ranks and Rank.TEN in ranks:
            score += 8
            reasons.append(f"A-10{SUIT_SYMBOL[suit]}")

    # Long suits
    suit_counts: dict[Suit, int] = {}
    for c in hand:
        suit_counts[c.suit] = suit_counts.get(c.suit, 0) + 1
    for suit, count in suit_counts.items():
        if count >= 4 and Rank.ACE in suit_ranks.get(suit, set()):
            score += 5
            reasons.append(f"long {SUIT_SYMBOL[suit]}")

    # Tens without aces are risky
    tens_without_ace = sum(
        1 for c in hand
        if c.rank == Rank.TEN and Rank.ACE not in suit_ranks.get(c.suit, set())
    )
    score -= tens_without_ace * 3

    # No trump is risky — higher threshold needed
    score -= 5

    reason_str = "БК: " + ", ".join(reasons) if reasons else "БК: weak"
    return score, reason_str


# Bid hierarchy: higher index = higher bid
_BID_HIERARCHY = [
    BidType.CLUBS, BidType.DIAMONDS, BidType.HEARTS, BidType.SPADES,
    BidType.NO_TRUMPS, BidType.ALL_TRUMPS,
]

CONTRA_THRESHOLD = 35  # how strong our hand must be to contra their contract


def _evaluate_contra(hand: list[Card], their_bid: BidType) -> tuple[float, str]:
    """Evaluate whether to contra the opponents' bid."""
    score = 0.0
    reasons = []

    if their_bid in BID_SUITS:
        # They bid a suit trump — how strong are WE in that suit?
        trump_suit = BID_SUITS[their_bid]
        our_trumps = [c for c in hand if c.suit == trump_suit]
        trump_ranks = {c.rank for c in our_trumps}

        # Having J or 9 of their trump is great for us (we hold their key cards)
        if Rank.JACK in trump_ranks:
            score += 15
            reasons.append("J козов (hold)")
        if Rank.NINE in trump_ranks:
            score += 10
            reasons.append("9 козов (hold)")

        # Side aces = sure tricks for us
        side_aces = sum(1 for c in hand if c.rank == Rank.ACE and c.suit != trump_suit)
        score += side_aces * 7
        if side_aces:
            reasons.append(f"{side_aces} side Aces")

        # Long off-suits with aces
        suit_counts: dict[Suit, int] = {}
        for c in hand:
            suit_counts[c.suit] = suit_counts.get(c.suit, 0) + 1
        for suit, count in suit_counts.items():
            if suit != trump_suit and count >= 4:
                score += 4
                reasons.append(f"long {SUIT_SYMBOL[suit]}")

    elif their_bid == BidType.ALL_TRUMPS:
        # They bid all trumps — our Jacks and Nines hurt them
        jacks = sum(1 for c in hand if c.rank == Rank.JACK)
        nines = sum(1 for c in hand if c.rank == Rank.NINE)
        score += jacks * 12
        score += nines * 6
        if jacks >= 2:
            reasons.append(f"{jacks} Jacks (hold)")
        if nines >= 2:
            reasons.append(f"{nines} Nines")

    elif their_bid == BidType.NO_TRUMPS:
        # They bid no trumps — our Aces dominate
        aces = sum(1 for c in hand if c.rank == Rank.ACE)
        score += aces * 10
        if aces >= 2:
            reasons.append(f"{aces} Aces")

    reason_str = "К: " + ", ".join(reasons) if reasons else "К: weak hand"
    return score, reason_str


def evaluate_bid(
    hand: list[Card],
    current_bid: BidType | None = None,
    announcer_seat: int = -1,
) -> Recommendation:
    """Evaluate what to bid given the current hand and bidding context.

    In Belot, bidding happens with only 5 cards (3 more are dealt after).
    Thresholds are scaled to hand size.

    Args:
        hand: Our cards (typically 5 during bidding)
        current_bid: What's already been bid (None or PASS = no bid yet)
        announcer_seat: Who made the current bid (-1 = nobody)
    """
    if not hand:
        return Recommendation("bid", None, BidType.PASS, "No cards", 0.0)

    # Scale threshold to hand size: with 5 cards scores are naturally lower
    hand_size = len(hand)
    threshold = BID_THRESHOLD * hand_size / 8  # ~26 for 5 cards, 42 for 8
    contra_thresh = CONTRA_THRESHOLD * hand_size / 8

    # Determine if someone already bid a real contract
    has_active_bid = (
        current_bid is not None
        and current_bid not in (BidType.PASS, BidType.CONTRA, BidType.RECONTRA)
    )

    # If opponents bid, we can consider contra
    opponent_bid = has_active_bid and announcer_seat in TEAM2

    # Evaluate all contract types
    scores: dict[BidType, tuple[float, str]] = {}
    for bid, suit in BID_SUITS.items():
        scores[bid] = _evaluate_suit_trump(hand, suit)
    scores[BidType.ALL_TRUMPS] = _evaluate_all_trumps(hand)
    scores[BidType.NO_TRUMPS] = _evaluate_no_trumps(hand)

    if has_active_bid:
        # --- Someone already bid: we can only bid higher, contra, or pass ---

        # Filter to only bids higher than the current one
        try:
            current_idx = _BID_HIERARCHY.index(current_bid)
        except ValueError:
            current_idx = len(_BID_HIERARCHY)  # current bid not in hierarchy

        higher_bids = {
            bid: scores[bid] for bid in scores
            if bid in _BID_HIERARCHY
            and _BID_HIERARCHY.index(bid) > current_idx
        }

        # Evaluate contra if opponent bid
        contra_score = 0.0
        contra_reason = ""
        if opponent_bid:
            contra_score, contra_reason = _evaluate_contra(hand, current_bid)

        # Find best available option
        best_higher = None
        best_higher_score = -1.0
        best_higher_reason = ""
        for bid, (sc, reason) in higher_bids.items():
            if sc > best_higher_score and sc >= threshold:
                best_higher = bid
                best_higher_score = sc
                best_higher_reason = reason

        # Decision: higher bid vs contra vs pass
        if best_higher and best_higher_score > contra_score:
            confidence = min(1.0, best_higher_score / 100.0)
            return Recommendation(
                "bid", None, best_higher, best_higher_reason, confidence,
            )
        elif opponent_bid and contra_score >= contra_thresh:
            confidence = min(1.0, contra_score / 70.0)
            return Recommendation(
                "bid", None, BidType.CONTRA, contra_reason, confidence,
            )
        else:
            # Pass — mention why
            bid_label = {
                BidType.CLUBS: "♣", BidType.DIAMONDS: "♦",
                BidType.HEARTS: "♥", BidType.SPADES: "♠",
                BidType.NO_TRUMPS: "БК", BidType.ALL_TRUMPS: "ВК",
            }.get(current_bid, str(current_bid))
            return Recommendation(
                "bid", None, BidType.PASS,
                f"ПАС (vs {bid_label})",
                0.7,
            )
    else:
        # --- No active bid yet: evaluate freely ---
        best_bid = max(scores, key=lambda b: scores[b][0])
        best_score, best_reason = scores[best_bid]

        if best_score >= threshold:
            confidence = min(1.0, best_score / 100.0)
            return Recommendation(
                "bid", None, best_bid, best_reason, confidence,
            )
        else:
            return Recommendation(
                "bid", None, BidType.PASS,
                f"ПАС (best: {best_reason}, score={best_score:.0f})",
                0.7,
            )


# ── Play Advisor ─────────────────────────────────────────────────────

def _get_legal_plays(
    hand: list[Card],
    table_cards: list[TableCard],
    trump: BidType | None,
) -> list[Card]:
    """Determine legal card plays following Belot rules."""
    if not hand:
        return []
    if not table_cards:
        # Leading: can play anything
        return list(hand)

    led_suit = table_cards[0].card.suit
    trump_suit = BID_SUITS.get(trump)
    is_all_trumps = trump == BidType.ALL_TRUMPS

    # Cards that follow the led suit
    follow = [c for c in hand if c.suit == led_suit]

    if follow:
        if is_all_trumps or (trump_suit and led_suit == trump_suit):
            # Led suit is trump — must play higher trump if possible
            best_on_table = max(
                (tc.card for tc in table_cards if tc.card.suit == led_suit),
                key=lambda c: _rank_strength(c, trump),
                default=None,
            )
            if best_on_table:
                higher = [
                    c for c in follow
                    if _rank_strength(c, trump) > _rank_strength(best_on_table, trump)
                ]
                if higher:
                    return higher
        return follow

    # Can't follow suit
    if trump == BidType.NO_TRUMPS:
        # No trump obligation — play anything
        return list(hand)

    # Must trump if possible
    trumps_in_hand = [c for c in hand if _is_trump_card(c, trump)]
    if trumps_in_hand:
        # Check if must overtrump
        table_trumps = [
            tc.card for tc in table_cards if _is_trump_card(tc.card, trump)
        ]
        if table_trumps:
            best_table_trump = max(table_trumps, key=lambda c: _rank_strength(c, trump))
            higher_trumps = [
                c for c in trumps_in_hand
                if _rank_strength(c, trump) > _rank_strength(best_table_trump, trump)
            ]
            if higher_trumps:
                return higher_trumps
            # If partner is winning with the best trump, can play any trump
            if table_cards:
                winner_idx = _current_trick_winner_idx(table_cards, trump)
                winner_seat = table_cards[winner_idx].seat
                if winner_seat in TEAM1:
                    return trumps_in_hand
        return trumps_in_hand

    # Can't follow suit AND can't trump — play anything
    return list(hand)


def _current_trick_winner_idx(table_cards: list[TableCard], trump: BidType | None) -> int:
    """Index of the currently winning card on the table."""
    if not table_cards:
        return 0
    led_suit = table_cards[0].card.suit
    trump_suit = BID_SUITS.get(trump)
    is_all_trumps = trump == BidType.ALL_TRUMPS

    best_idx = 0
    for i in range(1, len(table_cards)):
        c = table_cards[i].card
        b = table_cards[best_idx].card

        c_is_trump = _is_trump_card(c, trump)
        b_is_trump = _is_trump_card(b, trump)

        if c_is_trump and not b_is_trump:
            best_idx = i
        elif not c_is_trump and b_is_trump:
            pass
        elif c_is_trump and b_is_trump:
            if _rank_strength(c, trump) > _rank_strength(b, trump):
                best_idx = i
        else:
            # Both plain
            if c.suit == led_suit and b.suit != led_suit:
                best_idx = i
            elif c.suit == led_suit and b.suit == led_suit:
                if _rank_strength(c, trump) > _rank_strength(b, trump):
                    best_idx = i
    return best_idx


def _trick_points(table_cards: list[TableCard], trump: BidType | None) -> int:
    """Total point value of cards currently on the table."""
    return sum(_card_value(tc.card, trump) for tc in table_cards)


def recommend_play(
    hand: list[Card],
    table_cards: list[TableCard],
    trump: BidType | None,
    tracker: CardTracker,
    trick_history: list[TrickRecord],
) -> Recommendation:
    """Recommend best card to play."""
    if not hand:
        return Recommendation("play", None, None, "No cards", 0.0)

    legal = _get_legal_plays(hand, table_cards, trump)
    if not legal:
        return Recommendation("play", None, None, "No legal plays", 0.0)
    if len(legal) == 1:
        return Recommendation(
            "play", legal[0], None,
            f"Only legal play",
            1.0,
        )

    position = len(table_cards)  # 0=lead, 1=2nd, 2=3rd, 3=4th

    if position == 0:
        return _recommend_lead(legal, hand, trump, tracker)
    else:
        return _recommend_follow(legal, hand, table_cards, trump, tracker, position)


def _recommend_lead(
    legal: list[Card],
    hand: list[Card],
    trump: BidType | None,
    tracker: CardTracker,
) -> Recommendation:
    """Recommend a card when leading a new trick."""
    candidates: list[tuple[Card, float, str]] = []

    trump_suit = BID_SUITS.get(trump)
    is_all_trumps = trump == BidType.ALL_TRUMPS

    for card in legal:
        score = 0.0
        reasons = []

        is_trump = _is_trump_card(card, trump)
        is_master = tracker.is_master(card, trump)

        if is_master:
            # Masters are excellent leads — guaranteed to win
            points = _card_value(card, trump)
            score += 30 + points
            reasons.append("suit master")
            if points >= 10:
                reasons.append(f"+{points}pts")
        elif is_trump:
            # Leading trump to draw out opponents' trumps
            our_trumps = [c for c in hand if _is_trump_card(c, trump)]
            remaining_trumps = [
                c for c in tracker.remaining
                if _is_trump_card(c, trump)
            ]
            if len(our_trumps) > len(remaining_trumps) / 2:
                # We have trump majority — good to lead trump
                score += 20
                reasons.append("trump draw")
                # Lead high trumps first
                score += _rank_strength(card, trump) * 2
            else:
                # Don't waste trumps when we're short
                score += 5
                reasons.append("save trump")

        if not is_trump and not is_master:
            # Non-trump, non-master lead
            remaining = tracker.remaining_in_suit(card.suit)
            value = _card_value(card, trump)

            # Prefer leading from long suits
            suit_length = len([c for c in hand if c.suit == card.suit])
            score += suit_length * 2

            # Check if opponents are void in this suit (they could trump)
            opp_void = (
                card.suit in tracker.suit_voids.get(1, set()) or
                card.suit in tracker.suit_voids.get(3, set())
            )
            if opp_void and not is_all_trumps:
                score -= 15
                reasons.append("opp void!")

            # Check if partner is void (partner can trump for us)
            partner_void = card.suit in tracker.suit_voids.get(2, set())
            if partner_void and trump_suit and not is_all_trumps:
                score += 8
                reasons.append("partner trumps")

            # Prefer low cards when not master (don't give away points)
            if value >= 10:
                score -= 8
                reasons.append(f"risky {value}pts")
            else:
                score += 5
                reasons.append("low lead")

        if not reasons:
            reasons.append("neutral")
        candidates.append((card, score, ", ".join(reasons)))

    candidates.sort(key=lambda x: x[1], reverse=True)
    best_card, best_score, best_reason = candidates[0]
    confidence = min(1.0, max(0.3, best_score / 50.0))

    return Recommendation("play", best_card, None, best_reason, confidence)


def _recommend_follow(
    legal: list[Card],
    hand: list[Card],
    table_cards: list[TableCard],
    trump: BidType | None,
    tracker: CardTracker,
    position: int,
) -> Recommendation:
    """Recommend a card when following (2nd, 3rd, or 4th to play)."""
    winner_idx = _current_trick_winner_idx(table_cards, trump)
    winner_seat = table_cards[winner_idx].seat
    partner_winning = winner_seat in TEAM1
    trick_pts = _trick_points(table_cards, trump)
    led_suit = table_cards[0].card.suit

    candidates: list[tuple[Card, float, str]] = []

    for card in legal:
        score = 0.0
        reasons = []
        value = _card_value(card, trump)
        can_follow_suit = card.suit == led_suit
        is_trump = _is_trump_card(card, trump)

        # Would this card win the trick?
        test_table = list(table_cards) + [TableCard(card, "us", 0)]
        new_winner_idx = _current_trick_winner_idx(test_table, trump)
        would_win = new_winner_idx == len(test_table) - 1
        total_pts = trick_pts + value

        if position == 3:
            # FOURTH (last to play) — perfect information
            if partner_winning:
                # Partner wins: dump highest point card to give partner points
                score += value * 3
                reasons.append(f"feed partner +{value}")
            else:
                # Opponent winning
                if would_win:
                    # We can take it — worth it if enough points
                    score += 25 + total_pts
                    reasons.append(f"win trick (+{total_pts}pts)")
                else:
                    # Can't win — dump lowest value card
                    score += (20 - value) * 2
                    reasons.append("dump low")

        elif position == 2:
            # THIRD (partner already played)
            if partner_winning:
                # Partner is winning — play low or feed points
                if would_win:
                    # We'd overtake partner — only if adds significant value
                    score += value * 1.5
                    reasons.append("support partner")
                else:
                    score += value * 2  # feed points to partner
                    reasons.append(f"feed +{value}")
            else:
                # Opponent winning
                if would_win:
                    score += 20 + total_pts
                    reasons.append(f"beat opp (+{total_pts})")
                else:
                    # Can't win — dump cheap
                    score += (15 - value) * 2
                    reasons.append("can't beat, dump low")

        elif position == 1:
            # SECOND (after left opponent led)
            if would_win:
                # Can win — but partner still to play
                if is_trump and not _is_trump_card(table_cards[0].card, trump):
                    # Trumping — good if trick is valuable
                    if trick_pts >= 10 or total_pts >= 15:
                        score += 15 + total_pts
                        reasons.append(f"trump in (+{total_pts})")
                    else:
                        score += 5
                        reasons.append("trump (low value)")
                else:
                    # Can win by following suit
                    if tracker.is_master(card, trump):
                        score += 25
                        reasons.append("master, cash it")
                    else:
                        # Win cheaply — partner hasn't played yet
                        score += 10 - value * 0.5
                        reasons.append("win, let partner help")
            else:
                # Can't win — play low and hope partner takes it
                score += (15 - value) * 2
                reasons.append("play low for partner")

        if not reasons:
            reasons.append("neutral")
        candidates.append((card, score, ", ".join(reasons)))

    candidates.sort(key=lambda x: x[1], reverse=True)
    best_card, best_score, best_reason = candidates[0]
    confidence = min(1.0, max(0.3, best_score / 50.0))

    return Recommendation("play", best_card, None, best_reason, confidence)


# ── Point Counter ────────────────────────────────────────────────────

def count_points(trick_history: list[TrickRecord], trump: BidType | None) -> tuple[int, int]:
    """Count points won by each team. Returns (our_points, their_points)."""
    our_pts = 0
    their_pts = 0
    for trick in trick_history:
        trick_value = sum(_card_value(tc.card, trump) for tc in trick.cards)
        if trick.winner_seat in TEAM1:
            our_pts += trick_value
        else:
            their_pts += trick_value

    # Last trick bonus
    if trick_history:
        last_winner = trick_history[-1].winner_seat
        # Only add if all 8 tricks played
        if len(trick_history) == 8:
            if last_winner in TEAM1:
                our_pts += LAST_TRICK_BONUS
            else:
                their_pts += LAST_TRICK_BONUS

    return our_pts, their_pts


def remaining_points(tracker: CardTracker, trump: BidType | None) -> int:
    """Points still in play (remaining cards + our hand)."""
    pts = 0
    for card in tracker.remaining:
        pts += _card_value(card, trump)
    for card in tracker._hand:
        pts += _card_value(card, trump)
    return pts


# ── BelotBrain — Main Orchestrator ───────────────────────────────────

class BelotBrain:
    """Top-level AI that produces recommendations from game state."""

    def __init__(self):
        self.tracker = CardTracker()
        self._prev_phase: Phase = Phase.UNKNOWN
        self._prev_hand_count: int = 0
        self._last_recommendation: Recommendation | None = None

    def update(self, state: GameState) -> Recommendation | None:
        """Analyze game state and produce a recommendation."""
        # Reset on new round
        if (state.phase == Phase.BIDDING and self._prev_phase != Phase.BIDDING
                and self._prev_phase != Phase.UNKNOWN):
            self.reset_round()
        if state.phase == Phase.BETWEEN_ROUNDS:
            if self._prev_phase != Phase.BETWEEN_ROUNDS:
                self.reset_round()
            self._prev_phase = state.phase
            return None

        # Sync tracker
        self.tracker.sync_from_state(state)

        # Update state with tracked info
        state.suit_voids = dict(self.tracker.suit_voids)
        our_pts, their_pts = count_points(state.trick_history, state.trump)
        state.our_points = our_pts
        state.their_points = their_pts

        rec = None
        if state.phase == Phase.BIDDING:
            rec = evaluate_bid(
                state.hand,
                current_bid=state.current_bid,
                announcer_seat=state.announcer_seat,
            )
        elif state.phase == Phase.PLAYING:
            hand_count = len(state.hand)
            table_count = len(state.table_cards)

            # If our hand just shrank (we played a card), keep the old
            # recommendation until the next trick state is clear.
            # This prevents stale reads where the table hasn't updated yet.
            if (hand_count < self._prev_hand_count
                    and hand_count > 0
                    and self._last_recommendation is not None):
                rec = self._last_recommendation
            else:
                rec = recommend_play(
                    state.hand, state.table_cards, state.trump,
                    self.tracker, state.trick_history,
                )
                # Debug: log when recommending a non-follow-suit card
                if rec and rec.card and state.table_cards:
                    led_suit = state.table_cards[0].card.suit
                    has_suit = any(c.suit == led_suit for c in state.hand)
                    if has_suit and rec.card.suit != led_suit:
                        print(f"WARNING: recommending {rec.card} but have "
                              f"{led_suit.value} cards! hand={state.hand} "
                              f"table={[tc.card for tc in state.table_cards]} "
                              f"trump={state.trump}")

        self._prev_phase = state.phase
        self._prev_hand_count = len(state.hand)
        if rec is not None:
            self._last_recommendation = rec
        return rec

    def reset_round(self):
        self.tracker.reset()
        self._last_recommendation = None
