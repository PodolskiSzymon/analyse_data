"""`python -m analyzer api-test` - test API Vinted na żywo (prośba użytkownika 2026-11-13).

Kilka zapytań (~10, zwykle < 1 MB przez proxy), bez zapisu do głównej bazy (tylko odczyt):
  1. katalog: partycja z największą dziurą w pokryciu (albo dowolna z 500–960 ofert) - strony 1..5:
     ile ofert na stronie, total_entries / total_pages / per_page, nowe klucze, powtórki ID między stronami,
     ceny poza zakresem zapytania,
  2. katalog bez filtra ceny, strona 1 (czy sama kategoria działa),
  3. szczegóły (sidebar) najnowszej aktywnej oferty - czy są pluginy item_status / description / attributes,
  4. jedno zdjęcie z CDN (bez proxy).
Wynik: tekst na ekran + `<folder bazy>/api_test/<czas>/` (podsumowanie + surowe odpowiedzi bez danych sprzedawców -
do wysłania w rozmowie). Przy problemach - ntfy (jak w watch).
"""
import json
import logging
from datetime import datetime
from pathlib import Path

from sniper.config import CATALOG_ONLY_HEADERS, CATALOG_URL

from .catalog import CATALOG_REFERER, build_params, parse_page, widen
from .config import catalog_label
from .health import Health, partition_coverage
from .probe import redact

log = logging.getLogger("analyzer.apitest")


def pick_partition(conn, catalog_id):
    """(price_from, price_to, total) - partycja z największym brakiem w bazie, inaczej największa ≤ 960."""
    run = conn.execute("SELECT MAX(done_run_id) FROM partitions WHERE catalog_id=? AND active=1",
                       (catalog_id,)).fetchone()[0]
    best = None
    if run is not None:
        for row in conn.execute("SELECT price_from, price_to, last_total, done_run_id FROM partitions WHERE "
                                "catalog_id=? AND active=1 AND last_total BETWEEN 300 AND 960 AND price_to IS NOT NULL",
                                (catalog_id,)):
            cov = partition_coverage(conn, catalog_id, row[3])
            label = f"{row[0]:g}-{format(row[1], 'g')} zł"
            have = next((h for lab, _t, h in cov if lab == label), row[2])
            gap = row[2] - have
            if best is None or gap > best[3]:
                best = (row[0], row[1], row[2], gap)
    if best is None:
        return 300.0, 400.0, None, None
    return best


