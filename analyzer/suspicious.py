"""Flagi podejrzanych ofert (PLAN_ANALIZY.md, A3) - bez sieci, główna baza tylko do odczytu, wynik do
`analysis.db: flags(listing_id, flag, detail)`.

Flagi (każda osobno; WYKLUCZAJĄCE ze statystyk cen - `EXCLUDING`, informacyjne - reszta):
  * `blocked`         - stan `blocked` (sprzedana, a strona oferty 404) - NIE wyklucza: 2026-10-25 ceny blocked
                        rozkładają się jak ceny sold (to głównie sprzedane, których stronę Vinted usunął),
  * `dup_title_price` - ten sam KONKRETNY znormalizowany tytuł (≥ 4 słowa / ≥ 20 znaków; „Laptop”, „iPhone 15”
                        to tysiące niezależnych ofert) i ta sama cena (±1 zł) u ≥ 3 ofert w 30 dni, a cena < 60%
                        mediany konfiguracji (powtarzane „iPhone 16 Pro 512 GB za 519 zł”),
  * `shop_like`       - jak wyżej, ale po cenie rynkowej (sklep / hurtownik z jednakowymi ofertami) - NIE wyklucza,
  * `offsite`         - namawianie do kontaktu / płatności poza Vinted (WhatsApp, Telegram, „tylko przez OLX”,
                        numer telefonu, e-mail, BLIK…), w kilkunastu językach - wyklucza,
  * `offsite_mention` - samo słowo olx / allegro („kupiony na Allegro”) - NIE wyklucza,
  * `too_cheap`       - cena < 40% mediany tej samej konfiguracji (min. 8 ofert, bez uszkodzonych) - wyklucza,
  * `is_suspicious`   - `photo.is_suspicious = true` w surowej pozycji katalogu - tylko z `--photo-flag`, po
                        sprawdzeniu hipotezy komendą `suspicious-diag` (PLAN_ANALIZY.md B2).

`python -m analyzer suspicious-report [--photo-flag]`  ·  `python -m analyzer suspicious-diag`
"""
import re
from bisect import bisect_left, bisect_right

from . import analysis, rawstore
from .extract import norm
from .sample import _EMAIL

EXCLUDING = ("dup_title_price", "offsite", "too_cheap", "is_suspicious")
INFO = ("blocked", "shop_like", "offsite_mention")
ALL_FLAGS = ("blocked", "dup_title_price", "offsite", "too_cheap", "shop_like", "offsite_mention", "is_suspicious")

DUP_MIN, DUP_PRICE_ZL, DUP_DAYS, DUP_BELOW = 3, 1.0, 30, 0.60
CHEAP_BELOW, CHEAP_MIN_N = 0.40, 8
STATES = analysis.MARKET_STATES + ("unlisted", "hidden")

# Tekst po extract.norm (małe litery, bez polskich znaków / akcentów, zwinięte spacje; interpunkcja zostaje).
_OFFSITE = [(name, re.compile(rx)) for name, rx in (
    ("whatsapp", r"what'?s ?app|\bwatsapp|\bwa\.me\b"),
    ("telegram", r"\btelegram\w*|\bt\.me/"),
    ("viber", r"\bviber\b"),
    ("blik", r"\bblik\w*\b"),
    ("poza vinted", r"kontakt\w* poza|poza (?:vinted|platform\w*|aplikacj\w*|portal\w*)|outside (?:of )?vinted|"
                    r"off vinted|aus?ss?erhalb (?:von )?vinted|außerhalb (?:von )?vinted|mimo (?:vinted|platform\w*)|"
                    r"in afara (?:vinted|platformei)|vinteden kivul|fuori (?:da |di )?vinted|"
                    r"(?:en )?dehors de vinted|fuera de vinted|utanfor vinted|uden for vinted|uz vinted|"
                    r"buiten vinted|fora d[oa] vinted|mimo aplikac\w*"),
    ("przelew poza", r"tylko odbior osobisty i przelew|przelew\w* (?:bezposrednio|na konto|na rachunek)|"
                     r"platnosc (?:bezposrednio|na konto|przelewem na)|bank transfer only|direct (?:bank )?transfer|"
                     r"paypal (?:friends|f&f|przyjaciel)"),
    ("tylko olx/allegro", r"(?:tylko|wylacznie|jedynie|only|exclusively|sprzedaz|sprzedam|sprzedaje|transakcj\w*|"
                          r"kontakt\w*|napisz|pisz\w*|kup\w* przez|via|zapraszam na)\W+(?:[\w-]+\W+){0,3}?"
                          r"(?:olx|allegro)\b"),
)]
_MENTION = re.compile(r"\b(?:olx|allegro)\b")
# Numer telefonu: 9-13 cyfr (spacje/myślniki między grupami) z „+” albo słowem kontaktu tuż przed - same ciągi
# liczb („128 256 512”, rozdzielczości) nie wystarczą.
_PHONE = re.compile(r"(?:\+\s?\d{2,3}|\b(?:tel\w*|phone|nr|numer\w*|number|dzwon\w*|zadzwon\w*|sms|call|"
                    r"kontakt\w*|whats ?app|viber|mobil\w*|handy)\b\.?:?\s*(?:\+?\s?\d{2,3})?)"
                    r"[\s-]?(?:\d[\s-]?){8,12}\d?(?!\d)")


