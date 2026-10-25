"""Stan techniczny oferty przez AI: sprawna / drobna usterka / na części, zbity ekran, blokada - z opisu i zdjęć.

Prośba użytkownika 2026-10-25: reguły (`extract.FOR_PARTS` + zaprzeczenia) mylą się przy „bez defektów”, zaprzeczeniu
kilka słów dalej, opisach w obcych językach; AI czyta sens całego opisu i widzi zdjęcie.

* Kandydaci (`--scope`, po przecinku):
    - `flagged` (domyślnie) - reguły uznały ofertę za uszkodzoną ALBO tekst w ogóle wspomina usterkę (także
      zaprzeczoną: „bez defektów”) - tam reguły są niepewne,
    - `sold`    - sprzedane, blocked i usunięte z opisem (dane o rynku),
    - `all`     - wszystkie oferty z opisem (drogo - najpierw `--estimate`).
  Tylko nasze kategorie i stany rynkowe; oferty bez opisu pomijamy (sam tytuł + zdjęcie rzadko rozstrzyga).
* Zdjęcia jako URL - z zapisanych szczegółów `sidebar` (bez nich samo główne z katalogu); w CLI domyślnie 3
  (próba 2026-10-25: ~1 090 tokenów / zdjęcie, śr. 6,6 zdjęcia na ofertę), `--photos 0` = sam tekst. Zdjęcia,
  których Vinted już nie udostępnia (usunięta oferta → dostawca AI: 404 „Cannot fetch content”), nie psują oceny:
  ta sama oferta idzie od razu ponownie samym tekstem. Zdjęcia pobiera dostawca AI - nie nasze proxy, zero ruchu do
  Vinted (sprawdzanie /services przed wysłaniem kosztowałoby proxy i i tak nie gwarantuje zdjęć). Pobiera je
  dostawca AI, nie nasze proxy. Dostawca i klucz jak w Sniperze (SNIPER_AI_PROVIDER / SNIPER_AI_API_KEY), model
  ANALYZER_AI_MODEL (domyślnie tani: gemini-3.8-flash / claude-haiku-5-5).
* Główna baza tylko do odczytu; wynik i cache w `analysis.db: ai_condition` (klucz: tytuł + opis - ta
  sama treść nie idzie drugi raz, także przy innym `--photos`). Przerwane w połowie - wznowienie od miejsca przerwania.
* Przed wywołaniami: szacunek kosztu i pytanie o zgodę (`--yes` pomija pytanie, `--estimate` tylko liczy).
* `report` bierze stan z AI zamiast z reguł tam, gdzie AI odpowiedziało (uszkodzona = na części / zbity ekran /
  blokada).

`python -m analyzer ai-condition [--scope flagged] [--photos N] [--limit N] [--estimate] [--yes]`
"""
import asyncio
import hashlib
import json
import logging

from . import analysis, rawstore
from .extract import CRACKED, FOR_PARTS, LOCKED, norm

log = logging.getLogger("analyzer.ai")

CONDITIONS = ("working", "minor_issues", "for_parts", "unknown")
TRI = ("yes", "no", "unknown")
STATES = ("active", "reserved", "sold", "blocked", "deleted", "closed", "unlisted", "hidden")
SOLD_STATES = ("sold", "blocked", "deleted", "closed")
DESC_CHARS = 3000

SCHEMA = {
    "type": "object",
    "properties": {
        "condition": {"type": "string", "enum": list(CONDITIONS), "description": "Stan techniczny (instrukcja)."},
        "cracked_screen": {"type": "string", "enum": list(TRI), "description": "Pęknięty / zbity ekran lub szybka."},
        "locked": {"type": "string", "enum": list(TRI),
                   "description": "Blokada konta / aktywacji / BIOS / MDM uniemożliwiająca normalne użycie."},
        "photo_damage": {"type": "string", "enum": list(TRI), "description": "Czy NA ZDJĘCIU widać uszkodzenie."},
        "evidence": {"type": "string", "description": "Max 12 słów: cytat z opisu (w oryginale), który rozstrzyga."},
    },
    "required": ["condition", "cracked_screen", "locked", "photo_damage", "evidence"],
    "additionalProperties": False,
}

