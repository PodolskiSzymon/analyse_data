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
