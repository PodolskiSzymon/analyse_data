"""CLI analizatora: python -m analyzer <polecenie>  (z katalogu głównego repozytorium).

  probe  --catalog 3580 [--item ID ...]   etap 0: odpowiedzi Vinted do sprawdzenia założeń -> data/probe/
  crawl  --catalog 3580                   pełne przejście kategorii -> data/analyzer.db (wznawia przerwane)
  probe-show [folder]                     wyciąg z plików probe do wklejenia (bez sieci)
  watch  [--catalog 3580]                 bez końca: crawl + resolve, między przejściami details (10-14 h)
  details [--limit N]                     szczegóły ofert (opis, atrybuty, „Dodane”) raz na ofertę
  resolve [--limit N]                     zniknięte z katalogu -> sold / deleted / unlisted (1 zapytanie/ofertę)
  classify-report / reclassify            klasyfikacja ofert z kategorii mieszanych (bez sieci)
  classify-ai [--limit N]                 RAM + inna kategoria w tytule -> AI ocenia zdjęcie główne (bez proxy)
  recheck [--states deleted] [--limit N]  naprawa: 'deleted' od nowa przez /services + sidebar (sold/deleted/active)
  html-details [--states sold] [--limit N] opisy sprzedanych ze strony HTML (gdy API ich już nie poda)
  extract [--again] / extract-report      parametry ofert regułami + pokrycie i konfiguracje z cenami (bez sieci)
  ntfy-test                               testowe powiadomienie na telefon (ntfy)
  check <link|ID> [...]                   czy oferta jest sprzedana (/services + sidebar przez proxy) + co wie baza
  resolve-report                          dlaczego 0 sprzedanych: zapisane odpowiedzi resolvera + próbka do wysłania
  suspicious-report [--photo-flag]        flagi podejrzanych ofert (oszustwa, kontakt poza Vinted) -> analysis.db
  suspicious-diag                         rozkład photo.is_suspicious (i innych pól logicznych) wg stanu
  relist-report                           ponowne wystawienia (usunięta + wystawiona od nowa) -> analysis.db
  report [--age-days 14] [--photo-flag]   raport rynku: flagi + relisty + statystyki -> reports/<data>/summary.md,
                                          configs.csv, report.html (bez sieci, baza tylko do odczytu)
  export-analysis [--with-descriptions]   eksport do analizy w czacie (csv.gz, bez danych sprzedawców) -> export/<data>/
  ai-condition [--scope flagged] [--photos 3] [--limit N] [--estimate] [--yes]
                                          stan techniczny przez AI (opis + zdjęcia) -> analysis.db; najpierw koszt
  sniper-guide [--promo 26] [--ship 20]   wytyczne dla Snipera z danych (ceny, max zakup wg reguły zysku) -> guides/
  auto [--force]                          automat (AI stanu nowych ofert, raport, wytyczne Snipera) - jak w watch
  photos [--limit N]                      archiwum zdjęć ofert (bez proxy) - jak w watch
  remote                                  pilot z telefonu (ntfy): start/stop watch i Snipera, status, logi (PILOT.md)
  sample [--per-category N]               próbka ofert z opisami (bez danych sprzedawcy) -> data/sample_*.jsonl
  diag                                    zmiany cen i braki pokrycia w ostatnim przejściu (bez sieci)
  status                                  podsumowanie bazy (oferty, stany, partycje, przejścia, transfer)
"""
import argparse
import asyncio
import logging
import sqlite3
from pathlib import Path

from . import db
from .config import AnalyzerConfig, build_session, catalog_label

log = logging.getLogger("analyzer")


