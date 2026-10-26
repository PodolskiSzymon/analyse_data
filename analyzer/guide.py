"""Wytyczne dla Snipera generowane z danych rynku (PLAN_ANALIZY.md, D1 + D4):
`python -m analyzer sniper-guide [--promo 26] [--ship 20] [--min-offers 8]` → `reports/<data>/guides/<kategoria>.md`.

Bez sieci, główna baza tylko do odczytu; flagi, relisty i stan z AI z `analysis.db` (najpierw `report`).

Reguła zysku użytkownika (2026-10-26, zmiana z 2026-10-25): zysk = cena sprzedaży − koszt zakupu − koszty (Podbicie
międzynarodowe 7 dni ~26 zł + wysyłka ~20 zł), marża = zysk / cena sprzedaży; zysk ZAWSZE ≥ 300 zł („zysk < 300 zł to
za mało”), a przy niższej marży rośnie: ≥ 40% → 300 zł, 35% → 400, 30% → 500 (+20 zł na punkt), marża < 30% → nie
kupujemy (2026-10-26 po ofercie S25 z marżą 19%: „dla sprzętu powyżej 1000 zł marża min. 30%” - poniżej 1000 zł
zysk ≥ 300 zł i tak wymusza ≥ 30%). (Wcześniej: dopuszczalne 20–30% marży; 30% → 700 zł +40 zł/pkt; wyjątek 150 zł.)

Grupy (tylko sprawne - stan z AI, inaczej z reguł; bez flag wykluczających i ofert z relistem):
laptopy - karta graficzna (gamingowe), MacBooki - linia + chip + RAM, reszta - linia CPU + RAM; telefony / tablety -
model + pamięć; konsole - platforma + wariant; karty graficzne - układ + VRAM; RAM - typ + rodzaj + pojemność;
dyski - typ + pojemność.

Cena szybkiej sprzedaży S (≤ 7 dni, kupujący porównujący ceny) - wersja 1, dopóki `watch` z szybkim resolverem nie
zbierze cen sprzedaży: mediana OSTATNIEJ ceny ofert, które zniknęły (sprzedane + blocked + usunięte; ≥ 10 sztuk -
usunięte w części to sprzedaże, ich cena ≈ cenie sprzedanych), a przy mniejszej liczbie - środek między p25 a medianą
cen aktywnych - WYŻSZA z tych dwóch wartości (2026-10-25: sama mediana zniknięć zaniżała - część to wycofane / tańsze
oferty; sprzedaże użytkownika: MSI RTX 4060 3 650 zł w 5 dni przy medianie zniknięć 3 358 i środku p25–med ~3 600,
Scar RTX 3080 4 700 zł przy 4 496). Kupujący „nieświadomy” - p75 aktywnych (górna granica).
"""
import json
import math
import re

from . import analysis

STATES = ("active", "reserved", "sold", "blocked", "deleted", "closed")
GONE = ("sold", "blocked", "deleted", "closed")
MIN_GONE_FOR_S = 10
PROMO, SHIP = 26.0, 20.0
CAT_TITLE = {"laptop": "Laptopy", "phone": "Telefony", "tablet": "Tablety", "console": "Konsole",
             "gpu": "Karty graficzne", "ram": "Pamięci RAM", "storage": "Dyski SSD"}
MIN_PROFIT, PROFIT_PER_POINT = 300.0, 20.0  # zysk ≥ 300 zł; +20 zł za każdy punkt marży poniżej 40%
MIN_MARGIN = 0.30                            # marża poniżej 30% - nigdy
MIXED_BELOW = 0.10                 # > 10% aktywnych ofert już ≤ max zakup → grupa mieszana, cena sprzedaży niepewna
TOP_ROWS = 80                      # wierszy tabeli na kategorię (koszt tokenów w zapytaniu Snipera)
# Katalogi Vinted Snipera → nasze kategorie (jak sniper/categories.py; mieszane - kategoria z tytułu).
SNIPER_CATALOGS = {3580: ("laptop",), 3661: ("phone",), 3728: ("tablet",), 3025: ("console",),
                   3582: ("gpu", "storage", "ram"), 3583: ("storage",), 3584: ("ram", "storage", "gpu")}
