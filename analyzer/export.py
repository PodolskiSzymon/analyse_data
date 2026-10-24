"""Eksport do analizy w czacie (PLAN_ANALIZY.md, A6): `python -m analyzer export-analysis [--with-descriptions]`.

Bez sieci, główna baza tylko do odczytu, zapis strumieniowy (gzip) do `<folder bazy>/export/<RRRR-MM-DD>/`:
  * listings.csv.gz         - oferty (bez `seller_hash`, `photo_url`; bez stanów ignored / unclassified),
  * features.csv.gz         - parametry z ekstrakcji (z fields_json),
  * observations_real.csv.gz - tylko PRAWDZIWE zmiany ceny / rezerwacji (db.real_change, bez dryfu kursu) +
                              pierwsza obserwacja każdej oferty,
  * crawl_runs.csv          - przejścia,
  * flags.csv, relists.csv  - z analysis.db (jeśli był `report` / `suspicious-report` / `relist-report`),
  * descriptions.jsonl.gz   - (opcja) opis z zamaskowanym e-mailem / telefonem / linkiem (sample.redact), obcięty do
                              2000 znaków, + atrybuty formularza.
RODO: bez danych sprzedawców (ID, nazwa, hash) - zostaje tylko kraj sprzedawcy.
"""
import csv
import gzip
import json

from . import analysis, db
from .progress import Bar
from .sample import redact

SKIP_COLUMNS = {"seller_hash", "photo_url"}
SKIP_STATES = ("ignored", "unclassified")
DESC_CHARS = 2000
TARGET_MB = 50


def _columns(conn, table, skip=()):
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] not in skip]


def _write(path, header, rows, label, total=None, progress=True):
    bar = Bar(label, total) if progress else None
    opener = (lambda: gzip.open(path, "wt", encoding="utf-8", newline="")) if path.suffix == ".gz" else \
        (lambda: open(path, "w", encoding="utf-8", newline=""))
    n = 0
    with opener() as f:
        w = csv.writer(f)
        w.writerow(header)
        for n, row in enumerate(rows, 1):
            w.writerow(row)
            if bar and n % 5000 == 0:
                bar.update(n)
    if bar:
        bar.update(n)
        bar.finish()
    return n


def real_observations(conn):
    """Obserwacje bez dryfu kursu: pierwsza oferty + każda prawdziwa zmiana (strumieniowo, kolejność klucza)."""
    sql = """SELECT o.listing_id, o.seen_at, o.price, o.total_price, o.is_reserved, o.favourite_count,
                    COALESCE(d.seller_currency, l.seller_currency) AS cur
             FROM observations o JOIN listings l ON l.id = o.listing_id
             LEFT JOIN details d ON d.listing_id = o.listing_id
             WHERE l.state NOT IN ('ignored', 'unclassified')
             ORDER BY o.listing_id, o.seen_at"""
    current, last = None, None
    for r in conn.execute(sql):
        obs = {"price": r["price"], "is_reserved": r["is_reserved"]}
        if r["listing_id"] != current:
            current, last = r["listing_id"], None
        if last is None or db.real_change(last, obs, r["cur"]):
            last = obs
            yield (r["listing_id"], r["seen_at"], r["price"], r["total_price"], r["is_reserved"],
                   r["favourite_count"])


def run(conn, out, aconn=None, with_descriptions=False, progress=True, say=None):
    """→ {nazwa pliku: (wierszy, bajtów)}."""
    say = say or (lambda _t: None)
    files = {}
    marks = ",".join("?" * len(SKIP_STATES))

    cols = _columns(conn, "listings", SKIP_COLUMNS)
    total = conn.execute(f"SELECT COUNT(*) FROM listings WHERE state NOT IN ({marks})", SKIP_STATES).fetchone()[0]
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM listings WHERE state NOT IN ({marks}) ORDER BY id",
                        SKIP_STATES)
    files["listings.csv.gz"] = _write(out / "listings.csv.gz", cols, rows, "listings", total, progress)

    cols = _columns(conn, "features")
    total = conn.execute("SELECT COUNT(*) FROM features").fetchone()[0]
    rows = conn.execute(f"SELECT {', '.join(cols)} FROM features ORDER BY listing_id")
    files["features.csv.gz"] = _write(out / "features.csv.gz", cols, rows, "features", total, progress)

    total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    files["observations_real.csv.gz"] = _write(
        out / "observations_real.csv.gz",
        ["listing_id", "seen_at", "price", "total_price", "is_reserved", "favourite_count"],
        real_observations(conn), "observations (z wszystkich)", None, progress)
    say(f"  observations: {total} w bazie → {files['observations_real.csv.gz']} prawdziwych zmian")

    cols = _columns(conn, "crawl_runs")
    files["crawl_runs.csv"] = _write(out / "crawl_runs.csv", cols, conn.execute(
        f"SELECT {', '.join(cols)} FROM crawl_runs ORDER BY id"), "crawl_runs", None, False)

    if aconn is not None:
        files["flags.csv"] = _write(out / "flags.csv", ["listing_id", "flag", "detail"], aconn.execute(
            "SELECT listing_id, flag, detail FROM flags ORDER BY listing_id"), "flags", None, False)
        files["relists.csv"] = _write(out / "relists.csv", ["old_id", "new_id", "score", "basis", "gap_days"],
                                      aconn.execute("SELECT old_id, new_id, score, basis, gap_days FROM relists "
                                                    "ORDER BY new_id"), "relists", None, False)

    if with_descriptions:
        total = conn.execute(f"SELECT COUNT(*) FROM details d JOIN listings l ON l.id = d.listing_id WHERE "
                             f"l.state NOT IN ({marks})", SKIP_STATES).fetchone()[0]
        bar = Bar("opisy", total) if progress else None
        n = 0
        with gzip.open(out / "descriptions.jsonl.gz", "wt", encoding="utf-8") as f:
            for n, r in enumerate(conn.execute(
                    f"""SELECT d.listing_id, d.description, d.attributes_json, d.source, d.is_localized
                        FROM details d JOIN listings l ON l.id = d.listing_id WHERE l.state NOT IN ({marks})
                        ORDER BY d.listing_id""", SKIP_STATES), 1):
                try:
                    attrs = json.loads(r["attributes_json"] or "{}")
                except ValueError:
                    attrs = {}
                f.write(json.dumps({"id": r["listing_id"], "description": redact(r["description"])[:DESC_CHARS],
                                    "attributes": attrs, "source": r["source"], "localized": r["is_localized"]},
                                   ensure_ascii=False) + "\n")
                if bar and n % 5000 == 0:
                    bar.update(n)
        if bar:
            bar.update(n)
            bar.finish()
        files["descriptions.jsonl.gz"] = n
    return {name: (n, (out / name).stat().st_size) for name, n in files.items()}


def size_lines(result, out):
    lines = [f"Eksport -> {out}"]
    total = 0
    for name, (n, size) in result.items():
        total += size
        lines.append(f"  {name:<26} {n:>9} wierszy  {size / 1e6:8.2f} MB")
    lines.append(f"  {'razem':<26} {'':>9}          {total / 1e6:8.2f} MB")
    if total > TARGET_MB * 1e6:
        lines.append(f"  ⚠ ponad {TARGET_MB} MB - wyślij bez descriptions.jsonl.gz albo same listings + features.")
    return lines
