r"""Popyt na modele (analiza 2026-11-16, POPYT.md): czy oferty danego modelu SCHODZĄ, a nie tylko „znikają”.

Na kopii bazy (tylko odczyt, bez sieci) dla używanych telefonów, tabletów (z czytnikami i tabletami graficznymi)
i konsol liczy per model:
  * nowe / mies.       - nowe oferty w oknie (pierwsze widzenie po pierwszym przejściu),
  * ≤3 d / ≤7 d        - udział nowych ofert, które zniknęły (bez ponownych wystawień) w 3 / 7 dni,
  * szybkie / tydz.    - ile takich szybkich zniknięć na tydzień (miara liczby kupujących),
  * stare              - udział aktywnych ofert wiszących od pierwszego przejścia (nikt ich nie chce),
  * fav / d            - mediana polubień na dzień życia nowej oferty,
  * obecny szacunek    - jak w Sniperze: max(mediana zniknięć, środek p25-mediana aktywnych),
  * cena szybkich      - mediana ceny ofert zniknionych ≤ 3 dni (cena, po której naprawdę schodzi).

Użycie (np. na kopii z serwera albo F:\analyzer.db na PC):
  python narzedzia\popyt.py --baza F:\analyzer.db
  python narzedzia\popyt.py --baza F:\analyzer.db --modele "iPad A16,reMarkable 2,Galaxy S23,MatePad 11"
  python narzedzia\popyt.py --baza F:\analyzer.db --od 2026-11-01 --do 2026-11-14
"""
import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime

GONE = ("sold", "deleted", "hidden", "gone_pending", "blocked", "closed")
READER = re.compile(r"remarkable\s*(?:paper\s*pro|2|1)?|kindle\s*(?:paperwhite|oasis|scribe|colorsoft)?|\bkobo\b|"
                    r"pocketbook|\bboox\b|\bonyx\b|tolino", re.I)
GRAPHIC = re.compile(r"wacom|huion|xp-?pen|cintiq|intuos|kamvas", re.I)
CONSOLES = [(n, re.compile(p, re.I)) for n, p in (
    ("Steam Deck OLED", r"steam\s*deck.*oled"), ("Steam Deck", r"steam\s*deck"),
    ("Switch OLED", r"switch.*oled|oled.*switch"), ("Switch Lite", r"switch.*lite"), ("Switch 2", r"switch\s*2"),
    ("PS5 Pro", r"ps5\s*pro|playstation\s*5\s*pro"), ("PS5", r"ps5|playstation\s*5"), ("PS4 Pro", r"ps4\s*pro"),
    ("PS4", r"ps4|playstation\s*4"), ("Xbox Series X", r"series\s*x"), ("Xbox Series S", r"series\s*s"),
    ("Xbox One", r"xbox\s*one"), ("PS Vita", r"vita"), ("PS Portal", r"portal"), ("ROG Ally", r"rog\s*ally"),
    ("Legion Go", r"legion\s*go"), ("Nintendo 3DS", r"3ds"), ("Switch", r"switch"), ("Wii U", r"wii\s*u"),
    ("Wii", r"\bwii\b"))]


def ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def pct(values, p):
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p
    f = int(k)
    return xs[f] + (xs[min(f + 1, len(xs) - 1)] - xs[f]) * (k - f)


def group(title, category, model):
    title = title or ""
    m = READER.search(title)
    if m:
        name = re.sub(r"\s+", " ", m.group(0).strip().lower())
        return "reMarkable 2" if re.match(r"remarkable ?2", name) else f"czytnik: {name}"
    if GRAPHIC.search(title):
        return "tablet graficzny"
    if category == "console":
        return next((n for n, p in CONSOLES if p.search(title)), None)
    return model