def offsite_hits(title, description):
    """→ (lista dopasowań wykluczających, czy jest sama wzmianka olx/allegro). Bez zapisywania numerów / adresów."""
    text = norm(f"{title or ''}\n{description or ''}")
    hits = [name for name, rx in _OFFSITE if rx.search(text)]
    if _EMAIL.search(description or "") or _EMAIL.search(title or ""):
        hits.append("e-mail")
    if _PHONE.search(text):
        hits.append("telefon")
    return hits, bool(_MENTION.search(text))


def _rows(conn, category):
    """Oferty kategorii potrzebne do flag cenowych: (id, tytuł znorm., cena, first_seen, config_key, rodzic,
    uszkodzona, stan)."""
    sql = f"""SELECT l.id, l.title, l.state, l.first_seen,
                     CASE WHEN l.state='sold' THEN COALESCE(l.sold_price, l.price_now) ELSE l.price_now END AS price,
                     f.config_key, f.model, f.cpu, f.cpu_line, f.ram_gb, f.gpu,
                     COALESCE(f.for_parts, 0) OR COALESCE(f.locked, 0) OR COALESCE(f.cracked, 0) AS damaged
              FROM listings l LEFT JOIN features f ON f.listing_id = l.id
              WHERE l.category = ? AND l.state IN ({",".join("?" * len(STATES))})"""
    for r in conn.execute(sql, (category, *STATES)):
        yield (r["id"], analysis.norm_title(r["title"]), r["price"], analysis.parse_ts(r["first_seen"]),
               r["config_key"],
               analysis.parent_key(category, r["config_key"], r["cpu"], r["cpu_line"], r["ram_gb"], r["model"],
                                   r["gpu"]),
               bool(r["damaged"]), r["state"])


def reference_medians(rows):
    """Mediany cen sprawnych ofert: {config_key: (mediana, n)}, {rodzic: (mediana, n)} - grupy z n ≥ CHEAP_MIN_N."""
    by_key, by_parent = {}, {}
    for _id, _t, price, _fs, key, parent, damaged, _st in rows:
        if damaged or price is None:
            continue
        if key:
            by_key.setdefault(key, []).append(price)
        if parent:
            by_parent.setdefault(parent, []).append(price)
    pick = lambda groups: {k: (analysis.median(v), len(v)) for k, v in groups.items()  # noqa: E731
                           if len(v) >= CHEAP_MIN_N}
    return pick(by_key), pick(by_parent)


def price_flags(rows):
    """Flagi cenowe jednej kategorii → [(id, flaga, opis)]."""
    out = []
    med_key, med_parent = reference_medians(rows)

    def ref(key, parent):
        if key in med_key:
            return med_key[key] + ("konfiguracji",)
        if parent in med_parent:
            return med_parent[parent] + ("poziom wyżej",)
        return None

    for lid, _t, price, _fs, key, _parent, damaged, state in rows:
        if state == "blocked":
            out.append((lid, "blocked", "stan blocked"))
        if not damaged and price is not None and key in med_key:
            med, n = med_key[key]
            if price < CHEAP_BELOW * med:
                out.append((lid, "too_cheap", f"{price:.0f} zł < 40% mediany {med:.0f} zł (n={n})"))
    by_title = {}
    for row in rows:
        if row[1] and analysis.specific_title(row[1]) and row[2] is not None and row[3] is not None:
            by_title.setdefault(row[1], []).append(row)
    for group in by_title.values():
        if len(group) < DUP_MIN:
            continue
        group.sort(key=lambda r: r[2])
        prices = [r[2] for r in group]
        for row in group:
            lo, hi = bisect_left(prices, row[2] - DUP_PRICE_ZL), bisect_right(prices, row[2] + DUP_PRICE_ZL)
            near = [r for r in group[lo:hi] if abs((r[3] - row[3]).total_seconds()) <= DUP_DAYS * 86400]
            if len(near) < DUP_MIN:
                continue
            reference = ref(row[4], row[5])
            if reference and row[2] < DUP_BELOW * reference[0]:
                out.append((row[0], "dup_title_price", f"{len(near)} ofert po {row[2]:.0f} zł, mediana "
                                                       f"{reference[2]} {reference[0]:.0f} zł"))
            else:
                why = f"mediana {reference[2]} {reference[0]:.0f} zł" if reference else "brak mediany"
                out.append((row[0], "shop_like", f"{len(near)} ofert po {row[2]:.0f} zł, {why}"))
    return out


