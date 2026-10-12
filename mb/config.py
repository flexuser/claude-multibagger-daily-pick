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

# ---------------------------------------------------------------------------
# Universe & liquidity gates
# ---------------------------------------------------------------------------
CFG = dict(
    # Market-cap band (Rs crore). Below = nano / manipulative; above = hard to 10x.
    min_mcap_cr=400,
    max_mcap_cr=25000,
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
    max_pledge=20,
    # Minimum ROCE for quality gate
    min_roce=12,
    # Max debt/equity for quality gate
    max_de=1.2,
    # Max 3y dilution %
    max_dilution=12,
    # Prefer companies still "undiscovered"
    max_inst_pct=40,
    max_analysts=12,
)

# ---------------------------------------------------------------------------
# Pillar weights (sum does not need to be 100; composite is weighted avg)
# Higher weight on proof / quality / catalyst for true multibagger edge
# ---------------------------------------------------------------------------
WEIGHTS = dict(
    runway=10,       # theme + still-small revenue base
    moat=9,          # ROCE, margins, keyword proxies
    proof=18,        # growth + acceleration (most important)
    leverage=12,     # operating leverage / profit vs sales
    quality=14,      # capital quality, cash conversion, coverage
    discovery=7,     # still under-owned / under-covered
    valuation=7,     # PE/PEG not extreme
    confirm=6,       # price/volume confirmation
    ownership=9,     # promoter + smart-money trends
    catalyst=8,      # expansion, orders, capex
)

PILLAR_NAMES = dict(
    runway="Runway (theme + small base)",
    moat="Moat (proxy)",
    proof="Proof (growth acceleration)",
    leverage="Operating leverage",
    quality="Capital quality",
    discovery="Still undiscovered",
    valuation="Valuation vs growth",
    confirm="Market confirmation",
    ownership="Ownership and smart money",
    catalyst="Expansion and catalysts",
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
