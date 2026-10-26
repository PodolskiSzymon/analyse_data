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
    assert "seller_hash" in rows[0] and "photo_url" not in rows[0]                  # sprzedawca jako hash
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


def test_export_analysis_split(market, tmp_path, flagged):
    """--split: folder na kategorię, te same wiersze co bez podziału; wspólne pliki w folderze głównym."""
    import csv
    import gzip

    from analyzer import export
    path, truth = market
    conn, aconn = analysis.open_ro(path), analysis.open_analysis(path)
    whole = export.run(conn, tmp_path / "a", aconn, with_descriptions=True, progress=False)
    split = export.run(conn, tmp_path / "b", aconn, with_descriptions=True, progress=False, split=True)
    cats = {r[0] for r in conn.execute("SELECT DISTINCT category FROM listings WHERE state NOT IN "
                                       "('ignored', 'unclassified')")}
    conn.close()
    aconn.close()
    for name in ("listings.csv.gz", "features.csv.gz", "observations_real.csv.gz", "descriptions.jsonl.gz"):
        parts = {k: v for k, v in split.items() if k.endswith("/" + name)}
        assert parts and sum(n for n, _ in parts.values()) == whole[name][0], name
    assert {k.split("/")[0] for k in split if "/" in k and k.endswith("listings.csv.gz")} == cats
    assert "crawl_runs.csv" in split and "flags.csv" in split
    cat = sorted(cats)[0]
    with gzip.open(tmp_path / "b" / cat / "listings.csv.gz", "rt", encoding="utf-8") as f:
        assert {r["category"] for r in csv.DictReader(f)} == {cat}
    lines = export.size_lines(split, tmp_path / "b")
    assert any(line.strip().startswith(cat + "/") for line in lines)


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
    stats = asyncio.run(ai_condition.run(aconn, items, backend, concurrency=1, progress=False, stop_after=10,
                                         retries=()))
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


def test_rate_limiter_window():
    """Okno 60 s: 3 zapytania/min i 10 000 tokenów/min - czwarte (albo za dużo tokenów) czeka do zwolnienia okna."""
    import asyncio

    from analyzer.ai_condition import RateLimiter
    now, waits = [0.0], []

    async def sleep(seconds):
        waits.append(seconds)
        now[0] += seconds

    async def scenario():
        lim = RateLimiter(3, 10_000, clock=lambda: now[0], sleep=sleep)
        for _ in range(3):
            await lim.acquire(1000)
        assert waits == []
        await lim.acquire(1000)                    # 4. zapytanie w tej samej minucie → czeka 60 s
        assert waits == [60] and now[0] == 60
        await lim.acquire(9000)                    # 1000 + 9000 = 10 000 - mieści się
        now[0] += 1
        await lim.acquire(500)                     # przekroczyłoby TPM → czeka do wypadnięcia z okna
        assert waits[-1] == pytest.approx(59)

    asyncio.run(scenario())


def test_ai_condition_retries_rate_limit_and_runs_in_parallel(market, tmp_path):
    import asyncio
    import shutil
    import time

    from analyzer import ai_condition
    path, _truth = market
    copy = tmp_path / "analyzer.db"
    shutil.copy(path, copy)
    conn, aconn = analysis.open_ro(copy), analysis.open_analysis(copy)
    items = ai_condition.candidates(conn, aconn, ("sold",), photos=0)[:200]

    class Slow(FakeConditionBackend):
        def __init__(self):
            super().__init__()
            self.live = self.peak = 0
            self.limited = set()

        async def ask(self, text, photos, **kw):
            self.live += 1
            self.peak = max(self.peak, self.live)
            try:
                await asyncio.sleep(0.05)              # „sieć”
                if text not in self.limited and len(self.limited) < 7:
                    self.limited.add(text)
                    raise RuntimeError("429 RESOURCE_EXHAUSTED. Resource has been exhausted (e.g. check quota).")
                return await super().ask(text, photos, **kw)
            finally:
                self.live -= 1

    async def no_wait(_seconds):
        pass

    backend = Slow()
    started = time.monotonic()
    stats = asyncio.run(ai_condition.run(aconn, items, backend, concurrency=40, progress=False, sleep=no_wait))
    took = time.monotonic() - started
    assert (stats["done"], stats["failed"], stats["retried"]) == (200, 0, 7)     # 429 ponowione, nie błędy
    assert backend.peak == 40 and took < 2.5                  # 200 × 0,05 s po 1 naraz = 10 s
    assert ai_condition.transient(RuntimeError("503 UNAVAILABLE: model overloaded"))
    assert not ai_condition.transient(ValueError("nieznany stan: 'broken'"))
    conn.close()
    aconn.close()