def photo_flags(conn, progress=None):
    """`is_suspicious` z ostatniej surowej odpowiedzi: pozycja katalogu (photo.is_suspicious) albo szczegóły oferty
    (sidebar: photos[].is_suspicious) - true w którejkolwiek."""
    say = progress or (lambda _t: None)
    found = {}
    for kind in ("catalog", "sidebar"):
        last_id, last_body, n = None, None, 0

        def check(lid, body):
            try:
                fields = _diag_fields(kind, rawstore.decompress(body))
            except Exception:
                return
            hits = [name for name, value in fields.items() if value and name.lower().endswith("is_suspicious")]
            if hits:
                found.setdefault(lid, []).extend(f"{kind}:{h}" for h in hits)

        sql = f"""SELECT r.listing_id, r.body FROM raw r JOIN listings l ON l.id = r.listing_id
                  WHERE r.kind=? AND l.state IN ({",".join("?" * len(STATES))})
                  ORDER BY r.listing_id, r.fetched_at"""
        for lid, body in conn.execute(sql, (kind, *STATES)):
            if lid != last_id and last_id is not None:
                check(last_id, last_body)
                n += 1
                if n % 20000 == 0:
                    say(f"  zdjęcia ({kind}): {n} ofert...")
            last_id, last_body = lid, body
        if last_id is not None:
            check(last_id, last_body)
    return [(lid, "is_suspicious", ", ".join(hits) + "=true") for lid, hits in sorted(found.items())]


def compute(conn, photo_flag=False, progress=None):
    """Wszystkie flagi → [(id, flaga, opis)] (bez zapisu)."""
    say = progress or (lambda _t: None)
    out = []
    for category in analysis.CATEGORIES:
        say(f"  flagi cenowe: {category}...")
        out += price_flags(list(_rows(conn, category)))
    say("  opisy (kontakt poza Vinted)...")
    sql = f"""SELECT l.id, l.title, d.description FROM listings l LEFT JOIN details d ON d.listing_id = l.id
              WHERE l.category IN ({",".join("?" * len(analysis.CATEGORIES))})
                AND l.state IN ({",".join("?" * len(STATES))})"""
    for n, r in enumerate(conn.execute(sql, (*analysis.CATEGORIES, *STATES)), 1):
        hits, mention = offsite_hits(r["title"], r["description"])
        if hits:
            out.append((r["id"], "offsite", ", ".join(hits)))
        elif mention:
            out.append((r["id"], "offsite_mention", "olx/allegro"))
        if n % 50000 == 0:
            say(f"    {n} ofert...")
    if photo_flag:
        say("  photo.is_suspicious z surowych pozycji katalogu...")
        out += photo_flags(conn, progress)
    return out


def run(conn, aconn, photo_flag=False, progress=None):
    """Liczy flagi i zapisuje do analysis.db (tabela flags od nowa). → liczba wierszy."""
    rows = compute(conn, photo_flag, progress)
    with aconn:
        aconn.execute("DELETE FROM flags")
        aconn.executemany("INSERT OR REPLACE INTO flags (listing_id, flag, detail) VALUES (?, ?, ?)", rows)
        analysis.set_meta(aconn, "flags_at", analysis.latest_seen(conn))
        analysis.set_meta(aconn, "photo_flag", int(bool(photo_flag)))
    return len(rows)


def load(aconn, excluding=EXCLUDING):
    """{listing_id: {flagi}} - tylko flagi wykluczające (domyślnie)."""
    out = {}
    for lid, flag in aconn.execute("SELECT listing_id, flag FROM flags"):
        if excluding is None or flag in excluding:
            out.setdefault(lid, set()).add(flag)
    return out


