<div align="center">

<!-- Animated header banner -->
<img src="https://capsule-render.vercel.app/api?type=waving&color=0:1a1a2e,50:16213e,100:e94560&height=220&section=header&text=Belot%20Bot%20%F0%9F%83%8F&fontSize=60&fontColor=ffffff&fontAlignY=35&animation=fadeIn&desc=AI-Powered%20Bulgarian%20Belot%20Assistant&descSize=18&descAlignY=55&descAlign=50" width="100%"/>

<!-- Badges -->
<p>
  <img src="https://img.shields.io/badge/python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/PyQt6-41CD52?style=for-the-badge&logo=qt&logoColor=white" alt="PyQt6"/>
  <img src="https://img.shields.io/badge/Safari-000000?style=for-the-badge&logo=safari&logoColor=white" alt="Safari"/>
  <img src="https://img.shields.io/badge/macOS-000000?style=for-the-badge&logo=apple&logoColor=white" alt="macOS"/>
</p>

<p>
  <img src="https://img.shields.io/badge/status-active-success?style=flat-square" alt="Status"/>
  <img src="https://img.shields.io/badge/belot.bg-supported-e94560?style=flat-square" alt="Belot.bg"/>
  <img src="https://img.shields.io/github/license/Kryskata-C/belot-bot?style=flat-square&color=blue" alt="License"/>
</p>

<!-- Typing animation -->
<img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=600&size=22&pause=1000&color=E94560&center=true&vCenter=true&multiline=true&repeat=true&width=600&height=80&lines=Real-time+card+tracking+%F0%9F%83%8F;AI+bidding+%26+play+recommendations+%F0%9F%A7%A0;Zero+interaction+%E2%80%94+just+watch+%26+win+%F0%9F%8F%86" alt="Typing SVG" />

---