# ------------------------------------------------------------------ D1 + D4: wytyczne dla Snipera


def test_profit_rule_matches_user_examples():
    from analyzer.guide import max_buy, min_profit
    # 2026-10-26: zysk zawsze ≥ 300 zł, 35% → 400, 30% → 500 zł, marża < 30% nigdy (S25: 19% przyszło jako okazja)
    assert [min_profit(m) for m in (0.45, 0.40, 0.35, 0.30)] == pytest.approx([300, 300, 400, 500])
    assert min_profit(0.29) is None and min_profit(0.19) is None
    for buy, sale in ((1350, 2375), (2500, 3650)):                     # flipy użytkownika (koszty 46 zł)
        limit, profit, margin = max_buy(sale)
        assert buy <= limit, (buy, sale, limit)
    assert max_buy(4700)[0] < 3660                                      # Scar 17 (22%) - dziś już za drogo
    for sale in range(400, 20000, 25):                                 # nigdy zysk < 300 ani marża < 30%
        deal = max_buy(sale)
        if deal:
            assert deal[1] >= 300 - 1e-6 and deal[2] >= 0.30 - 1e-9 and deal[1] >= min_profit(deal[2]) - 1e-6, sale
    s25 = max_buy(2394)                                                 # Galaxy S25 z maila: max zakup ~1 630 zł
    assert s25[2] >= 0.30 and s25[0] < 1899
    assert max_buy(340) is None
    buys = [max_buy(x)[0] for x in range(400, 6000, 10)]               # bez skoków: droższa sprzedaż = wyższy próg
    assert all(b2 > b1 for b1, b2 in zip(buys, buys[1:]))


def test_group_names():
    from analyzer.guide import group_key
    row = dict(config_key=None, model=None, cpu=None, cpu_line=None, ram_gb=None, gpu=None)
    assert group_key("laptop", {**row, "gpu": "rtx 4060", "cpu": "i7-13620h", "ram_gb": 16}) == "RTX 4060"
    assert group_key("laptop", {**row, "model": "macbook air 13 2020", "cpu": "apple m1", "ram_gb": 8}) == \
        "MacBook Air M1 8 GB RAM"
    assert group_key("laptop", {**row, "cpu": "i5-8350u", "ram_gb": 16, "gpu": "integrated"}) == \
        "intel core i5 8–9 gen. · 16 GB RAM (zintegrowana grafika)"
    assert group_key("laptop", {**row, "cpu_line": "intel core i5", "ram_gb": 16}) is None     # bez generacji
    from analyzer.guide import cpu_generation
    assert [cpu_generation(c) for c in ("i5-4200u", "i7-10750h", "i5-1135g7", "i5-1240p", "i3-13100",
                                        "ryzen 5 3500u", "ryzen 7 5800h", "ryzen 5 7530u", "i5-520m", "apple m1")] == [
        "do 7 gen.", "10–11 gen.", "10–11 gen.", "12+ gen.", "12+ gen.", "1000–3000", "4000–5000", "6000+",
        "do 7 gen.", None]
    assert group_key("console", {**row, "config_key": "Xbox One|ones|?"}) == "Xbox One S"
    assert group_key("console", {**row, "config_key": "Xbox 360|360|?"}) == "Xbox 360"
    assert group_key("console", {**row, "config_key": "PlayStation 4|2|?"}) == "PlayStation 4"
    assert group_key("phone", {**row, "config_key": "iphone 13|128"}) == "iphone 13 128 GB"
    assert group_key("phone", {**row, "config_key": "iphone 13|?"}) is None
    assert group_key("console", {**row, "config_key": "PlayStation 5|slim|?"}) == "PlayStation 5 slim"
    assert group_key("storage", {**row, "config_key": "nvme|2000"}) == "NVMe 2 TB"
    assert group_key("gpu", {**row, "config_key": "gtx 1050 ti|4"}) == "GTX 1050 Ti 4 GB"
    assert group_key("laptop", {**row, "cpu": "i5-8350u", "ram_gb": 1}) is None
    assert group_key("ram", {**row, "config_key": "ddr4|so-dimm|16"}) == "DDR4 SO-DIMM (laptop) 16 GB"


