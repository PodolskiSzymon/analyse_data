"""Statystyki rynku per konfiguracja (PLAN_ANALIZY.md, A5) - bez sieci, główna baza tylko do odczytu.

Grupa = (poziom, kategoria, klucz, rynek PL/zagr, stan sprawne/uszkodzone):
  * poziom `config` - `features.config_key`, `parent` - klucz poziom wyżej (`analysis.parent_key`: laptop
    cpu_line+RAM, telefon model bez pojemności…), `category` - cała kategoria (klucz „*”, także oferty bez klucza).
`blocked` (sprzedana, a strona oferty 404) liczymy jako SPRZEDANĄ - u użytkownika 2026-10-25 ceny blocked mają
taki sam rozkład względem mediany jak sold (mediana ilorazu 0,94 vs 0,91), więc to głównie zwykłe sprzedaże, których
stronę Vinted potem usuwa; oszustwa wycinają flagi cenowe.
Wykluczone: flagi WYKLUCZAJĄCE z `suspicious` i oferty, które mają relist (A z pary A→B - to nie zniknięcie ani
sprzedaż; czas na rynku liczony od początku łańcucha).

Miary (opis wzorów także w summary.md):
  * ceny ofertowe aktywnych (`price_now`) i „sprzedaży” (`sold_price` = ostatnia cena wystawienia → górna granica),
  * sell-through w widełkach: mianownik = sold + deleted + aktywne starsze niż `age_days`;
    dolna = sold / mianownik, górna = (sold + deleted) / mianownik (część deleted to sprzedane - zastrzeżenie 1),
  * dni do sprzedaży: od created_at (albo first_seen, jeśli oferta pojawiła się PO pierwszym przejściu katalogu)
    do last_seen - oferty z pierwszego przejścia bez created_at pominięte (zastrzeżenie 3),
  * obniżki: tylko prawdziwe zmiany (`db.real_change` - bez dryfu kursu), % ofert z ≥ 1 obniżką, mediana obniżki
    (od pierwszej ceny do najniższej), dni do pierwszej obniżki, sell-through z obniżką / bez,
  * popyt: polubienia / wyświetlenia aktywnych vs sprzedanych, spread = mediana sprzedanych / mediana aktywnych.
"""
from datetime import timedelta

from . import analysis, db
from .progress import Bar

STATES = ("active", "reserved", "sold", "deleted", "closed", "blocked")
LOW_DATA = 3
DELAY_EDGES = (1, 2, 4, 7, 10)            # przedziały zwłoki sprawdzenia zniknięcia (dni) - eksperyment C4


class Group:
    __slots__ = ("active", "sold", "deleted", "days", "n_deleted", "n_old", "fav_a", "fav_s", "views_a", "views_s",
                 "n_drop_base", "n_drop", "drop_pct", "drop_days", "by_drop")

    def __init__(self):
        self.active, self.sold, self.deleted, self.days = [], [], [], []
        self.n_deleted = self.n_old = self.n_drop_base = self.n_drop = 0
        self.fav_a, self.fav_s, self.views_a, self.views_s = [], [], [], []
        self.drop_pct, self.drop_days = [], []
        self.by_drop = {True: [0, 0, 0], False: [0, 0, 0]}      # obniżka? → [sold, deleted, stare aktywne]

    def metrics(self):
        med, pct = analysis.median, analysis.percentile
        denom = len(self.sold) + self.n_deleted + self.n_old

        def through(sold, deleted, old):
            d = sold + deleted + old
            return round(sold / d, 4) if d else None

        a_med, s_med = med(self.active), med(self.sold)
        return {
            "n_active": len(self.active), "active_p25": pct(self.active, .25), "active_med": a_med,
            "active_p75": pct(self.active, .75),
            "n_sold": len(self.sold), "sold_p25": pct(self.sold, .25), "sold_med": s_med,
            "sold_p75": pct(self.sold, .75),
            "n_deleted": self.n_deleted, "deleted_p25": pct(self.deleted, .25), "deleted_med": med(self.deleted),
            "deleted_p75": pct(self.deleted, .75), "n_old_active": self.n_old,
            "st_low": round(len(self.sold) / denom, 4) if denom else None,
            "st_high": round((len(self.sold) + self.n_deleted) / denom, 4) if denom else None,
            "days_med": med(self.days), "days_n": len(self.days),
            "drop_share": round(self.n_drop / self.n_drop_base, 4) if self.n_drop_base else None,
            "drop_pct_med": med(self.drop_pct), "drop_days_med": med(self.drop_days),
            "st_low_dropped": through(*self.by_drop[True]), "st_low_not_dropped": through(*self.by_drop[False]),
            "n_dropped": self.n_drop,
            "fav_active_med": med(self.fav_a), "fav_sold_med": med(self.fav_s),
            "views_active_med": med(self.views_a), "views_sold_med": med(self.views_s),
            "spread": round(s_med / a_med, 4) if s_med and a_med else None,
            "low_data": len(self.sold) < LOW_DATA,
        }


