"""Ponowne wystawienia (PLAN_ANALIZY.md, A4) - bez sieci, główna baza tylko do odczytu, wynik do
`analysis.db: relists(old_id, new_id, score, basis, gap_days)`.

Oferta B jest relistem A, gdy:
  * A zniknęła (`deleted` / `closed` / `sold` / `unlisted`), B ma nowsze ID, ta sama `category`,
  * ta sama marka i model (jeśli oba znane), cena B (bieżąca) w ±15% ceny A,
  * B pojawiła się w katalogu od 1 dnia PRZED ostatnim widzeniem A do 14 dni po nim,
  * tytuł: ten sam po normalizacji (`analysis.norm_title`) albo podobny (difflib ≥ 0,9), oraz:
      - obie mają opis → opisy podobne (difflib ≥ 0,8 na pierwszych 500 znakach) - podstawa `description`,
      - brak opisu do porównania → podstawa `title`, ostrzej (u użytkownika 2026-10-24 „Laptop”, „HP laptop”
        z przerwą 12 dni wychodziły jako relisty - przypadek, nie ta sama rzecz): IDENTYCZNY tytuł, konkretny
        (≥ 4 słowa albo ≥ 20 znaków po normalizacji), cena w ±5%, B pojawiła się najwyżej 2 dni po zniknięciu A,
      - opis do porównania musi mieć ≥ 40 znaków (samo „Sprzedam” nie potwierdza niczego).
Każda oferta jest relistem najwyżej jednej i ma najwyżej jeden relist (najbliższy w czasie). Łańcuch A→B→C = jedna
„oferta logiczna” (czas na rynku od pierwszego first_seen). Zdjęć nie porównujemy (koszt transferu).

`python -m analyzer relist-report`
"""
from bisect import bisect_left, bisect_right
from datetime import timedelta
from difflib import SequenceMatcher

from . import analysis

OLD_STATES = ("deleted", "closed", "sold", "unlisted")
NEW_STATES = analysis.MARKET_STATES + ("unlisted", "hidden")
PRICE_TOL, BEFORE_DAYS, AFTER_DAYS = 0.15, 1.0, 14.0
TITLE_MIN, DESC_MIN, DESC_CHARS, DESC_MIN_CHARS = 0.90, 0.80, 500, 40
# relist z samego tytułu (bez opisów): tytuł konkretny, cena prawie ta sama, krótka przerwa
TITLE_BASIS_WORDS, TITLE_BASIS_CHARS, TITLE_BASIS_PRICE, TITLE_BASIS_DAYS = 4, 20, 0.05, 2.0


def specific_title(title):
    """Czy znormalizowany tytuł jest dość konkretny, by sam (bez opisu) potwierdzał relist."""
    return analysis.specific_title(title, TITLE_BASIS_WORDS, TITLE_BASIS_CHARS)


def _ratio(a, b, minimum, matcher=None):
    """difflib ratio z tanimi odrzuceniami (długość, quick_ratio). matcher - SequenceMatcher z ustawionym seq2 = b
    (difflib buforuje analizę seq2 - jedna oferta A porównywana z wieloma B)."""
    if not a or not b or 2 * min(len(a), len(b)) / (len(a) + len(b)) < minimum:
        return 0.0
    m = matcher or SequenceMatcher(None, "", b, autojunk=False)
    m.set_seq1(a)
    if m.real_quick_ratio() < minimum or m.quick_ratio() < minimum:
        return 0.0
    return m.ratio()


class _Row:
    __slots__ = ("id", "title", "brand", "model", "price", "first", "last", "state", "key", "has_desc", "words", "block")

    def __init__(self, r):
        self.id, self.state, self.price = r["id"], r["state"], r["price_now"]
        self.title = analysis.norm_title(r["title"])
        self.brand = analysis.norm_title(r["brand"]) or None
        self.model = analysis.norm_title(r["fmodel"] or r["model"]) or None
        self.first, self.last = analysis.parse_ts(r["first_seen"]), analysis.parse_ts(r["last_seen"])
        self.key, self.has_desc = r["config_key"], bool(r["has_desc"])
        self.words = frozenset(self.title.split())
        self.block = self.brand, self.key or "t:" + " ".join(self.title.split()[:3])


def _load(conn, category):
    sql = f"""SELECT l.id, l.title, l.brand, l.model, l.price_now, l.first_seen, l.last_seen, l.state,
                     f.model AS fmodel, f.config_key,
                     EXISTS(SELECT 1 FROM details d WHERE d.listing_id = l.id AND d.description IS NOT NULL
                            AND d.description != '') AS has_desc
              FROM listings l LEFT JOIN features f ON f.listing_id = l.id
              WHERE l.category = ? AND l.state IN ({",".join("?" * len(NEW_STATES))}) AND l.price_now IS NOT NULL"""
    return [_Row(r) for r in conn.execute(sql, (category, *NEW_STATES))]


def _span(index, key, t_lo, t_hi):
    """(od, do) - zakres kandydatów indeksu `key` z first_seen w oknie czasowym."""
    if key not in index:
        return 0, 0
    firsts = index[key][1]
    return bisect_left(firsts, t_lo), bisect_right(firsts, t_hi)


