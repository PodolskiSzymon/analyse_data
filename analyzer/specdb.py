"""Baza modeli laptopów: kod modelu → procesor / karta (2026-11-20, pomysł użytkownika: „ogromny plik z wszystkimi
modelami laptopów - po samej nazwie podać mniej więcej parametry”).

Po co: 2/3 ogłoszeń laptopów nie podaje procesora („Laptop Lenovo IdeaPad 3 15ITL6”), więc nie mają klucza do median
po specyfikacji. Dokładny kod modelu (15ITL6, X515MA, AN515-58, Latitude 5320, 250 G8) zwykle wyznacza platformę.

Plik `data/specdb.sqlite` (obok analyzer.db, poza repo):
  * `model_specs` - konfiguracje modeli (kod, marka, nazwa, procesor, karta, RAM, dysk, rok, źródło, adres),
  * `pages` - pobrane strony (skompresowany HTML; każda strona pobierana RAZ, parser można poprawiać bez sieci),
  * `queue` - kolejka adresów do pobrania (wznawianie po przerwaniu).

Źródła:
  1. własne ogłoszenia (`learn`): kod w tytule / opisie + procesor podany przez sprzedawcę; kod „pewny”, gdy ≥ 3 oferty
     i ≥ 80% zgodnych co do linii i generacji procesora (kopia 07.11: 108 kodów),
  2. strony ze specyfikacjami (`crawl`) - parser na stronę w `SITES` (dopisujemy po próbkach HTML od użytkownika;
     ogólny parser czyta dane schema.org / JSON-LD, jeśli strona je ma).
Pobieranie: bez proxy, jedna strona naraz, losowa przerwa (domyślnie 25-90 s) i dłuższa co kilkadziesiąt stron,
`robots.txt` respektowany, 403 / 429 = koniec przebiegu (nie obchodzimy blokad). Tylko strony, których regulamin na to
pozwala - najlepiej oficjalne API / pliki (Icecat Open, Lenovo PSREF).

Wynik trafia do comparables.db jako tabela `model_codes` (kod → procesor, karta) - analizator uzupełnia nią
specyfikację przy budowie median, a Sniper przy ocenie (te same wzory kodów: `model_codes` tu i w
unreachable_sniper/sniper/specs.py, test MODEL_CODE_PARITY).
"""
import json
import logging
import random
import re
import sqlite3
import time
import zlib
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

log = logging.getLogger("analyzer.specdb")

SCHEMA = """
CREATE TABLE IF NOT EXISTS model_specs (code TEXT NOT NULL, brand TEXT, name TEXT, cpu TEXT, gpu TEXT, ram_gb INTEGER,
                                        ssd_gb INTEGER, year INTEGER, source TEXT NOT NULL, url TEXT, n INTEGER,
                                        added_at TEXT);
CREATE INDEX IF NOT EXISTS model_specs_code ON model_specs(code);
CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, site TEXT, fetched_at TEXT, status INTEGER, body BLOB,
                                  error TEXT);
CREATE TABLE IF NOT EXISTS queue (url TEXT PRIMARY KEY, site TEXT, kind TEXT, added_at TEXT, done INTEGER DEFAULT 0);
"""
USER_AGENT = "Mozilla/5.0 (compatible; laptop-specs-research/1.0; one-time, slow)"

# Kody modeli (te same wzory w unreachable_sniper/sniper/specs.py: model_codes - test MODEL_CODE_PARITY):
# Lenovo „15ITL6 / 14ALC6 / 15IAH7”, ASUS „X515MA / FX506HC / K513EA”, Acer „A315-56 / AN515-58 / SF314-511 / N20C5”,
# Dell / HP / Lenovo biznesowe „Latitude 5320 / EliteBook 840 G5 / ThinkPad T480”, HP „15s-eq2 / 15-dw1 / 250 G8”.
_LENOVO = r"\d{2}(?:itl|alc|iil|are|ada|ach|iah|iau|irh|imh|iml|ikb|isk|ast|ihu|ara|abr|apr|amn|aba|irl|iap|arh|aph|irx)\d{0,2}"
MODEL_CODE = re.compile(
    r"\b(" + _LENOVO +
    r"|(?:an|a|sf|sp|sv|ph|pt|ex|en|ag|al|aspire\s?)\d{3}-\d{2,3}[a-z]?"
    r"|n\d{2}[a-z]\d"
    r"|(?:latitude|inspiron|vostro|precision|elitebook|probook|zbook)\s?\d{3,4}[a-z]?(?:\s?g\d{1,2})?"
    r"|thinkpad\s?[a-z]\d{2,3}[a-z]?(?:\s?gen\s?\d)?"
    r"|\d{2}s?-[a-z]{2}\d{1,4}"
    r"|\d{3}\s?g\d{1,2}"
    r"|[a-z]{1,2}\d{3}[a-z]{1,3})\b")
