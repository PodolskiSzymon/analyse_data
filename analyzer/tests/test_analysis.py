"""Testy analizy danych (PLAN_ANALIZY.md, A2-A6) na atrapie rynku (fake_market) - bez sieci."""
import pytest

from analyzer import analysis
from analyzer.tests import fake_market


@pytest.fixture(scope="module")
def market(tmp_path_factory):
    path = tmp_path_factory.mktemp("rynek") / "analyzer.db"
    truth = fake_market.build(path)
    return path, truth


# ------------------------------------------------------------------ A2: atrapa


def test_fake_market_builds_consistent_database(market):
    path, truth = market
    conn = analysis.open_ro(path)
    n = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    assert 2000 <= n <= 5000 and n == len(truth.rows)
    states = {r[0] for r in conn.execute("SELECT DISTINCT state FROM listings")}
    assert {"active", "sold", "deleted", "blocked", "below_min", "ignored"} <= states
    cats = {r[0] for r in conn.execute("SELECT DISTINCT category FROM listings")}
    assert set(analysis.CATEGORIES) <= cats
    # zagraniczne z ułamkową ceną, obniżki i oferty z pierwszego przejścia bez created_at są w atrapie
    assert any(r["market"] == "zagr" for r in truth.rows.values())
    assert sum(r["drop"] is not None for r in truth.rows.values()) > 100
    assert any(r["initial"] and r["created_at"] is None for r in truth.rows.values())
    assert analysis.initial_until(conn)[3580].startswith("2026-10-11T12:00")
    assert analysis.latest_seen(conn) == truth.now
    with pytest.raises(Exception):                    # tylko do odczytu
        conn.execute("UPDATE listings SET state='x'")
    conn.close()


def test_helpers():
    assert analysis.percentile([1, 2, 3, 4], 0.5) == 2.5 and analysis.percentile([], 0.5) is None
    assert analysis.percentile([10, 20, 30, 40, 50], 0.25) == 20
    assert analysis.market("PLN", 10.5) == "PL" and analysis.market("EUR", 10) == "zagr"
    assert analysis.market(None, 950.37) == "zagr" and analysis.market(None, 950.0) == "PL"
    assert analysis.cpu_line_of("i5-8350u") == "intel core i5"
    assert analysis.cpu_line_of("ryzen 5 5500u") == "amd ryzen 5" and analysis.cpu_line_of("apple m1 pro") == "apple m1"
    assert analysis.parent_key("laptop", "x|i5-8350u|?|16|256", cpu="i5-8350u", ram_gb=16) == "intel core i5|16"
    assert analysis.parent_key("phone", "iphone 13|128", model="iphone 13") == "iphone 13"
    assert analysis.parent_key("console", "playstation 5|disc|?") == "playstation 5|disc"
    assert analysis.parent_key("ram", "ddr4|so-dimm|16") == "ddr4|16"
    assert analysis.parent_key("storage", "nvme|1000") == "1000"


# ------------------------------------------------------------------ A3: flagi podejrzanych


@pytest.fixture(scope="module")
def flagged(market):
    from analyzer import suspicious
    path, truth = market
    conn, aconn = analysis.open_ro(path), analysis.open_analysis(path)
    suspicious.run(conn, aconn)
    yield conn, aconn, truth
    conn.close()
    aconn.close()


def test_flags_match_truth_exactly(flagged):
    conn, aconn, truth = flagged
    got = {}
    for lid, flag in aconn.execute("SELECT listing_id, flag FROM flags"):
        got.setdefault(lid, set()).add(flag)
    assert got == truth.flags          # tło atrapy nie dostaje żadnej flagi, scenariusze - dokładnie oczekiwane


def test_suspicious_report_and_exclusions(flagged):
    from analyzer import suspicious
    conn, aconn, truth = flagged
    excluded = suspicious.load(aconn)
    assert truth.ids["shop0"] not in excluded and truth.ids["mention_allegro"] not in excluded   # informacyjne
    assert excluded[truth.ids["dup_blocked"]] == {"dup_title_price", "too_cheap"}     # blocked tylko informacyjnie
    assert truth.ids["blocked_console"] not in excluded and truth.ids["generic0"] not in excluded
    lines = suspicious.report(conn, aconn)
    row = next(line for line in lines if line.startswith("dup_title_price"))
    assert row.split()[1:9] == ["0", "4", "0", "0", "0", "0", "0", "4"]
    assert any(f"https://www.vinted.pl/items/{truth.ids['off_olx']}" in line for line in lines)
    assert "(is_suspicious wyłączone" in "\n".join(lines)
    head = next(i for i, line in enumerate(lines) if line.startswith("stan       ofert"))
    blocked = lines[head + 1]
    assert blocked.split()[1:4] == ["2", "1", "0.13"]        # 519 zł / mediana iPhone 16 Pro (~4100 zł)