INSTRUCTION = """Oceniasz STAN TECHNICZNY przedmiotu z ogłoszenia Vinted (laptop, telefon, tablet, konsola, karta
graficzna, RAM, dysk). Opis bywa w dowolnym języku (polski, czeski, rumuński, węgierski, litewski, niemiecki…) i bywa
tłumaczony automatycznie. Czytaj SENS całego opisu: zaprzeczenia („bez defektów”, „nie ma żadnych uszkodzeń ani rys”,
„no defects”, „nie jest uszkodzony”) oznaczają brak usterki, także gdy zaprzeczenie stoi kilka słów przed usterką.
condition:
- working: działa w pełni; zwykłe ślady użytkowania, rysy, przetarcia, słabsza bateria zgodna z wiekiem to nadal working;
- minor_issues: działa, ale ma konkretną usterkę nieblokującą (np. martwy piksel, nie działa jeden klawisz / głośnik /
  kamera / port, bateria wymaga wymiany, pęknięta obudowa bez wpływu na działanie);
- for_parts: na części, do naprawy, nie włącza się, nie działa podstawowa funkcja, uszkodzona płyta / ekran
  uniemożliwia używanie, sprzedawany jako uszkodzony;
- unknown: opis i zdjęcie nie pozwalają ocenić.
cracked_screen / locked / photo_damage: yes / no / unknown (no tylko gdy to wynika z opisu lub zdjęcia).
Nie oceniaj ceny ani uczciwości sprzedawcy. Odpowiedz wyłącznie JSON-em według schematu."""

# Przybliżenia do szacunku kosztu PRZED wywołaniami (po próbie --limit 50 program poda rzeczywiste tokeny).
CHARS_PER_TOKEN = 3.5
INSTRUCTION_TOKENS = 450
IMAGE_TOKENS = 1100
OUTPUT_TOKENS = {"gemini": 120, "anthropic": 120}      # próba 50 ofert (gemini-3.8-flash): śr. 97 z „myśleniem”


def damaged(result):
    """Uszkodzona w sensie statystyk (osobna grupa `uszk`): na części, zbity ekran albo blokada."""
    return result["condition"] == "for_parts" or result["cracked_screen"] == "yes" or result["locked"] == "yes"


def parse_result(text):
    data = json.loads(text)
    out = {"condition": str(data.get("condition") or "").strip().lower()}
    if out["condition"] not in CONDITIONS:
        raise ValueError(f"nieznany stan: {out['condition']!r}")
    for name in ("cracked_screen", "locked", "photo_damage"):
        value = str(data.get(name) or "unknown").strip().lower()
        out[name] = value if value in TRI else "unknown"
    out["evidence"] = str(data.get("evidence") or "")[:200]
    return out


def mentions_fault(title, description):
    """Czy tekst w ogóle wspomina usterkę (także zaprzeczoną) - tam reguły bywają niepewne."""
    text = norm(f"{title or ''}\n{description or ''}")
    return bool(FOR_PARTS.search(text) or CRACKED.search(text) or LOCKED.search(text))


def content_key(title, description, photos=()):
    """Klucz pamięci wyników: tytuł + opis. Zdjęcia celowo poza kluczem - inne `--photos` nie wysyła ponownie
    ofert już ocenionych (`--again` wymusza)."""
    return hashlib.sha256("\x1f".join([title or "", description or ""]).encode()).hexdigest()


def photo_urls(conn, row, n=None):
    """Zdjęcia oferty: wszystkie z zapisanych szczegółów (sidebar), a bez nich główne z katalogu. n - najwyżej tyle
    (None = bez limitu, 0 = żadne)."""
    if n is not None and n <= 0:
        return []
    urls = [row["photo_url"]] if row["photo_url"] else []
    if n is None or n > len(urls):
        from sniper.extractor import extract_photo_urls, unwrap_sidebar

        raw = conn.execute("SELECT body FROM raw WHERE listing_id=? AND kind='sidebar' ORDER BY fetched_at DESC "
                           "LIMIT 1", (row["id"],)).fetchone()
        if raw is not None:
            try:
                more = extract_photo_urls(unwrap_sidebar(rawstore.decompress(raw[0])))
            except Exception:
                more = []
            if more:                          # w szczegółach pełne rozmiary - wtedy one zamiast miniatury
                urls = more
    return urls if n is None else urls[:n]