SNIPER_WEIGHTS = {3580: 3}         # laptopy skanowane 3× częściej (największe zyski, najszybciej znikają)
PRICE_TO_HEADROOM = 1.15           # do „Zaproponuj cenę”: oferta trochę powyżej max zakupu też warta oceny


# ---------------------------------------------------------------------------------------------- reguła zysku


def min_profit(margin):
    """Minimalny zysk (zł) przy danej marży; None = za niska marża (< 30%)."""
    if margin < MIN_MARGIN - 1e-9:
        return None
    return MIN_PROFIT if margin >= 0.40 else MIN_PROFIT + PROFIT_PER_POINT * 100 * (0.40 - margin)


def max_buy(sale, costs=PROMO + SHIP):
    """Najwyższa cena zakupu, przy której flip spełnia regułę (zysk ≥ min_profit(marża)) → (cena, zysk, marża) albo
    None, gdy przy tej cenie sprzedaży żaden zakup się nie opłaca.

    Najmniejszy dopuszczalny zysk P*: w przedziale marży 30–40% warunek P ≥ 300 + 2000·(0,4 − P/S) daje
    P ≥ 1100·S / (S + 2000) (i zawsze ≥ 300 zł, ≥ 30% S); przy marży ≥ 40% wystarcza P ≥ max(0,4·S, 300)."""
    if not sale or sale <= 0:
        return None
    k = PROFIT_PER_POINT * 100
    candidates = [max(0.4 * sale, MIN_PROFIT)]
    p2 = max(MIN_MARGIN * sale, MIN_PROFIT, (MIN_PROFIT + 0.4 * k) * sale / (sale + k))
    if p2 < 0.4 * sale:
        candidates.append(p2)
    profit = min(candidates)
    buy = sale - costs - profit
    if buy <= 0:
        return None
    return buy, profit, profit / sale


# ---------------------------------------------------------------------------------------------- grupy


def _gb(value):
    return f"{value} GB" if value not in (None, "", "?") else None


def _gpu_name(text):
    return text.upper().replace(" TI", " Ti").replace(" SUPER", " Super")


def cpu_generation(cpu):
    """Przedział generacji procesora z modelu (do grup laptopów ze zintegrowaną grafiką) albo None.
    i5-8350u → „8–9 gen.”, i5-1240p → „12+ gen.”, ryzen 5 5500u → „4000–5000”. Ten sam „i5 · 16 GB” z 2013 i z 2022 r.
    to zupełnie inne ceny (2026-10-25: grupy bez generacji miały 12–14% ofert poniżej max zakupu = cena zawyżona)."""
    cpu = (cpu or "").lower()
    m = re.match(r"i[3579]-(\d{3,5})", cpu)
    if m:
        d = m.group(1)
        gen = int(d[:2]) if len(d) == 5 or (len(d) == 4 and d[0] == "1") else int(d[0]) if len(d) == 4 else 1
        return "do 7 gen." if gen <= 7 else "8–9 gen." if gen <= 9 else "10–11 gen." if gen <= 11 else "12+ gen."
    m = re.match(r"ryzen [3579] (?:pro )?(\d)\d{3}", cpu)
    if m:
        series = int(m.group(1))
        return "1000–3000" if series <= 3 else "4000–5000" if series <= 5 else "6000+"
    return None


