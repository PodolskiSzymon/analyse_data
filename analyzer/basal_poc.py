"""Test (proof of concept) lokalnego modelu decyzyjnego basal-2.0-mini jako „bramkarza” przed medianami
(2026-11-06, plan użytkownika: regex → mały model na GPU → mediany; tu kroki 2-3, krok 1 w BASAL_GPU.md).

    python -m analyzer basal-sample --rodzina s23 --limit 40      # krok 2: próbka z bazy → data/basal/*.jsonl
    python -m analyzer basal-test --plik data/basal/s23_....jsonl   # krok 3: basal → etykieta + pewność + czas + VRAM

basal (github.com/rkinas/basal) NIE generuje tekstu: dostaje stan (ogłoszenie) i pytania z listą dozwolonych
odpowiedzi, zwraca skalibrowane prawdopodobieństwa (POST /v1/systemone; serwer: basal-serve albo llama-server
z GGUF po `basal-export-gguf --systemone`). Dlatego „czysty JSON z etykietą” = wybór z naszej listy etykiet + pewność.
Baza użytkownika to SQLite (analyzer.db), nie PostgreSQL. Bez danych sprzedawców; e-mail / telefon / linki w opisach
maskowane (sample.redact).
"""
import json
import random
import re
import statistics
import subprocess
import time
from datetime import datetime
from pathlib import Path

from .sample import redact

DESCRIPTION_CHARS = 1200            # basal-2.0-mini: kontekst 8k tokenów, ale krótszy prompt = szybciej na 920M

# Rodziny do testu. Etykiety = odpowiedzi, z których basal wybiera (klucz → opis dla modelu).
FAMILIES = {
    "s23": {
        "name": "Samsung Galaxy S23",
        "title": re.compile(r"(?<![a-z0-9])s\s?23(?!\d)", re.I),
        "labels": {
            "s23_base": "Samsung Galaxy S23 - podstawowy model (nie FE, nie Plus, nie Ultra), sprawny telefon",
            "s23_plus": "Samsung Galaxy S23+ / S23 Plus, sprawny telefon",
            "s23_ultra": "Samsung Galaxy S23 Ultra, sprawny telefon",
            "s23_fe": "Samsung Galaxy S23 FE (Fan Edition, tańsza wersja), sprawny telefon",
            "uszkodzony": "telefon S23 dowolnej wersji, ale uszkodzony, zbity, na części, nie działa albo zablokowany",
            "akcesorium": "nie telefon, tylko akcesorium albo część: etui, szkło, ładowarka, pudełko, obudowa, wyświetlacz",
            "podrobka": "podróbka / klon / replika („Ultra Mod”, nieznany producent), nie oryginalny Samsung",
            "inny": "inny telefon albo nie da się ustalić",
        },
        # Krótkie przypadki z zaprzeczeniami i pułapkami - dopisywane do testu (oznaczone [test]).
        "tricky": [
            ("Samsung Galaxy S23 128GB (nie FE!)", "Oryginalny S23, nie wersja FE. Bez rys, w pełni sprawny.",
             "s23_base"),
            ("Samsung S23 - nie uszkodzony, ekran bez rys", "Telefon działa idealnie, żadnych pęknięć.", "s23_base"),
            ("Samsung S23 256GB", "Zbita szybka z tyłu, ekran pęknięty w rogu, działa.", "uszkodzony"),
            ("Etui do Samsung S23 Ultra", "Sprzedam etui silikonowe, telefon niedostępny.", "akcesorium"),
            ("Samsung Galaxy S23 FE 128GB", "Sprzedaję S23 FE zamiast zwykłego S23 - pomyłka przy zakupie.", "s23_fe"),
            ("S23 Ultra 256GB + etui gratis", "Telefon sprawny, w zestawie etui i szkło.", "s23_ultra"),
            ("Samsung S23 Ultra Mod 16/512 nowy", "Dual SIM, Android 13, nie jest to oryginał Samsunga.", "podrobka"),
            ("Samsung S23", "Na części - nie włącza się po zalaniu.", "uszkodzony"),
        ],
    },
}

QUESTIONS_FLAGS = {
    "uszkodzony": "Czy z ogłoszenia wynika, że telefon jest uszkodzony, zbity, na części, nie działa albo zablokowany? "
                  "Uwaga na zaprzeczenia: „nie uszkodzony”, „bez rys” = sprawny.",
    "akcesorium": "Czy sprzedawane jest TYLKO akcesorium albo część (etui, szkło, ładowarka, pudełko) zamiast telefonu? "
                  "Etui dodane gratis do telefonu = nie.",
}


