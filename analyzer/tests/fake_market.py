"""Atrapa rynku do testów analizy (PLAN_ANALIZY.md, A2): syntetyczna baza SQLite w schemacie analizatora.

`build(path)` → `Truth`: ~3 tys. ofert w 7 kategoriach. Dwie warstwy:
  * „tło” - konfiguracje z losowymi (stałe ziarno) cenami, stanami, rynkiem PL/zagr., created_at, obniżkami i dryfem
    kursu; tytuły unikatowe (losowy dopisek), więc tło nie tworzy relistów ani duplikatów,
  * scenariusze ręczne z wartościami do policzenia na kartce: grupa `galaxy s21|128` (liczby co do sztuki w teście),
    oszustwa (ten sam tytuł + cena, za tanio, „tylko OLX”, telefon, e-mail), sklep z jednakowymi ofertami, relisty
    (para, łańcuch A→B→C, bez opisu) i oferty podobne, które relistami NIE są.
`Truth` zawiera opis każdej oferty (do niezależnego przeliczenia statystyk w teście), oczekiwane flagi i relisty.
"""
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from analyzer import db
from analyzer.details import content_hash

UTC = timezone.utc
LAPTOP_START = datetime(2026, 10, 11, 8, tzinfo=UTC)
OTHER_START = datetime(2026, 10, 12, 8, tzinfo=UTC)
NOW = datetime(2026, 10, 24, 8, tzinfo=UTC)          # ostatnie przejście = „teraz” raportu
RUN_HOURS = 4                                        # przejście trwa 4 h → initial_until = start + 4 h
CATALOG = {"laptop": 3580, "phone": 3661, "console": 3025, "tablet": 3728, "gpu": 3582, "ram": 3584,
           "storage": 3583}


def iso(ts):
    return ts.isoformat(timespec="milliseconds") if ts else None


def run_times(category):
    start = LAPTOP_START if category == "laptop" else OTHER_START
    out, ts = [], start
    while ts <= NOW:
        out.append(ts)
        ts += timedelta(hours=12)
    return out


def initial_until(category):
    return (LAPTOP_START if category == "laptop" else OTHER_START) + timedelta(hours=RUN_HOURS)


# kategoria → [(config_key, parent, base_price, n, features, tytuł, marka)]
BULK = {
    "laptop": [
        ("thinkpad t480|i5-8350u|integrated|16|256", "intel core i5|16", 1200, 260,
         dict(model="thinkpad t480", cpu="i5-8350u", gpu="integrated", ram_gb=16, storage_gb=256),
         "Lenovo ThinkPad T480 i5-8350U 16GB 256GB", "Lenovo"),
        ("macbook air 13 2020|apple m1|?|8|256", "apple m1|8", 2200, 200,
         dict(model="macbook air 13 2020", cpu="apple m1", ram_gb=8, storage_gb=256),
         "MacBook Air 13 2020 M1 8GB 256GB", "Apple"),
        ("?|i7-10750h|rtx 2060|16|512", "intel core i7|16", 2800, 120,
         dict(cpu="i7-10750h", gpu="rtx 2060", ram_gb=16, storage_gb=512), "Laptop gamingowy i7-10750H RTX 2060",
         "MSI"),
    ],
    "phone": [
        ("iphone 13|128", "iphone 13", 1500, 300, dict(model="iphone 13", storage_gb=128), "iPhone 13 128GB", "Apple"),
        ("iphone 16 pro|512", "iphone 16 pro", 4200, 120, dict(model="iphone 16 pro", storage_gb=512),
         "iPhone 16 Pro 512GB", "Apple"),
    ],
    "tablet": [
        ("ipad air|64", "ipad air", 1300, 150, dict(model="ipad air", storage_gb=64), "iPad Air 64GB", "Apple"),
    ],
    "console": [
        ("playstation 5|disc|?", "playstation 5|disc", 1700, 250, dict(), "PlayStation 5 z napędem", "Sony"),
        ("nintendo switch|oled|?", "nintendo switch|oled", 1050, 150, dict(), "Nintendo Switch OLED", "Nintendo"),
    ],
    "gpu": [
        ("rtx 3060|12", "rtx 3060", 1000, 150, dict(gpu="rtx 3060"), "Karta graficzna RTX 3060 12GB", "MSI"),
    ],
    "ram": [
        ("ddr4|so-dimm|16", "ddr4|16", 120, 200, dict(), "Pamięć RAM DDR4 16GB SO-DIMM", "Kingston"),
    ],
    "storage": [
        ("nvme|1000", "1000", 250, 200, dict(storage_gb=1000), "Dysk SSD NVMe 1TB", "Samsung"),
    ],
}

