"""Game state detector via JavaScript injection into Safari.

Reads the Phaser game internals directly — no OCR or template matching needed.
"""

from __future__ import annotations

import json
import math
from safari_js import run_js
from game_state import (
    GameState, Card, TableCard, TrickRecord, Declaration, DeclarationType,
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
    7: BidType.CLUBS, 8: BidType.DIAMONDS,
    9: BidType.HEARTS, 10: BidType.SPADES,
    11: BidType.NO_TRUMPS, 12: BidType.ALL_TRUMPS,
}
# Large codes: actual codes seen during play
# Confirmed: 99=Clubs, 100=Diamonds, 104=Hearts, 115=Spades
_TRUMP_MAP_LARGE = {
    99: BidType.CLUBS, 100: BidType.DIAMONDS,
    104: BidType.HEARTS, 115: BidType.SPADES,
    108: BidType.SPADES,   # alternate code (unconfirmed)
    112: BidType.NO_TRUMPS, 116: BidType.ALL_TRUMPS,
    # Original codes (keep as fallback)
    105: BidType.DIAMONDS, 110: BidType.HEARTS,
    120: BidType.NO_TRUMPS, 125: BidType.ALL_TRUMPS,
}


# Declaration text/frame patterns → (DeclarationType, points)
_DECL_TEXT_MAP: dict[str, tuple[DeclarationType, int]] = {
    "terza":  (DeclarationType.TERZA, 20),
    "терца":  (DeclarationType.TERZA, 20),
    "терци":  (DeclarationType.TERZA, 20),   # plural form on belot.bg
    "tierce": (DeclarationType.TERZA, 20),
    "quarta": (DeclarationType.QUARTA, 50),
    "кварта": (DeclarationType.QUARTA, 50),
    "кварти": (DeclarationType.QUARTA, 50),   # plural form
    "quart":  (DeclarationType.QUARTA, 50),
    "kenta":  (DeclarationType.KENTA, 100),
    "кента":  (DeclarationType.KENTA, 100),
    "квинти": (DeclarationType.KENTA, 100),   # plural form
    "квинта": (DeclarationType.KENTA, 100),
    "quint":  (DeclarationType.KENTA, 100),
    "belot":  (DeclarationType.BELOT, 20),
    "белот":  (DeclarationType.BELOT, 20),
    "carre":  (DeclarationType.CARE, 100),
    "каре":   (DeclarationType.CARE, 100),
    "карета": (DeclarationType.CARE, 100),    # plural form
    "care":   (DeclarationType.CARE, 100),
}

# Points → type refinement for caré
_CARE_POINTS_MAP = {
    150: DeclarationType.CARE_9,
    200: DeclarationType.CARE_J,
    100: DeclarationType.CARE,
}


