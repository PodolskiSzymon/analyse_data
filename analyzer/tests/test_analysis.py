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


def test_photo_flag_and_diag(market, tmp_path):
    from analyzer import suspicious
    path, truth = market
    conn = analysis.open_ro(path)
    photo = {lid for lid, flag, _ in suspicious.photo_flags(conn)}
    assert photo == {truth.ids[n] for n in ("dup_blocked", "dup_sold", "dup_deleted", "dup_active",
                                             "blocked_console")}
    lines = suspicious.photo_diag(conn, per_state=500)
    row = next(line for line in lines if line.startswith("photo.is_suspicious"))
    assert "100.0% (2/2)" in row          # oba blocked mają is_suspicious=true
    assert any(line.startswith("is_promoted") for line in lines)
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