def report(conn, aconn, examples=10):
    """Liczby per flaga i kategoria, ile ofert wyklucza (w tym sprzedanych) + przykładowe linki."""
    flags = {}
    for lid, flag, detail in aconn.execute("SELECT listing_id, flag, detail FROM flags ORDER BY listing_id DESC"):
        flags.setdefault(flag, []).append((lid, detail))
    ids = sorted({lid for rows in flags.values() for lid, _ in rows})
    info = {}
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        for r in conn.execute(f"SELECT id, category, state, price_now, sold_price, title FROM listings "
                              f"WHERE id IN ({','.join('?' * len(chunk))})", chunk):
            info[r["id"]] = r
    totals = dict(conn.execute(f"SELECT category, COUNT(*) FROM listings WHERE state IN "
                               f"({','.join('?' * len(STATES))}) GROUP BY category", STATES).fetchall())
    lines = ["Flagi podejrzanych ofert (oferty w stanach rynkowych; WYKL = wykluczona ze statystyk cen)", ""]
    header = "flaga".ljust(17) + "".join(c[:7].rjust(8) for c in analysis.CATEGORIES) + "   razem  sprzed."
    lines.append(header)
    for flag in ALL_FLAGS:
        rows = flags.get(flag, [])
        by_cat = {}
        for lid, _ in rows:
            if lid in info:
                by_cat[info[lid]["category"]] = by_cat.get(info[lid]["category"], 0) + 1
        sold = sum(1 for lid, _ in rows if lid in info and info[lid]["state"] == "sold")
        mark = "WYKL" if flag in EXCLUDING else "info"
        lines.append(f"{flag:<16} " + "".join(f"{by_cat.get(c, 0):>8}" for c in analysis.CATEGORIES)
                     + f"{len(rows):>8} {sold:>7}  {mark}")
    excluded = {lid for f in EXCLUDING for lid, _ in flags.get(f, [])}
    by_cat = {}
    for lid in excluded:
        if lid in info:
            by_cat[info[lid]["category"]] = by_cat.get(info[lid]["category"], 0) + 1
    lines.append("wykluczone razem " + "".join(f"{by_cat.get(c, 0):>8}" for c in analysis.CATEGORIES)
                 + f"{len(excluded):>8}")
    lines.append("ofert w kategorii" + "".join(f"{totals.get(c, 0):>8}" for c in analysis.CATEGORIES)
                 + f"{sum(totals.values()):>8}")
    lines += [""] + price_check(conn)
    photo = aconn.execute("SELECT value FROM meta WHERE key='photo_flag'").fetchone()
    if not photo or photo[0] != "1":
        lines.append("(is_suspicious wyłączone - włącz: --photo-flag, po sprawdzeniu `suspicious-diag`)")
    for flag in ALL_FLAGS:
        rows = flags.get(flag, [])
        if not rows:
            continue
        lines += ["", f"{flag} - przykłady ({min(examples, len(rows))} z {len(rows)}):"]
        for lid, detail in rows[:examples]:
            r = info.get(lid)
            if r is None:
                continue
            price = r["sold_price"] if r["state"] == "sold" and r["sold_price"] is not None else r["price_now"]
            title = "".join(ch for ch in (r["title"] or "") if ord(ch) < 0x2000)[:40]
            lines.append(f"  https://www.vinted.pl/items/{lid}  {r['category']:<7} {r['state']:<8} "
                         f"{price or 0:>8.0f} zł  {title}  [{detail}]")
    return lines


# ---------------------------------------------------------------------------------------------- diagnostyka B2