**Belot Bot** reads the game state directly from [belot.bg](https://belot.bg)'s Phaser engine via JavaScript injection into Safari, runs real-time AI strategy analysis, and displays recommendations on a sleek overlay — no screenshots, no OCR, no clicking.

</div>

---

## How It Works

```
┌──────────────┐     JS Injection      ┌──────────────┐     Strategy       ┌──────────────┐
│              │ ──────────────────────▶│              │ ──────────────────▶│              │
│  Safari +    │   Extract cards,       │  JS Detector │   Evaluate hand,   │  AI Brain    │
│  Belot.bg    │   bids, scores from    │              │   pick best bid    │  (Strategy)  │
│              │   Phaser internals     │              │   or card to play  │              │
└──────────────┘                        └──────────────┘                    └──────┬───────┘
                                                                                  │
                                                                                  ▼
                                                                           ┌──────────────┐
                                                                           │  PyQt6 GUI   │
                                                                           │  Overlay     │
                                                                           │  Dashboard   │
                                                                           └──────────────┘
```

<div align="center">
<table>
<tr>
<td align="center"><b>🎴 Card Detection</b><br/><sub>Reads hand & table cards directly from Phaser sprites</sub></td>
<td align="center"><b>🧠 AI Strategy</b><br/><sub>Evaluates all contract types with scoring heuristics</sub></td>
<td align="center"><b>📊 Card Tracker</b><br/><sub>Tracks all 32 cards — seen, unseen, in hand</sub></td>
</tr>
<tr>
<td align="center"><b>🏆 Bid Advisor</b><br/><sub>Recommends optimal bids based on hand strength</sub></td>
<td align="center"><b>🃏 Play Advisor</b><br/><sub>Suggests the best card considering trick position</sub></td>
<td align="center"><b>👁️ Void Detection</b><br/><sub>Tracks which opponents are void in which suits</sub></td>
</tr>
</table>
</div>

---

## Features

- **Zero-latency detection** — reads Phaser game objects directly, no OCR or template matching
- **Smart bidding** — evaluates all 6 contract types (♣ ♦ ♥ ♠ БК ВК) with per-suit scoring
- **Positional play** — knows if you're leading, following, or last to play
- **Trick tracking** — remembers every trick, detects who won, counts points
- **Void tracking** — identifies when opponents can't follow suit
- **Contra/Recontra** — knows when to double based on hand strength vs opponent's bid
- **Per-seat bid display** — see what every player bid (You, East, Partner, West)
- **Always-on-top overlay** — draggable dashboard that stays visible over Safari

---

## Quick Start

### Prerequisites

- **macOS** (uses AppleScript to inject JS into Safari)
- **Python 3.10+**
- **Safari** with Developer menu enabled

### Enable Safari JavaScript Injection

1. Open Safari → **Settings** → **Advanced**
2. Check **"Show features for web developers"**
3. This enables AppleScript access to Safari's JavaScript context

### Install & Run

```bash
# Clone the repo
git clone https://github.com/Kryskata-C/belot-bot.git
cd belot-bot

# Install dependencies
pip install PyQt6 opencv-python numpy

# Run the bot
python main.py
```

### Usage

1. Open [belot.bg](https://belot.bg) in **Safari** and enter a match
2. Run `python main.py` — the overlay window appears
3. Click **START** on the overlay
4. Play your game — the bot shows recommendations in real-time
5. Click **STOP** or press `Ctrl+Q` to quit

---

## Architecture

```
belot-bot/
├── main.py          # Entry point — wires detector → brain → GUI
├── js_detector.py   # Primary detector — JS injection into Safari/Phaser
├── safari_js.py     # AppleScript bridge — runs JS in Safari tabs
├── detector.py      # Fallback visual detector (OpenCV template matching)
├── game_state.py    # Data model — Card, BidType, Phase, GameState
├── strategy.py      # AI brain — bidding evaluation & play recommendations
├── gui.py           # PyQt6 overlay — frameless always-on-top dashboard
├── calibrate.py     # Region calibration tool for visual detector
├── capture.py       # Screen capture utility
├── regions.json     # Screen region coordinates (visual detector)
└── templates/       # Template images for fallback detection
    ├── bids/
    ├── cards/
    └── digits/
```

### Detection Pipeline

The bot runs a scan loop every **500ms**:

1. **`safari_js.py`** — executes JavaScript in the active Safari tab via AppleScript
2. **`js_detector.py`** — the injected JS reads Phaser's internal game objects:
   - `m.playerSeats[0].playersHand` → your cards
   - `m.trickGraphic.children` → cards on the table
   - `m.currentAnnounce` → active bid/contract
   - Score text objects → НИЕ/ВИЕ scores
3. **`strategy.py`** — the `BelotBrain` analyzes the game state:
   - During **bidding**: evaluates hand strength for each contract type against thresholds
   - During **play**: considers trick position, remaining cards, trump status, and voids
4. **`gui.py`** — paints everything on a custom PyQt6 overlay

### Bidding Strategy

| Contract | Key Factors |
|----------|-------------|
| ♣ ♦ ♥ ♠ | J+9 trump power, side aces, suit length |
| ВК (All Trumps) | Multiple J+9 combos across suits |
| БК (No Trumps) | Aces, long suits, tens with protection |
| Контра | Strong holding in opponent's declared suit |

Bid threshold scales with hand size — **~26 for 5 cards** (initial deal), **42 for 8 cards** (full hand).

---

## Tech Stack

<div align="center">

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| GUI Framework | PyQt6 |
| Game Integration | JavaScript injection via AppleScript |
| Computer Vision | OpenCV (fallback detector) |
| Target Game | [belot.bg](https://belot.bg) (Phaser.js) |
| Platform | macOS only |

</div>

---

## Disclaimer

This project is built for **educational purposes** and as a programming exercise in game state extraction, AI strategy, and real-time overlay systems. Use responsibly.

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=0:1a1a2e,50:16213e,100:e94560&height=120&section=footer&animation=fadeIn" width="100%"/>

<sub>Built with 🃏 and ☕ by <a href="https://github.com/Kryskata-C">Kryskata-C</a></sub>

</div>