def test_photo_flag_and_diag(market, tmp_path):
    from analyzer import suspicious
    path, truth = market
    conn = analysis.open_ro(path)
    photo = {lid for lid, flag, _ in suspicious.photo_flags(conn)}
    assert photo == {truth.ids[n] for n in ("dup_blocked", "dup_sold", "dup_deleted", "dup_active",
                                             "blocked_console")}
    lines = suspicious.photo_diag(conn, per_state=500)
    row = next(line for line in lines if line.startswith("photo.is_suspicious"))
    assert "100.0% (2/2)" in row          # oba blocked mają is_suspicious=true (katalog)
    row = next(line for line in lines if line.startswith("photos[].is_suspicious"))
    assert "100.0% (1/1)" in row          # sidebar: blocked z opisem (dup_blocked) - choć jedno zdjęcie true
    assert any(line.startswith("is_promoted") for line in lines)
    assert any(line.startswith("is_closed") for line in lines)
    conn.close()


@pytest.mark.parametrize("title, desc, hits", [
    ("iPhone 15 Pro", "Sprzedaż wyłącznie przez OLX/Allegro", ["tylko olx/allegro"]),
    ("Laptop", "Kontakt: whats app", ["whatsapp"]),
    ("Laptop", "Write me on Telegram", ["telegram"]),
    ("Laptop", "Kontakt außerhalb von Vinted bitte", ["poza vinted"]),
    ("Laptop", "Scrie-mi în afara Vinted", ["poza vinted"]),
    ("Laptop", "Tylko odbiór osobisty i przelew", ["przelew poza"]),
    ("Laptop", "Płatność BLIK na telefon", ["blik"]),
    ("Laptop", "tel. 600-700-800", ["telefon"]),
    ("Laptop", "Zadzwoń +48 600 700 800", ["telefon"]),
    ("Laptop", "pisz: jan@example.com", ["e-mail"]),
])
def test_offsite_detected(title, desc, hits):
    from analyzer.suspicious import offsite_hits
    assert offsite_hits(title, desc)[0] == hits


@pytest.mark.parametrize("desc", [
    "Pojemności 128 256 512 GB do wyboru", "Rozdzielczość 1920 1080 144 Hz", "IMEI 356789012345678",
    "Kupiony na Allegro, faktura", "Bateria 100%, numer seryjny na zdjęciu", "Signal wifi mocny",
])
def test_offsite_false_positives(desc):
    from analyzer.suspicious import offsite_hits
    assert offsite_hits("Laptop", desc)[0] == []


# ------------------------------------------------------------------ A4: relisty


@pytest.fixture(scope="module")
def relisted(market):
    from analyzer import relist
    path, truth = market
    conn, aconn = analysis.open_ro(path), analysis.open_analysis(path)
    relist.run(conn, aconn)
    yield conn, aconn, truth
    conn.close()
    aconn.close()


def test_relists_match_truth_exactly(relisted):
    from analyzer import relist
    conn, aconn, truth = relisted
    assert relist.load(aconn) == truth.relists     # para, łańcuch A→B→C, bez opisu; podobne nie-relisty pominięte
    basis = dict(aconn.execute("SELECT new_id, basis FROM relists").fetchall())
    assert basis[truth.ids["r1_new"]] == "description" and basis[truth.ids["r3_new"]] == "title"
    assert basis[truth.ids["r2_c"]] == "description"          # podobny tytuł + podobny opis