def used(status):
    return not (status or "").startswith(("Nowy", "New"))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baza", required=True)
    ap.add_argument("--modele", default="", help="po przecinku; domyślnie wszystkie z ≥ --min nowymi ofertami")
    ap.add_argument("--od", default=None, help="początek okna nowych ofert (domyślnie: 4 dni po pierwszym przejściu)")
    ap.add_argument("--do", default=None, help="koniec okna (domyślnie: 4 dni przed ostatnim widzeniem w bazie)")
    ap.add_argument("--min", type=int, default=20, help="minimum nowych ofert modelu w tabeli")
    a = ap.parse_args()
    conn = sqlite3.connect(f"file:{a.baza}?mode=ro", uri=True)
    first, last = conn.execute("SELECT MIN(first_seen), MAX(last_seen) FROM listings "
                               "WHERE category IN ('phone','tablet','console')").fetchone()
    start = a.od or datetime.fromtimestamp(ts(first) + 4 * 86400).strftime("%Y-%m-%d")
    end = a.do or datetime.fromtimestamp(ts(last) - 4 * 86400).strftime("%Y-%m-%d")
    days = max((ts(end + "T00:00:00+00:00") - ts(start + "T00:00:00+00:00")) / 86400, 1)
    print(f"Baza {a.baza}: dane {first[:10]} - {last[:10]}, okno nowych ofert {start} - {end} ({days:.0f} dni)",
          flush=True)
    relisted = {r[0] for r in conn.execute("SELECT old_id FROM a_relists")} \
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='a_relists'").fetchone() else set()
    groups = defaultdict(list)
    n = 0
    for row in conn.execute("SELECT id, title, category, model, status_label, state, first_seen, last_seen, price_now, "
                            "favourite_count FROM listings WHERE category IN ('phone','tablet','console') "
                            "AND price_now IS NOT NULL"):
        n += 1
        if n % 50000 == 0:
            print(f"  ... {n} ofert", flush=True)
        g = group(row[1], row[2], row[3])
        if g and used(row[4]):
            groups[g].append(row)
    wanted = [m.strip() for m in a.modele.split(",") if m.strip()]
    out = []
    for g, rows in groups.items():
        if wanted and g not in wanted:
            continue
        life = lambda r: (ts(r[7]) - ts(r[6])) / 86400  # noqa: E731
        new = [r for r in rows if start <= r[6][:10] <= end and r[5] != "unlisted"]
        fast3 = [r for r in new if r[5] in GONE and life(r) <= 3 and r[0] not in relisted]
        fast7 = [r for r in new if r[5] in GONE and life(r) <= 7 and r[0] not in relisted]
        active = [r for r in rows if r[5] in ("active", "reserved")]
        gone = [r[8] for r in rows if r[5] in ("sold", "blocked", "deleted", "closed")]
        stale = [r for r in active if r[6][:10] < start]
        if len(new) < (1 if wanted else a.min):
            continue
        p25, med = pct([r[8] for r in active], .25), pct([r[8] for r in active], .5)
        mid = (p25 + med) / 2 if active else None
        gone_med = pct(gone, .5) if len(gone) >= 10 else None
        current = max([x for x in (gone_med, mid) if x] or [0]) or None
        out.append((g, len(new) / days * 30, len(fast3) / len(new) if new else 0, len(fast7) / len(new) if new else 0,
                    len(fast7) / days * 7, len(stale) / max(len(active), 1),
                    pct([(r[9] or 0) / max(life(r), 1) for r in new], .5), current,
                    pct([r[8] for r in fast3], .5) if len(fast3) >= 3 else None, len(fast3)))
    out.sort(key=lambda x: -x[3])
    print(f"\n{'model':24} {'nowe/m':>6} {'≤3d':>4} {'≤7d':>4} {'szyb/t':>6} {'stare':>5} {'fav/d':>5} "
          f"{'szacunek':>8} {'szybkie':>7} {'różn.':>5}  klasa")
    for g, month, s3, s7, flow, stale, favd, current, fastp, nf in out:
        diff = f"{(fastp / current - 1) * 100:+4.0f}%" if fastp and current else "    -"
        klass = ("gorący" if s7 >= .5 and flow >= 3 else "martwy" if s7 < .15 or flow < .7
                 else "wolny" if s7 < .25 or flow < 2 else "normalny")
        print(f"{g[:24]:24} {month:6.0f} {s3:4.0%} {s7:4.0%} {flow:6.1f} {stale:5.0%} {favd or 0:5.2f} "
              f"{current or 0:8.0f} {fastp or 0:7.0f} {diff}  {klass}" + (f" (szybkich tylko {nf})" if nf < 5 else ""))
    print("\n≤7d = udział nowych ofert zniknionych w tydzień (bez ponownych wystawień); szyb/t = takich zniknięć na "
          "tydzień;\nstare = aktywne wiszące od początku okna; szacunek = jak dziś w Sniperze; szybkie = mediana ceny "
          "zniknionych ≤ 3 dni.", file=sys.stderr)


if __name__ == "__main__":
    main()
