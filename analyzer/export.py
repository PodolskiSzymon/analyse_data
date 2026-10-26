"""Eksport do analizy w czacie (PLAN_ANALIZY.md, A6): `python -m analyzer export-analysis [--with-descriptions]
[--split]`.

Bez sieci, główna baza tylko do odczytu, zapis strumieniowy (gzip) do `<folder bazy>/export/<RRRR-MM-DD>/`:
  * listings.csv.gz         - oferty (bez `photo_url`; bez stanów ignored / unclassified); `seller_hash` = ten sam
                              sprzedawca → ten sam kod (handlarze, relisty, „ofert na sprzedawcę”), bez nicka,
  * features.csv.gz         - parametry z ekstrakcji (z fields_json),
  * observations_real.csv.gz - tylko PRAWDZIWE zmiany ceny / rezerwacji (db.real_change, bez dryfu kursu) +
                              pierwsza obserwacja każdej oferty,
  * crawl_runs.csv          - przejścia,
  * flags.csv, relists.csv  - z analysis.db (jeśli był `report` / `suspicious-report` / `relist-report`),
  * descriptions.jsonl.gz   - (opcja) opis z zamaskowanym e-mailem / telefonem / linkiem (sample.redact), obcięty do
                              2000 znaków, + atrybuty formularza.
`--split` (2026-10-26): pliki per oferta (listings, features, observations, opisy) w podfolderach `<kategoria>/` -
jeden folder = jedna paczka do wysłania (mniejsze pliki, statystyki kategorii w całości); crawl_runs / flags /
relists zostają wspólne w folderze głównym. Jedno przejście po tabelach (4 GB RAM), pliki otwarte naraz.
"""
import csv
import gzip
import json

from . import analysis, db
from .progress import Bar
from .sample import redact