# ---------------------------------------------------------------------------------------------- krok 2: próbka

def _hint(title, description):
    """Grupa do losowania warstwowego (żeby w próbce były trudne przypadki, nie same „S23 Ultra 256 GB”)."""
    t, d = title.lower(), (description or "").lower()
    if re.search(r"\b(etui|case|husa|obudow|szk[lł]o|folia|ładowar|pude[lł]k)", t):
        return "akcesorium?"
    if re.search(r"zbit|pęk|pek|uszkodz|na cz[eę]ści|nie dzia|blokad|crack|broken|zalan", t + " " + d):
        return "uszkodzenie?"
    if re.search(r"\bmod\b|klon|replik|copy|kopia", t + " " + d):
        return "podróbka?"
    if re.search(r"\bnie\b|\bbez\b|zamiast|\bnot\b", d):
        return "zaprzeczenie w opisie"
    if re.search(r"\bfe\b|s23\s?fe", t):
        return "FE"
    if "ultra" in t:
        return "Ultra"
    if re.search(r"plus|\+", t):
        return "Plus"
    return "zwykły"


def sample(conn, family="s23", limit=40, seed=7):
    """Oferty rodziny z opisem (tytuł + opis + cena + stan) - losowanie warstwowe po grupach z `_hint`.
    → lista słowników."""
    fam = FAMILIES[family]
    sql = """SELECT l.id, l.title, l.price_now, l.sold_price, l.state, l.status_label, d.description
             FROM listings l JOIN details d ON d.listing_id = l.id
             WHERE l.category = 'phone' AND d.description IS NOT NULL AND (l.title LIKE ? OR l.title LIKE ?)"""
    groups = {}
    for r in conn.execute(sql, ("%23%", "%23%")):
        if not fam["title"].search(r[1] or ""):
            continue
        groups.setdefault(_hint(r[1], r[6]), []).append(r)
    rnd = random.Random(seed)
    for rows in groups.values():
        rnd.shuffle(rows)
    picked, i = [], 0
    while len(picked) < limit and any(i < len(g) for g in groups.values()):
        for name in sorted(groups):
            if i < len(groups[name]) and len(picked) < limit:
                picked.append((name, groups[name][i]))
        i += 1
    out = []
    for name, r in picked:
        price = r[3] if r[4] == "sold" and r[3] else r[2]
        out.append({"id": r[0], "title": r[1], "price": price, "state": r[4], "condition": r[5], "hint": name,
                    "description": redact((r[6] or "")[:DESCRIPTION_CHARS])})
    return out, {k: len(v) for k, v in groups.items()}


def print_sample(rows, counts):
    print(f"Grupy w bazie: {', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}")
    for n, r in enumerate(rows, 1):
        desc = " ".join(r["description"].split())[:140]
        price = f"{r['price']:.0f} zł" if r["price"] else "? zł"
        print(f"\n{n:>3}. [{r['hint']}] {r['title']} | {price} | {r['condition'] or '?'} | {r['state']}")
        print(f"     {desc}")


def save_sample(rows, family, out_dir):
    path = Path(out_dir) / "basal" / f"{family}_{datetime.now():%Y%m%d_%H%M}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------- krok 3: test basal

def state_text(offer):
    price = f"{offer['price']:.0f} zł" if offer.get("price") else "?"
    return (f"Ogłoszenie z Vinted (kategoria: telefony).\nTytuł: {offer['title']}\nCena: {price}\n"
            f"Stan (formularz): {offer.get('condition') or '?'}\nOpis: {offer.get('description') or ''}")


def build_request(offer, family):
    fam = FAMILIES[family]
    return {"state": state_text(offer), "questions": {
        "etykieta": {"type": "choice", "instructions": f"Co dokładnie jest sprzedawane? (rodzina: {fam['name']}). "
                     "Czytaj cały opis - zaprzeczenia („nie FE”, „nie uszkodzony”) zmieniają znaczenie.",
                     "criteria": fam["labels"]},
        **{k: {"type": "noul", "instructions": v} for k, v in QUESTIONS_FLAGS.items()}}}


def rule_label(offer):
    """Dla porównania: co powiedziałyby same reguły (tytuł + reguły uszkodzeń analizatora)."""
    from .extract import CRACKED, FOR_PARTS, LOCKED, has_fault, norm
    t, d = norm(offer["title"]), norm(offer.get("description") or "")
    if re.search(r"\b(etui|case|husa|szklo|folia)\b", t) and not re.search(r"\d{2,3}\s*gb", t):
        return "akcesorium"
    if any(has_fault(p, f"{t}\n{d}") for p in (FOR_PARTS, CRACKED, LOCKED)):
        return "uszkodzony"
    if re.search(r"\bfe\b|s23\s?fe", t):
        return "s23_fe"
    if "ultra" in t:
        return "s23_ultra"
    if re.search(r"plus|\+", t):
        return "s23_plus"
    return "s23_base"


