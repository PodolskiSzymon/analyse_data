"""Porównywalne oferty dla Snipera (2026-10-26, pomysł użytkownika: „biorę części tytułu, sprawdzam w bazie medianę
takich przedmiotów” - jak przy laptopach po karcie graficznej, ale dla każdego ogłoszenia).

`build()` (wołane w `sniper-guide` i w automacie) zapisuje `<guides>/comparables.db`: tytuł (słowa jak w Sniperze:
małe litery, litery i cyfry rozdzielone, „PS5” → „playstation 5”), kategoria, cena, czy oferta zniknęła. Indeks
pełnotekstowy SQLite FTS5 + słownik częstości słów (fts5vocab) - Sniper szuka po rzadkich (znaczących) słowach tytułu.
Tylko sprawne: bez flag wykluczających, ponownych wystawień i uszkodzonych (AI / reguły). Bez danych sprzedawców.
Plik ~kilkadziesiąt MB, budowa strumieniowo (4 GB RAM u użytkownika).

Laptopy dodatkowo w tabeli `laptop_specs` (2026-11-01, pomysł użytkownika: „za specyfikację ludzie płacą, nie za
model”): karta graficzna (dedykowana), linia procesora + generacja, chip i linia MacBooka, RAM, dysk (przedział) -
Sniper liczy mediany od najdokładniejszej specyfikacji do samej karty / procesora (sniper/specs.py, te same reguły).
"""
import re
import sqlite3
from pathlib import Path

STATES = ("active", "reserved", "sold", "blocked", "deleted", "closed")
GONE = ("sold", "blocked", "deleted", "closed")
_ALIASES = ((re.compile(r"\bps\s?([345])\b"), r"playstation \1"), (re.compile(r"\bgameboy\b"), "game boy"))


