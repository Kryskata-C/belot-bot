"""Game state detector via JavaScript injection into Safari.

Reads the Phaser game internals directly — no OCR or template matching needed.
"""

from __future__ import annotations

import json
import math
from safari_js import run_js
from game_state import (
    GameState, Card, TableCard, TrickRecord,
    Rank, Suit, BidType, Phase,
)

# Frame name char → our enums
_RANK_MAP = {
    "7": Rank.SEVEN, "8": Rank.EIGHT, "9": Rank.NINE, "t": Rank.TEN,
    "j": Rank.JACK, "q": Rank.QUEEN, "k": Rank.KING, "a": Rank.ACE,
}
_SUIT_MAP = {
    "c": Suit.CLUBS, "d": Suit.DIAMONDS, "h": Suit.HEARTS, "s": Suit.SPADES,
}

# Belot.bg announce codes → BidType (bidding phase: 1-6)
_ANNOUNCE_MAP = {
    1: BidType.CLUBS, 2: BidType.DIAMONDS, 3: BidType.HEARTS, 4: BidType.SPADES,
    5: BidType.NO_TRUMPS, 6: BidType.ALL_TRUMPS,
}

# Belot.bg currentAnnounce codes → trump BidType (playing phase)
# Small codes (5-10): legacy/alternate encoding
_TRUMP_MAP = {
    5: BidType.CLUBS, 6: BidType.DIAMONDS,
    7: BidType.HEARTS, 8: BidType.SPADES,
    9: BidType.NO_TRUMPS, 10: BidType.ALL_TRUMPS,
    11: BidType.CONTRA, 12: BidType.RECONTRA,
}
# Large codes (100+): actual codes seen during play
# Pattern: 100 + suit_index * 5 (index: clubs=0, dia=1, hearts=2, spades=3, NT=4, AT=5)
_TRUMP_MAP_LARGE = {
    100: BidType.CLUBS, 105: BidType.DIAMONDS,
    110: BidType.HEARTS, 115: BidType.SPADES,
    120: BidType.NO_TRUMPS, 125: BidType.ALL_TRUMPS,
}


def _decode_announce(code: int) -> BidType | None:
    """Try all known announce code mappings."""
    if code in _TRUMP_MAP_LARGE:
        return _TRUMP_MAP_LARGE[code]
    if code in _TRUMP_MAP:
        return _TRUMP_MAP[code]
    if code in _ANNOUNCE_MAP:
        return _ANNOUNCE_MAP[code]
    return None