def _parse_declaration_text(text: str) -> tuple[DeclarationType, int] | None:
    """Try to match text to a declaration type."""
    lower = text.lower().strip()
    for key, val in _DECL_TEXT_MAP.items():
        if key in lower:
            return val
    # Try numeric points extraction (e.g. "20", "50", "100", "150", "200")
    points_map = {20: DeclarationType.TERZA, 50: DeclarationType.QUARTA,
                  100: DeclarationType.KENTA, 150: DeclarationType.CARE_9,
                  200: DeclarationType.CARE_J}
    for pts, dtype in points_map.items():
        if str(pts) in lower:
            return (dtype, pts)
    return None


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

    // FULL dump: all own + prototype property names on m, with types and values
    result.all_m_props = {};
    var allKeys = [];
    try { allKeys = allKeys.concat(Object.getOwnPropertyNames(m)); } catch(e) {}
    try { allKeys = allKeys.concat(Object.keys(m)); } catch(e) {}
    try {
        var proto = Object.getPrototypeOf(m);
        if (proto) allKeys = allKeys.concat(Object.getOwnPropertyNames(proto));
    } catch(e) {}
    // deduplicate
    var seen = {};
    for (var ki = 0; ki < allKeys.length; ki++) {
        var k = allKeys[ki];
        if (seen[k]) continue;
        seen[k] = true;
        try {
            var v = m[k];
            if (typeof v === 'number' || typeof v === 'boolean') {
                result.all_m_props[k] = v;
            } else if (typeof v === 'string' && v.length < 100) {
                result.all_m_props[k] = v;
            } else if (v === null) {
                result.all_m_props[k] = null;
            } else if (Array.isArray(v)) {
                result.all_m_props[k] = 'Array(' + v.length + ')';
            } else if (typeof v === 'object' && v !== null) {
                // For objects, list their scalar sub-properties
                var sub = {};
                var subKeys = Object.keys(v);
                var hasSub = false;
                for (var si = 0; si < Math.min(subKeys.length, 30); si++) {
                    var sv = v[subKeys[si]];
                    if (typeof sv === 'number' || typeof sv === 'string' || typeof sv === 'boolean' || sv === null) {
                        sub[subKeys[si]] = sv;
                        hasSub = true;
                    }
                }
                if (hasSub) {
                    result.all_m_props[k] = sub;
                } else {
                    result.all_m_props[k] = 'Object(' + subKeys.length + ' keys)';
                }
            }
        } catch(e) {}
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

    // DEBUG: dump ALL scalar properties on seat 0 (player) to find contract clues
    result.seat0_all = {};
    var ps0 = m.playerSeats[0];
    try {
        var psKeys = Object.getOwnPropertyNames(ps0);
        for (var pi = 0; pi < psKeys.length; pi++) {
            var pk = psKeys[pi];
            try {
                var pv = ps0[pk];
                if (typeof pv === 'number' || typeof pv === 'string' || typeof pv === 'boolean') {
                    result.seat0_all[pk] = pv;
                }
            } catch(e) {}
        }
    } catch(e) {}

    // Also check if currentTopAnnouncer is an object with useful info
    result.top_announcer_raw = null;
    try {
        var ta = m.currentTopAnnouncer;
        if (ta && typeof ta === 'object') {
            result.top_announcer_raw = {};
            for (var tk in ta) {
                if (typeof ta[tk] === 'number' || typeof ta[tk] === 'string' || typeof ta[tk] === 'boolean') {
                    result.top_announcer_raw[tk] = ta[tk];
                }
            }
        } else if (typeof ta === 'number') {
            result.top_announcer_raw = ta;
        }
    } catch(e) {}

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

    // ── Declarations bar probe ────────────────────────────────
    result.declarations_bar = [];
    function scanDecl(obj, path, depth) {
        if (!obj || depth > 5) return;
        var info = {};
        if (obj.frameName) info.frame = obj.frameName;
        if (obj.text && typeof obj.text === 'string') info.text = obj.text;
        if (obj.key && typeof obj.key === 'string') info.key = obj.key;
        if (typeof obj.visible === 'boolean') info.visible = obj.visible;
        if (typeof obj.alpha === 'number') info.alpha = obj.alpha;
        if (typeof obj.x === 'number') info.x = Math.round(obj.x);
        if (typeof obj.y === 'number') info.y = Math.round(obj.y);
        if (Object.keys(info).length > 0) {
            info.path = path;
            result.declarations_bar.push(info);
        }
        if (obj.children) {
            for (var i = 0; i < obj.children.length; i++) {
                scanDecl(obj.children[i], path + '[' + i + ']', depth + 1);
            }
        }
    }
    if (m.declarationsBar) {
        scanDecl(m.declarationsBar, 'declarationsBar', 0);
    }

    // Scan m for other declaration-related arrays/objects
    result.declaration_props = {};
    var declKeys = ['declar', 'combo', 'combination', 'Declar', 'Combo', 'Combination'];
    for (var key in m) {
        try {
            var kl = key.toLowerCase();
            var isDecl = false;
            for (var di = 0; di < declKeys.length; di++) {
                if (kl.indexOf(declKeys[di].toLowerCase()) !== -1) { isDecl = true; break; }
            }
            if (!isDecl) continue;
            var val = m[key];
            if (typeof val === 'number' || typeof val === 'string' || typeof val === 'boolean') {
                result.declaration_props[key] = val;
            } else if (Array.isArray(val)) {
                var arr = [];
                for (var ai = 0; ai < Math.min(val.length, 20); ai++) {
                    var item = val[ai];
                    if (typeof item === 'number' || typeof item === 'string') {
                        arr.push(item);
                    } else if (item && typeof item === 'object') {
                        var entry = {};
                        for (var ek in item) {
                            if (typeof item[ek] === 'number' || typeof item[ek] === 'string' || typeof item[ek] === 'boolean') {
                                entry[ek] = item[ek];
                            }
                        }
                        arr.push(entry);
                    }
                }
                result.declaration_props[key] = arr;
            } else if (val && typeof val === 'object') {
                var sub = {};
                var subKeys = Object.keys(val);
                for (var si = 0; si < Math.min(subKeys.length, 20); si++) {
                    var sv = val[subKeys[si]];
                    if (typeof sv === 'number' || typeof sv === 'string' || typeof sv === 'boolean') {
                        sub[subKeys[si]] = sv;
                    }
                }
                if (Object.keys(sub).length > 0) result.declaration_props[key] = sub;
            }
        } catch(e) {}
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
        self._debug_dumped = False

        # Declaration tracking
        self._declarations: list[Declaration] = []
        self._prev_decl_bar_sig: str = ""  # signature to detect changes

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
        variation = data.get("announce_variation", 0)

        # Debug: log raw announce code when it changes
        if announce > 0 and announce != getattr(self, '_last_announce_code', 0):
            self._last_announce_code = announce
            decoded = _decode_announce(announce)
            print(f"[BID] raw announce code={announce} decoded={decoded}")
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

        # ── Declaration parsing (only during play) ────────────────
        decl_bar = data.get("declarations_bar", [])
        decl_props = data.get("declaration_props", {})

        if state.phase == Phase.PLAYING:
            # Build a signature to detect changes
            decl_sig = json.dumps(decl_bar, sort_keys=True) + json.dumps(decl_props, sort_keys=True)

            if decl_sig != self._prev_decl_bar_sig and (decl_bar or decl_props):
                self._prev_decl_bar_sig = decl_sig

                # Debug: log raw declaration data so we can see what the game sends
                if decl_bar:
                    visible_items = [d for d in decl_bar
                                     if d.get("visible", True) and d.get("alpha", 1) > 0]
                    if visible_items:
                        print(f"[DECL] declarations_bar visible: {json.dumps(visible_items)}")
                if decl_props:
                    print(f"[DECL] declaration_props: {json.dumps(decl_props)}")

                new_decls: list[Declaration] = []

                # Parse from bar children — text fields have format "count|LABEL"
                # e.g. "0|ТЕРЦИ" = 0 terzas, "2|КВАРТИ" = 2 quartas
                # Only create declarations when count > 0
                for item in decl_bar:
                    if not item.get("visible", True) or item.get("alpha", 0) <= 0:
                        continue
                    text = item.get("text", "")
                    if not text:
                        continue
                    # Parse "count|LABEL" format
                    if "|" in text:
                        parts = text.split("|", 1)
                        try:
                            count = int(parts[0])
                        except ValueError:
                            continue
                        if count <= 0:
                            continue
                        label = parts[1]
                    else:
                        label = text
                        # Skip non-declaration UI text (buttons, etc.)
                        if label.strip() in ("Свали!", ""):
                            continue

                    parsed = _parse_declaration_text(label)
                    if parsed:
                        dtype, pts = parsed
                        seat = self._guess_decl_seat(item)
                        new_decls.append(Declaration(type=dtype, seat=seat, points=pts))

                # Parse from declaration_props arrays (structured data)
                for key, val in decl_props.items():
                    if not isinstance(val, list):
                        continue
                    for entry in val:
                        if not isinstance(entry, dict):
                            continue
                        seat = entry.get("seat", entry.get("player", entry.get("playerIndex", -1)))
                        dtype_str = str(entry.get("type", entry.get("name", "")))
                        pts = entry.get("points", entry.get("value", 0))
                        parsed = _parse_declaration_text(dtype_str)
                        if not parsed:
                            continue
                        dtype, default_pts = parsed
                        actual_pts = pts if isinstance(pts, int) and pts > 0 else default_pts
                        if dtype == DeclarationType.CARE and actual_pts in _CARE_POINTS_MAP:
                            dtype = _CARE_POINTS_MAP[actual_pts]
                        if isinstance(seat, int) and 0 <= seat <= 3:
                            new_decls.append(Declaration(type=dtype, seat=seat, points=actual_pts))

                if new_decls:
                    existing_sigs = {(d.type, d.seat) for d in self._declarations}
                    for d in new_decls:
                        if (d.type, d.seat) not in existing_sigs:
                            self._declarations.append(d)
                            existing_sigs.add((d.type, d.seat))
                            print(f"[DECL] New: seat={d.seat} type={d.type.value} pts={d.points}")

        state.declarations = list(self._declarations)

        # Reset on new round
        if state.phase == Phase.BETWEEN_ROUNDS and self._prev_phase != Phase.BETWEEN_ROUNDS:
            self.reset_round()
        self._prev_phase = state.phase

        return state

    @staticmethod
    def _guess_decl_seat(item: dict) -> int:
        """Guess which seat a declaration belongs to from path or position."""
        path = item.get("path", "")
        # If path contains a seat index like [0], [1], etc.
        for i in range(4):
            if f"[{i}]" in path and path.index(f"[{i}]") < 30:
                return i
        # Position-based heuristic: bottom=0, right=1, top=2, left=3
        x, y = item.get("x", 0), item.get("y", 0)
        if x == 0 and y == 0:
            return -1
        # Very rough heuristic based on typical game layout
        if y > 400:
            return 0   # bottom = player
        elif y < 200:
            return 2   # top = partner
        elif x > 500:
            return 1   # right = east
        elif x < 300:
            return 3   # left = west
        return -1

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
        self._debug_dumped = False
        self._declarations.clear()
        self._prev_decl_bar_sig = ""
        # Keep _trick_center and _prev_card_counts — they persist across rounds