def setup_logging(db_path):
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(fmt)
    handlers = [console]
    if str(db_path) != ":memory:":
        path = Path(db_path).parent / "analyzer.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        to_file = logging.FileHandler(path, encoding="utf-8")
        to_file.setFormatter(fmt)
        handlers.append(to_file)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    for noisy in ("httpx", "httpcore", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def cmd_crawl(cfg, catalogs):
    from .crawler import Crawler

    conn = db.connect(cfg.db_path)
    session = build_session()
    try:
        crawler = Crawler(cfg, session, conn)
        for catalog_id in catalogs:
            await crawler.run(catalog_id)
        log.info("[TRANSFER] %s", session.traffic.window_report()[0])
    finally:
        await session.close()
        conn.close()


async def cmd_watch(cfg, catalogs, resolve_limit, with_details=True):
    """Bez końca: pełne przejście każdej kategorii + resolve, potem do następnego przejścia (ANALYZER_WATCH_HOURS,
    losowo) spokojne pobieranie szczegółów ofert, które ich jeszcze nie mają."""
    import random
    from datetime import datetime, timedelta, timezone

    from .crawler import Crawler
    from .details import fetch_details
    from .resolver import resolve

    while True:
        next_start = datetime.now(timezone.utc) + timedelta(hours=random.uniform(*cfg.watch_hours))
        conn = db.connect(cfg.db_path)
        session = build_session()
        try:
            crawler = Crawler(cfg, session, conn)
            for catalog_id in catalogs:
                await crawler.run(catalog_id)
            await run_ai_classify(cfg, conn)
            await resolve(cfg, session, conn, resolve_limit)
            await watch_extras(cfg, conn)
            for line in status_lines(conn):
                log.info("[STATUS] %s", line)
            if with_details or cfg.photos:
                log.info("[WATCH] Do następnego przejścia (%s UTC): %s.", next_start.strftime("%H:%M"),
                         " + ".join(x for x in ("szczegóły ofert (proxy)" if with_details else "",
                                                "archiwum zdjęć (bez proxy)" if cfg.photos else "") if x))
                jobs = []
                if with_details:
                    jobs.append(fetch_details(cfg, session, conn, deadline=next_start))
                if cfg.photos:
                    from .photos import archive
                    jobs.append(archive(cfg, conn, deadline=next_start))
                for result in await asyncio.gather(*jobs, return_exceptions=True):
                    if isinstance(result, Exception):
                        log.error("[WATCH] Szczegóły / zdjęcia przerwane błędem: %r", result)
            log.info("[TRANSFER] %s", session.traffic.window_report()[0])
        except Exception:
            log.exception("[WATCH] Cykl przerwany błędem - spróbuję przy następnym.")
        finally:
            await session.close()
            conn.close()
        wait = (next_start - datetime.now(timezone.utc)).total_seconds()
        log.info("[WATCH] Następne przejście za %.1f h (Ctrl+C = koniec; przerwane przejście zostanie wznowione).",
                 max(wait, 0) / 3600)
        if wait > 0:
            await asyncio.sleep(wait)


async def watch_extras(cfg, conn):
    """Po resolve w każdym cyklu watch: ekstrakcja, alarm „brak sprzedaży”, automat (2× w tygodniu: AI stanu nowych
    ofert, raport, wytyczne Snipera). Błąd żadnego z nich nie przerywa watch."""
    from . import analysis, auto

    try:
        from . import extract
        log.info("[EXTRACT] Nowe / zmienione oferty: %d.", extract.run(conn))
    except Exception:
        log.exception("[EXTRACT] Błąd ekstrakcji - spróbuję w następnym cyklu.")
    try:
        aconn = analysis.open_analysis(cfg.db_path)
        try:
            await auto.sold_alarm(cfg, conn, aconn)
        finally:
            aconn.close()
    except Exception:
        log.exception("[ALARM] Błąd sprawdzania sprzedaży.")
    try:
        await auto.run(cfg)
    except Exception:
        log.exception("[AUTO] Automat przerwany błędem - spróbuję w następnym cyklu.")


async def run_ai_classify(cfg, conn, limit=None, retry_failed=False):
    """Kategoria ze zdjęcia (AI) dla ofert „RAM + inna kategoria w tytule”. Błąd AI nie przerywa cyklu watch."""
    if not cfg.ai_classify:
        return None
    from .ai_classify import classify_photos
    try:
        return await classify_photos(cfg, conn, limit=limit, retry_failed=retry_failed)
    except Exception:
        log.exception("[AI] Sprawdzanie zdjęć przerwane błędem - kategorie z reguł zostają, ponowię w kolejnym cyklu.")
        return None


async def cmd_classify_ai(cfg, limit, retry_failed):
    conn = db.connect(cfg.db_path)
    try:
        stats = await run_ai_classify(cfg, conn, limit, retry_failed)
        if stats is None:
            print("Wyłączone (ANALYZER_AI_CLASSIFY=false) albo błąd - patrz log.")
        left = conn.execute("SELECT category_check, COUNT(*) FROM listings WHERE category_check IS NOT NULL "
                            "GROUP BY category_check").fetchall()
        print("Stan sprawdzania zdjęć: " + (", ".join(f"{r[0]} {r[1]}" for r in left) or "nic do sprawdzenia"))
    finally:
        conn.close()


def recheck_links(conn, since, show=("sold", "hidden"), per_state=50):
    """Linki do ofert, którym recheck (od `since`) ustawił jeden ze stanów `show` - do sprawdzenia w przeglądarce."""
    lines = []
    for state in show:
        rows = conn.execute("SELECT id, category, price_now, sold_price, seller_price, seller_currency, title "
                            "FROM listings WHERE services_at >= ? AND state = ? ORDER BY id DESC LIMIT ?",
                            (since, state, per_state)).fetchall()
        if not rows:
            continue
        lines.append(f"{state} ({len(rows)}{'+' if len(rows) == per_state else ''}):")
        for r in rows:
            price = r["sold_price"] if state == "sold" and r["sold_price"] is not None else r["price_now"]
            seller = f" ({r['seller_price']:g} {r['seller_currency']})" if r["seller_price"] else ""
            lines.append(f"  https://www.vinted.pl/items/{r['id']}  {r['category']:<8} {price or 0:>9.2f} zł{seller}  "
                         f"{(r['title'] or '')[:50]}")
    return lines


async def cmd_recheck(cfg, states, limit, again, human=False, delay=(0.6, 1.5), show=("sold", "hidden")):
    import time

    from . import notify
    from .pacing import HumanPacer
    from .progress import ConsoleBar
    from .resolver import recheck, recheck_candidates

    bar = ConsoleBar()
    console = [h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler]
    for handler in console:
        handler.addFilter(bar)          # wpisy logu nie rozjeżdżają paska
    pacer = HumanPacer(base=delay) if human else None
    log.info("[RECHECK] Tempo: odstęp losowo %g-%g s%s. Cały ruch do Vinted przez proxy (SNIPER_PROXY_*).", *delay,
             ", mniej więcej co pół godziny przerwa 10-120 s, po 12 h pracy odpoczynek 8 h" if human
             else " bez przerw (--pauses: przerwy co ~pół godziny i 8 h po 12 h); przy 429 czekam 5/15/30/60 min")
    cfg.page_delay = delay
    conn = db.connect(cfg.db_path)
    session = build_session()
    since = db.utcnow()
    started = time.monotonic()
    try:
        try:
            counts = await recheck(cfg, session, conn, states, limit, again, pacer=pacer, progress=bar)
        except Exception as exc:
            bar.finish()
            await notify.send("Analyzer: recheck przerwany błędem", [repr(exc)[:300]], priority=4, tags=("warning",))
            raise
        bar.finish()
        links = recheck_links(conn, since, show)
        if links:
            print("\nDo sprawdzenia w przeglądarce (wyniki tego uruchomienia):\n" + "\n".join(links) + "\n", flush=True)
        transfer = session.traffic.window_report()[0]
        log.info("[TRANSFER] %s", transfer)
        left = len(recheck_candidates(conn, states))
        hours = (time.monotonic() - started) / 3600
        await notify.send(
            f"Analyzer: recheck {'skończony' if not left else 'zatrzymany'} ({sum(counts.values())} ofert, "
            f"{hours:.1f} h)",
            [", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nic do zrobienia",
             f"zostało do sprawdzenia: {left}", transfer.split("|")[0].strip()])
        for row in conn.execute("SELECT category, state, COUNT(*) AS n FROM listings WHERE services_at IS NOT NULL "
                                "GROUP BY category, state ORDER BY category, n DESC"):
            log.info("[RECHECK] sprawdzone przez /services: %-8s %-10s %d", row["category"], row["state"], row["n"])
    finally:
        bar.finish()
        for handler in console:
            handler.removeFilter(bar)
        await session.close()
        conn.close()


async def cmd_check(cfg, items):
    from .check import check

    conn = db.connect(cfg.db_path) if Path(cfg.db_path).exists() else None
    session = build_session()
    try:
        print("\n".join(await check(session, conn, items)))
    finally:
        await session.close()
        if conn is not None:
            conn.close()


async def cmd_html_dump(cfg, items):
    """Zapisuje fragment strony, który program pobiera (do baneru wysyłki - bez nazwy sprzedawcy) do pliku + wynik
    parsera - do sprawdzenia, czemu parser czegoś nie znalazł."""
    import json as _json

    from .check import parse_id
    from .html_details import fetch_sidebar_html, parse_page

    session = build_session()
    try:
        for text in items:
            item_id = parse_id(text)
            status, html = await fetch_sidebar_html(session, item_id)
            path = Path(cfg.db_path).parent / f"html_dump_{item_id}.html"
            path.write_text(html, encoding="utf-8")
            parsed = parse_page(html) if html else None
            print(f"{item_id}: HTTP {status}, pobrano {len(html.encode()) / 1000:.0f} KB (po rozpakowaniu), "
                  f"panel boczny: {'jest' if '<aside id="sidebar"' in html else 'BRAK'} -> {path}")
            print("  parser: " + _json.dumps(parsed, ensure_ascii=False)[:600])
        log.info("[TRANSFER] %s", session.traffic.window_report()[0])
    finally:
        await session.close()


async def cmd_html_details(cfg, states, limit, delay, random_order=False):
    from . import notify
    from .html_details import fetch_html_details
    from .progress import ConsoleBar

    cfg.page_delay = delay
    bar = ConsoleBar()
    console = [h for h in logging.getLogger().handlers if type(h) is logging.StreamHandler]
    for handler in console:
        handler.addFilter(bar)
    conn = db.connect(cfg.db_path)
    session = build_session()
    try:
        counts = await fetch_html_details(cfg, session, conn, states, limit, progress=bar, random_order=random_order)
        bar.finish()
        transfer = session.traffic.window_report()[0]
        log.info("[TRANSFER] %s", transfer)
        await notify.send(f"Analyzer: html-details skończony ({sum(counts.values())} ofert)",
                          [", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "nic do zrobienia",
                           transfer.split("|")[0].strip()])
    finally:
        bar.finish()
        for handler in console:
            handler.removeFilter(bar)
        await session.close()
        conn.close()


async def cmd_details(cfg, limit):
    from .details import fetch_details

    conn = db.connect(cfg.db_path)
    session = build_session()
    try:
        await fetch_details(cfg, session, conn, limit)
        log.info("[TRANSFER] %s", session.traffic.window_report()[0])
    finally:
        await session.close()
        conn.close()


async def cmd_resolve(cfg, limit):
    from .resolver import resolve

    conn = db.connect(cfg.db_path)
    session = build_session()
    try:
        await resolve(cfg, session, conn, limit)
        log.info("[TRANSFER] %s", session.traffic.window_report()[0])
    finally:
        await session.close()
        conn.close()


async def cmd_probe(cfg, catalog_id, items):
    from .probe import Probe

    session = build_session()
    try:
        await Probe(session, catalog_id).run(items)
    finally:
        await session.close()


def coverage_lines(conn, tolerance=1.0, tolerance_pct=1.5, progress=None):
    """Kontrola kompletności: dla każdej partycji ile ofert z bazy (bieżąca cena ± max(tolerance zł, tolerance_pct %))
    vs total_entries z Vinted. Tolerancja procentowa - filtr Vinted liczy oferty zagraniczne po swoim kursie
    (diag 2026-10-12), więc ich cena w zł bywa poza przedziałem o ułamek procenta.
    Ceny jednej kategorii wczytywane raz i liczone bisekcją (wcześniej jedno zapytanie na partycję - minuty na
    słabym komputerze przy tysiącu partycji)."""
    from bisect import bisect_left, bisect_right

    say = progress or (lambda _text: None)
    lines = []
    rows = conn.execute("SELECT * FROM partitions WHERE active=1 AND last_total IS NOT NULL ORDER BY catalog_id, "
                        "price_from").fetchall()
    by_catalog, prices = {}, {}
    for row in rows:
        key = (row["catalog_id"], row["done_run_id"])
        if key not in prices:
            say(f"  kontrola pokrycia: {catalog_label(row['catalog_id'])}...")
            prices[key] = sorted(r[0] for r in conn.execute(
                "SELECT price_now FROM listings WHERE catalog_id=? AND last_run_id=? AND price_now IS NOT NULL", key))
        lo = row["price_from"] - max(tolerance, row["price_from"] * tolerance_pct / 100)
        hi = (row["price_to"] + max(tolerance, row["price_to"] * tolerance_pct / 100)
              if row["price_to"] is not None else 1e12)
        have = bisect_right(prices[key], hi) - bisect_left(prices[key], lo)
        stats = by_catalog.setdefault(row["catalog_id"], {"parts": 0, "short": 0, "missing": 0, "worst": []})
        stats["parts"] += 1
        if have < row["last_total"]:
            stats["short"] += 1
            stats["missing"] += row["last_total"] - have
            stats["worst"].append((row["last_total"] - have, row["price_from"], row["price_to"], row["last_total"], have))
    for catalog_id, st in by_catalog.items():
        tol = f"±max({tolerance:g} zł, {tolerance_pct:g}%)" if tolerance_pct else f"±{tolerance:g} zł"
        lines.append(f"kategoria {catalog_label(catalog_id)}: kontrola pokrycia - partycji z brakami {st['short']}/{st['parts']}, "
                     f"brakuje łącznie ~{st['missing']} ofert (tolerancja ceny {tol})")
        for miss, lo, hi, total, have in sorted(st["worst"], reverse=True)[:5]:
            lines.append(f"    {lo:g}-{'∞' if hi is None else format(hi, 'g')} zł: Vinted {total}, w bazie {have} "
                         f"(brak {miss})")
    return lines


def status_lines(conn, progress=None):
    say = progress or (lambda _text: None)
    lines = []
    say("  liczę oferty według kategorii i stanu...")
    for row in conn.execute("SELECT COALESCE(category, '?') AS category, state, COUNT(*) AS n FROM listings "
                            "GROUP BY category, state ORDER BY category, n DESC"):
        lines.append(f"przedmiot {row['category']:<8}: {row['state']:<13} {row['n']}")
    say("  liczę pobrane szczegóły...")
    for row in conn.execute("SELECT COALESCE(category, '?') AS category, COUNT(*) AS n, SUM(details_at IS NOT NULL) AS d "
                            "FROM listings WHERE state IN ('active', 'reserved', 'unlisted') GROUP BY category"):
        lines.append(f"przedmiot {row['category']:<8}: szczegóły pobrane dla {row['d']}/{row['n']} śledzonych ofert")
    for row in conn.execute(
            "SELECT catalog_id, COUNT(*) AS n, SUM(last_total) AS total, SUM(last_items) AS items, "
            "SUM(oversize) AS oversize FROM partitions WHERE active=1 GROUP BY catalog_id"):
        lines.append(f"kategoria {catalog_label(row['catalog_id'])}: partycji {row['n']}, suma total_entries "
                     f"{row['total'] if row['total'] is not None else '?'}, zebrano {row['items'] or 0}, "
                     f"oversize {row['oversize'] or 0}")
    say("  partycje i ostatnie przejścia...")
    for row in conn.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT 5"):
        lines.append(f"przejście #{row['id']} kat. {row['catalog_id']}: start {row['started_at']}, koniec "
                     f"{row['finished_at'] or '(niedokończone)'}, zapytań {row['requests']}, "
                     f"{(row['bytes'] or 0) / 1024 / 1024:.2f} MB, widziane {row['seen']}, nowe {row['new_ids']}, "
                     f"zmienione {row['changed']}, zniknięte {row['gone']}, błędy {row['errors']}")
    if not lines:
        return ["Baza pusta - uruchom: python -m analyzer crawl"]
    return lines + coverage_lines(conn, progress=say)


def data_size_line(db_path):
    """Rozmiar plików bazy (analyzer.db + -wal + -shm) i folderu danych."""
    base = Path(db_path)
    files = [base, base.with_name(base.name + "-wal"), base.with_name(base.name + "-shm")]
    db_mb = sum(f.stat().st_size for f in files if f.exists()) / 1e6
    folder_mb = sum(f.stat().st_size for f in base.parent.rglob("*") if f.is_file()) / 1e6
    return f"Baza: {db_mb:,.1f} MB ({base}), cały folder {base.parent}: {folder_mb:,.1f} MB"


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m analyzer", description="Category Analyzer (Vinted)")
    sub = parser.add_subparsers(dest="command", required=True)
    p_crawl = sub.add_parser("crawl", help="pełne przejście kategorii")
    p_crawl.add_argument("--catalog", type=int, action="append", help="catalog_id (domyślnie ANALYZER_CATALOGS)")
    p_watch = sub.add_parser("watch", help="bez końca: crawl + resolve co ANALYZER_WATCH_HOURS (domyślnie 10-14 h)")
    p_watch.add_argument("--catalog", type=int, action="append")
    p_watch.add_argument("--resolve-limit", type=int, default=None)
    p_watch.add_argument("--no-details", action="store_true", help="bez pobierania szczegółów między przejściami")
    p_details = sub.add_parser("details", help="szczegóły ofert (opis, atrybuty) - raz na ofertę")
    p_details.add_argument("--limit", type=int, default=None)
    p_resolve = sub.add_parser("resolve", help="etap 2: zniknięte oferty -> sprzedana / usunięta / niewidoczna")
    p_resolve.add_argument("--limit", type=int, default=None, help="najwyżej tyle ofert w jednym uruchomieniu")
    p_probe = sub.add_parser("probe", help="etap 0: zapis odpowiedzi Vinted do sprawdzenia założeń")
    p_probe.add_argument("--catalog", type=int, default=None)
    p_probe.add_argument("--item", type=int, action="append", default=[], help="ID oferty do details/sidebar")
    p_show = sub.add_parser("probe-show", help="wyciąg z zapisanych plików probe (bez sieci)")
    p_show.add_argument("folder", nargs="?", default=None, help="domyślnie najnowszy data/probe/*")
    sub.add_parser("status", help="podsumowanie bazy")
    sub.add_parser("diag", help="diagnostyka bazy (zmiany cen, braki pokrycia) - bez sieci")
    p_recheck = sub.add_parser("recheck", help="naprawa stanów: oferty 'deleted' sprawdzone od nowa (/services + "
                                                "sidebar) -> sold / deleted / active ...; można przerwać i wznowić")
    p_recheck.add_argument("--states", default="deleted",
                           help="stany do sprawdzenia, po przecinku (domyślnie deleted; np. deleted,unlisted,hidden)")
    p_recheck.add_argument("--limit", type=int, default=None)
    p_recheck.add_argument("--again", action="store_true", help="także oferty już sprawdzone przez /services")
    p_recheck.add_argument("--delay", default="0.6-1.5", help="odstęp między ofertami w s, losowo z zakresu "
                                                             "(domyślnie 0.6-1.5)")
    p_recheck.add_argument("--show", default="sold,hidden",
                           help="po zakończeniu wypisz linki ofert z tymi wynikami (domyślnie sold,hidden; np. "
                                "sold,hidden,deleted,active)")
    p_recheck.add_argument("--links-only", action="store_true",
                           help="bez sprawdzania - tylko linki z dotychczasowych wyników recheck (--show)")
    p_recheck.add_argument("--pauses", action="store_true",
                           help="„ludzkie” przerwy: co ~pół godziny 10-120 s i 8 h odpoczynku po 12 h (domyślnie bez)")
    p_html = sub.add_parser("html-details", help="opisy i atrybuty ze strony oferty (HTML, ~35 KB/ofertę) dla ofert "
                                                "bez szczegółów - domyślnie sprzedanych")
    p_html.add_argument("--states", default="sold", help="stany ofert, po przecinku (domyślnie sold)")
    p_html.add_argument("--limit", type=int, default=None)
    p_html.add_argument("--delay", default="0.6-1.5", help="odstęp między ofertami w s (domyślnie 0.6-1.5)")
    p_html.add_argument("--random", action="store_true", help="losowa kolejność (próbka, np. --states deleted "
                                                              "--limit 200 do sprawdzenia, czy 'deleted' są usunięte)")
    p_html.add_argument("--dump", nargs="+", metavar="LINK_LUB_ID",
                        help="tylko zapisz pobrany fragment strony tych ofert do data/html_dump_<ID>.html (diagnoza)")
    p_extract = sub.add_parser("extract", help="parametry ofert regułami (CPU, GPU, RAM, dysk, model, bateria, stan) - "
                                               "bez sieci")
    p_extract.add_argument("--again", action="store_true", help="wszystkie oferty od nowa")
    sub.add_parser("extract-report", help="pokrycie pól i najczęstsze konfiguracje z cenami - bez sieci")
    sub.add_parser("ntfy-test", help="testowe powiadomienie na telefon (temat z ANALYZER_NTFY_TOPIC / SNIPER_NTFY_TOPIC)")
    p_check = sub.add_parser("check", help="czy oferta jest sprzedana: link(i) albo ID - jedno zapytanie na ofertę")
    p_check.add_argument("items", nargs="+", help="link https://www.vinted.pl/items/... albo samo ID")
    sub.add_parser("resolve-report", help="diagnostyka rozpoznawania sprzedaży (zapisane odpowiedzi) - bez sieci")
    p_susp = sub.add_parser("suspicious-report", help="flagi podejrzanych ofert -> analysis.db + raport (bez sieci, "
                                                      "baza tylko do odczytu)")
    p_susp.add_argument("--photo-flag", action="store_true",
                        help="także flaga is_suspicious (photo.is_suspicious=true) - po sprawdzeniu suspicious-diag")
    p_sdiag = sub.add_parser("suspicious-diag", help="rozkład photo.is_suspicious i innych pól logicznych pozycji "
                                                     "katalogu w stanach blocked/sold/deleted/active (bez sieci)")
    p_sdiag.add_argument("--per-state", type=int, default=2000)
    sub.add_parser("relist-report", help="ponowne wystawienia (usunięta oferta wystawiona od nowa z nowym ID) -> "
                                         "analysis.db + raport (bez sieci, baza tylko do odczytu)")
    p_report = sub.add_parser("report", help="raport rynku per konfiguracja -> reports/<data>/ (summary.md, "
                                             "configs.csv, report.html) - bez sieci, baza tylko do odczytu")
    p_report.add_argument("--age-days", type=int, default=14,
                          help="aktywne starsze niż tyle dni liczą się do mianownika sell-through (domyślnie 14)")
    p_report.add_argument("--photo-flag", action="store_true", help="wykluczaj też is_suspicious (po suspicious-diag)")
    p_export = sub.add_parser("export-analysis", help="oferty, parametry, prawdziwe zmiany cen, przejścia (+ flagi, "
                                                      "relisty) -> export/<data>/*.csv.gz - bez sieci, bez danych "
                                                      "sprzedawców")
    p_export.add_argument("--with-descriptions", action="store_true",
                          help="także opisy (e-mail/telefon/link zamaskowane, max 2000 znaków) -> descriptions.jsonl.gz")
    p_aic = sub.add_parser("ai-condition", help="stan techniczny (sprawna / usterka / na części, zbity ekran, "
                                                "blokada) przez AI z opisu i zdjęć -> analysis.db; przed wywołaniami "
                                                "szacunek kosztu")
    p_aic.add_argument("--scope", default="flagged",
                       help="flagged (reguły: usterka albo wzmianka o usterce - domyślnie), sold (sprzedane / blocked "
                            "/ usunięte), all (wszystkie z opisem); po przecinku")
    p_aic.add_argument("--photos", type=int, default=3,
                       help="najwyżej tyle zdjęć na ofertę (domyślnie 3; 0 = sam tekst; 99 = wszystkie)")
    p_aic.add_argument("--limit", type=int, default=None, help="najwyżej tyle ofert (np. 50 na próbę)")
    p_aic.add_argument("--concurrency", type=int, default=None, help="zapytań naraz (domyślnie 48)")
    p_aic.add_argument("--rpm", type=int, default=None,
                       help="najwyżej tyle zapytań na minutę (domyślnie 900 - 90%% limitu Tier 1; 0 = bez limitu)")
    p_aic.add_argument("--tpm", type=int, default=None,
                       help="najwyżej tyle tokenów wejścia na minutę (domyślnie 1800000; 0 = bez limitu)")
    p_aic.add_argument("--estimate", action="store_true", help="tylko policz oferty i koszt, bez wywołań AI")
    p_aic.add_argument("--yes", action="store_true", help="bez pytania o zgodę na koszt")
    p_aic.add_argument("--again", action="store_true", help="także oferty już ocenione")
    p_aic.add_argument("--show", action="store_true", help="tylko raport z dotychczasowych wyników")
    p_guide = sub.add_parser("sniper-guide", help="wytyczne oceny okazji dla Snipera per kategoria (ceny z rynku, "
                                                  "max cena zakupu wg reguły zysku) -> reports/<data>/guides/*.md")
    p_guide.add_argument("--promo", type=float, default=26.0, help="koszt Podbicia (zł, domyślnie 26)")
    p_guide.add_argument("--ship", type=float, default=20.0, help="koszt wysyłki (zł, domyślnie 20)")
    p_guide.add_argument("--min-offers", type=int, default=8, help="grupa w tabeli od tylu aktywnych ofert")
    p_auto = sub.add_parser("auto", help="automat: flagi, relisty, AI stanu nowych ofert, raport, wytyczne Snipera "
                                          "(watch robi to sam co ANALYZER_AUTO_DAYS)")
    p_auto.add_argument("--force", action="store_true", help="teraz, nawet jeśli nie minęło ANALYZER_AUTO_DAYS")
    p_photos = sub.add_parser("photos", help="archiwum zdjęć ofert z CDN Vinted, bez proxy (watch robi to sam)")
    p_photos.add_argument("--limit", type=int, default=None)
    sub.add_parser("remote", help="pilot z telefonu przez ntfy: start / stop / status watch i Snipera (PILOT.md)")
    p_sample = sub.add_parser("sample", help="próbka ofert z opisami do projektu ekstrakcji -> data/sample_*.jsonl")
    p_sample.add_argument("--per-category", type=int, default=150)
    sub.add_parser("classify-report", help="klasyfikacja ofert z kategorii mieszanych - bez sieci")
    sub.add_parser("reclassify", help="ponowna klasyfikacja zapisanych ofert po poprawce reguł - bez sieci")
    p_ai = sub.add_parser("classify-ai", help="kategoria ze zdjęcia głównego (AI) dla ofert 'RAM + coś innego' w tytule")
    p_ai.add_argument("--limit", type=int, default=None, help="najwyżej tyle ofert (domyślnie ANALYZER_AI_CLASSIFY_LIMIT)")
    p_ai.add_argument("--retry-failed", action="store_true", help="ponów też oferty z błędem AI")
    args = parser.parse_args(argv)

    cfg = AnalyzerConfig()
    setup_logging(cfg.db_path)
    if args.command == "crawl":
        asyncio.run(cmd_crawl(cfg, args.catalog or list(cfg.catalogs)))
    elif args.command == "watch":
        asyncio.run(cmd_watch(cfg, args.catalog or list(cfg.catalogs), args.resolve_limit, not args.no_details))
    elif args.command == "classify-ai":
        asyncio.run(cmd_classify_ai(cfg, args.limit, args.retry_failed))
    elif args.command == "details":
        asyncio.run(cmd_details(cfg, args.limit))
    elif args.command == "resolve":
        asyncio.run(cmd_resolve(cfg, args.limit))
    elif args.command == "probe":
        asyncio.run(cmd_probe(cfg, args.catalog or cfg.catalogs[0], args.item))
    elif args.command == "probe-show":
        from .probe import show
        show(args.folder)
    elif args.command in ("classify-report", "reclassify"):
        from . import classify
        print(f"Otwieram bazę {cfg.db_path} ...", flush=True)
        try:
            conn = db.connect(cfg.db_path)
            if args.command == "reclassify":
                changes = classify.reclassify(conn, cfg.category_min, progress=lambda t: print(t, flush=True))
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc):
                raise
            raise SystemExit("Baza zajęta przez inny proces (pewnie watch w trakcie zapisu) - spróbuj za chwilę "
                             "albo zatrzymaj watch (Ctrl+C) i uruchom ponownie.")
        if args.command == "reclassify":
            print("Zmiany kategorii: " + (", ".join(f"{a} → {b}: {n}" for (a, b), n in sorted(changes.items()))
                                          or "brak"))
        print("\n".join(classify.report(conn)))
        conn.close()
    elif args.command == "recheck":
        states = tuple(x.strip() for x in args.states.split(",") if x.strip())
        from .config import parse_range
        delay = parse_range(args.delay, (0.6, 1.5))
        show = tuple(x.strip() for x in args.show.split(",") if x.strip())
        if args.links_only:
            conn = db.connect(cfg.db_path)
            print("\n".join(recheck_links(conn, "", show, per_state=200)) or "Brak wyników recheck w tych stanach.")
            conn.close()
            return
        asyncio.run(cmd_recheck(cfg, states, args.limit, args.again, human=args.pauses, delay=delay, show=show))
    elif args.command == "html-details":
        from .config import parse_range
        states = tuple(x.strip() for x in args.states.split(",") if x.strip())
        if args.dump:
            asyncio.run(cmd_html_dump(cfg, args.dump))
        else:
            asyncio.run(cmd_html_details(cfg, states, args.limit, parse_range(args.delay, (0.6, 1.5)), args.random))
    elif args.command in ("extract", "extract-report"):
        from . import extract
        print(f"Otwieram bazę {cfg.db_path} ...", flush=True)
        conn = db.connect(cfg.db_path)
        if args.command == "extract":
            extract.run(conn, args.again, progress=lambda t: print(t, flush=True))
        print("\n".join(extract.report(conn)))
        conn.close()
    elif args.command == "ntfy-test":
        from . import notify
        ok = asyncio.run(notify.send("Analyzer: test powiadomienia", ["Tak będzie wyglądać powiadomienie o końcu "
                                                                     "pracy recheck."]))
        print("Wysłano - sprawdź telefon." if ok else "Nie wysłano - patrz komunikat wyżej.")
    elif args.command == "check":
        asyncio.run(cmd_check(cfg, args.items))
    elif args.command == "resolve-report":
        from .resolve_diag import report
        print(f"Otwieram bazę {cfg.db_path} ...", flush=True)
        conn = db.connect(cfg.db_path)
        print("\n".join(report(conn, Path(cfg.db_path).parent, progress=lambda t: print(t, flush=True))))
        conn.close()
    elif args.command in ("suspicious-report", "suspicious-diag"):
        from . import analysis, suspicious
        say = lambda text: print(text, flush=True)  # noqa: E731
        say(f"Otwieram bazę {cfg.db_path} (tylko do odczytu) ...")
        conn = analysis.open_ro(cfg.db_path)
        if args.command == "suspicious-diag":
            lines = suspicious.photo_diag(conn, args.per_state, progress=say)
            name = "suspicious_diag.txt"
        else:
            aconn = analysis.open_analysis(cfg.db_path)
            say(f"Liczę flagi -> {analysis.analysis_path(cfg.db_path)}")
            suspicious.run(conn, aconn, args.photo_flag, progress=say)
            lines = suspicious.report(conn, aconn)
            aconn.close()
            name = "suspicious.txt"
        conn.close()
        path = analysis.out_dir(cfg.db_path) / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        say("")
        print("\n".join(lines))
        say(f"\nZapisano też do {path}")
    elif args.command == "relist-report":
        from . import analysis, relist
        say = lambda text: print(text, flush=True)  # noqa: E731
        say(f"Otwieram bazę {cfg.db_path} (tylko do odczytu) ...")
        conn, aconn = analysis.open_ro(cfg.db_path), analysis.open_analysis(cfg.db_path)
        say(f"Szukam relistów -> {analysis.analysis_path(cfg.db_path)}")
        relist.run(conn, aconn, progress=say)
        lines = relist.report(conn, aconn)
        conn.close()
        aconn.close()
        path = analysis.out_dir(cfg.db_path) / "relists.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        say("")
        print("\n".join(lines))
        say(f"\nZapisano też do {path}")
    elif args.command == "report":
        import time

        from . import analysis, report
        say = lambda text: print(text, flush=True)  # noqa: E731
        started = time.monotonic()
        say(f"Otwieram bazę {cfg.db_path} (tylko do odczytu) ...")
        conn, aconn = analysis.open_ro(cfg.db_path), analysis.open_analysis(cfg.db_path)
        out = analysis.out_dir(cfg.db_path)
        paths, lines, _ = report.build(conn, aconn, out, args.age_days, args.photo_flag, progress=say)
        conn.close()
        aconn.close()
        say("")
        print("\n".join(lines))
        say(f"\nGotowe w {(time.monotonic() - started) / 60:.1f} min. Pliki:")
        for path in paths.values():
            say(f"  {path}  ({path.stat().st_size / 1e6:.2f} MB)")
        say("Wklej summary.md do czatu (albo wyślij plik); report.html otwórz w przeglądarce.")
    elif args.command == "export-analysis":
        from . import analysis, export
        say = lambda text: print(text, flush=True)  # noqa: E731
        say(f"Otwieram bazę {cfg.db_path} (tylko do odczytu) ...")
        conn = analysis.open_ro(cfg.db_path)
        aconn = analysis.open_analysis(cfg.db_path) if analysis.analysis_path(cfg.db_path).exists() else None
        out = analysis.out_dir(cfg.db_path, "export")
        result = export.run(conn, out, aconn, args.with_descriptions, say=say)
        conn.close()
        if aconn is not None:
            aconn.close()
        print("\n".join(export.size_lines(result, out)))
    elif args.command == "ai-condition":
        from . import ai_condition, analysis
        from .ai_classify import DEFAULT_MODELS, Backend
        from sniper.config import AiConfig
        say = lambda text: print(text, flush=True)  # noqa: E731
        say(f"Otwieram bazę {cfg.db_path} (tylko do odczytu) ...")
        conn, aconn = analysis.open_ro(cfg.db_path), analysis.open_analysis(cfg.db_path)
        try:
            if not args.show:
                ai_cfg = AiConfig()
                model = cfg.ai_model or DEFAULT_MODELS.get(ai_cfg.provider, ai_cfg.model)
                scopes = tuple(x.strip() for x in args.scope.split(",") if x.strip())
                photos_label = "wszystkie" if args.photos is None else args.photos
                say(f"Szukam ofert ({', '.join(scopes)}, zdjęcia: {photos_label})...")
                items = ai_condition.candidates(conn, aconn, scopes, args.limit, args.photos, args.again, say)
                say(f"Dostawca {ai_cfg.provider}, model {model}.")
                print("\n".join(ai_condition.estimate(items, ai_cfg.provider, ai_condition.prices(ai_cfg, model))))
                go = bool(items) and not args.estimate
                if go and not ai_cfg.api_key:
                    say("Brak klucza AI (SNIPER_AI_API_KEY w sniper\\.env) - nic nie wysyłam.")
                    go = False
                if go and not args.yes:
                    go = input(f"Wysłać {len(items)} ofert do AI (zdjęcia: {photos_label})? [t/N] ").strip().lower() \
                        in ("t", "tak", "y", "yes")
                if go:
                    async def call():
                        backend = Backend(ai_cfg, model)
                        try:
                            return await ai_condition.run(
                                aconn, items, backend,
                                args.concurrency or ai_condition.CONCURRENCY,
                                rpm=ai_condition.RPM if args.rpm is None else args.rpm,
                                tpm=ai_condition.TPM if args.tpm is None else args.tpm)
                        finally:
                            await backend.close()
                    st = asyncio.run(call())
                    price = ai_condition.prices(ai_cfg, model)
                    cost = (f", koszt ~${(st['tokens_in'] * price[0] + st['tokens_out'] * price[1]) / 1e6:.2f}"
                            if price else "")
                    say(f"Ocenione {st['done']}, błędy {st['failed']}, ponowienia {st['retried']}; "
                        f"tokeny {st['tokens_in']}/{st['tokens_out']} "
                        f"(śr. {st['tokens_in'] / max(st['done'], 1):.0f}/{st['tokens_out'] / max(st['done'], 1):.0f} "
                        f"na ofertę){cost}")
                    if st["stopped"]:
                        say(f"PRZERWANE po serii błędów (ostatni: {st['stopped']}). Pewnie skończyły się środki na "
                            "koncie API albo limit zapytań - doładuj / odczekaj i uruchom tę samą komendę ponownie.")
            lines = ai_condition.report(conn, aconn)
        finally:
            conn.close()
            aconn.close()
        path = analysis.out_dir(cfg.db_path) / "ai_condition.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\n" + "\n".join(lines))
        say(f"\nZapisano też do {path}")
    elif args.command == "sniper-guide":
        from . import analysis, guide
        say = lambda text: print(text, flush=True)  # noqa: E731
        say(f"Otwieram bazę {cfg.db_path} (tylko do odczytu) ...")
        conn, aconn = analysis.open_ro(cfg.db_path), analysis.open_analysis(cfg.db_path)
        if not aconn.execute("SELECT COUNT(*) FROM flags").fetchone()[0]:
            say("UWAGA: brak flag w analysis.db - najpierw: python -m analyzer report (inaczej oszustwa zostaną w cenach)")
        out = analysis.out_dir(cfg.db_path) / "guides"
        result = guide.build(conn, aconn, out, args.promo, args.ship, args.min_offers, progress=say)
        conn.close()
        aconn.close()
        print("\n".join(guide.summary_lines(result)))
        say(f"\nWytyczne: {out}  (po jednym pliku na kategorię - przyślij je albo wklej podgląd)")
        if result:
            say(f"Katalogi Snipera (catalogs.json, SNIPER_CATALOGS=auto): {guide.catalogs_line(result)}")
        if result and cfg.sniper_guides_dir:
            from .auto import publish
            copied = publish(cfg, result)
            say(f"Skopiowano do Snipera ({cfg.sniper_guides_dir}): " + ", ".join(Path(c).name for c in copied))
        elif result:
            say("Do Snipera: ustaw ANALYZER_SNIPER_GUIDES_DIR=C:\\Users\\szymo\\unreachable_sniper\\sniper\\guides"
                " w sniper\\.env - wtedy wytyczne i catalogs.json kopiują się same.")
    elif args.command == "auto":
        from . import auto
        result = asyncio.run(auto.run(cfg, force=args.force, progress=lambda t: print(t, flush=True)))
        print("Nie minęło jeszcze ANALYZER_AUTO_DAYS - użyj --force." if result is None else "Gotowe.")
    elif args.command == "photos":
        from .photos import archive, status_line
        conn = db.connect(cfg.db_path)
        asyncio.run(archive(cfg, conn, limit=args.limit))
        conn.close()
        print(status_line(cfg))
    elif args.command == "remote":
        from . import remote
        asyncio.run(remote.main(cfg))
    elif args.command == "sample":
        from .sample import export
        print(f"Otwieram bazę {cfg.db_path} ...", flush=True)
        conn = db.connect(cfg.db_path)
        path, counts = export(conn, Path(cfg.db_path).parent, args.per_category,
                              progress=lambda text: print(text, flush=True))
        conn.close()
        print(f"Zapisano {sum(counts.values())} ofert ({', '.join(f'{k} {v}' for k, v in counts.items())}) -> {path}")
        print(f"Rozmiar: {path.stat().st_size / 1e6:.1f} MB")
    elif args.command == "diag":
        from .diag import report
        conn = db.connect(cfg.db_path)
        print("\n".join(report(conn)))
        conn.close()
    elif args.command == "status":
        say = lambda text: print(text, flush=True)  # noqa: E731
        say(f"Otwieram bazę {cfg.db_path} ...")
        conn = db.connect(cfg.db_path)
        lines = status_lines(conn, progress=say)
        conn.close()
        say("")
        print("\n".join(lines))
        say("")
        say(data_size_line(cfg.db_path))
        from .photos import status_line as photos_line
        say(photos_line(cfg))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Przerwane ręcznie - `python -m analyzer crawl` wznowi przejście.")