def group_key(category, r):
    """Nazwa grupy cenowej oferty (czytelna dla człowieka i modelu AI) albo None."""
    key = r["config_key"]
    parts = key.split("|") if key else []
    if category == "laptop":
        model = (r["model"] or "").lower()
        cpu = (r["cpu"] or "").lower()
        if "macbook" in model or cpu.startswith("apple"):
            line = "MacBook Pro" if "pro" in model else "MacBook Air" if "air" in model else "MacBook"
            chip = re.search(r"apple (m\d(?: (?:pro|max|ultra))?)", cpu)
            if not chip:
                return None
            return " ".join(x for x in (line, chip.group(1).upper().replace(" PRO", " Pro").replace(" MAX", " Max"),
                                         _gb(r["ram_gb"]) and f"{r['ram_gb']} GB RAM") if x)
        gpu = (r["gpu"] or "").lower()
        if re.match(r"(rtx|gtx|rx|arc|quadro)\b", gpu):
            return _gpu_name(gpu)
        line = analysis.cpu_line_of(r["cpu"], r["cpu_line"])
        gen = cpu_generation(r["cpu"])
        # bez generacji (sam „i5” w tytule) grupa miesza laptopy sprzed 10 lat z nowymi - pomijamy
        if line and gen and r["ram_gb"] and r["ram_gb"] >= 2:          # „1 GB RAM” = błąd odczytu
            return f"{line} {gen} · {r['ram_gb']} GB RAM (zintegrowana grafika)"
        return None
    if category in ("phone", "tablet"):
        if not parts:
            return None
        return f"{parts[0]} {parts[1]} GB" if len(parts) > 1 and parts[1] != "?" else None
    if category == "console":
        if len(parts) < 2:
            return None
        platform, variant = parts[0], parts[1]
        if variant == "?" or variant.lower() in platform.lower() or variant.isdigit():
            # „Xbox 360 360” → „Xbox 360”; sama liczba to śmieć z tytułu („PS4 + 2 pady” → „PlayStation 4 2”,
            # 2026-10-26: Sniper dopasowywał do niej każde „PS4 … 2xpad” z progiem 239 zł)
            return platform
        last = platform.split()[-1].lower()
        if variant.lower().startswith(last) and len(variant) > len(last):
            variant = variant[len(last):].upper() if len(variant) - len(last) <= 2 else variant[len(last):]
        return f"{platform} {variant}"                           # „Xbox One ones” → „Xbox One S”
    if category == "gpu":
        if len(parts) < 2 or parts[1] == "?":
            return None
        return f"{_gpu_name(parts[0])} {parts[1]} GB"
    if category == "ram":
        if len(parts) < 3 or parts[0] == "?":
            return None
        form = {"so-dimm": "SO-DIMM (laptop)", "dimm": "DIMM (PC)"}.get(parts[1], "")
        return " ".join(x for x in (parts[0].upper(), form, f"{parts[2]} GB") if x)
    if category == "storage":
        if len(parts) < 2 or parts[0] == "?":
            return None
        kind = {"nvme": "NVMe", "sata_ssd": "SATA SSD"}.get(parts[0], parts[0])
        size = int(parts[1]) if parts[1].isdigit() else None
        return f"{kind} {size // 1000} TB" if size and size >= 1000 else f"{kind} {parts[1]} GB"
    return None


def collect(conn, excluded=None, relists=None, ai_damaged=None, progress=None):
    """{kategoria: {grupa: {"active": [ceny], "active_pl": [...], "active_zagr": [...], "gone": [...],
    "sold": [...]}}} - tylko sprawne, bez wykluczonych i ofert z relistem."""
    say = progress or (lambda _t: None)
    excluded, relists, ai_damaged = excluded or {}, relists or {}, ai_damaged or {}
    old_ids = set(relists.values())
    sql = f"""SELECT l.id, l.state, l.price_now, l.sold_price, COALESCE(d.seller_currency, l.seller_currency) AS cur,
                     f.config_key, f.model, f.cpu, f.cpu_line, f.ram_gb, f.gpu,
                     COALESCE(f.for_parts, 0) OR COALESCE(f.locked, 0) OR COALESCE(f.cracked, 0) AS damaged
              FROM listings l LEFT JOIN features f ON f.listing_id = l.id LEFT JOIN details d ON d.listing_id = l.id
              WHERE l.category = ? AND l.state IN ({",".join("?" * len(STATES))})"""
    out = {}
    for category in analysis.CATEGORIES:
        say(f"  {category}...")
        groups = out.setdefault(category, {})
        for r in conn.execute(sql, (category, *STATES)):
            if r["id"] in excluded or r["id"] in old_ids:
                continue
            if ai_damaged.get(r["id"], bool(r["damaged"])):
                continue
            name = group_key(category, r)
            if not name:
                continue
            g = groups.setdefault(name, {"active": [], "active_pl": [], "active_zagr": [], "gone": [], "sold": []})
            if r["state"] in ("active", "reserved"):
                if r["price_now"] is None:
                    continue
                g["active"].append(r["price_now"])
                g["active_pl" if analysis.market(r["cur"], r["price_now"]) == "PL" else "active_zagr"].append(
                    r["price_now"])
            else:
                price = r["sold_price"] if r["sold_price"] is not None else r["price_now"]
                if price is None:
                    continue
                g["gone"].append(price)
                if r["state"] in ("sold", "blocked"):
                    g["sold"].append(price)
    return out


