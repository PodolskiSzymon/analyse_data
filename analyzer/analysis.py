"""Wspólne narzędzia analizy danych (PLAN_ANALIZY.md, część A) - bez sieci.

Zasada: główna baza (`analyzer.db`) jest współdzielona z działającym `watch` → czytamy ją TYLKO do odczytu
(`open_ro`), bez migracji. Wyniki pośrednie (flagi podejrzanych, relisty) idą do osobnej bazy `analysis.db` obok
głównej (`open_analysis`), raporty do `reports/<data>/`, eksporty do `export/<data>/`.
"""
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

# Nasze kategorie przedmiotu (listings.category), w kolejności raportów.
CATEGORIES = ("laptop", "phone", "tablet", "console", "gpu", "ram", "storage")
# Stany, które biorą udział w statystykach rynku (reszta: below_min, ignored, unclassified, gone_pending… - poza).
ACTIVE, SOLD = "active", "sold"
GONE_NOT_SOLD = ("deleted", "closed")        # zniknięte bez potwierdzonej sprzedaży
MARKET_STATES = (ACTIVE, "reserved", SOLD, *GONE_NOT_SOLD, "blocked")

ANALYSIS_SCHEMA = """
CREATE TABLE IF NOT EXISTS flags (
  listing_id INTEGER NOT NULL,
  flag       TEXT NOT NULL,
  detail     TEXT,
  PRIMARY KEY (listing_id, flag)
);
CREATE TABLE IF NOT EXISTS relists (
  old_id   INTEGER NOT NULL,
  new_id   INTEGER NOT NULL PRIMARY KEY,
  score    REAL NOT NULL,
  basis    TEXT,                       -- 'description' (ten sam / podobny opis) albo 'title' (bez opisu do porównania)
  gap_days REAL                        -- dni od ostatniego widzenia starej do pierwszego widzenia nowej
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def open_ro(path):
    """Główna baza tylko do odczytu (URI mode=ro - działa też na Windows i przy włączonym watch)."""
    path = Path(path)
    if not path.exists():
        raise SystemExit(f"Nie ma bazy {path} - ustaw ANALYZER_DB w sniper\\.env")
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def analysis_path(db_path):
    return Path(db_path).parent / "analysis.db"


def open_analysis(db_path):
    """Baza wyników pośrednich (flagi, relisty) - tworzona w razie potrzeby obok analyzer.db."""
    path = analysis_path(db_path) if str(db_path) != ":memory:" else ":memory:"
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(ANALYSIS_SCHEMA)
    return conn


def out_dir(db_path, kind="reports", day=None):
    """Folder wyników obok bazy: <folder bazy>/<kind>/<RRRR-MM-DD>/ (kind: reports / export)."""
    from datetime import date

    path = Path(db_path).parent / kind / (day or date.today().isoformat())
    path.mkdir(parents=True, exist_ok=True)
    return path


def set_meta(aconn, key, value):
    aconn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value)))


# ---------------------------------------------------------------------------------------------- tekst, czas, liczby


def norm_title(text):
    """Znormalizowany tytuł: małe litery, bez akcentów i znaków, zwinięte spacje („iPhone 16 Pro, 512GB!” →
    „iphone 16 pro 512gb”)."""
    text = unicodedata.normalize("NFKD", (text or "").lower().replace("ł", "l"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = " ".join(re.sub(r"[^\w]+", " ", text).split())
    return re.sub(r"\b(\d+) (gb|tb|mb|mhz|hz|cali|cal|inch)\b", r"\1\2", text)   # „512 GB” = „512GB”


def specific_title(title, words=4, chars=20):
    """Czy znormalizowany tytuł jest konkretny (≥ 4 słowa albo ≥ 20 znaków): „laptop lenovo”, „iphone 15 pro” -
    nie (tysiące niezależnych ofert o takim tytule), „apple iphone 16 pro 512gb czarny tytan” - tak."""
    return len(title.split()) >= words or len(title) >= chars


def parse_ts(text):
    if not text:
        return None
    try:
        ts = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def days_between(start, end):
    a, b = parse_ts(start), parse_ts(end)
    if a is None or b is None:
        return None
    return (b - a).total_seconds() / 86400


def percentile(values, q):
    """Percentyl z interpolacją liniową (jak numpy domyślnie); values posortowane albo nie. Pusta lista → None."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def median(values):
    return percentile(values, 0.5)