SKIP_COLUMNS = {"photo_url"}
NO_CATEGORY = "bez_kategorii"
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
    """Obserwacje bez dryfu kursu: pierwsza oferty + każda prawdziwa zmiana (strumieniowo, kolejność klucza)
    → (kategoria, wiersz)."""
    sql = """SELECT o.listing_id, o.seen_at, o.price, o.total_price, o.is_reserved, o.favourite_count,
                    COALESCE(d.seller_currency, l.seller_currency) AS cur, l.category
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
            yield r["category"], (r["listing_id"], r["seen_at"], r["price"], r["total_price"], r["is_reserved"],
                                  r["favourite_count"])


class _Files:
    """Pliki csv(.gz) otwierane przy pierwszym wierszu: jeden (split=False) albo po jednym na kategorię."""

    def __init__(self, out, name, header, split):
        self.out, self.name, self.header, self.split = out, name, header, split
        self.files, self.counts = {}, {}

    def path(self, key):
        return self.out / (f"{key or NO_CATEGORY}/{self.name}" if self.split else self.name)

    def _writer(self, key):
        key = (key or NO_CATEGORY) if self.split else ""
        if key not in self.files:
            path = self.path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            f = gzip.open(path, "wt", encoding="utf-8", newline="") if path.suffix == ".gz" else \
                open(path, "w", encoding="utf-8", newline="")
            w = csv.writer(f)
            if self.header:
                w.writerow(self.header)
            self.files[key], self.counts[key] = (f, w), 0
        return key, self.files[key]

    def write(self, key, row):
        key, (_f, w) = self._writer(key)
        w.writerow(row)
        self.counts[key] += 1

    def raw(self, key, text):
        key, (f, _w) = self._writer(key)
        f.write(text)
        self.counts[key] += 1

    def close(self):
        for f, _w in self.files.values():
            f.close()
        if not self.files and not self.split:          # pusty plik z nagłówkiem, jak wcześniej
            self._writer("")
            self.files[""][0].close()
        return {(f"{k}/{self.name}" if self.split else self.name): n for k, n in self.counts.items()}


def _stream(files, rows, label, total, progress):
    """rows: (kategoria, wiersz) → pliki; pasek postępu co 5000."""
    bar = Bar(label, total) if progress else None
    n = 0
    for n, (key, row) in enumerate(rows, 1):
        files.write(key, row)
        if bar and n % 5000 == 0:
            bar.update(n)
    if bar:
        bar.update(n)
        bar.finish()
    return files.close()


def run(conn, out, aconn=None, with_descriptions=False, progress=True, say=None, split=False):
    """→ {ścieżka pliku względem out: (wierszy, bajtów)}."""
    say = say or (lambda _t: None)
    files = {}
    marks = ",".join("?" * len(SKIP_STATES))

    cols = _columns(conn, "listings", SKIP_COLUMNS)
    total = conn.execute(f"SELECT COUNT(*) FROM listings WHERE state NOT IN ({marks})", SKIP_STATES).fetchone()[0]
    rows = conn.execute(f"SELECT category, {', '.join(cols)} FROM listings WHERE state NOT IN ({marks}) ORDER BY id",
                        SKIP_STATES)
    files.update(_stream(_Files(out, "listings.csv.gz", cols, split), ((r[0], r[1:]) for r in rows), "listings",
                         total, progress))

    cols = _columns(conn, "features")
    total = conn.execute("SELECT COUNT(*) FROM features").fetchone()[0]
    rows = conn.execute(f"SELECT l.category, {', '.join('f.' + c for c in cols)} FROM features f "
                        f"LEFT JOIN listings l ON l.id = f.listing_id ORDER BY f.listing_id")
    files.update(_stream(_Files(out, "features.csv.gz", cols, split), ((r[0], r[1:]) for r in rows), "features",
                         total, progress))

    total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    obs = _stream(_Files(out, "observations_real.csv.gz",
                         ["listing_id", "seen_at", "price", "total_price", "is_reserved", "favourite_count"], split),
                  real_observations(conn), "observations (z wszystkich)", None, progress)
    files.update(obs)
    say(f"  observations: {total} w bazie → {sum(obs.values())} prawdziwych zmian")

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
        descs = _Files(out, "descriptions.jsonl.gz", None, split)
        n = 0
        for n, r in enumerate(conn.execute(
                f"""SELECT d.listing_id, d.description, d.attributes_json, d.source, d.is_localized, l.category
                    FROM details d JOIN listings l ON l.id = d.listing_id WHERE l.state NOT IN ({marks})
                    ORDER BY d.listing_id""", SKIP_STATES), 1):
            try:
                attrs = json.loads(r["attributes_json"] or "{}")
            except ValueError:
                attrs = {}
            descs.raw(r["category"], json.dumps({"id": r["listing_id"],
                                                 "description": redact(r["description"])[:DESC_CHARS],
                                                 "attributes": attrs, "source": r["source"],
                                                 "localized": r["is_localized"]}, ensure_ascii=False) + "\n")
            if bar and n % 5000 == 0:
                bar.update(n)
        if bar:
            bar.update(n)
            bar.finish()
        files.update(descs.close())
    return {name: (n, (out / name).stat().st_size) for name, n in sorted(files.items())}


def size_lines(result, out):
    lines = [f"Eksport -> {out}"]
    total = 0
    for name, (n, size) in result.items():
        total += size
        lines.append(f"  {name:<36} {n:>9} wierszy  {size / 1e6:8.2f} MB")
    lines.append(f"  {'razem':<36} {'':>9}          {total / 1e6:8.2f} MB")
    folders = {}
    for name, (_n, size) in result.items():
        if "/" in name:
            folder = name.split("/")[0]
            folders[folder] = folders.get(folder, 0) + size
    if folders:
        lines.append("Paczki do wysłania (folder = kategoria; wspólne crawl_runs/flags/relists dołącz raz):")
        for folder, size in sorted(folders.items(), key=lambda kv: -kv[1]):
            warn = "  ⚠ duża - wyślij bez descriptions" if size > TARGET_MB * 1e6 else ""
            lines.append(f"  {folder + '/':<36} {size / 1e6:8.2f} MB{warn}")
    elif total > TARGET_MB * 1e6:
        lines.append(f"  ⚠ ponad {TARGET_MB} MB - użyj --split (paczka na kategorię) albo wyślij bez "
                     f"descriptions.jsonl.gz.")
    return lines