_EXTRACT_JS = r"""
(function() {
    var pg = (typeof Phaser !== 'undefined' && Phaser.GAMES && Phaser.GAMES[0]);
    if (!pg) return JSON.stringify({error: 'no_phaser'});

    var m = pg.state.states.main;
    if (!m) return JSON.stringify({error: 'no_main'});

    var result = {};

    // Hand cards (seat 0 = player)
    var hand = m.playerSeats[0].playersHand;
    result.hand = [];
    if (hand && hand.children) {
        for (var i = 0; i < hand.children.length; i++) {
            var c = hand.children[i];
            if (c.frameName && c.frameName.length === 2) {
                result.hand.push(c.frameName);
            }
        }
    }

    // Table cards (current trick)
    result.table = [];
    result.starting_player = m.startingPlayer || 0;
    var seatNames = [];
    for (var s = 0; s < 4; s++) {
        seatNames.push(m.playerSeats[s].playerData.name);
    }
    result.seat_names = seatNames;

    if (m.trickGraphic && m.trickGraphic.children) {
        for (var i = 0; i < m.trickGraphic.children.length; i++) {
            var c = m.trickGraphic.children[i];
            if (c.frameName && c.frameName.length === 2) {
                var wx = 0, wy = 0;
                if (c.world) { wx = Math.round(c.world.x || 0); wy = Math.round(c.world.y || 0); }
                if (wx === 0 && wy === 0 && c.worldPosition) {
                    wx = Math.round(c.worldPosition.x || 0);
                    wy = Math.round(c.worldPosition.y || 0);
                }
                if (wx === 0 && wy === 0) {
                    wx = Math.round(c.x || 0);
                    wy = Math.round(c.y || 0);
                }
                result.table.push({
                    frame: c.frameName,
                    x: wx, y: wy,
                    idx: i
                });
            }
        }
    }

    // Score from text objects
    result.our_score = 0;
    result.their_score = 0;
    var world = pg.world;
    function findScore(obj, depth) {
        if (depth > 5) return;
        if (obj.text && typeof obj.text === 'string') {
            var lines = obj.text.split('\n');
            if (lines[0].trim() === '\u041D\u0418\u0415' && lines.length > 1) {
                result.our_score = parseInt(lines[1].trim()) || 0;
            }
            if (lines[0].trim() === '\u0412\u0418\u0415' && lines.length > 1) {
                result.their_score = parseInt(lines[1].trim()) || 0;
            }
        }
        if (obj.children) {
            for (var i = 0; i < obj.children.length; i++) findScore(obj.children[i], depth + 1);
        }
    }
    findScore(world, 0);

    // Current announce/bid & trump
    result.announce = m.currentAnnounce || 0;
    result.announce_variation = m.currentAnnounceVariation || 0;

    // Deep probe: find ALL announce/trump/bid related properties on m
    result.announce_props = {};
    var searchKeys = ['announce', 'Announce', 'trump', 'Trump', 'bid', 'Bid',
                      'contract', 'Contract', 'game_type', 'gameType', 'suit'];
    for (var key in m) {
        if (typeof m[key] === 'number' || typeof m[key] === 'string') {
            for (var sk = 0; sk < searchKeys.length; sk++) {
                if (key.toLowerCase().indexOf(searchKeys[sk].toLowerCase()) !== -1) {
                    result.announce_props[key] = m[key];
                }
            }
        }
    }

    // Check for visible announce icons/sprites on the UI
    result.visible_icons = [];
    function findIcons(obj, path, depth) {
        if (depth > 4) return;
        if (obj.frameName && obj.visible !== false && obj.alpha > 0) {
            var fn = obj.frameName;
            if (fn.indexOf('announce') !== -1 || fn.indexOf('icon') !== -1 ||
                fn.indexOf('trump') !== -1 || fn.indexOf('suit') !== -1 ||
                fn.indexOf('bid') !== -1) {
                result.visible_icons.push({path: path, frame: fn});
            }
        }
        if (obj.key && typeof obj.key === 'string' && obj.visible !== false) {
            var k = obj.key;
            if (k.indexOf('announce') !== -1 || k.indexOf('icon') !== -1 ||
                k.indexOf('trump') !== -1) {
                result.visible_icons.push({path: path, key: k, frame: obj.frameName || ''});
            }
        }
        if (obj.children) {
            for (var i = 0; i < obj.children.length; i++) {
                findIcons(obj.children[i], path + '[' + i + ']', depth + 1);
            }
        }
    }
    findIcons(pg.world, 'world', 0);

    // Also check each playerSeat for announce-related data
    result.seat_announces = [];
    for (var s = 0; s < 4; s++) {
        var ps = m.playerSeats[s];
        var info = {seat: s};
        for (var key in ps) {
            if (typeof ps[key] === 'number' || typeof ps[key] === 'string') {
                var kl = key.toLowerCase();
                if (kl.indexOf('announce') !== -1 || kl.indexOf('bid') !== -1 ||
                    kl.indexOf('trump') !== -1 || kl.indexOf('game') !== -1) {
                    info[key] = ps[key];
                }
            }
        }
        if (Object.keys(info).length > 1) result.seat_announces.push(info);
    }

    // Announcer and dealer
    result.announcer_seat = (typeof m.currentTopAnnouncer === 'number') ? m.currentTopAnnouncer : -1;
    result.dealer_seat = (typeof m.currentDealer === 'number') ? m.currentDealer : -1;

    // Card counts per seat (critical for seat detection)
    result.card_counts = [];
    for (var s = 0; s < 4; s++) {
        var h = m.playerSeats[s].playersHand;
        result.card_counts.push(h && h.children ? h.children.length : 0);
    }

    // Phase detection helpers
    result.trick_count = (m.trickGraphic && m.trickGraphic.children) ? m.trickGraphic.children.length : 0;
    result.hand_count = result.hand.length;

    // Detect announce/bidding UI visibility
    result.has_announce_ui = false;
    var announceProps = ['announceGroup', 'announcePopup', 'announce_popup',
                         'bidGroup', 'announceBar', 'announceButtons'];
    for (var ap = 0; ap < announceProps.length; ap++) {
        var ag = m[announceProps[ap]];
        if (ag && ag.visible !== false && ag.alpha > 0) {
            result.has_announce_ui = true;
            break;
        }
    }
    if (!result.has_announce_ui && m.announcePopupIcons && m.announcePopupIcons.visible) {
        result.has_announce_ui = true;
    }

    // Fallback: scan ALL m properties for visible groups with bid-related children
    if (!result.has_announce_ui) {
        for (var key in m) {
            try {
                var obj = m[key];
                if (!obj || typeof obj !== 'object' || obj === null) continue;
                if (obj.visible === false) continue;
                if (!obj.children || obj.children.length < 3) continue;
                var bidChildCount = 0;
                for (var ci = 0; ci < Math.min(obj.children.length, 20); ci++) {
                    var ch = obj.children[ci];
                    if (!ch || ch.visible === false) continue;
                    var fn = String(ch.frameName || '').toLowerCase();
                    if (fn.indexOf('club') !== -1 || fn.indexOf('diamond') !== -1 ||
                        fn.indexOf('heart') !== -1 || fn.indexOf('spade') !== -1 ||
                        fn.indexOf('pass') !== -1 || fn.indexOf('contra') !== -1 ||
                        fn.indexOf('trump') !== -1 || fn.indexOf('announce') !== -1 ||
                        fn.indexOf('bid') !== -1) {
                        bidChildCount++;
                    }
                }
                if (bidChildCount >= 2) {
                    result.has_announce_ui = true;
                    result.announce_ui_key = key;
                    break;
                }
            } catch(e) {}
        }
    }

    // Look for bid/announce history arrays on m
    result.announce_history = [];
    var historyKeys = ['announces', 'announceHistory', 'bidHistory', 'roundAnnounces',
                       'allAnnounces', 'bids', 'announcements', 'playerAnnounces'];
    for (var hi = 0; hi < historyKeys.length; hi++) {
        var arr = m[historyKeys[hi]];
        if (arr && Array.isArray(arr) && arr.length > 0) {
            result.announce_history = [];
            for (var ai = 0; ai < arr.length; ai++) {
                var item = arr[ai];
                if (typeof item === 'number') {
                    result.announce_history.push({value: item});
                } else if (typeof item === 'object' && item !== null) {
                    var entry = {};
                    for (var ek in item) {
                        if (typeof item[ek] === 'number' || typeof item[ek] === 'string') {
                            entry[ek] = item[ek];
                        }
                    }
                    result.announce_history.push(entry);
                }
            }
            result.announce_history_key = historyKeys[hi];
            break;
        }
    }

    // Phase/state related properties for diagnostics
    result.state_props = {};
    var stateKeys = ['phase', 'state', 'round', 'deal', 'status', 'turn', 'playing', 'bidding'];
    for (var key in m) {
        var val = m[key];
        if (typeof val === 'number' || typeof val === 'string' || typeof val === 'boolean') {
            var kl = key.toLowerCase();
            for (var sk = 0; sk < stateKeys.length; sk++) {
                if (kl.indexOf(stateKeys[sk]) !== -1) {
                    result.state_props[key] = val;
                    break;
                }
            }
        }
    }

    return JSON.stringify(result);
})()
"""