def test_relist_chain_roots_and_report(relisted):
    from analyzer import relist
    conn, aconn, truth = relisted
    roots = relist.roots(relist.load(aconn))
    ids = truth.ids
    assert roots[ids["r2_c"]] == roots[ids["r2_b"]] == roots[ids["r2_a"]] == ids["r2_a"]
    lines = relist.report(conn, aconn)
    laptop = next(line for line in lines if line.startswith("laptop"))
    deleted = sum(1 for r in truth.rows.values() if r["category"] == "laptop" and r["state"] == "deleted")
    assert laptop.split()[1:3] == [str(deleted), "4"]          # r1_old, r2_a, r2_b, r3_old
    assert any("łańcuchy" in line and "3: 2" in line for line in lines)


def test_relist_rules_unit():
    from analyzer.relist import match
    # para najbliższa w czasie wygrywa; stara i nowa użyte najwyżej raz
    pairs = [(5.0, 0.9, "title", 1, 3), (0.5, 0.9, "title", 1, 2), (0.5, 1.0, "description", 2, 3)]
    assert {(o, n) for o, n, *_ in match(pairs)} == {(1, 2), (2, 3)}


# ------------------------------------------------------------------ A5: statystyki i raport


@pytest.fixture(scope="module")
def stats_result(relisted, flagged):
    from analyzer import relist, stats, suspicious
    conn, aconn, truth = relisted
    return stats.collect(conn, suspicious.load(aconn, ("dup_title_price", "offsite", "too_cheap")),
                         relist.load(aconn), age_days=14, progress=False), truth


def test_galaxy_group_counted_by_hand(stats_result):
    """phone `galaxy s21|128`, PL, sprawne: aktywne 800/900/1000/1100/1200 (a1, a2 starsze niż 14 dni), sprzedane
    850/900/950 (dni: 2, 4; s3 z pierwszego przejścia bez created_at - pominięta), 2 usunięte; obniżki: a5 1300→1200
    po 2 dniach, s2 1000→900 po 2 dniach."""
    result, _ = stats_result
    m = result["groups"][("config", "phone", "galaxy s21|128", "PL", "ok")]
    assert (m["n_active"], m["active_p25"], m["active_med"], m["active_p75"]) == (5, 900, 1000, 1100)
    assert (m["n_sold"], m["sold_p25"], m["sold_med"], m["sold_p75"]) == (3, 875, 900, 925)
    assert (m["n_deleted"], m["n_old_active"]) == (2, 2)
    assert (m["st_low"], m["st_high"]) == (round(3 / 7, 4), round(5 / 7, 4))
    assert (m["days_med"], m["days_n"]) == (3.0, 2)
    assert m["drop_share"] == 0.2 and m["n_dropped"] == 2 and m["drop_days_med"] == 2.0
    assert m["drop_pct_med"] == pytest.approx((100 / 1300 * 100 + 10) / 2)
    assert (m["st_low_dropped"], m["st_low_not_dropped"]) == (1.0, round(2 / 6, 4))
    assert (m["fav_active_med"], m["fav_sold_med"], m["views_active_med"], m["views_sold_med"]) == (3, 20, 30, 200)
    assert m["spread"] == 0.9 and m["low_data"] is False
    foreign = result["groups"][("config", "phone", "galaxy s21|128", "zagr", "ok")]
    damaged = result["groups"][("config", "phone", "galaxy s21|128", "PL", "uszk")]
    assert (foreign["n_active"], foreign["active_med"], foreign["low_data"]) == (1, 950.37, True)
    assert (damaged["n_active"], damaged["active_med"]) == (1, 300)
    parent = result["groups"][("parent", "phone", "galaxy s21", "PL", "ok")]
    assert parent["n_sold"] == 3 and parent["active_med"] == 1000