def rows(groups, min_offers=8, costs=PROMO + SHIP):
    """Wiersze tabeli: [grupa, n aktywnych, p25, mediana, p75, PL med, zagr med, zniknęło, sprzedanych, S, źródło S,
    max zakup, zysk, marża, % aktywnych poniżej max zakupu] - grupy z ≥ min_offers aktywnymi, od najliczniejszych."""
    pct = analysis.percentile
    out = []
    for name, g in groups.items():
        a = sorted(g["active"])
        if len(a) < min_offers:
            continue
        p25, med, p75 = pct(a, .25), pct(a, .5), pct(a, .75)
        mid = (p25 + med) / 2
        gone_med = analysis.median(g["gone"]) if len(g["gone"]) >= MIN_GONE_FOR_S else None
        if gone_med is not None and gone_med > mid:
            sale, src = gone_med, f"zniknięte (n={len(g['gone'])})"
        else:
            sale, src = mid, "oferty p25–med"
        deal = max_buy(sale, costs)
        below = sum(1 for x in a if deal and x <= deal[0]) / len(a) if deal else 0.0
        out.append({"name": name, "n": len(a), "p25": p25, "med": med, "p75": p75,
                    "pl": analysis.median(g["active_pl"]), "zagr": analysis.median(g["active_zagr"]),
                    "gone": len(g["gone"]), "sold": len(g["sold"]), "sale": sale, "src": src,
                    "buy": deal[0] if deal else None, "profit": deal[1] if deal else None,
                    "margin": deal[2] if deal else None, "below": below})
    out.sort(key=lambda x: (-x["n"], x["name"]))
    return out


# ---------------------------------------------------------------------------------------------- pliki


def _zl(v):
    return "-" if v is None else f"{v:,.0f}".replace(",", " ")