def _parse_card(frame: str) -> Card | None:
    """Parse a 2-char frame name like 'ad' into a Card."""
    if len(frame) != 2:
        return None
    rank = _RANK_MAP.get(frame[0])
    suit = _SUIT_MAP.get(frame[1])
    if rank and suit:
        return Card(rank, suit)
    return None


class JSDetector:
    """Reads game state by injecting JS into Safari."""

    def __init__(self):
        self._seen_cards: set[Card] = set()
        self._prev_table_count: int = 0
        self._trick_history: list[TrickRecord] = []
        self._pending_trick_cards: list[TableCard] = []
        self._current_trump: BidType | None = None
        self._prev_phase: Phase = Phase.UNKNOWN
        self._full_hand_dealt: bool = False

        # Seat detection via card count tracking
        self._prev_card_counts: list[int] = [0, 0, 0, 0]
        self._prev_table_frames: list[str] = []
        self._card_seat_map: dict[str, int] = {}  # frameName → seat

        # Position-based center (learned from 4-card tricks)
        self._trick_center: tuple[float, float] | None = None

        # Per-seat bid tracking (persists across scans within a round)
        self._seat_bids: dict[int, BidType | None] = {0: None, 1: None, 2: None, 3: None}

    def detect(self) -> GameState:
        state = GameState()
        try:
            raw = run_js(_EXTRACT_JS)
            if not raw:
                return state
            data = json.loads(raw)
        except Exception as e:
            print(f"JS detect error: {e}")
            return state

        if "error" in data:
            return state

        # Hand
        for frame in data.get("hand", []):
            card = _parse_card(frame)
            if card:
                state.hand.append(card)

        # ── Seat detection via card count changes ──────────────────
        card_counts = data.get("card_counts", [0, 0, 0, 0])
        table_entries = data.get("table", [])
        table_frames = [e["frame"] for e in table_entries if isinstance(e, dict)]

        # Find new cards that appeared on the table
        new_frames = [f for f in table_frames if f not in self._prev_table_frames]

        # Find seats that lost a card (= they played)
        seats_that_played = []
        for seat in range(4):
            diff = self._prev_card_counts[seat] - card_counts[seat]
            if diff > 0:
                seats_that_played.extend([seat] * diff)

        # Match new cards to seats that played
        if len(new_frames) == 1 and len(seats_that_played) == 1:
            # Perfect match: one new card, one seat lost a card
            self._card_seat_map[new_frames[0]] = seats_that_played[0]
        elif len(new_frames) > 0 and len(seats_that_played) == len(new_frames):
            # Multiple cards appeared, same number of seats lost cards
            # Assign in order (play order)
            for i, frame in enumerate(new_frames):
                if i < len(seats_that_played):
                    self._card_seat_map[frame] = seats_that_played[i]

        # If table was cleared (new trick), reset the map
        if len(table_frames) < len(self._prev_table_frames):
            self._card_seat_map.clear()

        # Update previous state for next comparison
        self._prev_card_counts = list(card_counts)
        self._prev_table_frames = list(table_frames)

        # ── Learn trick center from card positions ─────────────────
        if len(table_entries) == 4:
            positions = []
            for e in table_entries:
                if isinstance(e, dict):
                    positions.append((e.get("x", 0), e.get("y", 0)))
            if all(px != 0 or py != 0 for px, py in positions):
                cx = sum(px for px, py in positions) / 4
                cy = sum(py for px, py in positions) / 4
                self._trick_center = (cx, cy)

        # ── Assign seats to table cards ────────────────────────────
        seat_names = data.get("seat_names", ["?", "?", "?", "?"])

        for entry in table_entries:
            if not isinstance(entry, dict):
                continue
            frame = entry["frame"]
            card = _parse_card(frame)
            if not card:
                continue

            # Priority 1: card count tracking (most reliable)
            seat = self._card_seat_map.get(frame, -1)

            # Priority 2: position-based with known center
            if seat == -1 and self._trick_center:
                px, py = entry.get("x", 0), entry.get("y", 0)
                if px != 0 or py != 0:
                    seat = self._seat_from_position(px, py)

            # Priority 3: startingPlayer + index
            if seat == -1:
                sp = data.get("starting_player", 0)
                idx = entry.get("idx", 0)
                seat = (sp + idx) % 4

            name = seat_names[seat] if 0 <= seat <= 3 else "?"
            state.table_cards.append(TableCard(card=card, player_name=name, seat=seat))
            self._seen_cards.add(card)

        # Track all seen cards
        for c in state.hand:
            self._seen_cards.add(c)
        state.seen_cards = set(self._seen_cards)

        # Score
        state.our_score = data.get("our_score", 0)
        state.their_score = data.get("their_score", 0)

        # Phase & bid
        announce = data.get("announce", 0)
        hand_count = data.get("hand_count", 0)
        trick_count = data.get("trick_count", 0)
        has_announce_ui = data.get("has_announce_ui", False)

        # Fallback: use announce_props when m.currentAnnounce is 0
        if announce == 0:
            aprops_early = data.get("announce_props", {})
            for key, val in aprops_early.items():
                if isinstance(val, int) and val > 0:
                    decoded = _decode_announce(val)
                    if decoded:
                        announce = val
                        break

        # Track when full hand is dealt (bidding → play transition)
        if hand_count == 8 and not self._full_hand_dealt:
            self._full_hand_dealt = True
        if not self._full_hand_dealt and trick_count > 0 and hand_count >= 1:
            self._full_hand_dealt = True
        if not self._full_hand_dealt and announce > 0 and hand_count >= 1:
            self._full_hand_dealt = True

        # Phase detection
        if hand_count == 0 and trick_count == 0:
            if self._full_hand_dealt:
                state.phase = Phase.BETWEEN_ROUNDS
            elif self._prev_phase == Phase.BIDDING:
                state.phase = Phase.BIDDING  # dealing transition
            else:
                state.phase = Phase.BETWEEN_ROUNDS
        elif has_announce_ui:
            state.phase = Phase.BIDDING
        elif not self._full_hand_dealt:
            if hand_count > 0:
                state.phase = Phase.BIDDING
            elif self._prev_phase == Phase.BIDDING:
                state.phase = Phase.BIDDING
            else:
                state.phase = Phase.BETWEEN_ROUNDS
        else:
            if hand_count > 0 or trick_count > 0:
                state.phase = Phase.PLAYING
            else:
                state.phase = Phase.BETWEEN_ROUNDS

        # ── Trump/bid detection ────────────────────────────────────
        aprops = data.get("announce_props", {})
        icons = data.get("visible_icons", [])
        seat_ann = data.get("seat_announces", [])

        if announce > 0:
            bid_type = _decode_announce(announce)
        else:
            bid_type = None

        # ── Per-seat bid tracking ─────────────────────────────────
        # Extract from seat_announces probe data
        for info in seat_ann:
            seat = info.get("seat", -1)
            if seat < 0 or seat > 3:
                continue
            for key, val in info.items():
                if key == "seat":
                    continue
                if isinstance(val, int) and val > 0:
                    decoded = _decode_announce(val)
                    if decoded:
                        self._seat_bids[seat] = decoded
                        break

        # Extract from announce_history array
        announce_hist = data.get("announce_history", [])
        for entry in announce_hist:
            if isinstance(entry, dict):
                seat = entry.get("seat", entry.get("player", entry.get("playerIndex", -1)))
                val = entry.get("value", entry.get("announce", entry.get("bid", 0)))
                if isinstance(seat, int) and 0 <= seat <= 3 and isinstance(val, int) and val > 0:
                    decoded = _decode_announce(val)
                    if decoded:
                        self._seat_bids[seat] = decoded

        # Also attribute the current announce to the announcer seat
        announcer = data.get("announcer_seat", -1)
        if bid_type and 0 <= announcer <= 3:
            self._seat_bids[announcer] = bid_type

        state.seat_bids = dict(self._seat_bids)

        # ── Set current_bid and trump ─────────────────────────────
        if state.phase == Phase.BIDDING:
            if bid_type and bid_type not in (BidType.CONTRA, BidType.RECONTRA):
                state.current_bid = bid_type
                self._current_trump = bid_type
            elif bid_type in (BidType.CONTRA, BidType.RECONTRA):
                state.current_bid = bid_type
                # keep _current_trump as the underlying contract

            # Set available_bids based on bidding rules
            _BID_HIERARCHY = [
                BidType.CLUBS, BidType.DIAMONDS, BidType.HEARTS,
                BidType.SPADES, BidType.NO_TRUMPS, BidType.ALL_TRUMPS,
            ]
            if state.current_bid is None or state.current_bid == BidType.PASS:
                state.available_bids = list(_BID_HIERARCHY) + [BidType.PASS]
            elif state.current_bid in (BidType.CONTRA, BidType.RECONTRA):
                state.available_bids = [BidType.PASS]
            else:
                try:
                    idx = _BID_HIERARCHY.index(state.current_bid)
                    state.available_bids = _BID_HIERARCHY[idx + 1:] + [
                        BidType.CONTRA, BidType.PASS,
                    ]
                except ValueError:
                    state.available_bids = [BidType.PASS]

        elif state.phase == Phase.PLAYING:
            if bid_type and bid_type not in (BidType.CONTRA, BidType.RECONTRA):
                self._current_trump = bid_type

            if self._current_trump:
                state.trump = self._current_trump
                state.current_bid = self._current_trump

        # Announcer and dealer
        state.announcer_seat = data.get("announcer_seat", -1)
        state.dealer_seat = data.get("dealer_seat", -1)

        # Trick completion tracking
        current_table_count = len(state.table_cards)
        if self._prev_table_count == 4 and current_table_count < 4:
            if len(self._pending_trick_cards) == 4:
                winner = self._determine_trick_winner(
                    self._pending_trick_cards, self._current_trump
                )
                self._trick_history.append(TrickRecord(
                    cards=list(self._pending_trick_cards),
                    winner_seat=winner,
                    trump=self._current_trump,
                ))

        if current_table_count == 4:
            self._pending_trick_cards = list(state.table_cards)
        self._prev_table_count = current_table_count

        state.trick_history = list(self._trick_history)

        # Reset on new round
        if state.phase == Phase.BETWEEN_ROUNDS and self._prev_phase != Phase.BETWEEN_ROUNDS:
            self.reset_round()
        self._prev_phase = state.phase

        return state

    def _seat_from_position(self, px: float, py: float) -> int:
        """Determine seat from card position relative to learned trick center."""
        if not self._trick_center:
            return -1
        cx, cy = self._trick_center
        dx = px - cx
        dy = py - cy
        if abs(dx) < 5 and abs(dy) < 5:
            return -1
        angle = math.atan2(dy, dx) * 180 / math.pi
        if -45 <= angle <= 45:
            return 1      # right (East)
        elif 45 < angle <= 135:
            return 0      # bottom (us)
        elif angle > 135 or angle < -135:
            return 3      # left (West)
        else:
            return 2      # top (partner)

    def _determine_trick_winner(
        self, cards: list[TableCard], trump: BidType | None
    ) -> int:
        if not cards:
            return -1
        led_suit = cards[0].card.suit
        trump_suit = self._bid_to_suit(trump)
        is_all_trumps = trump == BidType.ALL_TRUMPS

        best_idx = 0
        for i in range(1, len(cards)):
            if self._beats(
                cards[i].card, cards[best_idx].card,
                led_suit, trump_suit, is_all_trumps
            ):
                best_idx = i
        return cards[best_idx].seat

    @staticmethod
    def _bid_to_suit(bid: BidType | None) -> Suit | None:
        _map = {
            BidType.CLUBS: Suit.CLUBS, BidType.DIAMONDS: Suit.DIAMONDS,
            BidType.HEARTS: Suit.HEARTS, BidType.SPADES: Suit.SPADES,
        }
        return _map.get(bid) if bid else None

    @staticmethod
    def _beats(
        challenger: Card, current_best: Card,
        led_suit: Suit, trump_suit: Suit | None, is_all_trumps: bool,
    ) -> bool:
        trump_order = [
            Rank.SEVEN, Rank.EIGHT, Rank.QUEEN, Rank.KING,
            Rank.TEN, Rank.ACE, Rank.NINE, Rank.JACK,
        ]
        plain_order = [
            Rank.SEVEN, Rank.EIGHT, Rank.NINE, Rank.JACK,
            Rank.QUEEN, Rank.KING, Rank.TEN, Rank.ACE,
        ]

        def is_trump(card: Card) -> bool:
            if is_all_trumps:
                return True
            return trump_suit is not None and card.suit == trump_suit

        def rank_value(card: Card) -> int:
            order = trump_order if is_trump(card) else plain_order
            return order.index(card.rank)

        c_trump = is_trump(challenger)
        b_trump = is_trump(current_best)

        if c_trump and not b_trump:
            return True
        if not c_trump and b_trump:
            return False
        if c_trump and b_trump:
            return rank_value(challenger) > rank_value(current_best)
        if challenger.suit == led_suit and current_best.suit != led_suit:
            return True
        if challenger.suit != led_suit:
            return False
        return rank_value(challenger) > rank_value(current_best)

    def reset_round(self):
        self._seen_cards.clear()
        self._trick_history.clear()
        self._pending_trick_cards.clear()
        self._current_trump = None
        self._prev_table_count = 0
        self._full_hand_dealt = False
        self._card_seat_map.clear()
        self._prev_table_frames.clear()
        self._seat_bids = {0: None, 1: None, 2: None, 3: None}
        # Keep _trick_center and _prev_card_counts — they persist across rounds