# Starsze sterowniki (np. 425.31 - ostatni dla laptopowych Keplerów, GeForce 920M) nie dodają nvidia-smi do PATH.
NVIDIA_SMI = ("nvidia-smi", r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe")


def vram_used():
    """Zajęta pamięć karty (MB) wg nvidia-smi; None, gdy brak nvidia-smi / karty."""
    for exe in NVIDIA_SMI:
        try:
            out = subprocess.run([exe, "--query-gpu=memory.used,memory.total,name", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True, timeout=10).stdout.strip().splitlines()
            used, total, name = [x.strip() for x in out[0].split(",")]
            return int(used), int(total), name
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            continue
    return None


def run_test(rows, family="s23", url="http://127.0.0.1:8000", client=None, with_tricky=True, say=print):
    """Każda oferta → POST /v1/systemone. → (wyniki, podsumowanie). Rzuca httpx.HTTPError przy braku serwera."""
    import httpx
    fam = FAMILIES[family]
    cases = [dict(r, expected=None) for r in rows]
    if with_tricky:
        cases += [{"id": f"test{i}", "title": t, "description": d, "price": None, "condition": None, "hint": "[test]",
                   "expected": e} for i, (t, d, e) in enumerate(fam["tricky"], 1)]
    own = client is None
    client = client or httpx.Client(timeout=120.0, trust_env=False)
    before = vram_used()
    peak = before[0] if before else None
    results, times = [], []
    try:
        for n, offer in enumerate(cases, 1):
            started = time.perf_counter()
            response = client.post(f"{url.rstrip('/')}/v1/systemone", json=build_request(offer, family))
            response.raise_for_status()
            wall = (time.perf_counter() - started) * 1000
            data = response.json()
            answers = data.get("answers") or {}
            label = (answers.get("etykieta") or {}).get("choice")
            conf = (answers.get("etykieta") or {}).get("confidence")
            flags = {k: (answers.get(k) or {}).get("noul") for k in QUESTIONS_FLAGS}
            server_ms = (data.get("usage") or {}).get("latency_ms")
            now = vram_used()
            if now and (peak is None or now[0] > peak):
                peak = now[0]
            times.append(wall)
            rule = rule_label(offer)
            res = {"id": offer["id"], "title": offer["title"], "label": label, "confidence": conf, "flags": flags,
                   "rule": rule, "expected": offer["expected"], "ms": round(wall), "server_ms": server_ms}
            results.append(res)
            mark = ""
            if offer["expected"]:
                mark = "  OK" if label == offer["expected"] else f"  BŁĄD (oczekiwane {offer['expected']})"
            elif rule != label:
                mark = f"  ≠ reguły: {rule}"
            say(f"{n:>3}. {offer['title'][:60]:<60} -> {label} -> {conf:.0%}" if conf is not None else
                f"{n:>3}. {offer['title'][:60]:<60} -> {label} -> ?")
            say(f"      uszkodzony {_pct(flags['uszkodzony'])}, akcesorium {_pct(flags['akcesorium'])} | "
                f"{wall:.0f} ms{mark}")
    finally:
        if own:
            client.close()
    tricky = [r for r in results if r["expected"]]
    summary = {
        "ofert": len(results),
        "czas_ms": {"średnio": round(statistics.mean(times)), "mediana": round(statistics.median(times)),
                    "max": round(max(times)), "pierwsza (z rozgrzewką)": round(times[0])} if times else {},
        "vram_mb": {"przed": before[0] if before else None, "szczyt": peak, "karta": before[2] if before else None,
                    "razem_mb": before[1] if before else None},
        "przypadki_testowe": f"{sum(r['label'] == r['expected'] for r in tricky)}/{len(tricky)}" if tricky else None,
        "zgodność z regułami": f"{sum(r['label'] == r['rule'] for r in results if not r['expected'])}/"
                               f"{sum(1 for r in results if not r['expected'])}",
    }
    return results, summary


def _pct(p):
    return "?" if p is None else f"{p:.0%}"


def save_results(results, summary, sample_path):
    path = Path(sample_path).with_name(Path(sample_path).stem + f"_wyniki_{datetime.now():%H%M}.json")
    path.write_text(json.dumps({"podsumowanie": summary, "wyniki": results}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path
