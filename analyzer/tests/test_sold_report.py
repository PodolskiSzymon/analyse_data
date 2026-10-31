"""F0 (PLAN_OCENY.md): sold-report na małej bazie z wartościami do policzenia ręcznie."""
from analyzer import db, sold_report


def _db(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    rows = [  # (id, kategoria, stan, last_seen, state_at)
        (1, "phone", "sold", "2026-10-25T00:00:00.000+00:00", "2026-10-25T06:00:00.000+00:00"),       # 6 h
        (2, "phone", "deleted", "2026-10-25T00:00:00.000+00:00", "2026-10-25T10:00:00.000+00:00"),    # 10 h
        (3, "phone", "deleted", "2026-10-25T00:00:00.000+00:00", "2026-10-25T20:00:00.000+00:00"),    # 20 h
        (4, "console", "blocked", "2026-10-24T00:00:00.000+00:00", "2026-10-26T00:00:00.000+00:00"),  # 2 dni
        (5, "console", "deleted", "2026-10-10T00:00:00.000+00:00", "2026-10-24T13:00:00.000+00:00"),  # recheck
        (6, "phone", "sold", "2026-10-10T00:00:00.000+00:00", "2026-10-20T00:00:00.000+00:00"),       # przed --od
        (7, "phone", "active", "2026-10-26T00:00:00.000+00:00", "2026-10-26T00:00:00.000+00:00"),
    ]
    with conn:
        for lid, cat, state, last, at in rows:
            conn.execute("INSERT INTO listings (id, catalog_id, category, title, first_seen, last_seen, state, "
                         "state_at) VALUES (?, 1, ?, 't', ?, ?, ?, ?)", (lid, cat, last, last, state, at))
        for start in ("2026-10-24T12:00:00.000+00:00", "2026-10-25T00:00:00.000+00:00",
                      "2026-10-26T06:00:00.000+00:00"):
            conn.execute("INSERT INTO crawl_runs (started_at, finished_at, kind, catalog_id) VALUES (?, ?, 'crawl', "
                         "3661)", (start, start.replace("T", "T").replace(":00:00.000", ":30:00.000")))
    return conn


def test_sold_report_counts(tmp_path):
    conn = _db(tmp_path)
    text = "\n".join(sold_report.report(conn, "2026-10-24T12:00"))
    conn.close()
    assert "3661: 3, przerwa max 30.0 h" in text                       # 25.10 00:00 → 26.10 06:00
    assert "Zniknięcia rozpoznane od 2026-10-24T12:00: 5" in text        # bez #6 (przed --od) i aktywnej
    row = {label: next(line.split()[-5:] for line in text.splitlines() if line.startswith("  " + label))
           for _limit, label in sold_report.BUCKETS[:3]}
    assert row["≤ 12 h"] == ["2", "1", "0", "1", "50.0%"]               # #1 sold 6 h, #2 deleted 10 h
    assert row["12–24 h"] == ["1", "0", "0", "1", "0.0%"]
    assert row["1–3 dni"] == ["1", "0", "1", "0", "100.0%"]             # #4 blocked
    assert "sprawdzone ≤ 24 h: 60.0% zniknięć" in text
    assert "phone        1 /      2 /  33.3%" in text and "console      1 /      0 / 100.0%" in text
    assert "10-25 sold 1 blocked 0 deleted 2; 10-26 sold 0 blocked 1 deleted 0" in text


def test_flips_template_and_report(tmp_path):
    from datetime import date

    from analyzer import flips
    path = tmp_path / "flips.csv"
    assert flips.write_template(path) and not flips.write_template(path)      # drugi raz nie nadpisuje
    assert flips.load(path) == []                                               # same modele, bez kosztów
    lines = ";".join(flips.COLUMNS)
    path.write_text(lines + "\n"
                    "# komentarz\n"
                    "2026-10-26;1;console;Nintendo Wii;140,50;RO;2026-10-30;T;;450;2026-10-31;2026-11-02;420;46;10;\n"
                    "2026-10-26;2;phone;iPhone 12 128 GB;700;SK;;N;bateria 78%;1100;2026-10-31;2026-11-05;1 080,00;;8;\n"
                    "2026-10-26;3;tablet;iPad Air 4;900;SK;;;;;;;;;9;\n", encoding="utf-8-sig")
    rows = flips.load(path)
    assert [r["cost"] for r in rows] == [140.5, 700.0, 900.0] and rows[1]["got"] == 1080.0
    text = "\n".join(flips.report(rows, today=date(2026, 11, 6)))
    assert "kupione 3, sprzedane 2, w toku 1 (zamrożone 900 zł)" in text
    # Wii: 420 - 140,5 - 46 = 233,5 (56%); iPhone: 1080 - 700 - 46 = 334 (30,9%) → razem 567,5 na 840,5
    assert "zysk 568 zł na 840 zł (68% kapitału)" in text
    assert "reguła (zysk ≥ 300 zł, marża ≥ 28% tanie / 25% drogie) spełniona w 1/2" in text
    assert "δ (rabat od ceny wystawienia): mediana 4.2% z 2" in text                # 6,7% i 1,8%
    assert "stan zgodny z ogłoszeniem: 1/2 (niezgodne: iPhone 12 128 GB)" in text
    assert "iPad Air 4 900 zł, 11 dni" in text


def test_cycle_line_and_activity(tmp_path):
    conn = _db(tmp_path)
    line = sold_report.cycle_line(conn, "2026-10-25T00:00:00.000+00:00")
    # od 25.10: #1 sold 6 h, #2 deleted 10 h, #3 deleted 20 h, #4 blocked 48 h
    assert line == ("Cykl: zniknięć 4, pewnych sprzedaży 2 (50.0%), sprawdzone ≤ 24 h 75.0%, "
                    "mediana zwłoki 20.0 h")
    assert sold_report.cycle_line(conn, "2026-11-01") == "Cykl: brak rozpoznanych zniknięć."
    activity = sold_report.activity_lines(conn, "2026-10-24T12:00")
    assert activity and "aktywne bez szczegółów: 1" in activity[0] and "10-26 0 / 1" in activity[0]
    conn.close()


def test_watch_default_interval(monkeypatch):
    from analyzer.config import AnalyzerConfig
    monkeypatch.delenv("ANALYZER_WATCH_HOURS", raising=False)
    assert AnalyzerConfig().watch_hours == (5.0, 7.0)


def test_resolver_fresh_first_and_rechecks_until_deadline(tmp_path):
    """27.10: watch sprawdza świeże zniknięcia od razu, a ponowne sprawdzenia niewidocznych tylko do końca cyklu
    (wcześniej ~12 tys. ponownych sprawdzeń co 3 dni blokowało następne przejście na kilkanaście godzin)."""
    import asyncio
    from datetime import datetime, timedelta, timezone

    from analyzer.config import AnalyzerConfig
    from analyzer.resolver import candidates, resolve

    conn = db.connect(tmp_path / "r.db")
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat(timespec="milliseconds")
    new = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    with conn:
        for lid, state, missed, at in [(1, "gone_pending", 1, new), (2, "unlisted", 1, old), (3, "hidden", 1, new),
                                       (4, "unlisted", 0, old), (5, "active", 0, old)]:
            conn.execute("INSERT INTO listings (id, catalog_id, category, title, first_seen, last_seen, state, "
                         "state_at, missed_runs) VALUES (?, 3661, 'phone', 't', ?, ?, ?, ?, ?)",
                         (lid, old, old, state, at, missed))
    assert [r["id"] for r in candidates(conn, 3.0)] == [1, 2]                  # jak dawniej (komenda resolve)
    assert [r["id"] for r in candidates(conn, 3.0, only="fresh")] == [1]
    assert [r["id"] for r in candidates(conn, 3.0, only="due")] == [2]
    cfg = AnalyzerConfig(db_path=":memory:")
    past = datetime.now(timezone.utc) - timedelta(seconds=1)
    counts = asyncio.run(resolve(cfg, None, conn, only="due", deadline=past))   # koniec czasu - bez zapytań
    assert counts == {}
    assert cfg.resolve_delay == (1.0, 2.5) and 1.0 <= cfg.pick_resolve_delay() <= 2.5
    conn.close()


def test_disable_quickedit_is_harmless_outside_windows():
    from analyzer.progress import disable_quickedit
    assert disable_quickedit() is False