def whole(value):
    return value is not None and abs(value - round(value)) < 0.005


def market(seller_currency, price=None):
    """'PL' (sprzedawca w zł) albo 'zagr' (inna waluta). Bez waluty (przed szczegółami): ułamkowa cena w zł =
    przeliczenie z obcej waluty → 'zagr'."""
    if seller_currency:
        return "PL" if seller_currency == "PLN" else "zagr"
    if price is not None and not whole(price):
        return "zagr"
    return "PL"


def initial_until(conn):
    """catalog_id → koniec PIERWSZEGO przejścia katalogu (ISO). Oferty z first_seen ≤ tej chwili były w katalogu już
    przed startem zbierania - first_seen ≠ data wystawienia (zastrzeżenie 3). Przejście niedokończone → start
    drugiego przejścia; brak drugiego → wszystkie oferty katalogu są „początkowe” (None = +∞)."""
    runs = {}
    for r in conn.execute("SELECT catalog_id, started_at, finished_at FROM crawl_runs WHERE catalog_id IS NOT NULL "
                          "AND COALESCE(kind, 'crawl') = 'crawl' ORDER BY catalog_id, started_at"):
        runs.setdefault(r["catalog_id"], []).append((r["started_at"], r["finished_at"]))
    out = {}
    for catalog_id, items in runs.items():
        first = items[0]
        out[catalog_id] = first[1] or (items[1][0] if len(items) > 1 else None)
    return out


def latest_seen(conn):
    """„Teraz” analizy = ostatnie widzenie oferty w katalogu (koniec ostatniego przejścia) - wynik nie zależy od
    godziny uruchomienia raportu."""
    row = conn.execute("SELECT MAX(last_seen) FROM listings").fetchone()
    return row[0] or datetime.now(timezone.utc).isoformat()


def cpu_line_of(cpu, cpu_line=None):
    """Linia procesora do klucza wyższego poziomu: „i5-8350u” → „intel core i5”, „ryzen 5 5500u” → „amd ryzen 5”,
    „apple m1 pro” → „apple m1”."""
    if cpu_line:
        return str(cpu_line).lower()
    if not cpu:
        return None
    cpu = str(cpu).lower()
    match = re.match(r"(i[3579])-", cpu)
    if match:
        return f"intel core {match.group(1)}"
    match = re.match(r"ultra ([579])", cpu)
    if match:
        return f"intel core ultra {match.group(1)}"
    match = re.match(r"ryzen ([3579])", cpu)
    if match:
        return f"amd ryzen {match.group(1)}"
    match = re.match(r"apple (m\d)", cpu)
    if match:
        return f"apple {match.group(1)}"
    return cpu.split()[0]


def parent_key(category, config_key, cpu=None, cpu_line=None, ram_gb=None, model=None, gpu=None):
    """Klucz poziom wyżej (dla konfiguracji z małą liczbą sprzedaży): laptop cpu_line+RAM (bez dysku, modelu, GPU),
    telefon/tablet model bez pojemności, konsola platforma+wariant, GPU sam układ, RAM typ+pojemność, dysk pojemność.
    None = nie da się ustalić."""
    parts = config_key.split("|") if config_key else None
    if category == "laptop":
        line = cpu_line_of(cpu, cpu_line)
        return f"{line}|{ram_gb}" if line and ram_gb else None
    if category in ("phone", "tablet"):
        return (model or (parts[0] if parts else None)) or None
    if not parts:
        return None
    if category == "console" and len(parts) >= 2:
        return f"{parts[0]}|{parts[1]}"
    if category == "gpu":
        return parts[0]
    if category == "ram" and len(parts) >= 3:
        return f"{parts[0]}|{parts[2]}"
    if category == "storage" and len(parts) >= 2:
        return parts[1]
    return None