def test_all_config_groups_match_truth(stats_result):
    """Niezależne przeliczenie z opisu ofert atrapy: liczności, mediany cen, dni do sprzedaży (relisty od początku
    łańcucha), stare aktywne - dla KAŻDEJ grupy konfiguracji."""
    from datetime import timedelta

    from analyzer import analysis as an
    result, truth = stats_result
    excluded = {lid for lid, flags in truth.flags.items() if flags & {"dup_title_price", "offsite", "too_cheap"}}
    old_ids = set(truth.relists.values())

    def root(lid):
        while lid in truth.relists:
            lid = truth.relists[lid]
        return truth.rows[lid]

    now = fake_market.NOW
    expected = {}
    for r in truth.rows.values():
        if r["key"] is None or r["state"] not in ("active", "sold", "deleted", "blocked") or r["id"] in excluded \
                or r["id"] in old_ids:
            continue
        g = expected.setdefault(("config", r["category"], r["key"], r["market"], "uszk" if r["damaged"] else "ok"),
                                {"a": [], "s": [], "d": 0, "days": [], "old": 0})
        rt = root(r["id"])
        start = rt["created_at"] or rt["first_seen"]
        reliable = rt["created_at"] is not None or not rt["initial"]
        if r["state"] == "active":
            g["a"].append(r["price_now"])
            g["old"] += now - start > timedelta(days=14)
        elif r["state"] in ("sold", "blocked"):                   # blocked = sprzedana (strona usunięta)
            g["s"].append(r["sold_price"] if r["sold_price"] is not None else r["price_now"])
            if reliable:
                g["days"].append((r["last_seen"] - start).total_seconds() / 86400)
        else:
            g["d"] += 1
    got = {k: m for k, m in result["groups"].items() if k[0] == "config"}
    assert set(got) == set(expected)
    for k, e in expected.items():
        m = got[k]
        assert (m["n_active"], m["n_sold"], m["n_deleted"], m["n_old_active"], m["days_n"]) == \
            (len(e["a"]), len(e["s"]), e["d"], e["old"], len(e["days"])), k
        assert m["active_med"] == pytest.approx(an.median(e["a"])) if e["a"] else m["active_med"] is None
        assert m["sold_med"] == pytest.approx(an.median(e["s"])) if e["s"] else m["sold_med"] is None
        assert m["days_med"] == pytest.approx(an.median(e["days"])) if e["days"] else m["days_med"] is None


def test_relist_chain_time_on_market(stats_result):
    """r1: A wystawiona 10-14 (created_at), usunięta, B sprzedana 10-21 → 7 dni (nie 3 dni od wystawienia B)."""
    from analyzer import stats
    result, truth = stats_result
    t480 = result["groups"][("config", "laptop", "thinkpad t480|i5-8350u|integrated|16|256", "PL", "ok")]
    assert t480["n_deleted"] == sum(1 for r in truth.rows.values() if r["key"] == "thinkpad t480|i5-8350u|integrated"
                                    "|16|256" and r["state"] == "deleted" and r["market"] == "PL" and not r["damaged"]
                                    and r["id"] not in truth.relists.values())
    g = stats.Group()
    row = {"favourite_count": None, "view_count": None}
    r1_old = truth.rows[truth.ids["r1_old"]]
    stats._add(g, "sold", 1190, row, r1_old["created_at"], True, truth.rows[truth.ids["r1_new"]]["last_seen"],
               fake_market.NOW, None, None)
    assert g.days == [7.0]


def test_price_drops_ignore_fx_drift(market):
    from analyzer import stats
    path, truth = market
    conn = analysis.open_ro(path)
    drops = stats.price_drops(conn, progress=False)
    expected = {lid for lid, r in truth.rows.items() if r["drop"] is not None}
    assert set(drops) == expected
    for lid in expected:
        first, low, at = drops[lid]
        assert (first - low) / first * 100 == pytest.approx(truth.rows[lid]["drop"]["pct"])
    conn.close()


