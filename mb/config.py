"""
Central configuration. Tune thresholds and weights here — nowhere else.
All values are starting points reasoned for Indian small/mid/micro caps
looking for multi-year multi-bagger potential, not fitted to history.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DOCS = ROOT / "docs"

UNIVERSE_CSV = DATA / "universe.csv"
CACHE_JSON = DATA / "fundamentals.json"
PICKS_JSON = DATA / "picks.json"
SIGNALS_JSON = DATA / "signals.json"
DD_JSON = DATA / "diligence.json"
SIGNALS_DEBUG = DATA / "signals_debug.json"
SNAPSHOT_DIR = DATA / "snapshots"
RULEBOOK_VERSION = "2026-10-16.1"

# Research-shortlist gates.
# Safety rules → Fail. Cohort preferences → Watchlist if the rest is intact.
GATES = dict(
    min_mcap_cr=300,
    max_mcap_cr=8000,
    min_sales_cagr=15,
    min_recent_sales=8,
    min_roce=15,
    min_cfo_pat=0.7,
    watch_cfo_pat=0.4,
    max_de_shortlist=0.5,
    max_de_fail=1.2,
    max_pledge=5,
    min_promoter=40,
    min_promoter_fail=25,
    max_dilution=12,
    max_pe=25,
    max_peg=1.2,
    max_recv_chg=80,
)

# ---------------------------------------------------------------------------
# Universe & liquidity gates
# ---------------------------------------------------------------------------
CFG = dict(
    # Market-cap band (Rs crore). Below = nano / manipulative; above = hard to 10x.
    min_mcap_cr=300,  # aligned with GATES
    max_mcap_cr=8000,  # aligned with GATES shortlist band
    # Avg daily turnover last ~3 months
    min_turnover_cr=1.5,
    min_price=20,
    # Fundamentals cache TTL
    ttl_days=7,
    # Need data for at least this many of the 10 pillars
    min_pillars=7,
    # More high-severity red flags than this → reject
    max_high_flags=1,
    # Revenue CAGR % (or latest quarter YoY) required
    min_growth=15,
    # Runner-ups shown on the page
    bench=4,
    # NSE event/ownership signals for top N by base score
    signal_top_n=35,
    # AI due diligence on up to this many finalists
    diligence_top_n=3,
    # Keep yesterday's pick unless beaten by this many points
    hysteresis=3.5,
    # Annual results older than this = stale
    stale_annual_days=420,
    # Promoter pledge % above this = hard reject
    max_pledge=5,
    # Minimum ROCE for quality gate
    min_roce=15,
    # Max debt/equity for quality gate
    max_de=1.2,
    # Max 3y dilution %
    max_dilution=12,
    # Prefer companies still "undiscovered"
    max_inst_pct=40,
    max_analysts=12,
)

# Rank only names that already passed every shortlist gate.
# A missing dimension is not reweighted; composite() returns None.
WEIGHTS = dict(
    quality=25,
    growth=25,
    cash=20,
    price=20,
    discovery=10,
)

PILLAR_NAMES = dict(
    quality="Quality (ROCE)",
    growth="Growth (history + recent)",
    cash="Cash and balance sheet",
    price="Price vs growth",
    discovery="Discovery (tie-break only)",
)

# ---------------------------------------------------------------------------
# Theme & moat keyword maps (Yahoo business summary + sector text)
# ---------------------------------------------------------------------------
THEMES = {
    "Defence and aerospace": [
        "defence", "defense", "aerospace", "radar", "missile", "military",
        "avionics", "naval", "unmanned", "drone", "ordnance",
    ],
    "Electronics and semiconductors": [
        "electronic manufacturing", "ems ", "semiconductor", "printed circuit",
        "pcb", "electronic components", "display", "chip", "fabless",
    ],
    "Energy transition": [
        "solar", "renewable", "battery", "lithium", "electric vehicle", "wind",
        "green hydrogen", "energy storage", "transmission", "smart meter",
        "ev charging",
    ],
    "Railways and infrastructure": [
        "railway", "metro", "wagon", "rolling stock", "infrastructure",
        "epc", "civil construction",
    ],
    "Specialty chemicals and CDMO": [
        "specialty chemical", "agrochemical", "intermediate", "cdmo",
        "contract manufacturing", "fluorin", "api ", "pharma intermediate",
    ],
    "Digital and data centres": [
        "data centre", "data center", "cloud", "cyber", "artificial intelligence",
        "saas", "software product",
    ],
    "Export manufacturing": [
        "precision component", "castings", "forgings", "export", "global customers",
        "auto component", "engineering product",
    ],
    "Healthcare and diagnostics": [
        "diagnostic", "hospital", "medical device", "healthcare", "pathology",
        "pharma", "formulation",
    ],
}

MOAT_WORDS = [
    "qualified", "certified", "approved", "licence", "license", "patent",
    "proprietary", "indigenous", "sole supplier", "mission-critical",
    "long-term contract", "in-house r&d", "design and development",
    "as9100", "nadcap", "regulated", "entry barrier", "high switching",
]

# Manual verification checklist shown on the page
VERIFY = [
    "Order book and its growth vs revenue (latest investor presentation or concall). Filing summaries are short; open the linked PDFs",
    "Export share and export margins (annual report segment note). Only export order announcements are detected, not margins",
    "Capex plan, how it is funded, and expected capacity timeline",
    "FII and DII trend from the latest shareholding pattern, if it shows n/a above",
    "Customer concentration and dependence on government orders",
    "Governance: auditor changes, related-party dealings, promoter track record",
    "Whether the growth is organic or came from a one-off order or acquisition",
    "Government policy / PLI / tariff exposure: does demand depend on a scheme that can change?",
    "Management commentary and guidance from the latest concall — not just the press release",
    "Sector cycle: is the whole theme already crowded in price (theme relative strength on the page)",
]

# NSE index constituent CSV sources (primary, fallback)
NSE_URLS = [
    (
        "https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",
    ),
    (
        "https://nsearchives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
    ),
    (
        "https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv",
        "https://www.niftyindices.com/IndexConstituent/ind_niftymicrocap250_list.csv",
    ),
]

UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)


# ---------------------------------------------------------------------------
# Short-term / Swing technical engine (1 day – 2 weeks)
# ---------------------------------------------------------------------------
SHORT_TERM = dict(
    # Liquidity
    min_price=30.0,
    min_avg_turnover_cr=1.5,
    min_volume_surge=1.15,

    # ATR & Risk
    atr_period=14,
    sl_atr_mult=1.35,
    t1_atr_mult=1.5,
    t2_atr_mult=2.5,
    t3_atr_mult=3.6,

    # Filters
    rsi_period=14,
    rsi_max=74,
    rsi_min=32,
    min_confidence=55,              # base threshold
    min_confidence_risk_off=62,

    # Structure
    swing_lookback=7,
    breakout_buffer_pct=0.10,

    # Regime – allow all, but risk_off demands higher confidence
    allow_regimes=["risk_on", "neutral", "risk_off"],

    # How many top liquid names to scan for short-term signals
    max_scan=180,
    # Max signals to show on the page
    max_show=3,
)

# Path for short-term signals cache
SHORT_JSON = DATA / "short_signals.json"
# Multi-day swing signal history (active + closed outcomes)
SWING_HISTORY_JSON = DATA / "swing_history.json"