def candidates(conn, rows, progress=None, every=5000):
    """Pary (stara, nowa) spełniające warunki → [(gap_dni, score, basis, old_id, new_id)].

    Dwa indeksy, w obu kandydaci posortowani po first_seen (okno czasowe bisekcją):
      * identyczny tytuł - wszystkie oferty,
      * oferty z opisem (podobny tytuł bez opisu i tak nie wystarcza): blok (marka, config_key albo 3 pierwsze słowa
        tytułu) oraz słowo tytułu → oferty. Tytuł podobny w ≥ 0,9 ma prawie wszystkie słowa wspólne, więc zamiast
        całego bloku wystarczą oferty z DWOMA najrzadszymi słowami tytułu A (numer modelu, kolor…) - bierzemy
        tańszą z dróg."""
    exact, blocks, postings, freq = {}, {}, {}, {}
    for row in rows:
        if row.first is None:
            continue
        exact.setdefault(row.title, []).append(row)
        if row.has_desc:
            blocks.setdefault(row.block, []).append(row)
            for word in row.words:
                postings.setdefault(word, []).append(row)
                freq[word] = freq.get(word, 0) + 1
    index = {}
    for name, groups in (("exact", exact), ("block", blocks), ("word", postings)):
        for k, group in groups.items():
            group.sort(key=lambda r: r.first)
            index[name, k] = (group, [r.first for r in group])
    descs = {}

    def desc(lid):
        if lid not in descs:
            r = conn.execute("SELECT description FROM details WHERE listing_id=?", (lid,)).fetchone()
            descs[lid] = analysis.norm_title((r[0] if r else "") or "")[:DESC_CHARS]
        return descs[lid]

    out, compared = [], 0
    say = progress or (lambda _t: None)
    for n, a in enumerate(rows, 1):
        if n % every == 0:
            say(f"    {n}/{len(rows)} ofert, porównań {compared}, par {len(out)}...")
        if a.state not in OLD_STATES or a.last is None:
            continue
        lo, hi = a.price * (1 - PRICE_TOL), a.price * (1 + PRICE_TOL)
        t_lo, t_hi = a.last - timedelta(days=BEFORE_DAYS), a.last + timedelta(days=AFTER_DAYS)
        pool = {}
        block = a.block
        spans = [(("exact", a.title),) + _span(index, ("exact", a.title), t_lo, t_hi)]
        if a.has_desc:
            # tańsza droga: cały blok (marka + klucz) albo dwa najrzadsze słowa tytułu - liczone bisekcją
            words = [_span(index, ("word", w), t_lo, t_hi) + (("word", w),)
                     for w in sorted(a.words, key=lambda w: (freq.get(w, 0), w))[:2]]
            by_block = _span(index, ("block", block), t_lo, t_hi)
            if sum(hi_ - lo_ for lo_, hi_, _k in words) < by_block[1] - by_block[0]:
                spans += [(k,) + (lo_, hi_) for lo_, hi_, k in words]
            else:
                spans.append((("block", block),) + by_block)
        for k, i_lo, i_hi in spans:
            if i_hi <= i_lo:
                continue
            for b in index[k][0][i_lo:i_hi]:
                if b.id > a.id and lo <= b.price <= hi and (k[0] == "exact" or b.block == block):
                    pool[b.id] = b
        matcher = None
        compared += len(pool)
        for b in pool.values():
            if a.brand and b.brand and a.brand != b.brand:
                continue
            if a.model and b.model and a.model != b.model:
                continue
            same_title = a.title == b.title
            if not same_title:
                if 2 * len(a.words & b.words) < len(a.words | b.words):
                    continue                 # mniej niż połowa słów wspólna - na pewno nie ≥ 0,9
                matcher = matcher or SequenceMatcher(None, "", a.title, autojunk=False)
                title_sim = _ratio(b.title, a.title, TITLE_MIN, matcher)
                if title_sim < TITLE_MIN:
                    continue
            else:
                title_sim = 1.0
            gap = (b.first - a.last).total_seconds() / 86400
            if a.has_desc and b.has_desc:
                da, dbb = desc(a.id), desc(b.id)
                if min(len(da), len(dbb)) < DESC_MIN_CHARS:
                    continue
                desc_sim = _ratio(da, dbb, DESC_MIN)
                if desc_sim < DESC_MIN:
                    continue
                out.append((gap, round(title_sim * desc_sim, 3), "description", a.id, b.id))
            elif same_title and specific_title(a.title) and gap <= TITLE_BASIS_DAYS \
                    and abs(b.price - a.price) <= TITLE_BASIS_PRICE * a.price:
                out.append((gap, 0.9, "title", a.id, b.id))
    return out


def match(pairs):
    """Przydział 1:1 - najpierw pary najbliższe w czasie, potem najlepszy wynik."""
    used_old, used_new, out = set(), set(), []
    for gap, score, basis, old, new in sorted(pairs, key=lambda p: (abs(p[0]), -p[1], p[4])):
        if old in used_old or new in used_new:
            continue
        used_old.add(old)
        used_new.add(new)
        out.append((old, new, score, basis, round(gap, 3)))
    return out