def test_sniper_guide_files(relisted, flagged, tmp_path):
    from analyzer import guide
    conn, aconn, truth = relisted
    result = guide.build(conn, aconn, tmp_path / "2026-10-25" / "guides")
    assert set(result) == set(analysis.CATEGORIES)
    path, rows = result["phone"]
    text = path.read_text(encoding="utf-8")
    assert "≤ 7 dni" in text and "40% → 300 zł" in text and "30% → 500 zł" in text and "marża < 30%" in text
    assert "nigdy poniżej 300 zł" in text and "Sprzedawca z Polski" in text
    iphone = next(r for r in rows if r["name"] == "iphone 13 128 GB")
    assert iphone["src"].startswith("zniknięte") and iphone["buy"] < iphone["sale"]
    # oszustwa (519 zł, flagi) nie zaniżają cen iPhone 16 Pro
    pro = next(r for r in rows if r["name"] == "iphone 16 pro 512 GB")
    assert pro["p25"] > 3000
    assert result["ram"][1][0]["buy"] is None                      # tani RAM nie spełnia minimalnego zysku
    ram_text = result["ram"][0].read_text(encoding="utf-8")
    assert "Praktycznie nieopłacalne" in ram_text and "| DDR4" not in ram_text     # bez wiersza w tabeli
    assert len(guide.summary_lines(result)) > 10
    # D5: zakresy cen katalogów dla Snipera (SNIPER_CATALOGS=auto)
    import json
    data = json.loads((path.parent / "catalogs.json").read_text(encoding="utf-8"))
    by_id = {c["catalog_id"]: c for c in data["catalogs"]}
    assert data["generated"] == "2026-10-25" and 3661 in by_id and by_id[3661]["categories"] == ["phone"]
    phone_buys = [r["buy"] for r in rows if guide.practical(r)]
    assert by_id[3661]["price_from"] <= 0.6 * min(phone_buys) and by_id[3661]["price_from"] % 50 == 0
    assert by_id[3661]["price_to"] >= max(phone_buys) * 1.15 and by_id[3661]["price_to"] % 100 == 0
    assert all(any(guide.practical(r) for cat in c["categories"] for r in result[cat][1]) for c in data["catalogs"])
    line = guide.catalogs_line(result)
    assert f"3661:{by_id[3661]['price_from']}-{by_id[3661]['price_to']}" in line
    if 3580 in by_id:
        assert by_id[3580]["weight"] == 3 and "*3" in line


def test_sale_price_takes_higher_estimate():
    from analyzer.guide import rows
    active = [3000.0] * 10 + [3400.0] * 10 + [3800.0] * 10              # p25 3 400 (interpolacja), mediana 3 400
    g = {"x": {"active": active, "active_pl": active, "active_zagr": [], "gone": [3000.0] * 12, "sold": []}}
    r = rows(g)[0]
    assert r["src"] == "oferty p25–med" and r["sale"] == pytest.approx((r["p25"] + r["med"]) / 2)
    g["x"]["gone"] = [3900.0] * 12
    assert rows(g)[0]["sale"] == 3900.0 and rows(g)[0]["src"].startswith("zniknięte")


# ------------------------------------------------------------------ E2: archiwum zdjęć, E3: automat, alarm