def prompt_text(row, description):
    attrs = {}
    try:
        attrs = json.loads(row["attributes_json"] or "{}")
    except ValueError:
        pass
    keep = {k: v for k, v in attrs.items() if k not in ("upload_date",)}
    lines = [f"Kategoria: {row['category']}", f"Tytuł: {row['title']}",
             f"Stan z formularza Vinted: {row['status_label'] or '-'}"]
    if keep:
        lines.append("Atrybuty: " + "; ".join(f"{k}: {v}" for k, v in list(keep.items())[:15]))
    lines.append("Opis:\n" + (description or "")[:DESC_CHARS])
    return "\n".join(lines)


def candidates(conn, aconn, scopes=("flagged",), limit=None, photos=None, again=False, progress=None):
    """Oferty do oceny (bez tych, które już mają wynik dla tej samej treści, chyba że again) →
    [(row, opis, zdjęcia, klucz)]. Kolejność: sprzedane / blocked, usunięte, reszta; nowsze najpierw."""
    say = progress or (lambda _t: None)
    done = {} if again else dict(aconn.execute("SELECT listing_id, content_key FROM ai_condition").fetchall())
    states = SOLD_STATES if set(scopes) == {"sold"} else STATES
    sql = f"""SELECT l.id, l.category, l.title, l.status_label, l.state, l.photo_url, l.price_now,
                     d.description, d.attributes_json,
                     COALESCE(f.for_parts, 0) OR COALESCE(f.cracked, 0) OR COALESCE(f.locked, 0) AS rule_damaged
              FROM listings l JOIN details d ON d.listing_id = l.id
              LEFT JOIN features f ON f.listing_id = l.id
              WHERE l.category IN ({",".join("?" * len(analysis.CATEGORIES))})
                AND l.state IN ({",".join("?" * len(states))})
                AND d.description IS NOT NULL AND length(d.description) >= 15"""
    picked = []
    for n, row in enumerate(conn.execute(sql, (*analysis.CATEGORIES, *states)), 1):
        if n % 50000 == 0:
            say(f"  przeglądam opisy: {n}...")
        ok = "all" in scopes or ("sold" in scopes and row["state"] in SOLD_STATES)
        if not ok and "flagged" in scopes:
            ok = bool(row["rule_damaged"]) or mentions_fault(row["title"], row["description"])
        if ok:
            picked.append(row)
    order = {"sold": 0, "blocked": 0, "deleted": 1, "closed": 1}
    picked.sort(key=lambda r: (order.get(r["state"], 2), -r["id"]))
    out = []
    for row in picked:
        urls = photo_urls(conn, row, photos)
        key = content_key(row["title"], row["description"], urls)
        if done.get(row["id"]) == key:
            continue
        out.append((row, row["description"], urls, key))
        if limit and len(out) >= limit:
            break
    return out


def prices(ai_cfg, model):
    from sniper.config import MODEL_PRICES

    if ai_cfg.price_in is not None and ai_cfg.price_out is not None:
        return ai_cfg.price_in, ai_cfg.price_out
    return MODEL_PRICES.get(model)


def estimate(items, provider, price):
    """Szacunek tokenów i kosztu (USD) dla listy kandydatów: z wybranymi zdjęciami (rzeczywista liczba zdjęć każdej
    oferty) oraz dla porównania sam tekst."""
    n = len(items)
    text_tokens = sum(len(prompt_text(row, desc)) for row, desc, _u, _k in items) / CHARS_PER_TOKEN
    n_photos = sum(len(urls) for _r, _d, urls, _k in items)
    out_tokens = OUTPUT_TOKENS.get(provider, 300) * n
    lines = [f"Do oceny: {n} ofert, zdjęć razem {n_photos} (śr. {n_photos / max(n, 1):.1f} na ofertę); tekst "
             f"~{text_tokens / max(n, 1):.0f} tokenów/ofertę (+ instrukcja {INSTRUCTION_TOKENS}), zdjęcie "
             f"~{IMAGE_TOKENS} tokenów, odpowiedź ~{OUTPUT_TOKENS.get(provider, 300)}."]
    for label, photos in ((f"ze zdjęciami ({n_photos})", n_photos), ("sam tekst (--photos 0)", 0)):
        tokens_in = text_tokens + n * INSTRUCTION_TOKENS + photos * IMAGE_TOKENS
        cost = f"~${(tokens_in * price[0] + out_tokens * price[1]) / 1e6:,.2f}" if price else "cena nieznana"
        lines.append(f"  {label}: wejście ~{tokens_in / 1e6:.1f} mln tokenów, wyjście ~{out_tokens / 1e6:.2f} mln "
                     f"→ {cost}")
    if not price:
        lines.append("  (brak ceny modelu w sniper/config.py MODEL_PRICES - ustaw SNIPER_AI_PRICE_IN / _OUT, USD za "
                     "1 mln tokenów)")
    return lines