FEATURE_COLS = ("model", "cpu", "cpu_line", "gpu", "ram_gb", "storage_gb", "for_parts", "locked", "cracked",
                "segment")


@dataclass
class Truth:
    rows: dict = field(default_factory=dict)            # id → opis oferty (dict)
    flags: dict = field(default_factory=dict)           # id → {flaga, …} (oczekiwane)
    relists: dict = field(default_factory=dict)         # new_id → old_id
    ids: dict = field(default_factory=dict)             # nazwa scenariusza → id
    now: str = iso(NOW)


class Builder:
    def __init__(self, conn, seed):
        self.conn = conn
        self.rng = random.Random(seed)
        self.truth = Truth()
        self.next_id = 10_000_000

    def add(self, category, title, price, state="active", *, key=None, parent=None, brand=None, first_seen=None,
            last_seen=None, created_at=None, currency=None, details_currency=None, description=None,
            features=None, for_parts=False, fav=None, views=None, prices=None, sold_price=None, flags=(),
            catalog_photo_suspicious=False, name=None, with_details=None, status_label="Bardzo dobry"):
        """Jedna oferta. prices = [(czas, cena), …] - historia obserwacji (domyślnie jedna przy first_seen);
        cena bieżąca = ostatnia. state_at = last_seen + 1 dzień dla zniknięć."""
        self.next_id += 1
        lid = self.next_id
        catalog_id = CATALOG[category]
        first_seen = first_seen or run_times(category)[0]
        if last_seen is None:
            last_seen = NOW if state in ("active", "below_min", "ignored") else first_seen
        prices = prices or [(first_seen, price)]
        price_now = prices[-1][1]
        if state == "sold" and sold_price is None:
            sold_price = price_now
        has_details = with_details if with_details is not None else description is not None
        if has_details and description is None:
            description = "Sprzedam, stan zgodny z opisem."
        state_at = last_seen + timedelta(days=1) if state not in ("active", "below_min", "ignored") else last_seen
        seller_currency = currency
        self.conn.execute(
            """INSERT INTO listings (id, catalog_id, category, category_src, title, brand, model, status_label,
                   currency, photo_url, created_at, first_seen, last_seen, last_run_id, missed_runs, state, state_at,
                   sold_price, days_to_sell, details_at, content_hash, favourite_count, view_count, price_now,
                   total_now, seller_currency, seller_price, services_at, seller_hash)
               VALUES (?, ?, ?, 'catalog', ?, ?, ?, ?, 'PLN', ?, ?, ?, ?, 1, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?,
                       NULL, ?, NULL)""",
            (lid, catalog_id, category, title, brand, (features or {}).get("model"), status_label,
             f"https://images1.vinted.net/{lid}.webp", iso(created_at), iso(first_seen), iso(last_seen),
             0 if state == "active" else 2, state, iso(state_at), sold_price,
             iso(first_seen) if has_details else None,
             content_hash(title, description) if has_details else None, fav, views, price_now,
             round(price_now * 1.05 + 2.5, 2), seller_currency,
             iso(state_at) if state in ("sold", "deleted", "blocked") else None))
        for seen_at, p in prices:
            self.conn.execute("INSERT INTO observations (listing_id, seen_at, price, total_price, is_reserved, "
                              "favourite_count) VALUES (?, ?, ?, ?, 0, ?)",
                              (lid, iso(seen_at), p, round(p * 1.05 + 2.5, 2), fav))
        if has_details:
            self.conn.execute(
                "INSERT INTO details (listing_id, fetched_at, description, attributes_json, upload_age, created_est, "
                "business, seller_currency, photo_count, is_localized, source) VALUES (?, ?, ?, '{}', NULL, ?, 0, ?, "
                "5, 0, 'sidebar')", (lid, iso(first_seen), description, iso(created_at), details_currency))
        feats = dict(features or {})
        if for_parts:
            feats["for_parts"] = 1
        feats.setdefault("segment", "for_parts" if for_parts else "working")
        if key is not None or features is not None:
            fields_json = json.dumps({k: {"value": v, "source": "title"} for k, v in feats.items()})
            self.conn.execute(
                f"INSERT INTO features (listing_id, category, version, extracted_at, fields_json, config_key, "
                f"{', '.join(FEATURE_COLS)}) VALUES (?, ?, 1, ?, ?, ?, {', '.join('?' * len(FEATURE_COLS))})",
                (lid, category, iso(NOW), fields_json, key, *(feats.get(c) for c in FEATURE_COLS)))
        raw = {"id": lid, "title": title, "is_promoted": False,
               "photo": {"is_suspicious": bool(catalog_photo_suspicious), "is_main": True, "is_hidden": False}}
        db.put_raw(self.conn, lid, "catalog", raw, iso(first_seen))
        if has_details:                 # szczegóły (sidebar): lista zdjęć z is_suspicious
            db.put_raw(self.conn, lid, "sidebar", {"item": {"id": lid, "is_closed": False, "photos": [
                {"is_main": True, "is_suspicious": False},
                {"is_main": False, "is_suspicious": bool(catalog_photo_suspicious)}]}}, iso(first_seen))
        # rynek i obniżki - tak jak liczy analiza (waluta: details > listings; bez waluty ułamkowa cena = zagr.)
        cur = details_currency or seller_currency
        mkt = ("PL" if cur == "PLN" else "zagr") if cur else ("zagr" if abs(price_now - round(price_now)) >= 0.005
                                                               else "PL")
        drop, last, low = None, {"price": prices[0][1], "is_reserved": 0}, prices[0][1]
        for seen_at, p in prices[1:]:
            obs = {"price": p, "is_reserved": 0}
            if not db.real_change(last, obs, cur):
                continue
            if p < last["price"] and drop is None:
                drop = {"at": seen_at}
            low = min(low, p)
            last = obs
        if drop is not None:
            drop["pct"] = (prices[0][1] - low) / prices[0][1] * 100
        self.truth.rows[lid] = dict(
            id=lid, category=category, catalog_id=catalog_id, key=key, parent=parent, market=mkt, state=state,
            price_now=price_now, sold_price=sold_price, damaged=bool(for_parts), created_at=created_at,
            first_seen=first_seen, last_seen=last_seen, initial=first_seen <= initial_until(category), fav=fav,
            views=views, drop=drop, title=title)
        if flags:
            self.truth.flags[lid] = set(flags)
        if name:
            self.truth.ids[name] = lid
        return lid

    # ------------------------------------------------------------------------------------------- tło

    def bulk(self):
        rng = self.rng
        for category, configs in BULK.items():
            runs = run_times(category)
            for key, parent, base, n, feats, title, brand in configs:
                for _ in range(n):
                    initial = rng.random() < 0.3
                    first_seen = runs[0] if initial else rng.choice(runs[1:-1])
                    created_at = None
                    if rng.random() < 0.5:
                        created_at = first_seen - timedelta(days=rng.uniform(0, 30) if initial else rng.uniform(0, 0.4))
                    state = rng.choices(["active", "sold", "deleted", "unlisted"], [50, 20, 25, 5])[0]
                    later = [t for t in runs if first_seen <= t < NOW]
                    last_seen = NOW if state == "active" else rng.choice(later)
                    foreign = rng.random() < 0.15
                    damaged = rng.random() < 0.05
                    p0 = base * rng.uniform(0.8, 1.2) * (0.4 if damaged else 1)
                    p0 = round(p0, 2) if foreign else float(round(p0 / 10) * 10)
                    if foreign and abs(p0 - round(p0)) < 0.005:
                        p0 += 0.37
                    prices = [(first_seen, p0)]
                    between = [t for t in runs if first_seen < t <= last_seen]
                    if foreign and between:                       # dryf kursu (<1%) - nie jest zmianą ceny
                        prices.append((between[0], round(p0 * 1.004, 2)))
                    if between and rng.random() < 0.25:            # prawdziwa obniżka
                        at = rng.choice(between)
                        if at > prices[-1][0]:
                            p1 = round(p0 * 0.9, 2) if foreign else float(round(p0 * 0.9 / 10) * 10)
                            prices.append((at, p1))
                    currency = None
                    with_details = rng.random() < 0.6
                    if foreign:
                        currency = rng.choice(["EUR", "RON", None])
                    elif with_details:
                        currency = "PLN"
                    suffix = " ".join("".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(6))
                                      for _ in range(3))
                    self.add(category, f"{title} {suffix}", p0, state, key=key, parent=parent, brand=brand,
                             first_seen=first_seen, last_seen=last_seen, created_at=created_at,
                             currency=currency if with_details else None,
                             details_currency=currency if with_details else None,
                             with_details=with_details, features=feats, for_parts=damaged,
                             fav=rng.randint(0, 40), views=rng.randint(10, 900), prices=prices)
        # poza analizą: tanie (below_min) i nie nasze (ignored)
        for i in range(20):
            self.add("laptop", f"Laptop tani {i}", 300.0, "below_min", brand="Acer")
        for i in range(10):
            self.add("laptop", f"Torba na laptopa {i}", 50.0, "ignored")

    # ------------------------------------------------------------------------------------------- scenariusze

    def galaxy(self):
        """Grupa phone `galaxy s21|128`, rynek PL, sprawna - wartości oczekiwane w teście (patrz docstring testu)."""
        d = lambda month_day_hour: datetime(2026, 10, *month_day_hour, tzinfo=UTC)  # noqa: E731
        key, parent, feats = "galaxy s21|128", "galaxy s21", dict(model="galaxy s21", storage_gb=128)
        common = dict(key=key, parent=parent, features=feats, brand="Samsung")
        self.add("phone", "Galaxy S21 128GB czarny", 800.0, first_seen=d((12, 8)), created_at=d((5, 8)), fav=1,
                 views=10, name="g_a1", **common)
        self.add("phone", "Galaxy S21 128GB szary", 900.0, first_seen=d((12, 20)), created_at=d((9, 8)), fav=2,
                 views=20, name="g_a2", **common)
        self.add("phone", "Galaxy S21 128GB biały", 1000.0, first_seen=d((20, 8)), fav=3, views=30, name="g_a3",
                 **common)
        self.add("phone", "Galaxy S21 128GB fioletowy", 1100.0, first_seen=d((20, 8)), fav=4, views=40, name="g_a4",
                 **common)
        self.add("phone", "Galaxy S21 128GB różowy", 1300.0, first_seen=d((20, 8)), fav=5, views=50, name="g_a5",
                 prices=[(d((20, 8)), 1300.0), (d((22, 8)), 1200.0)], **common)
        self.add("phone", "Galaxy S21 128GB zielony", 850.0, "sold", first_seen=d((14, 20)), created_at=d((14, 8)),
                 last_seen=d((16, 8)), fav=10, views=100, name="g_s1", **common)
        self.add("phone", "Galaxy S21 128GB niebieski", 1000.0, "sold", first_seen=d((15, 8)), last_seen=d((19, 8)),
                 fav=20, views=200, prices=[(d((15, 8)), 1000.0), (d((17, 8)), 900.0)], name="g_s2", **common)
        self.add("phone", "Galaxy S21 128GB granat", 950.0, "sold", first_seen=d((12, 8)), last_seen=d((13, 8)),
                 fav=30, views=300, name="g_s3", **common)
        self.add("phone", "Galaxy S21 128GB złoty", 1000.0, "deleted", first_seen=d((13, 8)), last_seen=d((15, 8)),
                 name="g_d1", **common)
        self.add("phone", "Galaxy S21 128GB srebrny", 1000.0, "deleted", first_seen=d((16, 8)), last_seen=d((18, 8)),
                 name="g_d2", **common)
        self.add("phone", "Galaxy S21 128 GB z Niemiec", 950.37, first_seen=d((16, 8)), currency="EUR",
                 details_currency="EUR", description="Handy in gutem Zustand.", name="g_foreign", **common)
        self.add("phone", "Galaxy S21 128GB zbity ekran", 300.0, first_seen=d((16, 8)), for_parts=True,
                 name="g_parts", **common)

    def frauds(self):
        d = lambda day, hour=8: datetime(2026, 10, day, hour, tzinfo=UTC)  # noqa: E731
        key, parent, feats = "iphone 16 pro|512", "iphone 16 pro", dict(model="iphone 16 pro", storage_gb=512)
        common = dict(key=key, parent=parent, features=feats, brand="Apple", catalog_photo_suspicious=True,
                      description="Nowy, nieużywany, zafoliowany, gwarancja Apple 24 miesiące, wysyłka gratis.")
        dup = {"dup_title_price", "too_cheap"}
        self.add("phone", "iPhone 16 Pro 512 GB", 519.0, "blocked", first_seen=d(14), last_seen=d(15),
                 flags=dup | {"blocked"}, name="dup_blocked", **common)
        self.add("phone", "iPhone 16 Pro 512GB!", 519.0, "sold", first_seen=d(16), last_seen=d(17), flags=dup,
                 name="dup_sold", **common)
        self.add("phone", "iphone 16 pro 512 gb", 520.0, "deleted", first_seen=d(18), last_seen=d(19), flags=dup,
                 name="dup_deleted", **common)
        self.add("phone", "IPHONE 16 PRO 512 GB", 519.0, first_seen=d(21), flags=dup, name="dup_active", **common)
        # ogólnikowy tytuł po tej samej (niskiej) cenie u 3 ofert - tysiące niezależnych „iPhone 15” → bez flagi
        for i in range(3):
            self.add("phone", "iPhone 15", 300.0, first_seen=d(14 + i), brand="Apple", name=f"generic{i}")
        # oszust wystawia tę samą ofertę od nowa → to też relisty (blocked nie jest „zniknięciem” do relistu)
        self.truth.relists[self.truth.ids["dup_deleted"]] = self.truth.ids["dup_sold"]
        self.truth.relists[self.truth.ids["dup_active"]] = self.truth.ids["dup_deleted"]
        self.add("phone", "iPhone 15 Pro 256GB", 900.0, "sold", first_seen=d(15), last_seen=d(16),
                 key="iphone 15 pro|256", parent="iphone 15 pro", features=dict(model="iphone 15 pro", storage_gb=256),
                 description="Stan idealny. Sprzedaż wyłącznie przez OLX/Allegro, tutaj nie odpisuję.",
                 flags={"offsite"}, name="off_olx")
        t480 = dict(key="thinkpad t480|i5-8350u|integrated|16|256", parent="intel core i5|16", brand="Lenovo",
                    features=BULK["laptop"][0][4])
        self.add("laptop", "ThinkPad T480 okazja", 1150.0, first_seen=d(18), description="Pisz na WhatsApp, szybciej "
                 "odpowiadam.", flags={"offsite"}, name="off_whatsapp", **t480)
        self.add("laptop", "ThinkPad T480 stan bdb", 1180.0, first_seen=d(18), description="Dzwoń: 600 700 800",
                 flags={"offsite"}, name="off_phone", **t480)
        self.add("laptop", "ThinkPad T480 sprawny", 1210.0, first_seen=d(18),
                 description="Pytania: jan.kowalski@example.com", flags={"offsite"}, name="off_email", **t480)
        self.add("laptop", "ThinkPad T480 business", 1220.0, first_seen=d(18),
                 description="Write me on Telegram for details.", flags={"offsite"}, name="off_telegram", **t480)
        self.add("laptop", "ThinkPad T480 z fakturą", 1230.0, first_seen=d(18),
                 description="Kupiony na Allegro, mam fakturę i pudełko.", flags={"offsite_mention"},
                 name="mention_allegro", **t480)
        self.add("laptop", "ThinkPad T480 tanio", 300.0, first_seen=d(19), flags={"too_cheap"}, name="cheap", **t480)
        self.add("laptop", "ThinkPad T480 na części", 300.0, first_seen=d(19), for_parts=True, name="cheap_parts",
                 **t480)
        ram = dict(key="ddr4|so-dimm|16", parent="ddr4|16", brand="Kingston", features={})
        for i in range(3):
            self.add("ram", "Pamięć RAM DDR4 16GB SO-DIMM 3200MHz", 120.0, first_seen=d(13 + i),
                     flags={"shop_like"}, name=f"shop{i}", **ram)
        self.add("console", "PlayStation 5 Slim Digital", 1500.0, "blocked", first_seen=d(17), last_seen=d(18),
                 key="playstation 5|slim|?", parent="playstation 5|slim", brand="Sony", features={},
                 flags={"blocked"}, catalog_photo_suspicious=True, name="blocked_console")

    def relists(self):
        d = lambda day, hour=8: datetime(2026, 10, day, hour, tzinfo=UTC)  # noqa: E731
        t480 = dict(key="thinkpad t480|i5-8350u|integrated|16|256", parent="intel core i5|16", brand="Lenovo",
                    features=BULK["laptop"][0][4])
        desc1 = "Laptop w bardzo dobrym stanie, bateria 90%, ładowarka w zestawie. Wysyłka 24h."
        a = self.add("laptop", "Lenovo ThinkPad T480 i5-8350U 16GB 256GB FHD", 1250.0, "deleted", first_seen=d(14, 20),
                     created_at=d(14), last_seen=d(17), description=desc1, name="r1_old", **t480)
        b = self.add("laptop", "Lenovo ThinkPad T480 i5-8350U 16GB 256GB FHD", 1190.0, "sold", first_seen=d(18),
                     created_at=d(18), last_seen=d(21), description=desc1, name="r1_new", **t480)
        self.truth.relists[b] = a
        desc2 = "ThinkPad T480, ekran 14 cali FHD IPS, bateria trzyma 4h. Bez rys na klapie."
        a = self.add("laptop", "ThinkPad T480 14 cali i5 16 GB RAM 256 SSD", 1100.0, "deleted", first_seen=d(13),
                     last_seen=d(14, 20), description=desc2, name="r2_a", **t480)
        b = self.add("laptop", "ThinkPad T480 14 cali i5 16GB RAM 256 SSD", 1100.0, "deleted", first_seen=d(15, 8),
                     last_seen=d(19), description=desc2, name="r2_b", **t480)
        c = self.add("laptop", "ThinkPad T480 14 cali i5 16GB RAM 256GB SSD", 1050.0, first_seen=d(19, 20),
                     description=desc2 + " Cena do negocjacji.", name="r2_c", **t480)
        self.truth.relists[b] = a
        self.truth.relists[c] = b
        dell = dict(key="latitude 7490|i5-8350u|integrated|8|256", parent="intel core i5|8", brand="Dell",
                    features=dict(model="latitude 7490", cpu="i5-8350u", gpu="integrated", ram_gb=8, storage_gb=256))
        a = self.add("laptop", "Dell Latitude 7490 i5 8GB 256GB", 900.0, "deleted", first_seen=d(13), last_seen=d(20),
                     name="r3_old", **dell)
        b = self.add("laptop", "Dell Latitude 7490 i5 8GB 256GB", 900.0, first_seen=d(19, 20), name="r3_new", **dell)
        self.truth.relists[b] = a
        # podobne, ale NIE relisty
        hp = dict(brand="HP", key="elitebook 840 g5|i5-8250u|integrated|8|256", parent="intel core i5|8",
                  features=dict(model="elitebook 840 g5", cpu="i5-8250u", gpu="integrated", ram_gb=8, storage_gb=256))
        self.add("laptop", "HP EliteBook 840 G5 i5 8GB 256GB", 1000.0, "deleted", first_seen=d(13), last_seen=d(16),
                 name="n_price_old", **hp)
        self.add("laptop", "HP EliteBook 840 G5 i5 8GB 256GB", 1400.0, first_seen=d(17), name="n_price_new", **hp)
        self.add("laptop", "HP ProBook 450 G5 i5 8GB", 950.0, "deleted", first_seen=d(13), last_seen=d(20),
                 brand="HP", name="n_time_old")
        self.add("laptop", "HP ProBook 450 G5 i5 8GB", 950.0, first_seen=d(16), brand="HP", name="n_time_new")
        self.add("laptop", "Asus VivoBook 15 i3 8GB 256GB", 1000.0, "deleted", first_seen=d(13), last_seen=d(16),
                 brand="Asus", description="Sprzedam laptopa po córce, działa bez zarzutu, mało używany.",
                 name="n_desc_old")
        self.add("laptop", "Asus VivoBook 15 i3 8GB 256GB", 1000.0, first_seen=d(17), brand="Asus",
                 description="Nowy, nieotwierany, gwarancja producenta 24 miesiące, paragon.", name="n_desc_new")
        # bez opisu: tytuł ogólnikowy („Laptop Lenovo”) i tytuł konkretny, ale B dopiero 5 dni później - nie relisty
        self.add("laptop", "Laptop Lenovo", 800.0, "deleted", first_seen=d(13), last_seen=d(16), brand="Lenovo",
                 name="n_generic_old")
        self.add("laptop", "Laptop Lenovo", 800.0, first_seen=d(16, 20), brand="Lenovo", name="n_generic_new")
        self.add("laptop", "Lenovo IdeaPad 5 Ryzen 5 16GB 512GB", 2000.0, "deleted", first_seen=d(13),
                 last_seen=d(15), brand="Lenovo", name="n_gap_old")
        self.add("laptop", "Lenovo IdeaPad 5 Ryzen 5 16GB 512GB", 2000.0, first_seen=d(20), brand="Lenovo",
                 name="n_gap_new")
        self.add("laptop", "Laptop 15,6 i5 8GB 256GB", 1000.0, "deleted", first_seen=d(13), last_seen=d(16),
                 brand="Acer", name="n_brand_old")
        self.add("laptop", "Laptop 15,6 i5 8GB 256GB", 1000.0, first_seen=d(17), brand="Asus", name="n_brand_new")

    def crawl_runs(self):
        for category in ("laptop", "phone", "console", "tablet", "gpu", "ram", "storage"):
            for ts in run_times(category):
                self.conn.execute("INSERT INTO crawl_runs (started_at, finished_at, kind, catalog_id) "
                                  "VALUES (?, ?, 'crawl', ?)",
                                  (iso(ts), iso(ts + timedelta(hours=RUN_HOURS)), CATALOG[category]))


def build(path, seed=7):
    """Buduje atrapę w `path` (plik SQLite) i zwraca Truth."""
    conn = db.connect(path)
    b = Builder(conn, seed)
    with conn:
        b.crawl_runs()
        b.bulk()
        b.galaxy()
        b.frauds()
        b.relists()
    conn.close()
    return b.truth