def price_drops(conn, progress=True):
    """Jedno przejście po observations (kolejność klucza głównego) → {id: (pierwsza cena, najniższa, chwila pierwszej
    obniżki)} dla ofert z co najmniej jedną PRAWDZIWĄ obniżką (db.real_change - dryf kursu pominięty)."""
    total = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    bar = Bar("obniżki (observations)", total) if progress else None
    sql = """SELECT o.listing_id, o.seen_at, o.price, o.is_reserved,
                    COALESCE(d.seller_currency, l.seller_currency) AS cur
             FROM observations o JOIN listings l ON l.id = o.listing_id
             LEFT JOIN details d ON d.listing_id = o.listing_id
             ORDER BY o.listing_id, o.seen_at"""
    out, current, first, low, last, drop_at = {}, None, None, None, None, None

    def close():
        if current is not None and drop_at is not None:
            out[current] = (first, low, drop_at)

    for n, r in enumerate(conn.execute(sql), 1):
        if bar and n % 5000 == 0:
            bar.update(n)
        if r["listing_id"] != current:
            close()
            current, drop_at = r["listing_id"], None
            first = low = r["price"]
            last = {"price": r["price"], "is_reserved": r["is_reserved"]}
            continue
        obs = {"price": r["price"], "is_reserved": r["is_reserved"]}
        if not db.real_change(last, obs, r["cur"]):
            continue
        if obs["price"] is not None and last["price"] is not None and obs["price"] < last["price"]:
            drop_at = drop_at or r["seen_at"]
        if obs["price"] is not None:
            low = obs["price"] if low is None else min(low, obs["price"])
        last = obs
    close()
    if bar:
        bar.update(total)
        bar.finish()
    return out


def collect(conn, excluded=None, relists=None, age_days=14, progress=True, ai_damaged=None):
    """→ {"groups": {(poziom, kat, klucz, rynek, stan): metryki}, "quality": {...}, "now": ...}.

    excluded - {id: flagi} (wykluczające), relists - {new_id: old_id}, ai_damaged - {id: uszkodzona?} z AI
    (ai_condition) - ma pierwszeństwo przed regułami ekstrakcji."""
    from .relist import roots as chain_roots

    excluded, relists = excluded or {}, relists or {}
    now = analysis.parse_ts(analysis.latest_seen(conn))
    initial = {k: analysis.parse_ts(v) for k, v in analysis.initial_until(conn).items()}
    old_ids = set(relists.values())
    roots = chain_roots(relists)
    root_rows = {}
    ids = sorted(set(roots.values()))
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        for r in conn.execute(f"SELECT id, catalog_id, created_at, first_seen FROM listings WHERE id IN "
                              f"({','.join('?' * len(chunk))})", chunk):
            root_rows[r["id"]] = r
    drops = price_drops(conn, progress)

    def start_of(row):
        """(początek oferty logicznej, czy wiarygodny dla czasu sprzedaży)."""
        src = root_rows.get(roots.get(row["id"])) or row
        created, first = analysis.parse_ts(src["created_at"]), analysis.parse_ts(src["first_seen"])
        until = initial.get(src["catalog_id"])
        reliable = created is not None or (first is not None and until is not None and first > until)
        return created or first, reliable

    groups, gone = {}, []
    quality = {"states": {}, "keyed": {}, "foreign": {}, "excluded": {}, "relist_old": {}, "delays": {}}
    age = timedelta(days=age_days)
    sql = f"""SELECT l.id, l.state, l.catalog_id, l.price_now, l.sold_price, l.created_at, l.first_seen, l.last_seen,
                     COALESCE(l.services_at, l.state_at) AS checked_at, l.favourite_count, l.view_count,
                     COALESCE(d.seller_currency, l.seller_currency) AS cur,
                     f.config_key, f.model, f.cpu, f.cpu_line, f.ram_gb, f.gpu,
                     COALESCE(f.for_parts, 0) OR COALESCE(f.locked, 0) OR COALESCE(f.cracked, 0) AS damaged
              FROM listings l LEFT JOIN features f ON f.listing_id = l.id
              LEFT JOIN details d ON d.listing_id = l.id
              WHERE l.category = ? AND l.state IN ({",".join("?" * len(STATES))})"""
    for category in analysis.CATEGORIES:
        total = conn.execute(f"SELECT COUNT(*) FROM listings WHERE category=? AND state IN "
                             f"({','.join('?' * len(STATES))})", (category, *STATES)).fetchone()[0]
        if not total:
            continue
        bar = Bar(f"{category:<8}", total) if progress else None
        for n, row in enumerate(conn.execute(sql, (category, *STATES)), 1):
            if bar and n % 2000 == 0:
                bar.update(n)
            _count(quality["states"], category, "deleted" if row["state"] == "closed" else
                   "active" if row["state"] == "reserved" else row["state"])
            state = {"closed": "deleted", "reserved": "active", "blocked": "sold"}.get(row["state"], row["state"])
            if row["id"] in excluded:
                _count(quality["excluded"], category, state)
                continue
            if row["id"] in old_ids:
                _count(quality["relist_old"], category, state)
                continue
            price = (row["sold_price"] if row["sold_price"] is not None else row["price_now"]) if state == "sold" \
                else row["price_now"]
            mkt = analysis.market(row["cur"], row["price_now"])
            is_damaged = ai_damaged.get(row["id"], bool(row["damaged"])) if ai_damaged else row["damaged"]
            cond = "uszk" if is_damaged else "ok"
            key = row["config_key"]
            parent = analysis.parent_key(category, key, row["cpu"], row["cpu_line"], row["ram_gb"], row["model"],
                                         row["gpu"])
            if key:
                _count(quality["keyed"], category, "yes")
            if mkt == "zagr":
                _count(quality["foreign"], category, state)
            if state in ("sold", "deleted") and row["checked_at"] and row["last_seen"]:
                delay = analysis.days_between(row["last_seen"], row["checked_at"])
                if delay is not None:
                    bucket = sum(delay >= e for e in DELAY_EDGES)
                    quality["delays"].setdefault((category, bucket, state), []).append(delay)
            if key and state in ("sold", "deleted") and price is not None:
                gone.append((category, key, mkt, cond, state, price))
            start, reliable = start_of(row)
            drop = drops.get(row["id"])
            last_seen = analysis.parse_ts(row["last_seen"])
            targets = [("category", "*")]
            if key:
                targets.append(("config", key))
            if parent:
                targets.append(("parent", parent))
            for level, k in targets:
                g = groups.get((level, category, k, mkt, cond))
                if g is None:
                    g = groups[(level, category, k, mkt, cond)] = Group()
                _add(g, state, price, row, start, reliable, last_seen, now, age, drop)
        if bar:
            bar.update(total)
            bar.finish()
    metrics = {k: g.metrics() for k, g in groups.items()}
    return {"groups": metrics, "quality": quality, "now": now.isoformat(), "age_days": age_days,
            "ratios": ratios(metrics, gone)}