def _copy_market(market, tmp_path):
    import shutil
    path, truth = market
    copy = tmp_path / "analyzer.db"
    shutil.copy(path, copy)
    return copy, truth


def _photo_cfg(db_path, **kw):
    from types import SimpleNamespace
    base = dict(db_path=str(db_path), photos_dir="", photos_concurrency=4, sold_alarm_hours=72.0,
                sold_alarm_min=300, auto_days=3.5, auto_ai_limit=3000, sniper_guides_dir="",
                sniper_guidelines_file="", ai_model="")
    base.update(kw)
    return SimpleNamespace(**base)


def test_photo_archive_downloads_all_photos_without_proxy(market, tmp_path):
    import asyncio

    import httpx

    from analyzer import db, photos
    path, truth = _copy_market(market, tmp_path)
    cfg = _photo_cfg(path)
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if "-2.jpg" in str(request.url) and len(seen) % 50 == 0:
            return httpx.Response(404)                       # pojedyncze usunięte zdjęcie
        return httpx.Response(200, content=b"JPEG" + str(request.url).encode())

    async def scenario(limit):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            conn = db.connect(path)
            try:
                return await photos.archive(cfg, conn, limit=limit, client=client)
            finally:
                conn.close()

    stats = asyncio.run(scenario(40))
    assert stats["offers"] == 40 and stats["photos"] > 40
    lid = truth.ids["cond_parts"]                            # ma szczegóły → oba zdjęcia z sidebara
    asyncio.run(scenario(None))
    files = photos.local_photos(photos.photos_dir(cfg), lid)
    assert [p.name for p in files] == ["01.jpg", "02.jpg"] and files[0].read_bytes().startswith(b"JPEG")
    assert str(lid // 1_000_000) in str(files[0].parent.parent)
    before = len(seen)
    assert asyncio.run(scenario(None))["offers"] == 0          # wszystko już jest - nic do pobrania
    assert len(seen) == before
    assert "Archiwum zdjęć:" in photos.status_line(cfg)


def test_sold_alarm(market, tmp_path):
    import asyncio
    from datetime import timedelta

    from analyzer import auto
    path, truth = _copy_market(market, tmp_path)
    conn, aconn = analysis.open_ro(path), analysis.open_analysis(path)
    now = fake_market.NOW + timedelta(days=1)
    alarm, sold, deleted = auto.sold_check(conn, hours=24 * 30, minimum=100, now=now)
    assert not alarm and sold > 0                            # w atrapie sprzedaże są
    sent = []

    async def send(title, lines, **kw):
        sent.append(title)
        return True

    cfg = _photo_cfg(path, sold_alarm_hours=24 * 30, sold_alarm_min=100)
    assert asyncio.run(auto.sold_alarm(cfg, conn, aconn, now=now, send=send)) is False and sent == []
    conn.close()
    import sqlite3
    rw = sqlite3.connect(path)                               # symulacja zmiany API: wszystkie sprzedane → deleted
    rw.execute("UPDATE listings SET state='deleted' WHERE state IN ('sold', 'blocked')")
    rw.commit()
    rw.close()
    conn = analysis.open_ro(path)
    assert asyncio.run(auto.sold_alarm(cfg, conn, aconn, now=now, send=send)) is True
    assert asyncio.run(auto.sold_alarm(cfg, conn, aconn, now=now + timedelta(hours=2), send=send)) is True
    assert len(sent) == 1 and "zmiana API" in sent[0]          # najwyżej raz na dobę
    assert asyncio.run(auto.sold_alarm(cfg, conn, aconn, now=now + timedelta(hours=25), send=send))
    assert len(sent) == 2
    conn.close()
    aconn.close()


def test_auto_pipeline_publishes_guides(market, tmp_path):
    import asyncio
    from datetime import timedelta

    from analyzer import auto
    path, truth = _copy_market(market, tmp_path)
    sniper = tmp_path / "sniper"
    sniper.mkdir()
    old = sniper / "guidelines.md"
    old.write_text("ręczne wytyczne", encoding="utf-8")
    cfg = _photo_cfg(path, sniper_guides_dir=str(sniper / "guides"), sniper_guidelines_file=str(old),
                     auto_ai_limit=20)
    sent = []

    async def send(title, lines, **kw):
        sent.append((title, lines))
        return True

    backend = FakeConditionBackend()
    now = fake_market.NOW
    summary = asyncio.run(auto.run(cfg, backend=backend, now=now, send=send))
    assert summary["ai"]["done"] == 20 and len(backend.calls) == 20
    assert (sniper / "guides" / "laptop.md").exists() and (sniper / "guides" / "phone.md").exists()
    assert (sniper / "guides" / "catalogs.json").exists()                     # SNIPER_CATALOGS=auto
    assert (sniper / "guides" / "comparables.db").exists()                    # porównywalne oferty
    assert old.read_text(encoding="utf-8").startswith("# Laptopy")             # laptop.md → plik Snipera
    assert (sniper / "guidelines.md.bak").read_text(encoding="utf-8") == "ręczne wytyczne"
    assert sent and "wytyczne Snipera" in sent[0][0]
    assert asyncio.run(auto.run(cfg, backend=backend, now=now + timedelta(days=1), send=send)) is None   # za wcześnie
    again = asyncio.run(auto.run(cfg, backend=backend, now=now + timedelta(days=4), send=send))
    assert again is not None and again["ai"]["done"] == 20                    # następne 20 nowych ofert


def test_ai_condition_uses_archived_photos(market, tmp_path):
    import asyncio
    from types import SimpleNamespace

    from analyzer import ai_condition, photos
    from analyzer.ai_classify import Backend
    path, truth = _copy_market(market, tmp_path)
    root = tmp_path / "photos"
    lid = truth.ids["cond_parts"]
    folder = photos.listing_dir(root, lid)
    folder.mkdir(parents=True)
    for i in (1, 2, 3, 4):
        (folder / f"0{i}.jpg").write_bytes(b"\xff\xd8 zdjecie")
    conn, aconn = analysis.open_ro(path), analysis.open_analysis(path)
    items = {row["id"]: urls for row, _d, urls, _k in
             ai_condition.candidates(conn, aconn, ("flagged",), photos=3, photos_root=root)}
    assert items[lid] == [str(folder / f"0{i}.jpg") for i in (1, 2, 3)]
    seen = {}

    class Messages:
        async def create(self, **kw):
            seen.update(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="{}")],
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    backend = Backend(SimpleNamespace(provider="anthropic", photos="url"), "m",
                      client=SimpleNamespace(beta=SimpleNamespace(messages=Messages())))
    asyncio.run(backend.ask("t", items[lid] + ["https://x/1.jpg"]))
    sources = [c["source"] for c in seen["messages"][0]["content"] if c["type"] == "image"]
    assert [s["type"] for s in sources] == ["base64", "base64", "base64", "url"]
    assert sources[0]["media_type"] == "image/jpeg"
    conn.close()
    aconn.close()