_NOT_CODES = re.compile(r"^(?:rtx|gtx|mx|rx|i[3579]|m\d|ddr|gb|tb)\d|^\d{3}g[b]?$")


def model_codes(text):
    """Kody modeli z tekstu (małe litery, bez spacji) - kolejność wystąpienia, bez powtórzeń."""
    out = []
    for match in MODEL_CODE.finditer((text or "").lower()):
        code = re.sub(r"\s+", "", match.group(1))
        if _NOT_CODES.match(code) or code in out:
            continue
        out.append(code)
    return out


def open_db(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def default_path(db_path):
    return Path(db_path).parent / "specdb.sqlite"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------------------------- 1. własne ogłoszenia
def learn(conn, spec_conn, min_offers=3, min_share=0.8, progress=None):
    """Kody z ogłoszeń laptopów, w których sprzedawca podał procesor → model_specs (source="vinted"). Kod pewny, gdy
    ≥ min_offers ofert i ≥ min_share zgodnych co do linii + generacji procesora (i karty, jeśli jest). → liczba kodów."""
    from .analysis import cpu_line_of
    from .guide import cpu_generation
    say = progress or (lambda _t: None)
    by_code = defaultdict(list)
    sql = """SELECT l.title, d.description, f.cpu, f.gpu FROM listings l JOIN features f ON f.listing_id = l.id
             LEFT JOIN details d ON d.listing_id = l.id WHERE l.category = 'laptop' AND f.cpu IS NOT NULL"""
    for n, (title, desc, cpu, gpu) in enumerate(conn.execute(sql), 1):
        if n % 20000 == 0:
            say(f"  ... {n} ofert")
        bucket = (cpu_line_of(cpu), cpu_generation(cpu))
        if not bucket[1]:
            continue
        for code in set(model_codes(title) + model_codes((desc or "")[:400])):
            by_code[code].append((bucket, cpu, gpu if gpu and gpu != "integrated" else None))
    rows = []
    for code, items in by_code.items():
        if len(items) < min_offers:
            continue
        (bucket, n_top), = Counter(b for b, _c, _g in items).most_common(1)
        if n_top / len(items) < min_share:
            continue
        cpu = Counter(c for b, c, _g in items if b == bucket).most_common(1)[0][0]
        gpus = Counter(g for b, _c, g in items if b == bucket)
        gpu, n_gpu = gpus.most_common(1)[0]
        gpu = gpu if gpu and n_gpu / n_top >= min_share else None
        rows.append((code, None, None, cpu, gpu, None, None, None, "vinted", None, len(items), _now()))
    spec_conn.execute("DELETE FROM model_specs WHERE source = 'vinted'")
    spec_conn.executemany("INSERT INTO model_specs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    spec_conn.commit()
    return len(rows)


# ---------------------------------------------------------------------------------------------- 2. strony
def _jsonld_products(html):
    """Ogólny parser: produkty schema.org z <script type="application/ld+json"> → konfiguracje."""
    out = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
                if item.get("@type") in ("Product", "ProductModel"):
                    text = " ".join(str(item.get(k) or "") for k in ("name", "model", "mpn", "sku", "description"))
                    props = item.get("additionalProperty") or []
                    text += " " + " ".join(f"{p.get('name')}: {p.get('value')}" for p in props if isinstance(p, dict))
                    out.append(config_from_text(text, name=item.get("name"), brand=(item.get("brand") or {}).get(
                        "name") if isinstance(item.get("brand"), dict) else item.get("brand")))
            elif isinstance(item, list):
                stack.extend(item)
    return [c for c in out if c.get("code") and (c.get("cpu") or c.get("gpu"))]


def config_from_text(text, name=None, brand=None, url=None):
    """Konfiguracja z dowolnego tekstu specyfikacji (te same wzory co ogłoszenia: analyzer/extract.py)."""
    from .extract import _cpu, _gpu, _ram, _storage, cpu_gen_text, norm
    t = norm(text)
    codes = model_codes(f"{name or ''} {text}")
    gpu = _gpu(t)
    return {"code": codes[0] if codes else None, "brand": brand, "name": name, "cpu": _cpu(t) or cpu_gen_text(t),
            "gpu": gpu if gpu and gpu != "integrated" else None, "ram_gb": _ram(t, loose=True),
            "ssd_gb": _storage(t, loose=True), "url": url}


# Parsery stron: nazwa → {"list": html → [adresy modeli], "model": html → [konfiguracje]}. Dopisujemy po próbkach HTML
# od użytkownika (struktura każdej strony inna); do tego czasu ogólny parser JSON-LD.
SITES = {
    "jsonld": {"list": lambda html, base: [], "model": lambda html: _jsonld_products(html)},
}


class Fetcher:
    """Pobieranie stron w ludzkim tempie: jedna naraz, losowa przerwa, dłuższa co `long_every` stron, robots.txt,
    403 / 429 = koniec przebiegu. Każda strona trafia do `pages` (drugi raz nie pobieramy)."""

    def __init__(self, spec_conn, site, pause=(25.0, 90.0), long_every=40, long_pause=(600.0, 1500.0), client=None,
                 sleep=time.sleep, say=print, rng=None):
        import httpx
        self.conn, self.site, self.pause, self.long_every, self.long_pause = spec_conn, site, pause, long_every, \
            long_pause
        self.client = client or httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "pl,en;q=0.8"},
                                             timeout=30.0, follow_redirects=True, trust_env=False)
        self.sleep, self.say, self.rng = sleep, say, rng or random.Random()
        self.robots = {}
        self.count = 0

    def allowed(self, url):
        from urllib.robotparser import RobotFileParser
        host = urlparse(url)
        root = f"{host.scheme}://{host.netloc}"
        if root not in self.robots:
            parser = RobotFileParser()
            try:
                r = self.client.get(root + "/robots.txt")
                parser.parse(r.text.splitlines() if r.status_code == 200 else [])
            except Exception:
                parser.parse([])
            self.robots[root] = parser
        return self.robots[root].can_fetch(USER_AGENT, url)

    def get(self, url):
        """→ HTML (z pamięci albo pobrany) albo None; wyjątek StopCrawl przy 403 / 429."""
        row = self.conn.execute("SELECT body, status FROM pages WHERE url = ?", (url,)).fetchone()
        if row and row["body"] is not None:
            return zlib.decompress(row["body"]).decode("utf-8", "replace")
        if not self.allowed(url):
            self.say(f"  robots.txt zabrania: {url}")
            self._save(url, None, None, "robots.txt")
            return None
        if self.count:
            wait = self.rng.uniform(*self.pause)
            if self.long_every and self.count % self.long_every == 0:
                wait += self.rng.uniform(*self.long_pause)
                self.say(f"  dłuższa przerwa: {wait / 60:.0f} min")
            self.sleep(wait)
        self.count += 1
        try:
            r = self.client.get(url)
        except Exception as exc:
            self._save(url, None, None, f"{type(exc).__name__}: {exc}"[:200])
            return None
        if r.status_code in (403, 429):
            self._save(url, r.status_code, None, "blokada")
            raise StopCrawl(f"{r.status_code} na {url} - kończę (nie obchodzimy blokad; spróbuj za kilka dni / API)")
        self._save(url, r.status_code, r.text if r.status_code == 200 else None, None)
        return r.text if r.status_code == 200 else None

    def _save(self, url, status, html, error):
        body = zlib.compress(html.encode("utf-8")) if html is not None else None
        self.conn.execute("INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?, ?)",
                          (url, self.site, _now(), status, body, error))
        self.conn.commit()