def header(category, costs, day, ai_count):
    profit_table = " · ".join(f"{m}% → {_zl(min_profit(m / 100))} zł" for m in (40, 35, 30))
    return [
        f"# {CAT_TITLE[category]} – wytyczne oceny okazji (z danych rynku, {day})", "",
        "## Strategia kupującego",
        "- Kupuję pod odsprzedaż na Vinted; sprzedaż w **≤ 7 dni** z Podbiciem międzynarodowym 7 dni (nie mrożę "
        "gotówki). Kupujący z całej UE (Vinted pokazuje ceny w zł).",
        f"- Koszty jednej transakcji: Podbicie ~{PROMO:.0f} zł + wysyłka ~{SHIP:.0f} zł (PL ~15, z daleka do 50) = "
        f"**{costs:.0f} zł**. Opłatę Vinted (5% + 2,90 zł) i weryfikację elektroniki płaci kupujący.",
        "- **Zysk** = cena sprzedaży − cena zakupu − koszty; **marża** = zysk / cena sprzedaży.",
        f"- Minimalny zysk zależy od marży: {profit_table}; marża < 30% – nie kupuję (także przy drogim sprzęcie).",
        f"- Zysk nigdy poniżej {_zl(MIN_PROFIT)} zł – mniejszy zysk nie jest wart zachodu.",
        "- Sprzedawca z Polski: paczka dochodzi w 1–2 dni zamiast ~5–10 z zagranicy – krócej mrożę gotówkę, szybciej "
        "obracam kapitałem. Program sam dodaje +1 do oceny okazji z Polski – oceniaj bez tej premii; w "
        "sell_days_estimate licz dni od zakupu do sprzedaży (z zagranicy dolicz dłuższą dostawę).",
        "- Nie kupuję uszkodzonych (na części, blokada, zbity ekran, nie działa) – wtedy nigdy okazja.",
        "- Przykłady (laptopy): ASUS TUF F15 1 350 → 2 375 zł w 2 dni (43%); MSI RTX 4060 2 500 → 3 650 zł w 5 dni "
        "(32%); ASUS ROG Scar 17 RTX 3080 3 660 → 4 700 zł w 6 dni (22%).", "",
        "## Jak oceniać ofertę",
        "1. Dopasuj ofertę do wiersza tabeli (model / karta graficzna / pamięć). Brak pasującego wiersza → oceniaj "
        "ostrożnie, uzasadnij cenę sprzedaży.",
        "2. Stan: tabela dotyczy sprawnych. Na części / blokada iCloud / zbity ekran → zwykle nie okazja (uszkodzone "
        "schodzą ~25–35% taniej i wolniej). Drobna usterka obniża cenę sprzedaży – uwzględnij ją.",
        "3. **Cena sprzedaży** = kolumna „sprzedam za ~” (szybko, ≤ 7 dni, kupujący porównujący ceny). "
        "Mocniejsza konfiguracja w grupie (więcej RAM / dysku, lepszy CPU, gwarancja, komplet) → bliżej p75; słabsza "
        "→ bliżej p25. p75 = górna granica (kupujący nieświadomy).",
        "4. Okazja, gdy cena oferty (z wysyłką) ≤ „max zakup” – albo gdy własne wyliczenie zysku i marży spełnia "
        "regułę wyżej. Podaj: szacowaną cenę sprzedaży, zysk, marżę i dni do sprzedaży.",
        f"5. ⚠ przy grupie = ponad {MIXED_BELOW * 100:.0f}% wystawionych ofert już kosztuje ≤ max zakup – grupa miesza "
        "tańsze i droższe wersje (generacja, wariant, zestaw), więc „sprzedam za ~” jest niepewne. Tam okazja tylko, "
        "gdy TA konkretna wersja jest wyraźnie tańsza niż podobne oferty (bliżej p25 niż mediany) – inaczej score ≤ 6.",
        "6. Uwaga na oszustwa: cena ≪ p25, „tylko OLX / WhatsApp / przelew”, nowe konto, ten sam tytuł i cena w wielu "
        "ofertach.", "",
        "## Skąd liczby",
        f"Oferty z Vinted (PL + zagranica) zebrane przez analizator; tylko sprawne (stan z AI dla {ai_count} ofert, "
        "reszta z reguł), bez podejrzanych i ponownych wystawień. „Sprzedam za ~” = mediana ostatniej ceny ofert, które "
        f"zniknęły (≥ {MIN_GONE_FOR_S}; część to usunięcia, nie sprzedaże), a przy mniejszej liczbie środek p25–mediana "
        "ofert. To ceny WYSTAWIENIA (z „Zaproponuj cenę” kupujący płaci czasem mniej). „% ofert ≤ max” = jak często "
        "trafia się okazja.", ""]


def practical(r):
    """Wiersz wart pokazania Sniperowi: okazja w ogóle możliwa (max zakup ≥ 40% p25 - inaczej trzeba by kupić za
    ułamek ceny rynkowej, czego nikt nie oferuje)."""
    return bool(r["buy"]) and r["buy"] >= 0.4 * r["p25"]