def test_report_files(market, tmp_path):
    import csv

    from analyzer import report
    path, truth = market
    conn, aconn = analysis.open_ro(path), analysis.open_analysis(path)
    out = tmp_path / "2026-10-24"
    out.mkdir()
    paths, lines, result = report.build(conn, aconn, out, bar=False)
    conn.close()
    aconn.close()
    text = paths["summary"].read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 150 and "górna granica" in text and "dolna = sold /" in text
    assert "`galaxy s21 / 128`" in text                 # „|” nie rozbija tabeli markdown
    header = None
    for line in text.splitlines():                     # każdy wiersz tabeli ma tyle kolumn co jej nagłówek
        if not line.startswith("|"):
            header = None
        elif header is None:
            header = line.count("|")
        else:
            assert line.count("|") == header, line
    with open(paths["configs"], encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(result["groups"])
    galaxy = next(r for r in rows if r["level"] == "config" and r["key"] == "galaxy s21|128" and r["market"] == "PL"
                  and r["cond"] == "ok")
    assert (galaxy["n_sold"], galaxy["sold_med"], galaxy["st_low"]) == ("3", "900.0", "0.43")
    page = paths["html"].read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and 'id=configs' in page and "http" not in page.split("<body>")[0]


# ------------------------------------------------------------------ A6: eksport


def test_export_analysis(market, tmp_path, flagged):
    import csv
    import gzip
    import json

    from analyzer import export
    path, truth = market
    conn, aconn = analysis.open_ro(path), analysis.open_analysis(path)
    result = export.run(conn, tmp_path, aconn, with_descriptions=True, progress=False)
    conn.close()
    aconn.close()
    assert set(result) == {"listings.csv.gz", "features.csv.gz", "observations_real.csv.gz", "crawl_runs.csv",
                           "flags.csv", "relists.csv", "descriptions.jsonl.gz"}
    with gzip.open(tmp_path / "listings.csv.gz", "rt", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert "seller_hash" not in rows[0] and "photo_url" not in rows[0]              # RODO / zbędne
    assert len(rows) == sum(1 for r in truth.rows.values() if r["state"] != "ignored")
    # observations: pierwsza + prawdziwe zmiany - dryf kursu (<1% u zagranicznych) wycięty
    with gzip.open(tmp_path / "observations_real.csv.gz", "rt", encoding="utf-8") as f:
        obs = list(csv.DictReader(f))
    expected = sum(1 + (r["drop"] is not None) for r in truth.rows.values() if r["state"] != "ignored")
    assert len(obs) == expected
    with gzip.open(tmp_path / "descriptions.jsonl.gz", "rt", encoding="utf-8") as f:
        descs = {d["id"]: d for d in map(json.loads, f)}
    assert descs[truth.ids["off_email"]]["description"] == "Pytania: [email]"
    assert "600 700 800" not in descs[truth.ids["off_phone"]]["description"]
    assert result["flags.csv"][0] == sum(len(v) for v in truth.flags.values())
    lines = export.size_lines(result, tmp_path)
    assert lines[-1].strip().startswith("razem")


def test_delay_buckets_and_price_ratios(stats_result):
    """Zwłoka sprawdzenia (atrapa: services_at = last_seen + 1 dzień) → przedział 1–2 dni; ilorazy cen do mediany
    aktywnych tej samej konfiguracji; ceny usuniętych w grupie."""
    from analyzer import report
    result, truth = stats_result
    rows = report.delay_rows(result)
    assert [r[0] for r in rows] == ["1–2 dni"]
    gone = [r for r in truth.rows.values() if r["state"] in ("sold", "deleted", "blocked")]
    assert rows[0][1] + rows[0][2] <= len(gone)
    g = result["groups"][("config", "phone", "galaxy s21|128", "PL", "ok")]
    assert (g["deleted_med"], g["deleted_p25"]) == (1000.0, 1000.0)
    ratios = result["ratios"][("phone", "PL", "ok")]
    assert ratios["sold"][1] > 3 and 0.8 < ratios["sold"][0] < 1.2      # tło: sprzedane ~ aktywne
    assert report.category_rows(result)[1][0] == "telefony"


@pytest.mark.parametrize("text, parts", [
    ("Bez defektów, wszystko działa", False), ("no defects", False), ("Działa, nie jest uszkodzony", False),
    ("not broken", False), ("Brak jakichkolwiek uszkodzeń i defektów", False), ("keine Defekte", False),
    ("na części", True), ("uszkodzony ekran", True), ("Bez rys, bez pęknięć. Uszkodzona bateria", True),
    ("bez ładowarki, uszkodzony", True), ("nie działa tylko jeden klawisz", True),
])
def test_for_parts_negation(text, parts):
    from analyzer.extract import FOR_PARTS, has_fault, norm
    assert has_fault(FOR_PARTS, norm(text)) is parts


# ------------------------------------------------------------------ stan techniczny przez AI (ai_condition)


class FakeConditionBackend:
    """Atrapa dostawcy AI: „na części” / „nie włącza” → for_parts, reszta → working; zapisuje zapytania."""
    model = "fake-model"

    def __init__(self):
        self.calls = []

    async def ask(self, text, photos, system=None, schema=None, max_tokens=None):
        import json
        self.calls.append((text, photos, system, schema))
        parts = "na części" in text or "nie włącza" in text
        return json.dumps({"condition": "for_parts" if parts else "working", "cracked_screen": "no",
                           "locked": "unknown", "photo_damage": "unknown",
                           "evidence": "na części" if parts else "bez defektów"}), (1000, 50)

    async def close(self):
        pass


def test_ai_condition_candidates_run_cache_and_report(market, tmp_path):
    import asyncio
    import shutil

    from analyzer import ai_condition
    path, truth = market
    copy = tmp_path / "analyzer.db"                       # własna analysis.db obok kopii bazy
    shutil.copy(path, copy)
    conn, aconn = analysis.open_ro(copy), analysis.open_analysis(copy)
    items = ai_condition.candidates(conn, aconn, ("flagged",))           # domyślnie wszystkie zdjęcia
    ids = {row["id"] for row, *_ in items}
    assert {truth.ids["cond_negated"], truth.ids["cond_parts"]} <= ids      # wzmianka o usterce (też zaprzeczona)
    assert truth.ids["off_whatsapp"] not in ids                             # opis bez wzmianki o usterce
    by_id = {row["id"]: urls for row, _d, urls, _k in items}
    assert len(by_id[truth.ids["cond_parts"]]) == 2                         # oba zdjęcia ze szczegółów (sidebar)
    assert len(ai_condition.candidates(conn, aconn, ("flagged",), photos=1)[0][2]) == 1
    backend = FakeConditionBackend()
    stats = asyncio.run(ai_condition.run(aconn, items, backend, progress=False, flush_every=7))
    assert stats["done"] == len(items) and stats["failed"] == 0 and stats["tokens_in"] == 1000 * len(items)
    assert backend.calls[0][2] == ai_condition.INSTRUCTION and backend.calls[0][3] == ai_condition.SCHEMA
    dmg = ai_condition.load_damaged(aconn)
    assert dmg[truth.ids["cond_parts"]] is True and dmg[truth.ids["cond_negated"]] is False
    assert ai_condition.candidates(conn, aconn, ("flagged",)) == []          # ta sama treść - z pamięci
    assert len(ai_condition.candidates(conn, aconn, ("flagged",), again=True)) == len(items)
    lines = ai_condition.report(conn, aconn)
    assert lines[0] == f"Stan z AI: {len(items)} ofert" and any("zgodność" in line for line in lines)
    sold = ai_condition.candidates(conn, aconn, ("sold",), photos=0, again=True)
    assert sold and all(row["state"] in ai_condition.SOLD_STATES for row, *_ in sold)
    assert all(urls == [] for _r, _d, urls, _k in sold)
    conn.close()
    aconn.close()


def test_ai_condition_overrides_rules_in_stats(stats_result, relisted):
    from analyzer import relist, stats, suspicious
    conn, aconn, truth = relisted
    base, _ = stats_result
    ai = {truth.ids["g_a1"]: True, truth.ids["g_parts"]: False}           # AI: a1 uszkodzona, „zbity ekran” sprawny
    result = stats.collect(conn, suspicious.load(aconn, ("dup_title_price", "offsite", "too_cheap")),
                           relist.load(aconn), progress=False, ai_damaged=ai)
    before = base["groups"][("config", "phone", "galaxy s21|128", "PL", "ok")]
    after = result["groups"][("config", "phone", "galaxy s21|128", "PL", "ok")]
    assert (before["n_active"], after["n_active"]) == (5, 5)              # -a1 (800), +g_parts (300)
    assert after["active_p25"] == 900 and after["active_med"] == 1000
    assert result["groups"][("config", "phone", "galaxy s21|128", "PL", "uszk")]["active_med"] == 800


def test_ai_condition_estimate_and_parse():
    from analyzer import ai_condition
    row = {"category": "laptop", "title": "x" * 35, "status_label": "Dobry", "attributes_json": "{}"}
    items = [(row, "y" * 315, ["u1", "u2", "u3"], "k")] * 1000
    lines = ai_condition.estimate(items, "gemini", (0.75, 3.75))
    assert lines[0].startswith("Do oceny: 1000 ofert, zdjęć razem 3000 (śr. 3.0")
    assert "ze zdjęciami (3000)" in lines[1] and "~$" in lines[1] and "sam tekst" in lines[2]
    assert "cena nieznana" in ai_condition.estimate(items, "gemini", None)[1]
    r = ai_condition.parse_result('{"condition": "minor_issues", "cracked_screen": "maybe", "locked": "no", '
                                  '"photo_damage": "yes", "evidence": "martwy piksel"}')
    assert r["cracked_screen"] == "unknown" and not ai_condition.damaged(r)
    with pytest.raises(ValueError):
        ai_condition.parse_result('{"condition": "broken"}')


def test_backend_sends_several_photos_anthropic():
    import asyncio
    from types import SimpleNamespace

    from analyzer.ai_classify import Backend
    seen = {}

    class Messages:
        async def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="{}")],
                                   usage=SimpleNamespace(input_tokens=10, output_tokens=2))

    client = SimpleNamespace(beta=SimpleNamespace(messages=Messages()))
    backend = Backend(SimpleNamespace(provider="anthropic", photos="url"), "claude-haiku-5-5", client=client)
    text, usage = asyncio.run(backend.ask("opis", ["https://a/1.jpg", "https://a/2.jpg"], system="S",
                                          schema={"type": "object"}, max_tokens=300))
    content = seen["messages"][0]["content"]
    assert [c["type"] for c in content] == ["image", "image", "text"] and seen["system"] == "S"
    assert seen["max_tokens"] == 300 and usage == (10, 2)


