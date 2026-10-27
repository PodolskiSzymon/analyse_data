"""F0 z PLAN_OCENY.md – zdrowie danych o sprzedaży (`python -m analyzer sold-report [--od 2026-10-24T12:00]`).

Bez sieci, tylko odczyt, kilka zapytań z agregacją (sekundy przy ~240 tys. ofert). Odpowiada na pytania:
  * czy `watch` chodzi bez przerw (przejścia per katalog, najdłuższa przerwa między startami),
  * jak szybko resolver rozpoznaje zniknięcia (zwłoka = state_at − last_seen),
  * czy sprzedane „znikają” z Vinted, gdy sprawdzamy późno (udział sold+blocked wśród zniknięć wg zwłoki –
    eksperyment C4 z PLAN_ANALIZY.md: przy szybkim sprawdzeniu udział powinien być wyższy),
  * tempo napływu pewnych sprzedaży (sold + blocked) na dzień i kategorię.
Wynik: kilkanaście linii do wklejenia w czat.
"""

GONE = ("sold", "blocked", "deleted")
# Kubełki zwłoki w godzinach (górna granica włącznie).
BUCKETS = ((12, "≤ 12 h"), (24, "12–24 h"), (72, "1–3 dni"), (None, "> 3 dni"))
DEFAULT_SINCE = "2026-10-24T12:00"      # po `recheck` z 24.10 (poprawny resolver: /services + sidebar)

_DELAY = "(julianday(state_at) - julianday(last_seen)) * 24"


def _bucket_sql():
    parts = [f"WHEN {_DELAY} <= {limit} THEN '{label}'" if limit else f"ELSE '{label}'" for limit, label in BUCKETS]
    return "CASE " + " ".join(parts) + " END"


def _pct(part, whole):
    return f"{part / whole * 100:.1f}%" if whole else "-"


def runs_lines(conn, since):
    """Ciągłość przejść: liczba, najdłuższa przerwa między startami (h), ostatni koniec – per katalog."""
    out = ["Przejścia od " + since[:16] + " (katalog: przejść, najdłuższa przerwa między startami, ostatni koniec):"]
    rows = conn.execute("SELECT catalog_id, started_at, finished_at FROM crawl_runs WHERE kind = 'crawl' "
                        "AND started_at >= ? ORDER BY catalog_id, started_at", (since,)).fetchall()
    per = {}
    for cid, start, end in rows:
        per.setdefault(cid, []).append((start, end))
    for cid, runs in per.items():
        gaps = [conn.execute("SELECT (julianday(?) - julianday(?)) * 24", (b[0], a[0])).fetchone()[0]
                for a, b in zip(runs, runs[1:])]
        last_end = next((e for _s, e in reversed(runs) if e), None)
        out.append(f"  {cid}: {len(runs)}, przerwa max {max(gaps):.1f} h" if gaps else f"  {cid}: {len(runs)}")
        out[-1] += f", ostatni koniec {last_end[:16] if last_end else 'w toku'}"
    if not per:
        out.append("  brak przejść – czy watch działa?")
    return out


def delay_lines(conn, since):
    """Zniknięcia rozpoznane od `since` wg zwłoki: ile, w tym sold / blocked / deleted, udział pewnych sprzedaży."""
    marks = ",".join("?" * len(GONE))
    rows = conn.execute(
        f"SELECT {_bucket_sql()} AS b, state, COUNT(*) FROM listings WHERE state IN ({marks}) AND state_at >= ? "
        f"GROUP BY 1, 2", (*GONE, since)).fetchall()
    table = {}
    for bucket, state, n in rows:
        table.setdefault(bucket, {}).update({state: n})
    total = sum(sum(v.values()) for v in table.values())
    out = [f"Zniknięcia rozpoznane od {since[:16]}: {total} (zwłoka = rozpoznanie − ostatnie widzenie)",
           "  zwłoka     zniknięć   sold  blocked  deleted   % sold+blocked"]
    for _limit, label in BUCKETS:
        v = table.get(label, {})
        n = sum(v.values())
        if not n:
            continue
        sure = v.get("sold", 0) + v.get("blocked", 0)
        out.append(f"  {label:<9} {n:>9} {v.get('sold', 0):>6} {v.get('blocked', 0):>8} {v.get('deleted', 0):>8}"
                   f"   {_pct(sure, n):>8}")
    fast = sum(sum(table.get(label, {}).values()) for limit, label in BUCKETS if limit and limit <= 24)
    out.append(f"  sprawdzone ≤ 24 h: {_pct(fast, total)} zniknięć (cel ≥ 90%)")
    return out


def category_lines(conn, since, max_delay_h=72):
    """Pewne sprzedaże (sold + blocked) i usunięte per kategoria, tylko szybko sprawdzone (zwłoka ≤ 3 dni)."""
    rows = conn.execute(
        f"SELECT category, state, COUNT(*), MIN(state_at), MAX(state_at) FROM listings WHERE state IN "
        f"('sold', 'blocked', 'deleted') AND state_at >= ? AND {_DELAY} <= ? GROUP BY 1, 2",
        (since, max_delay_h)).fetchall()
    per, first, last = {}, None, None
    for cat, state, n, lo, hi in rows:
        per.setdefault(cat, {})[state] = n
        first = lo if first is None or lo < first else first
        last = hi if last is None or hi > last else last
    days = conn.execute("SELECT julianday(?) - julianday(?)", (last, first)).fetchone()[0] if first else 0
    days = max(days or 0, 1 / 24)
    out = [f"Per kategoria (zwłoka ≤ {max_delay_h // 24} dni, okno {days:.1f} dnia): sold+blocked / deleted / % "
           f"/ pewnych sprzedaży na dzień"]
    for cat, v in sorted(per.items(), key=lambda kv: -(kv[1].get("sold", 0) + kv[1].get("blocked", 0))):
        sure = v.get("sold", 0) + v.get("blocked", 0)
        n = sure + v.get("deleted", 0)
        out.append(f"  {cat:<8} {sure:>5} / {v.get('deleted', 0):>6} / {_pct(sure, n):>6} / {sure / days:>5.1f}")
    return out


def daily_lines(conn, since, max_delay_h=72):
    rows = conn.execute(
        f"SELECT substr(state_at, 1, 10), SUM(state = 'sold'), SUM(state = 'blocked'), SUM(state = 'deleted') "
        f"FROM listings WHERE state IN ('sold', 'blocked', 'deleted') AND state_at >= ? AND {_DELAY} <= ? "
        f"GROUP BY 1 ORDER BY 1", (since, max_delay_h)).fetchall()
    return ["Na dzień (rozpoznanie, zwłoka ≤ 3 dni): " + "; ".join(
        f"{d[5:]} sold {s} blocked {b} deleted {x}" for d, s, b, x in rows)] if rows else []


def report(conn, since=DEFAULT_SINCE):
    return [*runs_lines(conn, since), "", *delay_lines(conn, since), "", *category_lines(conn, since),
            *daily_lines(conn, since)]