class StopCrawl(Exception):
    pass


def crawl(spec_conn, site, start_urls, max_pages=200, fetcher=None, say=print):
    """Kolejka: strony list (adresy modeli) → strony modeli (konfiguracje → model_specs). Wznawia się (queue.done).
    → (pobranych stron, zapisanych konfiguracji)."""
    parser = SITES[site]
    fetcher = fetcher or Fetcher(spec_conn, site, say=say)
    for url in start_urls:
        spec_conn.execute("INSERT OR IGNORE INTO queue VALUES (?, ?, 'list', ?, 0)", (url, site, _now()))
    spec_conn.commit()
    pages = configs = 0
    try:
        while pages < max_pages:
            row = spec_conn.execute("SELECT url, kind FROM queue WHERE site = ? AND done = 0 ORDER BY kind = 'list' "
                                    "DESC, added_at LIMIT 1", (site,)).fetchone()
            if not row:
                break
            html = fetcher.get(row["url"])
            pages += 1
            if html:
                if row["kind"] == "list":
                    for link in parser["list"](html, row["url"]):
                        spec_conn.execute("INSERT OR IGNORE INTO queue VALUES (?, ?, 'model', ?, 0)",
                                          (urljoin(row["url"], link), site, _now()))
                found = parser["model"](html)
                for c in found:
                    spec_conn.execute("INSERT INTO model_specs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                      (c["code"], c.get("brand"), c.get("name"), c.get("cpu"), c.get("gpu"),
                                       c.get("ram_gb"), c.get("ssd_gb"), c.get("year"), site, row["url"], 1, _now()))
                configs += len(found)
            spec_conn.execute("UPDATE queue SET done = 1 WHERE url = ?", (row["url"],))
            spec_conn.commit()
            say(f"  [{pages}] {row['url']} → {configs} konfiguracji razem")
    except StopCrawl as exc:
        say(f"  STOP: {exc}")
    return pages, configs