def tokens(text):
    """Te same słowa co sniper/guides.py: tokens (musi zostać zgodne)."""
    text = (text or "").lower()
    for pattern, repl in _ALIASES:
        text = pattern.sub(repl, text)
    # Litery z każdego języka (RO „vând”, SE „säljer”, CZ „prodám”) - samo [a-ząćęłńóśźż] cięło słowa na kawałki.
    text = re.sub(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", " ", text)
    return re.findall(r"[^\W\d_]+|\d+", text)


DEDICATED_GPU = re.compile(r"(rtx|gtx|rx|arc|quadro)\b")
SSD_BUCKETS = ((160, 128), (300, 256), (600, 512), (1200, 1000), (2500, 2000))


def ssd_bucket(gb):
    """Pojemność dysku → przedział (120/128 → 128, 240/250/256 → 256, 480/500/512 → 512, 1 TB, 2 TB, więcej)."""
    if not gb or gb < 32:
        return None
    return next((value for limit, value in SSD_BUCKETS if gb <= limit), 4000)


def laptop_spec(model, cpu, cpu_line, gpu, ram_gb, storage_gb):
    """Specyfikacja laptopa do median (jak sniper/specs.py: laptop_spec) → słownik albo None (za mało danych).
    Ścieżki: karta dedykowana | MacBook (linia + chip) | procesor (linia + generacja)."""
    from .analysis import cpu_line_of
    from .guide import cpu_generation

    gpu = (gpu or "").lower().strip()
    cpu = (cpu or "").lower().strip()
    model = (model or "").lower()
    chip = re.search(r"apple (m\d(?: (?:pro|max|ultra))?)", cpu)
    line = ("macbook air" if "air" in model else "macbook pro" if "pro" in model else None) if "macbook" in model or chip \
        else None
    spec = {"gpu": gpu if DEDICATED_GPU.match(gpu) else None,
            "cpu_line": cpu_line_of(cpu or None, cpu_line), "cpu_gen": cpu_generation(cpu) if cpu else None,
            "chip": chip.group(1) if chip else None, "line": line,
            "ram": int(ram_gb) if ram_gb else None, "ssd": ssd_bucket(storage_gb)}
    if spec["cpu_line"] and spec["cpu_line"].startswith("intel core ultra"):
        spec["cpu_gen"] = "core ultra"
    if spec["gpu"] or (spec["chip"] and spec["line"]) or (spec["cpu_line"] and spec["cpu_gen"]):
        return spec
    return None


def build(conn, path, excluded=None, old_ids=None, ai_damaged=None, progress=None):
    """→ liczba ofert zapisanych do `path` (plik budowany obok i podmieniany na końcu)."""
    say = progress or (lambda _t: None)
    excluded, old_ids, ai_damaged = excluded or {}, old_ids or set(), ai_damaged or {}
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    out = sqlite3.connect(str(tmp))
    out.executescript("""
        CREATE VIRTUAL TABLE offers USING fts5(words, category UNINDEXED, price UNINDEXED, gone UNINDEXED,
                                               tokenize = 'unicode61 remove_diacritics 2');
        CREATE VIRTUAL TABLE vocab USING fts5vocab(offers, 'row');
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE laptop_specs (gpu TEXT, cpu_line TEXT, cpu_gen TEXT, chip TEXT, line TEXT, ram INTEGER,
                                   ssd INTEGER, price REAL, gone INTEGER);
    """)
    sql = f"""SELECT l.id, l.category, l.title, l.state, l.price_now, l.sold_price,
                     COALESCE(f.for_parts, 0) OR COALESCE(f.locked, 0) OR COALESCE(f.cracked, 0) AS damaged,
                     f.model, f.cpu, f.cpu_line, f.gpu, f.ram_gb, f.storage_gb
              FROM listings l LEFT JOIN features f ON f.listing_id = l.id
              WHERE l.category IS NOT NULL AND l.state IN ({",".join("?" * len(STATES))})"""
    batch, specs, n, n_specs = [], [], 0, 0
    for r in conn.execute(sql, STATES):
        lid = r[0]
        if lid in excluded or lid in old_ids or ai_damaged.get(lid, bool(r[6])):
            continue
        gone = r[3] in GONE
        price = (r[5] if r[5] is not None else r[4]) if gone else r[4]
        words = " ".join(tokens(r[2]))
        if price is None or price <= 0 or not words:
            continue
        batch.append((words, r[1], float(price), int(gone)))
        if r[1] == "laptop":
            spec = laptop_spec(*r[7:13])
            if spec:
                specs.append((spec["gpu"], spec["cpu_line"], spec["cpu_gen"], spec["chip"], spec["line"], spec["ram"],
                              spec["ssd"], float(price), int(gone)))
        if len(batch) >= 20000:
            out.executemany("INSERT INTO offers VALUES (?, ?, ?, ?)", batch)
            n += len(batch)
            batch = []
            say(f"  porównywalne: {n} ofert...")
        if len(specs) >= 20000:
            out.executemany("INSERT INTO laptop_specs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", specs)
            n_specs += len(specs)
            specs = []
    if batch:
        out.executemany("INSERT INTO offers VALUES (?, ?, ?, ?)", batch)
        n += len(batch)
    if specs:
        out.executemany("INSERT INTO laptop_specs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", specs)
        n_specs += len(specs)
    out.executescript("""
        CREATE INDEX laptop_specs_gpu ON laptop_specs(gpu, ram, ssd);
        CREATE INDEX laptop_specs_cpu ON laptop_specs(cpu_line, cpu_gen, ram, ssd);
        CREATE INDEX laptop_specs_mac ON laptop_specs(line, chip, ram, ssd);""")
    out.execute("INSERT INTO meta VALUES ('rows', ?)", (str(n),))
    out.execute("INSERT INTO meta VALUES ('laptop_specs', ?)", (str(n_specs),))
    say(f"  laptopy ze specyfikacją (mediany po GPU / CPU / RAM / dysku): {n_specs}")
    out.execute("INSERT INTO offers(offers) VALUES ('optimize')")
    out.commit()
    out.close()
    tmp.replace(path)
    return n