def ratios(metrics, gone):
    """Cena sprzedanej / usuniętej względem mediany AKTYWNYCH tej samej konfiguracji (ten sam rynek i stan) →
    {(kategoria, rynek, stan): {"sold": [mediana, n], "deleted": [mediana, n]}}. Na poziomie kategorii zwykły spread
    (mediana sprzedanych / mediana aktywnych) myli skład: sprzedają się droższe modele (iPhone'y)."""
    out = {}
    for category, key, mkt, cond, state, price in gone:
        m = metrics.get(("config", category, key, mkt, cond))
        if not m or not m["active_med"] or m["n_active"] < 5:
            continue
        out.setdefault((category, mkt, cond), {"sold": [], "deleted": []})[state].append(price / m["active_med"])
    return {k: {s: [analysis.median(v), len(v)] for s, v in d.items()} for k, d in out.items()}


def _count(d, category, key):
    d.setdefault(category, {}).setdefault(key, 0)
    d[category][key] += 1


def _add(g, state, price, row, start, reliable, last_seen, now, age, drop):
    old = False
    if state == "active":
        if price is not None:
            g.active.append(price)
        old = start is not None and now - start > age
        g.n_old += old
        if row["favourite_count"] is not None:
            g.fav_a.append(row["favourite_count"])
        if row["view_count"] is not None:
            g.views_a.append(row["view_count"])
    elif state == "sold":
        if price is not None:
            g.sold.append(price)
        if reliable and start is not None and last_seen is not None:
            g.days.append(max((last_seen - start).total_seconds() / 86400, 0.0))
        if row["favourite_count"] is not None:
            g.fav_s.append(row["favourite_count"])
        if row["view_count"] is not None:
            g.views_s.append(row["view_count"])
    elif state == "deleted":
        g.n_deleted += 1
        if price is not None:
            g.deleted.append(price)
    g.n_drop_base += 1
    dropped = drop is not None
    if dropped:
        g.n_drop += 1
        first, low, at = drop
        if first and low is not None:
            g.drop_pct.append((first - low) / first * 100)
        at = analysis.parse_ts(at)
        if reliable and start is not None and at is not None:
            g.drop_days.append((at - start).total_seconds() / 86400)
    slot = g.by_drop[dropped]
    if state == "sold":
        slot[0] += 1
    elif state == "deleted":
        slot[1] += 1
    elif old:
        slot[2] += 1
