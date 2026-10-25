"""Archiwum zdjęć ofert na dysku (PLAN_ANALIZY.md, E2) - prośba użytkownika 2026-10-25: WSZYSTKIE zdjęcia, serwer ma
~400 GB wolnego miejsca.

* Skąd adresy: zapisane szczegóły oferty (raw `sidebar` → `photos[].full_size_url`), a bez nich samo zdjęcie główne
  z katalogu (`listings.photo_url`); gdy szczegóły dojdą później, brakujące zdjęcia zostaną dociągnięte.
* Pobieranie BEZPOŚREDNIO z CDN Vinted (images*.vinted.net) z domowego IP - bez proxy (zero kosztu Evomi), jak
  `ai_classify` przy SNIPER_AI_PHOTOS=download. Kilka naraz (`ANALYZER_PHOTOS_CONCURRENCY`, domyślnie 4).
* Układ: `<ANALYZER_PHOTOS_DIR albo folder bazy/photos>/<id // 1 000 000>/<id>/01.jpg, 02.jpg…` (podfoldery po
  milionie ID - Windows nie lubi setek tysięcy plików w jednym folderze); indeks w `photos/index.db` (osobna baza -
  główna bez migracji).
* Kolejność: oferty żywe (active / reserved / unlisted), najnowsze najpierw - zanim znikną (po usunięciu Vinted kasuje
  zdjęcia). W `watch` - równolegle z pobieraniem szczegółów, do startu następnego przejścia.
* ~150 KB / zdjęcie, ~6,6 zdjęcia / ofertę: obecne oferty ~150 GB, nowe ~1–2 GB / dzień.
"""
import asyncio
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import analysis, rawstore

log = logging.getLogger("analyzer.photos")

ALIVE = ("active", "reserved", "unlisted")
INDEX_SCHEMA = """
CREATE TABLE IF NOT EXISTS photos (
  listing_id INTEGER PRIMARY KEY,
  source     TEXT,                 -- sidebar (wszystkie zdjęcia) / catalog (tylko główne - szczegółów jeszcze brak)
  n_urls     INTEGER, n_saved INTEGER, bytes INTEGER,
  saved_at   TEXT, error TEXT
);
"""


def photos_dir(cfg):
    return Path(cfg.photos_dir) if getattr(cfg, "photos_dir", "") else Path(cfg.db_path).parent / "photos"


def listing_dir(root, listing_id):
    return Path(root) / str(int(listing_id) // 1_000_000) / str(int(listing_id))


def local_photos(root, listing_id):
    """Zapisane zdjęcia oferty (posortowane) - [] gdy brak."""
    folder = listing_dir(root, listing_id)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".webp", ".png"))


def open_index(root):
    Path(root).mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(Path(root) / "index.db"), timeout=30)
    conn.executescript(INDEX_SCHEMA)
    return conn


def urls_for(conn, row):
    """(źródło, [URL-e]) - wszystkie zdjęcia ze szczegółów, inaczej główne z katalogu."""
    if row["details_at"]:
        from sniper.extractor import extract_photo_urls, unwrap_sidebar

        raw = conn.execute("SELECT body FROM raw WHERE listing_id=? AND kind='sidebar' ORDER BY fetched_at DESC "
                           "LIMIT 1", (row["id"],)).fetchone()
        if raw is not None:
            try:
                urls = extract_photo_urls(unwrap_sidebar(rawstore.decompress(raw[0])))
            except Exception:
                urls = []
            if urls:
                return "sidebar", urls
    return "catalog", [row["photo_url"]] if row["photo_url"] else []


def candidates(conn, index, limit=None):
    """Żywe oferty z naszych kategorii bez archiwum - albo z samym zdjęciem głównym, a szczegóły już są."""
    done = dict(index.execute("SELECT listing_id, source FROM photos").fetchall())
    sql = f"""SELECT id, photo_url, details_at FROM listings
              WHERE state IN ({",".join("?" * len(ALIVE))}) AND category IN ({",".join("?" * len(analysis.CATEGORIES))})
              ORDER BY id DESC"""
    out = []
    for r in conn.execute(sql, (*ALIVE, *analysis.CATEGORIES)):
        source = done.get(r["id"])
        if source == "sidebar" or (source == "catalog" and not r["details_at"]):
            continue
        out.append(r)
        if limit and len(out) >= limit:
            break
    return out