# ------------------------------------------------------------------ pilot z telefonu (remote)


@pytest.mark.parametrize("text, pin, expected", [
    ("status", "", ("status", None)),
    ("Stop watch", "", ("stop", "watch")),
    ("sniper start", "", ("start", "sniper")),
    ("włącz wszystko", "", ("start", "all")),
    ("restart watch", "", ("restart", "watch")),
    ("log sniper", "", ("log", "sniper")),
    ("1234 stop all", "1234", ("stop", "all")),
    ("stop all", "1234", (None, "zły albo brak PIN-u")),
    ("stop", "", (None, "stop czego? watch / sniper / all")),
    ("hej", "", (None, "nieznane polecenie")),
    ("wytyczne", "", ("guides", None)),
])
def test_remote_parse(text, pin, expected):
    from analyzer.remote import parse
    assert parse(text, pin) == expected


def test_remote_controller(tmp_path):
    import asyncio

    from analyzer.remote import RESTART_AFTER_S, Controller, Program

    class Proc:
        n = 0

        def __init__(self):
            Proc.n += 1
            self.pid, self.code = 1000 + Proc.n, None

        def poll(self):
            return self.code

    now = [0.0]
    sent, killed = [], []
    programs = {name: Program(name, ["python"], str(tmp_path), tmp_path / f"{name}.log") for name in ("watch", "sniper")}
    (tmp_path / "watch.log").write_text("linia 1\nBŁĄD: coś\n", encoding="utf-8")

    async def send(title, lines, **kw):
        sent.append((title, lines))

    def kill_fn(proc):
        if proc is not None:
            proc.code = -9
            killed.append(proc.pid)

    c = Controller(programs, send, spawn_fn=lambda p: Proc(), kill_fn=kill_fn, clock=lambda: now[0])

    async def scenario():
        await c.handle("start all")
        assert programs["watch"].running() and programs["sniper"].running()
        await c.handle("stop sniper")
        assert not programs["sniper"].running() and killed == [programs["sniper"].proc.pid if programs["sniper"].proc
                                                                else 1002]
        await c.handle("status")
        assert "watch: DZIAŁA" in sent[-1][1][0] and sent[-1][1][1] == "sniper: zatrzymany"
        await c.handle("log watch")
        assert sent[-1][1][-1] == "BŁĄD: coś"
        # watch pada → powiadomienie, po 60 s ponowne uruchomienie
        programs["watch"].proc.code = 1
        await c.watchdog()
        assert "się wyłączył" in sent[-1][0] and not programs["watch"].running()
        now[0] += RESTART_AFTER_S
        await c.watchdog()
        assert programs["watch"].running() and programs["watch"].restarts == 1
        await c.watchdog()                                  # sniper zatrzymany ręcznie - strażnik go nie rusza
        assert not programs["sniper"].running()
        await c.handle("cokolwiek")
        assert sent[-1][0] == "Pilot: nie rozumiem"

    asyncio.run(scenario())