# ---------------------------------------------------------------------------------------------- 3. eksport
def code_map(spec_conn, min_share=0.8):
    """Kod → {"cpu", "gpu"} tylko, gdy konfiguracje zgadzają się co do linii + generacji procesora (≥ min_share);
    karta - gdy zgodna, inaczej None. Ogłoszenia (vinted) liczą się wagą n."""
    from .analysis import cpu_line_of
    from .guide import cpu_generation
    by_code = defaultdict(list)
    for code, cpu, gpu, n in spec_conn.execute("SELECT code, cpu, gpu, COALESCE(n, 1) FROM model_specs "
                                               "WHERE code IS NOT NULL AND cpu IS NOT NULL"):
        bucket = (cpu_line_of(cpu), cpu_generation(cpu))
        if bucket[1]:
            by_code[code].extend([(bucket, cpu, gpu)] * max(1, int(n)))
    out = {}
    for code, items in by_code.items():
        (bucket, n_top), = Counter(b for b, _c, _g in items).most_common(1)
        if n_top / len(items) < min_share:
            continue
        cpu = Counter(c for b, c, _g in items if b == bucket).most_common(1)[0][0]
        gpu, n_gpu = Counter(g for b, _c, g in items if b == bucket).most_common(1)[0]
        out[code] = {"cpu": cpu, "gpu": gpu if gpu and n_gpu / n_top >= min_share else None}
    return out


def lookup(codes_map, *texts):
    """Pierwszy znany kod z tekstów → {"cpu", "gpu", "code"} albo None."""
    for text in texts:
        for code in model_codes(text):
            if code in codes_map:
                return {**codes_map[code], "code": code}
    return None


def load_for(conn):
    """Mapa kodów z specdb.sqlite obok bazy analizatora (pusta, gdy pliku brak)."""
    try:
        path = conn.execute("PRAGMA database_list").fetchone()[2]
    except (sqlite3.Error, TypeError, IndexError):
        return {}
    if not path:
        return {}
    spec_path = default_path(path)
    if not spec_path.exists():
        return {}
    spec_conn = sqlite3.connect(f"file:{spec_path.as_posix()}?mode=ro", uri=True)
    try:
        return code_map(spec_conn)
    except sqlite3.Error:
        return {}
    finally:
        spec_conn.close()


def status(spec_conn):
    lines = []
    for source, n, codes in spec_conn.execute("SELECT source, COUNT(*), COUNT(DISTINCT code) FROM model_specs "
                                              "GROUP BY source"):
        lines.append(f"  {source}: {n} konfiguracji, {codes} kodów")
    pages = spec_conn.execute("SELECT COUNT(*), SUM(body IS NOT NULL) FROM pages").fetchone()
    queue = spec_conn.execute("SELECT COUNT(*), SUM(done = 0) FROM queue").fetchone()
    lines.append(f"  strony: {pages[0]} (z treścią {pages[1] or 0}); kolejka: {queue[0]} (do pobrania {queue[1] or 0})")
    lines.append(f"  pewnych kodów do wyceny (eksport do comparables.db): {len(code_map(spec_conn))}")
    return "\n".join(lines)