def _ext(url):
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix if suffix in (".jpg", ".jpeg", ".webp", ".png") else ".jpg"


async def archive(cfg, conn, root=None, limit=None, deadline=None, client=None, clock=None, sleep=asyncio.sleep):
    """Pobiera zdjęcia kandydatów do archiwum. deadline (datetime UTC) - koniec pracy (watch). → statystyki."""
    import httpx

    root = Path(root or photos_dir(cfg))
    index = open_index(root)
    clock = clock or (lambda: datetime.now(timezone.utc))
    rows = candidates(conn, index, limit)
    stats = {"offers": 0, "photos": 0, "bytes": 0, "errors": 0}
    log.info("[PHOTOS] Ofert do archiwum zdjęć: %d -> %s", len(rows), root)
    own = client is None
    # Bezpośrednio z domowego IP (trust_env=False) - zdjęcia nie idą przez proxy Evomi.
    client = client or httpx.AsyncClient(trust_env=False, timeout=30.0, follow_redirects=True)
    semaphore = asyncio.Semaphore(max(1, getattr(cfg, "photos_concurrency", 4)))

    async def one(row):
        source, urls = urls_for(conn, row)
        folder = listing_dir(root, row["id"])
        saved, size, error = 0, 0, None
        for i, url in enumerate(urls, 1):
            path = folder / f"{i:02d}{_ext(url)}"
            if path.exists():
                saved += 1
                continue
            async with semaphore:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                except Exception as exc:          # usunięte zdjęcie (404) / sieć - reszta oferty dalej
                    error = f"{type(exc).__name__}: {str(exc)[:120]}"
                    stats["errors"] += 1
                    continue
            folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(response.content)
            saved += 1
            size += len(response.content)
        stats["photos"] += saved
        stats["bytes"] += size
        stats["offers"] += 1
        return (row["id"], source, len(urls), saved, size, clock().isoformat(timespec="seconds"), error)

    pending = []
    try:
        batch = max(1, getattr(cfg, "photos_concurrency", 4)) * 4
        for start in range(0, len(rows), batch):
            if deadline and clock() >= deadline:
                log.info("[PHOTOS] Koniec czasu - reszta w następnym cyklu.")
                break
            pending += await asyncio.gather(*(one(r) for r in rows[start:start + batch]))
            if len(pending) >= 200:
                _flush(index, pending)
                log.info("[PHOTOS] %d ofert, %d zdjęć, %.1f MB, błędy %d", stats["offers"], stats["photos"],
                         stats["bytes"] / 1e6, stats["errors"])
            await sleep(0)
    finally:
        _flush(index, pending)
        index.close()
        if own:
            await client.aclose()
    log.info("[PHOTOS] Wynik: %d ofert, %d zdjęć, %.1f MB, błędy %d", stats["offers"], stats["photos"],
             stats["bytes"] / 1e6, stats["errors"])
    return stats


def _flush(index, pending):
    if pending:
        with index:
            index.executemany("INSERT OR REPLACE INTO photos (listing_id, source, n_urls, n_saved, bytes, saved_at, "
                              "error) VALUES (?, ?, ?, ?, ?, ?, ?)", pending)
        pending.clear()


def status_line(cfg):
    """Jedna linia do `status`: ile ofert / zdjęć / GB w archiwum."""
    root = photos_dir(cfg)
    if not (root / "index.db").exists():
        return f"Archiwum zdjęć: puste ({root})"
    index = sqlite3.connect(str(root / "index.db"))
    n, photos, size = index.execute("SELECT COUNT(*), SUM(n_saved), SUM(bytes) FROM photos").fetchone()
    index.close()
    return f"Archiwum zdjęć: {n} ofert, {photos or 0} zdjęć, {(size or 0) / 1e9:.1f} GB ({root})"