def test_remote_ignores_own_messages():
    import asyncio
    import json

    import httpx

    from analyzer import remote
    events = [{"event": "open"}, {"event": "message", "id": "a", "message": "status"},
              {"event": "message", "id": "b", "title": "Pilot: status", "message": "watch: DZIAŁA"},
              {"event": "message", "id": "c", "title": "Analyzer: automat", "message": "AI stan"},
              {"event": "message", "id": "d", "message": "stop sniper"}]
    body = "\n".join(json.dumps(e) for e in events) + "\n"
    got = []

    async def on_message(text):
        got.append(text)
        if len(got) == 2:
            raise asyncio.CancelledError

    def handler(request):
        since = request.url.params["since"]
        assert since.isdigit() and int(since) > 1_700_000_000          # znacznik czasu, nie „now” (ntfy: 400)
        return httpx.Response(200, text=body)

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    httpx.AsyncClient = lambda **kw: real(transport=transport, **{k: v for k, v in kw.items() if k != "trust_env"})
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(remote.listen("https://ntfy.example", "pilot-x", "", on_message))
    finally:
        httpx.AsyncClient = real
    assert got == ["status", "stop sniper"]



def test_remote_exports_guides(tmp_path):
    import asyncio
    from types import SimpleNamespace

    import httpx

    from analyzer import notify, remote
    sniper = tmp_path / "unreachable_sniper"
    (sniper / "sniper").mkdir(parents=True)
    (sniper / "sniper" / "guidelines.md").write_text("# Laptopy", encoding="utf-8")
    data = tmp_path / "data"
    for day in ("2026-10-24", "2026-10-25"):
        (data / "reports" / day / "guides").mkdir(parents=True)
        (data / "reports" / day / "guides" / "phone.md").write_text(day, encoding="utf-8")
    cfg = SimpleNamespace(db_path=str(data / "analyzer.db"))
    files = remote.guide_files(cfg, str(sniper))
    assert [f.name for f in files] == ["guidelines.md", "phone.md"] and "2026-10-25" in str(files[1])
    sent = []

    async def send_file(path, title):
        sent.append((path.name, title))
        return True

    drive = tmp_path / "G" / "program"
    lines = asyncio.run(remote.export_guides(cfg, send_file, str(drive), str(sniper)))
    assert (drive / "wytyczne" / "sniper_guidelines.md").read_text(encoding="utf-8") == "# Laptopy"
    assert (drive / "wytyczne" / "phone.md").exists() and "2 plików" in lines[0]
    assert sent == [("wytyczne_sniper.md", "Pilot: wytyczne_sniper.md")]          # jeden plik ze wszystkimi
    both = (data / "remote" / "wytyczne_sniper.md").read_text(encoding="utf-8")
    assert "# Laptopy" in both and "2026-10-25" in both and "sniper_guidelines.md" in both
    # D5: Sniper ma własne guides/ → to one (+ guidelines.md), bez kopii z reports/
    (sniper / "sniper" / "guides").mkdir()
    (sniper / "sniper" / "guides" / "laptop.md").write_text("# L", encoding="utf-8")
    (sniper / "sniper" / "guides" / "phone.md").write_text("# P", encoding="utf-8")
    assert [f.relative_to(sniper).as_posix() for f in remote.guide_files(cfg, str(sniper))] == [
        "sniper/guides/laptop.md", "sniper/guides/phone.md", "sniper/guidelines.md"]
    (sniper / "sniper" / "guides" / "laptop.md").unlink()
    (sniper / "sniper" / "guides" / "phone.md").unlink()
    lines = asyncio.run(remote.export_guides(cfg, send_file, "", str(sniper)))
    assert "ANALYZER_GDRIVE_DIR" in lines[0]
    # załącznik ntfy: PUT z nazwą pliku, tytuł „Pilot:” (pilot go pominie jako własny)
    seen = {}

    def handler(request):
        seen.update(method=request.method, url=str(request.url), filename=request.headers["Filename"],
                    title=request.headers["Title"], body=request.content)
        return httpx.Response(200, json={})

    async def put():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await notify.send_file(files[0], "Pilot: guidelines.md", topic_name="pilot-x", client=client)

    assert asyncio.run(put()) is True
    assert seen["method"] == "PUT" and seen["url"].endswith("/pilot-x") and seen["body"] == "# Laptopy".encode()
    assert seen["filename"] == "guidelines.md" and seen["title"] == "Pilot: guidelines.md"


