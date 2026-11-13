r"""Odbudowa photos/index.db z folderów ze zdjęciami (po przypadkowym usunięciu).

Każdy folder <katalog>/<id // 1 000 000>/<id>/ z plikami zdjęć = oferta zarchiwizowana:
  source = 'sidebar' gdy w bazie są szczegóły oferty (details_at), inaczej 'catalog' (tylko zdjęcie główne).
Watch pobierze potem zdjęcia tylko ofert, których nie ma w żadnym podanym folderze.

Użycie (watch ZATRZYMANY):
  python odbuduj_index.py --baza data\analyzer.db --index data\photos\index.db E:\photos data\photos
"""
import argparse, os, sqlite3, sys, time
from datetime import datetime, timezone

EXT = (".jpg", ".jpeg", ".webp", ".png")
SCHEMA = """CREATE TABLE IF NOT EXISTS photos (
  listing_id INTEGER PRIMARY KEY, source TEXT, n_urls INTEGER, n_saved INTEGER, bytes INTEGER,
  saved_at TEXT, error TEXT);"""

ap = argparse.ArgumentParser()
ap.add_argument("--baza", required=True, help="analyzer.db")
ap.add_argument("--index", required=True, help="gdzie zapisać index.db (folder zdjęć, z którego korzysta watch)")
ap.add_argument("foldery", nargs="+", help="foldery ze zdjęciami (HDD i serwer)")
a = ap.parse_args()

print("Wczytuję z bazy oferty ze szczegółami...", flush=True)
db = sqlite3.connect(f"file:{a.baza}?mode=ro", uri=True)
with_details = {r[0] for r in db.execute("SELECT id FROM listings WHERE details_at IS NOT NULL")}
db.close()
print(f"  ofert ze szczegółami: {len(with_details):,}", flush=True)

found = {}                                    # id -> (liczba zdjęć, bajty, czas pliku)
t0 = time.time()
for root in a.foldery:
    if not os.path.isdir(root):
        print(f"  pomijam (brak folderu): {root}"); continue
    print(f"Skanuję {root} ...", flush=True)
    for bucket in os.scandir(root):
        if not bucket.is_dir() or not bucket.name.isdigit():
            continue
        for d in os.scandir(bucket.path):
            if not d.is_dir() or not d.name.isdigit():
                continue
            n = size = 0; mtime = 0.0
            for f in os.scandir(d.path):
                if f.is_file() and f.name.lower().endswith(EXT):
                    st = f.stat(); n += 1; size += st.st_size; mtime = max(mtime, st.st_mtime)
            if n:
                lid = int(d.name)
                old = found.get(lid)
                if old is None or n > old[0]:
                    found[lid] = (n, size, mtime)
            if len(found) % 20000 == 0 and n:
                print(f"  ofert: {len(found):,}  ({time.time() - t0:.0f} s)", flush=True)
print(f"Znaleziono ofert ze zdjęciami: {len(found):,} w {time.time() - t0:.0f} s", flush=True)

idx = sqlite3.connect(a.index)
idx.executescript(SCHEMA)
before = idx.execute("SELECT COUNT(*) FROM photos").fetchone()[0]
rows = []
for lid, (n, size, mtime) in found.items():
    src = "sidebar" if lid in with_details else "catalog"
    ts = datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds")
    rows.append((lid, src, n, n, size, ts, None))
with idx:
    # INSERT OR IGNORE: wpisy, które watch zdążył już zapisać w nowym index.db, zostają
    idx.executemany("INSERT OR IGNORE INTO photos (listing_id, source, n_urls, n_saved, bytes, saved_at, error) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
n, s, b = idx.execute("SELECT COUNT(*), SUM(n_saved), SUM(bytes) FROM photos").fetchone()
idx.close()
print(f"index.db: było {before:,} wpisów, teraz {n:,} ofert, {s or 0:,} zdjęć, {(b or 0) / 1e9:.1f} GB -> {a.index}")
