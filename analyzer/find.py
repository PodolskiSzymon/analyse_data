"""Najtańsze AKTYWNE oferty z bazy (bez sieci): `python -m analyzer szukaj ram ddr4 dimm 16 --max 200`.

Prośba użytkownika 2026-10-25: części do stanowiska testowego (RAM DDR4 do PC) taniej niż przy ręcznym szukaniu.
Słowa muszą wystąpić w kluczu konfiguracji (np. `ddr4|dimm|16`) albo w tytule; liczby tylko w całości (16 ≠ 160).
RAM: forma (PC / laptop) także z kodu na naklejce w opisie - PC4-2400T-**U**A2 = DIMM, PC4-3200AA-**S**A1 = SO-DIMM;
słowo `dimm` = do PC (i nieznana forma, oznaczona „?”), `sodimm` = do laptopa.
Bez flag wykluczających (oszustwa itp.) i uszkodzonych (AI / reguły). Baza zna stan z ostatniego przejścia - oferta
mogła już zniknąć, link sprawdź. RODO: bez danych sprzedawcy.
"""
import re

from . import analysis

URL = "https://www.vinted.pl/items/{id}"
# PC4-2400T-UA2 / PC4-3200AA-SA1 (DDR4/5: litera po myślniku), PC3L-12800U / PC3-10600S (DDR3: zaraz po cyfrach)
_PC_CODE = re.compile(r"\bpc([345])l?-\d{4,5}(?:[a-z]{0,2}-([us])|([us]))", re.I)
_LAPTOP = re.compile(r"\bso-?dimm|sodimm|laptop\w*|notebook\w*|\bsod\b", re.I)
_DESKTOP = re.compile(r"\b(?:u-?)?dimm\b|desktop|stacjonar\w*|\bpc\b(?!\d)", re.I)


def ram_form(title, description=""):
    """'dimm' / 'so-dimm' / None z tytułu i opisu (kod z naklejki ma pierwszeństwo)."""
    text = f"{title or ''}\n{description or ''}"
    match = _PC_CODE.search(text)
    if match:
        return "dimm" if (match.group(2) or match.group(3)).lower() == "u" else "so-dimm"
    if _LAPTOP.search(text):
        return "so-dimm"
    return "dimm" if _DESKTOP.search(text) else None


def ram_type(title, description=""):
    """ddr3 / ddr4 / ddr5 z kodu naklejki (PC3L-12800 = DDR3, choć tytuł mówi „DDR4”) albo None."""
    match = _PC_CODE.search(f"{title or ''}\n{description or ''}")
    return f"ddr{match.group(1)}" if match else None


def _matches(word, key_parts, title):
    if word.isdigit():
        return word in key_parts or re.search(rf"(?<!\d){word}(?!\d)", title) is not None
    return any(word in part for part in key_parts) or word in title


def search(conn, aconn, category, words, max_price=None, limit=25, progress=None):
    """→ (lista ofert od najtańszej, mediana ceny tych samych dopasowań)."""
    from .ai_condition import load_damaged
    from .suspicious import EXCLUDING, load as load_flags

    words = [w.lower() for w in words]
    form_want = None
    if category == "ram":
        if any(w in ("sodimm", "so-dimm", "laptop") for w in words):
            form_want = "so-dimm"
        elif "dimm" in words or "pc" in words:
            form_want = "dimm"
        words = [w for w in words if w not in ("sodimm", "so-dimm", "laptop", "dimm", "pc")]
    excluded = load_flags(aconn, tuple(f for f in EXCLUDING if f != "is_suspicious"))
    ai = load_damaged(aconn)
    sql = """SELECT l.id, l.title, l.price_now, l.total_now, f.config_key, d.description,
                    COALESCE(d.seller_currency, l.seller_currency) AS cur,
                    COALESCE(f.for_parts, 0) OR COALESCE(f.locked, 0) OR COALESCE(f.cracked, 0) AS damaged
             FROM listings l JOIN features f ON f.listing_id = l.id LEFT JOIN details d ON d.listing_id = l.id
             WHERE f.category = ? AND l.state = 'active' AND l.price_now IS NOT NULL"""
    args = [category]
    if max_price is not None:
        sql += " AND l.price_now <= ?"
        args.append(max_price)
    found, prices = [], []
    for r in conn.execute(sql, args):
        if r["id"] in excluded or ai.get(r["id"], bool(r["damaged"])):
            continue
        title = (r["title"] or "").lower()
        key_parts = (r["config_key"] or "").lower().split("|")
        form = None
        if category == "ram":
            real = ram_type(r["title"], r["description"])
            if real and real != (key_parts[0] if key_parts else None):
                key_parts = [real] + key_parts[1:]           # naklejka mówi prawdę (DDR3 opisana jako DDR4)
            form = ram_form(r["title"], r["description"])
            if form_want == "so-dimm" and form != "so-dimm":
                continue
            if form_want == "dimm" and form == "so-dimm":
                continue
        if not all(_matches(w, key_parts, title) for w in words):
            continue
        prices.append(r["price_now"])
        found.append({"id": r["id"], "title": r["title"], "price": r["price_now"], "total": r["total_now"],
                      "key": r["config_key"], "market": analysis.market(r["cur"], r["price_now"]), "form": form,
                      "url": URL.format(id=r["id"])})
    found.sort(key=lambda x: x["price"])
    return found[:limit], (analysis.median(prices) if prices else None), len(found)


def lines(found, med, total, category):
    if not found:
        return ["Brak aktywnych ofert dla tych słów (spróbuj mniej słów albo bez --max)."]
    out = [f"Pasujących aktywnych ofert: {total}, mediana ceny {med:.0f} zł - najtańsze:"]
    for x in found:
        form = ""
        if category == "ram":
            form = {"dimm": "PC ", "so-dimm": "laptop "}.get(x["form"], "PC? ")
        out.append(f"  {x['price']:>6.0f} zł | {form}{x['key'] or '?'} | {x['market'] or '?':4} | "
                   f"{(x['title'] or '')[:48]:<48} | {x['url']}")
    if category == "ram":
        out.append("„PC?” = forma nieznana z tytułu i opisu - przed zakupem sprawdź naklejkę: PC4-…-U = do PC, "
                   "PC4-…-S = do laptopa, PC3 = DDR3.")
    out.append("Stan z ostatniego przejścia watch - część ofert mogła już zniknąć. Cena bez wysyłki i opłaty Vinted.")
    return out