def compute(conn, progress=None):
    say = progress or (lambda _t: None)
    out = []
    for category in analysis.CATEGORIES:
        say(f"  relisty: {category}...")
        rows = _load(conn, category)
        found = match(candidates(conn, rows, progress))
        say(f"    {len(found)} par z {len(rows)} ofert")
        out += found
    return out


def run(conn, aconn, progress=None):
    rows = compute(conn, progress)
    with aconn:
        aconn.execute("DELETE FROM relists")
        aconn.executemany("INSERT INTO relists (old_id, new_id, score, basis, gap_days) VALUES (?, ?, ?, ?, ?)",
                          rows)
        analysis.set_meta(aconn, "relists_at", analysis.latest_seen(conn))
    return len(rows)


def load(aconn):
    """{new_id: old_id}."""
    return dict(aconn.execute("SELECT new_id, old_id FROM relists").fetchall())


def roots(new_to_old):
    """{id: id pierwszej oferty łańcucha} dla każdej oferty w łańcuchu (także samej pierwszej)."""
    out = {}
    for lid in set(new_to_old) | set(new_to_old.values()):
        root, seen = lid, set()
        while root in new_to_old and root not in seen:
            seen.add(root)
            root = new_to_old[root]
        out[lid] = root
    return out


def report(conn, aconn, examples=10):
    pairs = aconn.execute("SELECT old_id, new_id, score, basis, gap_days FROM relists ORDER BY new_id DESC").fetchall()
    info = {}
    ids = sorted({p["old_id"] for p in pairs} | {p["new_id"] for p in pairs})
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        for r in conn.execute(f"SELECT id, category, state, price_now, title FROM listings WHERE id IN "
                              f"({','.join('?' * len(chunk))})", chunk):
            info[r["id"]] = r
    gone = {}
    for r in conn.execute(f"SELECT category, state, COUNT(*) AS n FROM listings WHERE state IN "
                          f"({','.join('?' * len(OLD_STATES))}) GROUP BY category, state", OLD_STATES):
        gone[(r["category"], r["state"])] = r["n"]
    lines = ["Ponowne wystawienia (relisty): zniknięta oferta A, a ta sama rzecz wystawiona od nowa jako B",
             "", "kategoria  deleted  w tym relist     %  | sold relist / unlisted relist | podstawa: opis / tytuł"]
    total = [0, 0]
    for cat in analysis.CATEGORIES:
        mine = [p for p in pairs if p["old_id"] in info and info[p["old_id"]]["category"] == cat]
        deleted = gone.get((cat, "deleted"), 0) + gone.get((cat, "closed"), 0)
        rel_del = sum(1 for p in mine if info[p["old_id"]]["state"] in ("deleted", "closed"))
        rel_sold = sum(1 for p in mine if info[p["old_id"]]["state"] == "sold")
        rel_unl = sum(1 for p in mine if info[p["old_id"]]["state"] == "unlisted")
        by_desc = sum(1 for p in mine if p["basis"] == "description")
        total[0] += deleted
        total[1] += rel_del
        if not deleted and not mine:
            continue
        lines.append(f"{cat:<9} {deleted:>8} {rel_del:>13} {rel_del / deleted if deleted else 0:6.1%}  | "
                     f"{rel_sold:>11} / {rel_unl:<15} | {by_desc} / {len(mine) - by_desc}")
    lines.append(f"{'razem':<9} {total[0]:>8} {total[1]:>13} {total[1] / total[0] if total[0] else 0:6.1%}")
    chains = roots(load(aconn))
    lengths = {}
    for lid, root in chains.items():
        lengths[root] = lengths.get(root, 0) + 1
    hist = {}
    for n in lengths.values():
        hist[n] = hist.get(n, 0) + 1
    lines.append("łańcuchy (ofert w łańcuchu: ile łańcuchów): "
                 + ", ".join(f"{n}: {c}" for n, c in sorted(hist.items())) if hist else "łańcuchów brak")
    gaps = sorted(p["gap_days"] for p in pairs)
    if gaps:
        lines.append(f"przerwa między zniknięciem A a pojawieniem się B: mediana {analysis.median(gaps):.1f} dni, "
                     f"p75 {analysis.percentile(gaps, 0.75):.1f} dni")
    lines += ["", f"Przykłady (A → B, do sprawdzenia w przeglądarce; {min(examples, len(pairs))} z {len(pairs)}):"]
    for p in pairs[:examples]:
        a, b = info.get(p["old_id"]), info.get(p["new_id"])
        if a is None or b is None:
            continue
        title = "".join(ch for ch in (b["title"] or "") if ord(ch) < 0x2000)[:40]
        lines.append(f"  https://www.vinted.pl/items/{a['id']} ({a['state']}, {a['price_now'] or 0:.0f} zł) → "
                     f"https://www.vinted.pl/items/{b['id']} ({b['state']}, {b['price_now'] or 0:.0f} zł) "
                     f"{p['basis']} {p['score']:.2f}, {p['gap_days']:+.1f} d  {title}")
    return lines