def photo_unavailable(exc):
    """Dostawca AI nie pobrał zdjęcia z podanego URL-a (Gemini: 404 NOT_FOUND „Cannot fetch content from the
    provided URL”; Claude: błąd pobrania obrazu z URL)."""
    text = str(exc).lower()
    return "cannot fetch content" in text or ("url" in text and ("404" in text or "not_found" in text or
                                                                  "could not" in text or "unable to" in text))


STOP_AFTER_ERRORS = 10        # tyle błędów z rzędu = koniec środków / limit / brak sieci → przerwij przebieg


async def run(aconn, items, backend, concurrency=4, progress=True, flush_every=25, stop_after=STOP_AFTER_ERRORS):
    """Wywołania AI dla kandydatów, zapis do analysis.db co `flush_every` (przerwanie nie traci wyników).
    Po `stop_after` błędach z rzędu (np. skończyły się środki na koncie API - przedpłata) przerywa resztę zamiast
    wysyłać tysiące nieudanych zapytań; następne uruchomienie zaczyna od ofert bez wyniku.
    → {"done", "failed", "tokens_in", "tokens_out", "stopped": ostatni błąd albo None}."""
    from .progress import Bar

    stats = {"done": 0, "failed": 0, "tokens_in": 0, "tokens_out": 0, "stopped": None}
    bar = Bar("AI stan", len(items)) if progress else None
    semaphore = asyncio.Semaphore(max(1, concurrency))
    pending = []

    def flush():
        with aconn:
            aconn.executemany(
                "INSERT OR REPLACE INTO ai_condition (listing_id, content_key, model, condition, cracked, locked, "
                "photo_damage, evidence, photos, tokens_in, tokens_out, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))", pending)
        pending.clear()

    streak = [0]

    async def one(item):
        row, desc, urls, key = item
        async with semaphore:
            if stats["stopped"]:                # przerwane - nie wysyłamy już nic
                return item, None, 0, 0
            try:
                try:
                    text, (t_in, t_out) = await backend.ask(prompt_text(row, desc), urls, system=INSTRUCTION,
                                                            schema=SCHEMA, max_tokens=300)
                except Exception as exc:
                    if not urls or not photo_unavailable(exc):
                        raise
                    log.info("[AI] Oferta %s: zdjęcia niedostępne (usunięte z Vinted) - oceniam z samego opisu.",
                             row["id"])
                    item = (row, desc, [], key)
                    text, (t_in, t_out) = await backend.ask(prompt_text(row, desc), [], system=INSTRUCTION,
                                                            schema=SCHEMA, max_tokens=300)
                result = parse_result(text)
                streak[0] = 0
                return item, result, t_in, t_out
            except Exception as exc:          # błąd jednej oferty nie zatrzymuje reszty (ponowi następne uruchomienie)
                message = (str(exc).splitlines() or [""])[0][:200] or type(exc).__name__
                log.warning("[AI] Oferta %s: %s", row["id"], message)
                streak[0] += 1
                if streak[0] >= stop_after and not stats["stopped"]:
                    stats["stopped"] = message
                    log.warning("[AI] %d błędów z rzędu - przerywam (ostatni: %s). Sprawdź środki / limit na koncie "
                                "API i uruchom ponownie - zrobione oferty są zapisane.", streak[0], message)
                return item, message, 0, 0

    tasks = [asyncio.ensure_future(one(i)) for i in items]
    try:
        for n, task in enumerate(asyncio.as_completed(tasks), 1):
            (row, _d, urls, key), result, t_in, t_out = await task
            stats["tokens_in"] += t_in
            stats["tokens_out"] += t_out
            if result is None:                  # pominięta po przerwaniu
                pass
            elif not isinstance(result, dict):
                stats["failed"] += 1
            else:
                stats["done"] += 1
                pending.append((row["id"], key, backend.model, result["condition"], result["cracked_screen"],
                                result["locked"], result["photo_damage"], result["evidence"], len(urls), t_in, t_out))
                if len(pending) >= flush_every:
                    flush()
            if bar:
                bar.update(n)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if pending:
            flush()
        if bar:
            bar.finish()
    return stats