async def run(cfg, session, conn, catalog_id, pages=5, out_dir=None, send=None, notify_problems=True,
              photo_client=None):
    from . import analysis, health as health_mod

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(out_dir) if out_dir else Path(cfg.db_path).parent / "api_test" / stamp
    out.mkdir(parents=True, exist_ok=True)
    lines, h = [], Health()

    def say(text):
        lines.append(text)
        print(text, flush=True)

    price_from, price_to, total_db, gap = pick_partition(conn, catalog_id)
    say(f"API test {stamp}: kategoria {catalog_label(catalog_id)}, partycja {price_from:g}-{price_to:g} zł"
        + (f" (w ostatnim przejściu Vinted {total_db}, brak w bazie {gap})" if total_db else ""))
    margin = getattr(cfg, "price_margin", 0.0) or 0.0
    low, high = widen(price_from, price_to, margin)
    collected, all_ids = 0, set()
    for page in range(1, pages + 1):
        params = build_params(catalog_id, page, cfg.per_page, low, high, cfg.order)
        try:
            data = await session.get_json(CATALOG_URL, params=params, referer=CATALOG_REFERER,
                                          extra_headers=CATALOG_ONLY_HEADERS)
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            h.request_error(f"HTTP {status}" if status else type(exc).__name__)
            say(f"  strona {page}: BŁĄD {exc!r}")
            break
        (out / f"katalog_strona_{page}.json").write_text(json.dumps(redact(data), ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
        result = parse_page(data if isinstance(data, dict) else {}, catalog_id, page, cfg.per_page, cfg.seller_salt)
        h.page(catalog_id, ("test", f"{price_from:g}-{price_to:g} zł"), page, cfg.per_page, result, (low, high),
               collected)
        ids = {it.id for it in result.items}
        again = len(ids & all_ids)
        all_ids |= ids
        collected += len(result.items)
        prices = [it.price for it in result.items if it.price is not None]
        pag = data.get("pagination") if isinstance(data, dict) else None
        say(f"  strona {page}: ofert {len(result.items)}, powtórzonych z poprzednich {again}, "
            f"ceny {min(prices) if prices else '-'}–{max(prices) if prices else '-'} zł | pagination: "
            f"{json.dumps(pag, ensure_ascii=False) if pag is not None else 'BRAK'}")
        if page == 1:
            say(f"  klucze odpowiedzi: {', '.join(sorted(data)) if isinstance(data, dict) else type(data).__name__}")
        if not result.items:
            break
    say(f"  razem: {collected} ofert, unikalnych ID {len(all_ids)}")

    try:
        data = await session.get_json(CATALOG_URL, params=build_params(catalog_id, 1, cfg.per_page, order=cfg.order),
                                      referer=CATALOG_REFERER, extra_headers=CATALOG_ONLY_HEADERS)
        result = parse_page(data if isinstance(data, dict) else {}, catalog_id, 1, cfg.per_page, cfg.seller_salt)
        say(f"Bez filtra ceny: ofert {len(result.items)}, total_entries {result.total_entries}, "
            f"total_pages {result.total_pages}")
    except Exception as exc:
        say(f"Bez filtra ceny: BŁĄD {exc!r}")

    row = conn.execute("SELECT id FROM listings WHERE catalog_id=? AND state='active' ORDER BY id DESC LIMIT 1",
                       (catalog_id,)).fetchone()
    if row is not None:
        from .resolver import fetch_sidebar
        try:
            status_code, body = await fetch_sidebar(session, row[0])
            h.sidebar(status_code, body)
            sidebar = body.get("item", body) if isinstance(body, dict) else {}
            names = [p.get("name") for p in (sidebar.get("plugins") or []) if isinstance(p, dict)]
            say(f"Szczegóły oferty {row[0]}: HTTP {status_code}, code {body.get('code') if isinstance(body, dict) else '?'}"
                f", pluginy: {', '.join(n for n in names if n) or 'BRAK'}")
            (out / "szczegoly.json").write_text(json.dumps(redact(body), ensure_ascii=False, indent=1),
                                                encoding="utf-8")
            missing = [p for p in health_mod.SIDEBAR_PLUGINS if p not in names] if status_code == 200 else []
            if missing:
                say(f"  BRAK pluginów: {', '.join(missing)}")
        except Exception as exc:
            say(f"Szczegóły oferty {row[0]}: BŁĄD {exc!r}")

    photo = conn.execute("SELECT photo_url FROM listings WHERE catalog_id=? AND state='active' AND photo_url IS NOT "
                         "NULL ORDER BY id DESC LIMIT 1", (catalog_id,)).fetchone()
    if photo is not None:
        import httpx
        client = photo_client or httpx.AsyncClient(trust_env=False, timeout=30, follow_redirects=True)
        try:
            r = await client.get(photo[0])
            ok = r.status_code == 200 and len(r.content) > 1000
            h.photos({"photos": int(ok), "errors": int(not ok)})
            say(f"Zdjęcie z CDN: HTTP {r.status_code}, {len(r.content)} B")
        except Exception as exc:
            say(f"Zdjęcie z CDN: BŁĄD {exc!r}")
        finally:
            if photo_client is None:
                await client.aclose()

    problems = h.evaluate_catalog() + h.evaluate_background()
    # Test robi kilka stron, więc progi „wielu stron” z watch są za wysokie - pojedyncze sygnały też zgłaszamy.
    extra = []
    if h.short_pages and not any(p.key == "katalog_krotkie" for p in problems):
        c, lab, p, n, t, got = h.short_pages[0]
        extra.append(health_mod.Problem("katalog_krotkie", "Vinted: krótka strona katalogu",
                                        [f"{lab}: strona {p} = {n} ofert, total_entries {t}, zebrane {got}."]))
    if h.repeated_pages and not any(p.key == "katalog_powtorki" for p in problems):
        c, lab, p, a, n = h.repeated_pages[0]
        extra.append(health_mod.Problem("katalog_powtorki", "Vinted: strona powtarza oferty",
                                        [f"{lab}: strona {p}: {a}/{n} ofert z poprzednich stron."]))
    if h.missing and h.items and not any(p.key == "katalog_pola" for p in problems):
        bad = {k: v for k, v in h.missing.items() if v >= h.items * 0.2}
        if bad:
            extra.append(health_mod.Problem("katalog_pola", "Vinted: brak pól w ofertach",
                                            [f"{k}: brak w {v}/{h.items}" for k, v in bad.items()]))
    problems += extra
    say("")
    if problems:
        say(f"WYNIK: {len(problems)} problem(y):")
        for p in problems:
            say(f"  - {p.title}: " + " | ".join(p.lines))
    else:
        say("WYNIK: API Vinted bez wykrytych zmian.")
    say(f"Pliki: {out}")
    (out / "podsumowanie.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if problems and notify_problems:
        aconn = analysis.open_analysis(cfg.db_path)
        try:
            await health_mod.report(cfg, problems, aconn, send=send)
        finally:
            aconn.close()
    return problems, lines
