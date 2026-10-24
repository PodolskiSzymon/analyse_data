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
    assert excluded[truth.ids["dup_blocked"]] == {"blocked", "dup_title_price", "too_cheap"}
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
    return stats.collect(conn, suspicious.load(aconn, ("blocked", "dup_title_price", "offsite", "too_cheap")),
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
    excluded = {lid for lid, flags in truth.flags.items() if flags & {"blocked", "dup_title_price", "offsite",
                                                                       "too_cheap"}}
    old_ids = set(truth.relists.values())

    def root(lid):
        while lid in truth.relists:
            lid = truth.relists[lid]
        return truth.rows[lid]

    now = fake_market.NOW
    expected = {}
    for r in truth.rows.values():
        if r["key"] is None or r["state"] not in ("active", "sold", "deleted") or r["id"] in excluded \
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
        elif r["state"] == "sold":
            g["s"].append(r["sold_price"])
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