def test_remote_sends_oceny_html(tmp_path, monkeypatch):
    import asyncio

    from analyzer import remote
    monkeypatch.delenv("SNIPER_LOG_DIR", raising=False)
    assert remote.parse("oceny") == ("report", None) and remote.parse("1234 raport", "1234") == ("report", None)
    sniper = tmp_path / "unreachable_sniper"
    sent = []

    async def send_file(path, title):
        sent.append(path.name)
        return True

    lines = asyncio.run(remote.export_report(send_file, "", str(sniper)))
    assert "Brak oceny.html" in lines[0] and not sent
    logs = sniper / "sniper" / "logs"
    logs.mkdir(parents=True)
    (logs / "oceny.html").write_text('<article class="card deal" x><article class="card" y>', encoding="utf-8")
    drive = tmp_path / "G"
    lines = asyncio.run(remote.export_report(send_file, str(drive), str(sniper)))
    assert "2 ofert, w tym okazji 1" in lines[0] and (drive / "sniper" / "oceny.html").exists()
    assert sent == ["oceny.html"]
    replies = []

    async def reply(title, lines, **kw):
        replies.append((title, lines))

    controller = remote.Controller({}, reply)
    controller.report_fn = lambda: remote.export_report(send_file, "", str(sniper))
    assert asyncio.run(controller.handle("oceny")) == "report" and replies[-1][0] == "Pilot: oceny"