def _bool_leaves(obj, path="", depth=0):
    """(ścieżka, wartość) każdego pola logicznego w JSON-ie; indeksy list zwinięte do „[]”."""
    if depth > 6:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _bool_leaves(v, f"{path}.{k}" if path else str(k), depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            yield from _bool_leaves(v, f"{path}[]", depth + 1)
    elif isinstance(obj, bool):
        yield path, obj


def _diag_fields(kind, body):
    """Pola do diagnostyki: katalog - photo.* i najwyższy poziom; sidebar (szczegóły) - photos[].*, najwyższy poziom
    i wszystko, co ma w nazwie „suspic”. Wartość per oferta = czy choć jedno true (lista zdjęć)."""
    from sniper.extractor import unwrap_sidebar

    item = unwrap_sidebar(body) if kind == "sidebar" else body
    if not isinstance(item, dict):
        return {}
    fields = {}
    for name, value in _bool_leaves(item):
        top = "." not in name and "[]" not in name
        keep = top or "suspic" in name.lower() or (
            name.startswith("photo.") if kind == "catalog" else name.startswith("photos[]."))
        if keep:
            fields[name] = fields.get(name, False) or value
    return fields


def photo_diag(conn, per_state=2000, states=("blocked", "sold", "deleted", "active"), progress=None):
    """Rozkład pól logicznych zdjęć (i najwyższego poziomu) w ostatniej surowej odpowiedzi: pozycja katalogu
    (`catalog`) i szczegóły oferty (`sidebar`, lista `photos`), osobno dla stanów - próbka losowa po `per_state`.
    Hipoteza użytkownika: oszustwa (blocked) mają is_suspicious=true. 2026-10-24: w katalogu pola NIE MA."""
    say = progress or (lambda _t: None)
    kinds = ("catalog", "sidebar")
    counts = {k: {} for k in kinds}
    sizes = {k: {} for k in kinds}
    for state in states:
        say(f"  {state}: losuję do {per_state} ofert...")
        ids = [r[0] for r in conn.execute("SELECT id FROM listings WHERE state=? ORDER BY RANDOM() LIMIT ?",
                                          (state, per_state))]
        for kind in kinds:
            sizes[kind][state] = 0
            for lid in ids:
                row = conn.execute("SELECT body FROM raw WHERE listing_id=? AND kind=? ORDER BY fetched_at DESC "
                                   "LIMIT 1", (lid, kind)).fetchone()
                if row is None:
                    continue
                try:
                    fields = _diag_fields(kind, rawstore.decompress(row[0]))
                except Exception:
                    continue
                sizes[kind][state] += 1
                for name, value in fields.items():
                    c = counts[kind].setdefault(name, {}).setdefault(state, [0, 0])
                    c[0] += value is True
                    c[1] += 1
    lines = []
    for kind in kinds:
        label = "pozycja katalogu (catalog)" if kind == "catalog" else "szczegóły oferty (sidebar)"
        lines += [f"{label}: % true (true/z polem), próbka z zapisaną odpowiedzią: "
                  + ", ".join(f"{s} {sizes[kind][s]}" for s in states), ""]
        lines.append("pole".ljust(36) + "".join(s.rjust(20) for s in states))
        names = sorted(counts[kind], key=lambda n: ("suspic" not in n.lower(), "." in n or "[]" in n, n),
                       reverse=False)
        for name in names:
            cells = []
            for state in states:
                t, n = counts[kind][name].get(state, [0, 0])
                cells.append((f"{t / n:6.1%} ({t}/{n})" if n else "-").rjust(20))
            lines.append(f"{name[:35]:<36}" + "".join(cells))
        if not any("suspic" in n.lower() for n in counts[kind]):
            lines.append("(brak pola z „suspic” w nazwie)")
        lines.append("")
    return lines


def price_check(conn):
    """Cena blocked vs sold względem mediany sprawnych ofert tej samej konfiguracji (albo poziom wyżej): czy
    `blocked` (sprzedana, a strona 404) to oszustwa (cena ≪ mediany), czy zwykłe sprzedaże, których stronę Vinted
    potem usuwa (cena ~ mediany)."""
    ratios = {"blocked": [], "sold": []}
    total = {"blocked": 0, "sold": 0}
    for category in analysis.CATEGORIES:
        rows = list(_rows(conn, category))
        med_key, med_parent = reference_medians(rows)
        for _lid, _t, price, _fs, key, parent, damaged, state in rows:
            if state not in ratios:
                continue
            total[state] += 1
            ref = med_key.get(key) or med_parent.get(parent)
            if ref and price and not damaged:
                ratios[state].append(price / ref[0])
    lines = ["Cena / mediana konfiguracji (sprawne): czy blocked to oszustwa (≪ mediany), czy zwykłe sprzedaże (~1,0)",
             "stan       ofert  z medianą  mediana ilorazu  < 40%  < 60%  60-90%  ≥ 90%"]
    for state, xs in ratios.items():
        n = len(xs)
        share = (lambda cond: f"{sum(1 for x in xs if cond(x)) / n:6.0%}") if n else (lambda cond: "     -")
        med = analysis.median(xs)
        lines.append(f"{state:<9} {total[state]:>6} {n:>10} {('-' if med is None else f'{med:.2f}'):>16} "
                     f"{share(lambda x: x < .4)} {share(lambda x: x < .6)} {share(lambda x: .6 <= x < .9)}  "
                     f"{share(lambda x: x >= .9)}")
    return lines
