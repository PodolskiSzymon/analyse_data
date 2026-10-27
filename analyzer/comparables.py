"""Porównywalne oferty dla Snipera (2026-10-26, pomysł użytkownika: „biorę części tytułu, sprawdzam w bazie medianę
takich przedmiotów” - jak przy laptopach po karcie graficznej, ale dla każdego ogłoszenia).

`build()` (wołane w `sniper-guide` i w automacie) zapisuje `<guides>/comparables.db`: tytuł (słowa jak w Sniperze:
małe litery, litery i cyfry rozdzielone, „PS5” → „playstation 5”), kategoria, cena, czy oferta zniknęła. Indeks
pełnotekstowy SQLite FTS5 + słownik częstości słów (fts5vocab) - Sniper szuka po rzadkich (znaczących) słowach tytułu.
Tylko sprawne: bez flag wykluczających, ponownych wystawień i uszkodzonych (AI / reguły). Bez danych sprzedawców.
Plik ~kilkadziesiąt MB, budowa strumieniowo (4 GB RAM u użytkownika).
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
    """)
    sql = f"""SELECT l.id, l.category, l.title, l.state, l.price_now, l.sold_price,
                     COALESCE(f.for_parts, 0) OR COALESCE(f.locked, 0) OR COALESCE(f.cracked, 0) AS damaged
              FROM listings l LEFT JOIN features f ON f.listing_id = l.id
              WHERE l.category IS NOT NULL AND l.state IN ({",".join("?" * len(STATES))})"""
    batch, n = [], 0
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
        if len(batch) >= 20000:
            out.executemany("INSERT INTO offers VALUES (?, ?, ?, ?)", batch)
            n += len(batch)
            batch = []
            say(f"  porównywalne: {n} ofert...")
    if batch:
        out.executemany("INSERT INTO offers VALUES (?, ?, ?, ?)", batch)
        n += len(batch)
    out.execute("INSERT INTO meta VALUES ('rows', ?)", (str(n),))
    out.execute("INSERT INTO offers(offers) VALUES ('optimize')")
    out.commit()
    out.close()
    tmp.replace(path)
    return n