def load_damaged(aconn):
    """{listing_id: uszkodzona?} z wyników AI (dla stats.collect)."""
    out = {}
    for lid, condition, cracked, locked in aconn.execute(
            "SELECT listing_id, condition, cracked, locked FROM ai_condition WHERE condition != 'unknown'"):
        out[lid] = damaged({"condition": condition, "cracked_screen": cracked, "locked": locked})
    return out


def report(conn, aconn, examples=10):
    """Rozkład stanów z AI i zgodność z regułami (features: for_parts / cracked / locked)."""
    rows = aconn.execute("SELECT listing_id, condition, cracked, locked, evidence FROM ai_condition").fetchall()
    if not rows:
        return ["Brak wyników AI - uruchom: python -m analyzer ai-condition"]
    rule = {}
    ids = [r["listing_id"] for r in rows]
    for start in range(0, len(ids), 900):
        chunk = ids[start:start + 900]
        for r in conn.execute(
                f"""SELECT l.id, l.category, l.title, COALESCE(f.for_parts, 0) OR COALESCE(f.cracked, 0)
                           OR COALESCE(f.locked, 0) AS d FROM listings l LEFT JOIN features f ON f.listing_id = l.id
                    WHERE l.id IN ({','.join('?' * len(chunk))})""", chunk):
            rule[r["id"]] = r
    by_cat, matrix, disagree = {}, {}, {"rule_only": [], "ai_only": []}
    for r in rows:
        info = rule.get(r["listing_id"])
        if info is None:
            continue
        by_cat.setdefault(info["category"], {}).setdefault(r["condition"], 0)
        by_cat[info["category"]][r["condition"]] += 1
        if r["condition"] == "unknown":
            continue
        ai = damaged({"condition": r["condition"], "cracked_screen": r["cracked"], "locked": r["locked"]})
        cell = (bool(info["d"]), ai)
        matrix[cell] = matrix.get(cell, 0) + 1
        if cell == (True, False):
            disagree["rule_only"].append((info, r))
        elif cell == (False, True):
            disagree["ai_only"].append((info, r))
    lines = [f"Stan z AI: {len(rows)} ofert", "", "kategoria   " + "".join(c.rjust(14) for c in CONDITIONS)]
    for cat in analysis.CATEGORIES:
        if cat in by_cat:
            lines.append(f"{cat:<11} " + "".join(f"{by_cat[cat].get(c, 0):>14}" for c in CONDITIONS))
    agree = matrix.get((True, True), 0) + matrix.get((False, False), 0)
    total = sum(matrix.values())
    lines += ["", "Zgodność z regułami (uszkodzona = na części / zbity ekran / blokada):",
              f"  oboje uszkodzona {matrix.get((True, True), 0)}, oboje sprawna {matrix.get((False, False), 0)}, "
              f"tylko reguły uszkodzona {matrix.get((True, False), 0)}, tylko AI uszkodzona "
              f"{matrix.get((False, True), 0)} → zgodność {agree / total if total else 0:.0%}"]
    for name, label in (("rule_only", "reguły: uszkodzona, AI: sprawna"), ("ai_only", "reguły: sprawna, AI: uszkodzona")):
        items = disagree[name][:examples]
        if items:
            lines += ["", f"{label} - przykłady ({len(items)} z {len(disagree[name])}):"]
            for info, r in items:
                title = "".join(ch for ch in (info["title"] or "") if ord(ch) < 0x2000)[:40]
                lines.append(f"  https://www.vinted.pl/items/{info['id']}  {info['category']:<7} {r['condition']:<12} "
                             f"{title}  [{r['evidence'][:60]}]")
    return lines