def test_ai_condition_stops_after_error_streak(market, tmp_path):
    """Skończone środki na koncie API (przedpłata): seria błędów → przerwanie, wyniki sprzed błędów zapisane."""
    import asyncio
    import shutil

    from analyzer import ai_condition
    path, _truth = market
    copy = tmp_path / "analyzer.db"
    shutil.copy(path, copy)
    conn, aconn = analysis.open_ro(copy), analysis.open_analysis(copy)
    items = ai_condition.candidates(conn, aconn, ("sold",), photos=0)
    assert len(items) > 30

    class Broke(FakeConditionBackend):
        async def ask(self, *a, **kw):
            if len(self.calls) >= 5:
                self.calls.append(None)
                raise RuntimeError("429 RESOURCE_EXHAUSTED: prepayment credits depleted")
            return await super().ask(*a, **kw)

    backend = Broke()
    stats = asyncio.run(ai_condition.run(aconn, items, backend, concurrency=1, progress=False, stop_after=10))
    assert stats["done"] == 5 and stats["failed"] == 10 and "RESOURCE_EXHAUSTED" in stats["stopped"]
    assert len(backend.calls) < len(items)                       # reszty już nie wysłał
    assert aconn.execute("SELECT COUNT(*) FROM ai_condition").fetchone()[0] == 5
    assert len(ai_condition.candidates(conn, aconn, ("sold",), photos=0)) == len(items) - 5   # wznowienie
    conn.close()
    aconn.close()