def test_find_ram_form_and_type():
    from analyzer.find import ram_form, ram_type
    assert ram_form("RAM 8GB", "naklejka PC4-2400T-UA2-11") == "dimm"
    assert ram_form("Samsung DDR4 8 GB", "M471A1K43DB1 PC4-3200AA-SA1") == "so-dimm"
    assert ram_form("DDR4 16GB do laptopa") == "so-dimm" and ram_form("DDR4 2x8GB DIMM") == "dimm"
    assert ram_form("Pamięć 8GB") is None
    assert ram_type("Pamięć ram DDR4", "8GB 2Rx8 PC3L-12800U-11-13-B1") == "ddr3"   # naklejka wygrywa


def test_find_search(market):
    from analyzer import analysis, find
    path, truth = market
    conn, aconn = analysis.open_ro(path), analysis.open_analysis(path)
    found, med, total = find.search(conn, aconn, "phone", ["iphone", "13", "128"], limit=5)
    assert found and total >= len(found) and med
    assert [x["price"] for x in found] == sorted(x["price"] for x in found)
    assert all("iphone 13" in x["key"] and x["url"].startswith("https://www.vinted.pl/items/") for x in found)
    capped, _, _ = find.search(conn, aconn, "phone", ["iphone"], max_price=found[0]["price"])
    assert capped and all(x["price"] <= found[0]["price"] for x in capped)
    text = "\n".join(find.lines(found, med, total, "phone"))
    assert "mediana" in text and "seller" not in text.lower()
    conn.close()
    aconn.close()


def test_remote_sniper_gets_own_env_not_pilots(tmp_path, monkeypatch):
    """Ustawienia z .env pilota nie mogą przesłonić unreachable_sniper/sniper/.env (SNIPER_NTFY_MIN_SCORE 5 vs 8)."""
    import sys
    from analyzer import remote
    env_file = tmp_path / ".env"
    env_file.write_text("# komentarz\nSNIPER_NTFY_MIN_SCORE=5\nexport SNIPER_X = 1\nANALYZER_DB=x\n", encoding="utf-8")
    assert remote.own_env_keys(env_file) == {"SNIPER_NTFY_MIN_SCORE", "SNIPER_X", "ANALYZER_DB"}
    monkeypatch.setenv("SNIPER_NTFY_MIN_SCORE", "5")
    monkeypatch.setenv("KEEP_ME", "1")
    seen = {}

    class FakePopen:
        def __init__(self, cmd, cwd, stdout, stderr, stdin, creationflags, env):
            seen.update(env)
            self.pid = 1

    monkeypatch.setattr(remote.subprocess, "Popen", FakePopen)
    program = remote.Program("sniper", [sys.executable, "-m", "sniper"], str(tmp_path), tmp_path / "s.log",
                             extra={"drop_env": {"SNIPER_NTFY_MIN_SCORE"}})
    remote.spawn(program)
    assert "SNIPER_NTFY_MIN_SCORE" not in seen and seen["KEEP_ME"] == "1" and seen["PYTHONUNBUFFERED"] == "1"


def test_comparables_db(relisted, flagged, tmp_path):
    import sqlite3

    from analyzer import comparables, guide
    conn, aconn, truth = relisted
    out = tmp_path / "2026-10-26" / "guides"
    guide.build(conn, aconn, out)
    db = sqlite3.connect(out / "comparables.db")
    n = int(db.execute("SELECT value FROM meta WHERE key='rows'").fetchone()[0])
    assert n > 100
    rows = db.execute("SELECT price, gone FROM offers WHERE offers MATCH ? AND category = 'phone'",
                      ('"iphone" "13" "128"',)).fetchall()
    assert len(rows) > 10 and any(g for _, g in rows) and any(not g for _, g in rows)
    assert db.execute("SELECT doc FROM vocab WHERE term = 'iphone'").fetchone()[0] > 10
    assert comparables.tokens("PS5 Slim iPhone13") == ["playstation", "5", "slim", "iphone", "13"]
    # oszustwa (flagi wykluczające) nie trafiają do porównań
    fraud_prices = db.execute("SELECT price FROM offers WHERE offers MATCH ? AND price < 600",
                              ('"iphone" "16" "pro"',)).fetchall()
    assert not fraud_prices
    db.close()