def table(rows_):
    shown = [r for r in rows_ if practical(r)]
    hidden = [r["name"] for r in rows_ if not practical(r)]
    lines = ["| grupa | ofert | p25 | mediana | p75 | PL / zagr. mediana | zniknęło (sprzed.) | sprzedam za ~ | "
             "max zakup | zysk / marża | % ofert ≤ max |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in shown[:TOP_ROWS]:
        mixed = " ⚠" if r["below"] > MIXED_BELOW else ""
        deal = f"{_zl(r['profit'])} / {r['margin'] * 100:.0f}%"
        lines.append(f"| {r['name']}{mixed} | {r['n']} | {_zl(r['p25'])} | {_zl(r['med'])} | {_zl(r['p75'])} | "
                     f"{_zl(r['pl'])} / {_zl(r['zagr'])} | {r['gone']} ({r['sold']}) | {_zl(r['sale'])} | "
                     f"{_zl(r['buy'])} | {deal} | {r['below'] * 100:.0f}% |")
    if hidden:
        lines += ["", f"Praktycznie nieopłacalne przy minimalnym zysku 300 zł (max zakup < 40% p25 albo brak) – "
                      f"{len(hidden)} grup: " + ", ".join(hidden[:60]) + ("…" if len(hidden) > 60 else "")]
    return lines


def build(conn, aconn, out, promo=PROMO, ship=SHIP, min_offers=8, progress=None):
    """Pliki wytycznych → {kategoria: (ścieżka, liczba wierszy)}."""
    from .ai_condition import load_damaged
    from .relist import load as load_relists
    from .suspicious import EXCLUDING, load as load_flags

    excluded = load_flags(aconn, tuple(f for f in EXCLUDING if f != "is_suspicious"))
    ai = load_damaged(aconn)
    data = collect(conn, excluded, load_relists(aconn), ai, progress)
    costs = promo + ship
    out.mkdir(parents=True, exist_ok=True)
    day = out.parent.name
    result = {}
    for category, groups in data.items():
        rows_ = rows(groups, min_offers, costs)
        if not rows_:
            continue
        n_shown = sum(1 for r in rows_ if practical(r))
        lines = header(category, costs, day, len(ai)) + [
            f"## Ceny ({len(rows_)} grup z ≥ {min_offers} ofertami, z szansą na okazję {n_shown}; pokazane "
            f"{min(n_shown, TOP_ROWS)} najliczniejszych)", ""]
        lines += table(rows_)
        path = out / f"{category}.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result[category] = (path, rows_)
    write_catalogs(result, out)
    return result


def catalogs(result):
    """Zakresy cen katalogów dla Snipera (SNIPER_CATALOGS=auto): od = 60% najniższego „max zakup” wśród grup
    z realną okazją (zaokrąglone w dół do 50), do = najwyższy „max zakup” × 1,15 (w górę do 100). Katalog bez
    opłacalnych grup jest pomijany (Sniper go nie skanuje)."""
    out = []
    for catalog_id, cats in SNIPER_CATALOGS.items():
        buys = [r["buy"] for c in cats if c in result for r in result[c][1] if practical(r)]
        if not buys:
            continue
        out.append({"catalog_id": catalog_id, "categories": [c for c in cats if c in result],
                    "price_from": max(50, int(math.floor(0.6 * min(buys) / 50) * 50)),
                    "price_to": int(math.ceil(max(buys) * PRICE_TO_HEADROOM / 100) * 100),
                    "weight": SNIPER_WEIGHTS.get(catalog_id, 1)})
    return out


def write_catalogs(result, out):
    """<out>/catalogs.json → ścieżka (None, gdy żaden katalog nie ma opłacalnych grup)."""
    rows_ = catalogs(result)
    if not rows_:
        return None
    path = out / "catalogs.json"
    path.write_text(json.dumps({"generated": out.parent.name, "catalogs": rows_}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def catalogs_line(result):
    """Ta sama lista w formacie SNIPER_CATALOGS (do ręcznego wpisania w sniper/.env)."""
    return ",".join(f"{c['catalog_id']}:{c['price_from']}-{c['price_to']}" + (f"*{c['weight']}" if c["weight"] > 1
                                                                              else "") for c in catalogs(result))


def summary_lines(result, per_category=8):
    """Krótki podgląd do terminala: najliczniejsze grupy z ceną sprzedaży i max zakupu."""
    lines = []
    for category, (path, rows_) in result.items():
        deals = [r for r in rows_ if practical(r)]
        lines += ["", f"{CAT_TITLE[category]}: {len(rows_)} grup, opłacalnych wg reguły {len(deals)} → {path.name}",
                  f"  {'grupa':<44} {'ofert':>6} {'sprzedam':>9} {'max zakup':>10} {'zysk':>6} {'marża':>6} "
                  f"{'%≤max':>6}"]
        for r in (deals or rows_)[:per_category]:
            margin = f"{r['margin'] * 100:.0f}%" if r["margin"] else "-"
            lines.append(f"  {r['name'][:44]:<44} {r['n']:>6} {_zl(r['sale']):>9} {_zl(r['buy']):>10} "
                         f"{_zl(r['profit']):>6} {margin:>6} {r['below'] * 100:>5.0f}%")
    return lines