def test_ai_condition_falls_back_to_text_when_photos_gone(market, tmp_path):
    """Zdjęcia usuniętej oferty: dostawca AI 404 „Cannot fetch content” → ta sama oferta samym tekstem; nie liczy się
    do serii błędów przerywającej przebieg."""
    import asyncio
    import shutil

    from analyzer import ai_condition
    path, _truth = market
    copy = tmp_path / "analyzer.db"
    shutil.copy(path, copy)
    conn, aconn = analysis.open_ro(copy), analysis.open_analysis(copy)
    items = ai_condition.candidates(conn, aconn, ("sold",), photos=2)[:30]
    assert all(urls for _r, _d, urls, _k in items)

    class PhotosGone(FakeConditionBackend):
        async def ask(self, text, photos, **kw):
            if photos:
                self.calls.append(("photo", photos))
                raise RuntimeError("404 NOT_FOUND. {'error': {'code': 404, 'message': 'Cannot fetch content from the "
                                   "provided URL. The URL could not be found.'}}")
            return await super().ask(text, photos, **kw)

    stats = asyncio.run(ai_condition.run(aconn, items, PhotosGone(), concurrency=1, progress=False, stop_after=5))
    assert (stats["done"], stats["failed"], stats["stopped"]) == (30, 0, None)
    assert {r[0] for r in aconn.execute("SELECT DISTINCT photos FROM ai_condition")} == {0}
    assert ai_condition.photo_unavailable(RuntimeError("400 Unable to download the file from the URL"))
    assert not ai_condition.photo_unavailable(RuntimeError("429 RESOURCE_EXHAUSTED"))
    conn.close()
    aconn.close()
