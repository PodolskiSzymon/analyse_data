"""Kontrola zmian API Vinted (health.py, apitest.py) - atrapy „zmienionego Vinted” bez sieci."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx

from analyzer import analysis, apitest, db, health
from analyzer.catalog import parse_page
from analyzer.crawler import Crawler
from analyzer.health import Health
from analyzer.tests.fakes import FakeMarket, market_prices, no_sleep
from analyzer.tests.test_analyzer import make_cfg

FIX = json.load(open(__file__.replace("analyzer/tests/test_health.py", "sniper/tests/fixtures.json"),
                     encoding="utf-8"))


def crawl(market, conn=None, catalog_id=3580, h=None, **cfg_kw):
    cfg = make_cfg(**cfg_kw)
    conn = conn or db.connect(":memory:")
    h = h if h is not None else Health()
    crawler = Crawler(cfg, session=None, conn=conn, sleep=no_sleep, fetch=market.fetch, health=h)
    run_id, complete = asyncio.run(crawler.run(catalog_id))
    return conn, h, run_id, complete


def keys(problems):
    return sorted(p.key for p in problems)


# ---------------------------------------------------------------------------------------------- atrapy zmian API
class ShortPages(FakeMarket):
    """Vinted oddaje najwyżej `cap` ofert na stronę, a w pagination dalej per_page z zapytania."""
    def __init__(self, prices, cap=40, report_cap=False, **kw):
        super().__init__(prices, **kw)
        self.cap, self.report_cap = cap, report_cap

    def response(self, page, per_page, price_from, price_to):
        ids = self.query(price_from, price_to)
        visible = ids[:self.limit]
        chunk = visible[(page - 1) * self.cap: page * self.cap]
        data = super().response(1, 10 ** 6, price_from, price_to)
        data["items"] = [it for it in data["items"] if it["id"] in set(chunk)]
        data["pagination"] = {"current_page": page, "per_page": self.cap if self.report_cap else per_page,
                              "total_entries": len(ids), "total_pages": max(1, -(-len(visible) // per_page))}
        return data


class CursorPaging(FakeMarket):
    """Paginacja przestała działać: każda strona zwraca stronę 1 (np. Vinted przeszedł na kursor)."""
    def response(self, page, per_page, price_from, price_to):
        data = super().response(1, per_page, price_from, price_to)
        data["pagination"]["current_page"] = page
        return data


class Mutated(FakeMarket):
    """Dowolna zmiana odpowiedzi: mutate(data) -> data."""
    def __init__(self, prices, mutate, **kw):
        super().__init__(prices, **kw)
        self.mutate = mutate

    def response(self, page, per_page, price_from, price_to):
        return self.mutate(super().response(page, per_page, price_from, price_to))


class NoPriceFilter(FakeMarket):
    def response(self, page, per_page, price_from, price_to):
        return super().response(page, per_page, None, None)


# ---------------------------------------------------------------------------------------------- normalny rynek
def test_normal_market_no_problems():
    market = FakeMarket(market_prices(5000))
    conn, h, run_id, complete = crawl(market)
    assert complete
    assert h.evaluate_catalog(conn) == []
    for i in range(30):                                  # nowe oferty między przejściami
        market.items[900000 + i] = 1500.0 + i
    h2 = Health()
    conn, h2, _, _ = crawl(market, conn=conn, h=h2)     # drugie przejście (plan z bazy) też czyste
    assert h2.evaluate_catalog(conn) == []
    assert h.pages > 10 and h.items >= 5000 and not h.missing


def test_normal_market_without_pagination_no_problems_except_missing_total():
    market = FakeMarket(market_prices(3000), with_pagination=False)
    conn, h, _, _ = crawl(market)
    assert keys(h.evaluate_catalog(conn)) == ["katalog_paginacja"]


def test_oversize_partition_is_not_a_short_page_alarm():
    market = FakeMarket([500.0] * 3000)            # 3000 ofert w jednej cenie - limit 960 wyników
    conn, h, _, _ = crawl(market)
    assert "katalog_krotkie" not in keys(h.evaluate_catalog(conn))


# ---------------------------------------------------------------------------------------------- krótkie strony
def test_short_pages_crawler_continues_and_collects_all():
    """2026-11-13: krótka strona, a total_entries większe - crawler pobiera dalej zamiast uznać koniec partycji."""
    prices = market_prices(2000)
    market = ShortPages(prices, cap=60)
    conn, h, run_id, complete = crawl(market)
    assert complete
    unique = conn.execute("SELECT COUNT(*) FROM listings WHERE last_run_id=?", (run_id,)).fetchone()[0]
    # bez poprawki: ~1 strona (60) na partycję; z poprawką prawie wszystko (próg 95% total_entries chroni przed
    # dodatkowym pustym zapytaniem na końcu każdej normalnej partycji)
    assert unique >= 1900
    assert "katalog_krotkie" in keys(h.evaluate_catalog(conn))


def test_short_pages_reported_per_page():
    market = ShortPages(market_prices(2000), cap=24, report_cap=True)
    conn, h, _, _ = crawl(market)
    found = keys(h.evaluate_catalog(conn))
    assert "katalog_per_page" in found and "katalog_krotkie" in found


def test_short_pages_message_mentions_partition():
    market = ShortPages(market_prices(2000), cap=24)
    conn, h, _, _ = crawl(market)
    p = next(p for p in h.evaluate_catalog(conn) if p.key == "katalog_krotkie")
    assert p.severe and any("strona" in line for line in p.lines)


# ---------------------------------------------------------------------------------------------- paginacja
def test_cursor_paging_detected_and_crawler_stops():
    market = CursorPaging(market_prices(4000))
    conn, h, run_id, complete = crawl(market)
    found = keys(h.evaluate_catalog(conn))
    assert "katalog_powtorki" in found
    assert any(k.startswith("przejscie_pokrycie_") for k in found)       # w bazie tylko strony 1
    # crawler nie kręci się po powtórkach: najwyżej 2 strony na partycję
    pages = {}
    for pf, pt, page in market.requests:
        pages[(pf, pt)] = max(pages.get((pf, pt), 0), page)
    assert max(pages.values()) <= 2


def test_new_pagination_keys_warn_not_severe():
    def mutate(data):
        data["pagination"]["next_page_token"] = "abc"
        data["search_cursor"] = "x"
        return data
    conn, h, _, _ = crawl(Mutated(market_prices(1000), mutate))
    p = next(p for p in h.evaluate_catalog(conn) if p.key == "katalog_nowe_pola")
    assert not p.severe and "next_page_token" in " ".join(p.lines) and "search_cursor" in " ".join(p.lines)


def test_items_key_renamed():
    def mutate(data):
        return {"data": {"items": data["items"]}, "pagination": data["pagination"]}
    conn, h, _, _ = crawl(Mutated(market_prices(1000), mutate))
    assert "katalog_struktura" in keys(h.evaluate_catalog(conn))


def test_empty_first_page_with_total():
    def mutate(data):
        data["items"] = []
        return data
    conn, h, _, _ = crawl(Mutated(market_prices(1000), mutate))
    assert "katalog_puste" in keys(h.evaluate_catalog(conn))


# ---------------------------------------------------------------------------------------------- pola ofert
def _drop(field_path):
    def mutate(data):
        for it in data["items"]:
            obj = it
            for k in field_path[:-1]:
                obj = obj.get(k, {})
            obj.pop(field_path[-1], None)
        return data
    return mutate


def test_missing_price_field():
    conn, h, _, _ = crawl(Mutated(market_prices(1000), _drop(["price"])), price_max=20000.0)
    p = next(p for p in h.evaluate_catalog(conn) if p.key == "katalog_pola")
    assert "cena" in " ".join(p.lines)


def test_missing_photo_and_user():
    def mutate(data):
        for it in data["items"]:
            it.pop("photo")
            it.pop("user")
        return data
    conn, h, _, _ = crawl(Mutated(market_prices(1000), mutate))
    text = " ".join(next(p for p in h.evaluate_catalog(conn) if p.key == "katalog_pola").lines)
    assert "zdjęcie" in text and "sprzedawca" in text


def test_missing_item_box():
    conn, h, _, _ = crawl(Mutated(market_prices(1000), _drop(["item_box"])))
    assert "katalog_pola" in keys(h.evaluate_catalog(conn))


def test_few_items_missing_field_no_alarm():
    count = {"n": 0}

    def mutate(data):
        for it in data["items"]:
            count["n"] += 1
            if count["n"] % 20 == 0:          # 5% ofert bez zdjęcia - normalne
                it.pop("photo")
        return data
    conn, h, _, _ = crawl(Mutated(market_prices(1000), mutate))
    assert "katalog_pola" not in keys(h.evaluate_catalog(conn))


def test_price_filter_ignored():
    conn, h, _, _ = crawl(NoPriceFilter(market_prices(800)))
    assert "katalog_filtr_ceny" in keys(h.evaluate_catalog(conn))


# ---------------------------------------------------------------------------------------------- błędy HTTP
def test_many_catalog_errors():
    market = FakeMarket(market_prices(2000), fail=lambda pf, pt, page: page >= 1 and (pf or 0) > 1000)
    conn, h, _, _ = crawl(market)
    p = next(p for p in h.evaluate_catalog(conn) if p.key == "katalog_bledy")
    assert "OSError" in " ".join(p.lines)


def test_few_errors_no_alarm():
    calls = {"n": 0}

    def fail(pf, pt, page):
        calls["n"] += 1
        return calls["n"] % 15 == 0
    conn, h, _, _ = crawl(FakeMarket(market_prices(3000), fail=fail))
    assert "katalog_bledy" not in keys(h.evaluate_catalog(conn))


# ---------------------------------------------------------------------------------------------- przejścia w bazie
def _history(conn, catalog_id, seen_list, new_ids=50):
    for seen in seen_list:
        conn.execute("INSERT INTO crawl_runs (started_at, finished_at, kind, catalog_id, seen, new_ids) VALUES "
                     "('2026-11-01T00:00:00', '2026-11-01T01:00:00', 'crawl', ?, ?, ?)", (catalog_id, seen, new_ids))
    conn.commit()


def test_run_drop_detected():
    conn = db.connect(":memory:")
    _history(conn, 3580, [20000, 21000, 19500])
    conn, h, run_id, _ = crawl(FakeMarket(market_prices(3000)), conn=conn)
    p = next(p for p in h.evaluate_catalog(conn) if p.key == "przejscie_spadek_3580")
    assert "mediana" in p.lines[0]


def test_run_drop_needs_history():
    conn = db.connect(":memory:")
    _history(conn, 3580, [20000, 21000])         # za krótka historia
    conn, h, _, _ = crawl(FakeMarket(market_prices(3000)), conn=conn)
    assert not any(k.startswith("przejscie_spadek") for k in keys(h.evaluate_catalog(conn)))


def test_run_similar_to_history_ok():
    conn = db.connect(":memory:")
    _history(conn, 3580, [3000, 3100, 2950, 3050])
    conn, h, _, _ = crawl(FakeMarket(market_prices(3000)), conn=conn)
    assert h.evaluate_catalog(conn) == []


def test_no_new_offers_in_big_run():
    market = FakeMarket(market_prices(4000))
    conn, _, _, _ = crawl(market)
    conn, h, run_id, _ = crawl(market, conn=conn)          # te same oferty drugi raz = 0 nowych
    assert f"przejscie_brak_nowych_3580" in keys(h.evaluate_catalog(conn))


def test_partition_coverage_helper():
    conn, h, run_id, _ = crawl(FakeMarket(market_prices(3000)))
    cov = health.partition_coverage(conn, 3580, run_id)
    assert cov and all(have >= total for _l, total, have in cov)


# ---------------------------------------------------------------------------------------------- szczegóły, zdjęcia
def test_sidebar_ok():
    h = Health()
    for _ in range(40):
        h.sidebar(200, FIX["sidebar_active"])
    for _ in range(20):
        h.sidebar(404, {"code": 104})
    assert h.evaluate_background() == []


def test_sidebar_plugins_missing():
    h = Health()
    body = dict(FIX["sidebar_active"])
    body["plugins"] = [p for p in body["plugins"] if p["name"] != "description"]
    for _ in range(40):
        h.sidebar(200, body)
    p = next(p for p in h.evaluate_background() if p.key == "szczegoly_struktura")
    assert "description" in " ".join(p.lines)


def test_sidebar_wrapped_in_item_ok():
    h = Health()
    for _ in range(40):
        h.sidebar(200, {"item": FIX["sidebar_active"], "code": 0})
    assert h.evaluate_background() == []


def test_details_odd_codes():
    h = Health()
    for _ in range(20):
        h.sidebar(200, FIX["sidebar_active"])
    for _ in range(20):
        h.sidebar(403, {"_text": "blocked"})
    h.details_error("ConnectError")
    assert "szczegoly_bledy" in keys(h.evaluate_background())


def test_photos_failing():
    h = Health()
    h.photos({"offers": 30, "photos": 10, "bytes": 0, "errors": 90})
    assert keys(h.evaluate_background()) == ["zdjecia_bledy"]
    h2 = Health()
    h2.photos({"offers": 30, "photos": 200, "bytes": 0, "errors": 5})
    assert h2.evaluate_background() == []


def test_details_fetch_feeds_health():
    from analyzer.details import fetch_details

    class Sess:
        async def get_json(self, *a, **k):
            raise AssertionError

    conn = db.connect(":memory:")
    crawl(FakeMarket(market_prices(50)), conn=conn)
    h = Health()

    async def fake_sidebar(session, item_id):
        body = dict(FIX["sidebar_active"])
        body["plugins"] = []
        return 200, body
    import analyzer.details as details_mod
    old = details_mod.fetch_sidebar
    details_mod.fetch_sidebar = fake_sidebar
    try:
        asyncio.run(fetch_details(make_cfg(details_delay=(0.0, 0.0)), Sess(), conn, sleep=no_sleep, health=h))
    finally:
        details_mod.fetch_sidebar = old
    assert h.sidebars == 50
    assert "szczegoly_struktura" in keys(h.evaluate_background())


# ---------------------------------------------------------------------------------------------- powiadomienia
def _cfg(**kw):
    cfg = make_cfg(**kw)
    cfg.health_notify, cfg.health_repeat_hours = True, 12.0
    for k, v in kw.items():
        setattr(cfg, k, v)
    return cfg


def test_report_dedupe_and_priority():
    sent = []

    async def send(title, lines, priority=3, tags=()):
        sent.append((title, priority, lines))
        return True
    aconn = analysis.open_analysis(":memory:")
    now = datetime(2026, 11, 13, 8, tzinfo=timezone.utc)
    p1 = health.Problem("katalog_krotkie", "Vinted: krótkie strony", ["x"])
    p2 = health.Problem("katalog_nowe_pola", "Vinted: nowe pola", ["y"], severe=False)
    assert asyncio.run(health.report(_cfg(), [p1, p2], aconn, now=now, send=send)) == ["katalog_krotkie",
                                                                                      "katalog_nowe_pola"]
    assert sent[0][1] == 5 and "2 problemy" in sent[0][0] and "api-test" in sent[0][2][-1]
    assert asyncio.run(health.report(_cfg(), [p1], aconn, now=now + timedelta(hours=3), send=send)) == []
    assert len(sent) == 1
    assert asyncio.run(health.report(_cfg(), [p1], aconn, now=now + timedelta(hours=13), send=send)) == \
        ["katalog_krotkie"]
    p3 = health.Problem("katalog_nowe_pola_x", "Vinted: nowe pola", ["y"], severe=False)
    asyncio.run(health.report(_cfg(), [p3], aconn, now=now, send=send))
    assert sent[-1][1] == 3


def test_report_disabled_and_failed_send():
    sent = []

    async def send(title, lines, priority=3, tags=()):
        sent.append(title)
        return False
    aconn = analysis.open_analysis(":memory:")
    p = health.Problem("katalog_bledy", "Vinted: błędy", ["x"])
    assert asyncio.run(health.report(_cfg(health_notify=False), [p], aconn, send=send)) == []
    assert sent == []
    assert asyncio.run(health.report(_cfg(), [p], aconn, send=send)) == []      # nieudana wysyłka
    assert asyncio.run(health.report(_cfg(), [p], aconn, send=send)) == []
    assert len(sent) == 2                                                         # ponawia, bo nie zapisano terminu


# ---------------------------------------------------------------------------------------------- api-test
class FakeSession:
    """Atrapa VintedSession.get_json dla api-test: katalog z FakeMarket (albo jego wariantu)."""
    def __init__(self, market):
        self.market = market

    async def get_json(self, url, params=None, referer=None, extra_headers=None):
        p = dict(params)
        price_from = float(p["price_from"]) if p.get("price_from") else None
        price_to = float(p["price_to"]) if p.get("price_to") else None
        return self.market.response(int(p["page"]), int(p["per_page"]), price_from, price_to)


def _photo_client(status=200, size=5000):
    return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, content=b"x" * size)))


def _api_test(market, tmp_path, sidebar=None, photo_status=200):
    import analyzer.resolver as resolver_mod
    conn, _, _, _ = crawl(FakeMarket(market_prices(3000)))
    cfg = _cfg(db_path=str(tmp_path / "analyzer.db"))
    sent = []

    async def send(title, lines, priority=3, tags=()):
        sent.append(title)
        return True

    async def fake_sidebar(session, item_id):
        return sidebar or (200, FIX["sidebar_active"])
    old = resolver_mod.fetch_sidebar
    resolver_mod.fetch_sidebar = fake_sidebar
    try:
        problems, lines = asyncio.run(apitest.run(cfg, FakeSession(market), conn, 3580, out_dir=tmp_path / "out",
                                                  send=send, photo_client=_photo_client(photo_status)))
    finally:
        resolver_mod.fetch_sidebar = old
    return problems, lines, sent


def test_api_test_ok(tmp_path):
    problems, lines, sent = _api_test(FakeMarket(market_prices(3000)), tmp_path)
    assert problems == [] and sent == []
    assert "bez wykrytych zmian" in lines[-2]
    assert (tmp_path / "out" / "katalog_strona_1.json").exists()
    saved = json.loads((tmp_path / "out" / "katalog_strona_1.json").read_text(encoding="utf-8"))
    assert all(it["user"] in ("<redacted>",) or it["user"].get("redacted") for it in saved["items"])   # RODO
    assert (tmp_path / "out" / "podsumowanie.txt").exists()


def test_api_test_cursor_paging(tmp_path):
    problems, lines, sent = _api_test(CursorPaging(market_prices(3000)), tmp_path)
    assert "katalog_powtorki" in keys(problems) and sent


def test_api_test_short_page(tmp_path):
    problems, _, sent = _api_test(ShortPages(market_prices(3000), cap=30), tmp_path)
    assert "katalog_krotkie" in keys(problems) and sent


def test_api_test_sidebar_and_photo(tmp_path):
    body = dict(FIX["sidebar_active"])
    body["plugins"] = []
    problems, lines, _ = _api_test(FakeMarket(market_prices(3000)), tmp_path, sidebar=(200, body), photo_status=404)
    assert any("BRAK pluginów" in line for line in lines)
    assert any("HTTP 404" in line for line in lines)


def test_parse_page_keeps_pagination_keys():
    page = parse_page({"items": [], "pagination": {"total_entries": 1, "next_page_token": "x"}}, 1, 1, 96)
    assert "next_page_token" in page.pagination_keys
