"""Test (proof of concept) lokalnego modelu decyzyjnego basal-2.0-mini jako „bramkarza” przed medianami
(2026-11-06, plan użytkownika: regex → mały model na GPU → mediany; tu kroki 2-3, krok 1 w BASAL_GPU.md).

    python -m analyzer basal-sample --rodzina s23 --limit 40      # krok 2: próbka z bazy → data/basal/*.jsonl
    python -m analyzer basal-test --plik data/basal/s23_....jsonl   # krok 3: basal → etykieta + pewność + czas + VRAM

Rodziny: s23 (telefony), ram, dyski, karty, procesory (07.11: także LICZBA SZTUK - „2x8 GB” = 2, „cena za sztukę,
mam 5” = 1 za podaną cenę - i czy cena jest za jedną sztukę z kilku; ważne przy podzespołach).

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
PART_FLAGS = {
    "uszkodzony": "Czy z ogłoszenia wynika, że sprzedawana rzecz jest uszkodzona, nie działa, ma błędy albo jest na "
                  "części? Uwaga na zaprzeczenia: „sprawna, bez artefaktów” = nie.",
    "cena_za_sztuke": "Czy podana cena dotyczy JEDNEJ sztuki z kilku, które ma sprzedawca (np. „cena za sztukę”, "
                      "„mam 5 sztuk”, „cena za jedną kość”)?",
}
# Ile sztuk dostaje kupujący za podaną cenę (klucze krótkie - basal wybiera jedną odpowiedź).
QUANTITY = {
    "1": "jedna sztuka (także: cena za sztukę z kilku dostępnych)",
    "2": "dwie sztuki (np. zestaw 2x8 GB, dwa dyski, dwie karty)",
    "3": "trzy sztuki",
    "4": "cztery sztuki (np. 4x4 GB)",
    "5+": "pięć lub więcej sztuk",
    "nie_wiadomo": "nie da się ustalić",
}
QUANTITY_QUESTION = ("Ile sztuk (kości RAM, dysków, kart graficznych, procesorów) dostaje kupujący za PODANĄ cenę? "
                     "Zestaw 2x8 GB = 2 kości. „Cena za sztukę, mam 4” = 1.")

FAMILIES.update({
    "ram": {
        "name": "pamięć RAM", "category": "ram", "title": None, "flags": PART_FLAGS, "quantity": True,
        "labels": {
            "ddr4_pc": "DDR4 do komputera stacjonarnego (DIMM), sprawna",
            "ddr4_laptop": "DDR4 do laptopa (SO-DIMM), sprawna",
            "ddr3": "DDR3 / DDR3L (PC albo laptop), sprawna",
            "ddr5": "DDR5, sprawna",
            "uszkodzony": "pamięć uszkodzona albo choć jedna kość nie działa",
            "inny": "nie pamięć RAM (sam radiator, inna część) albo nie da się ustalić",
        },
        "tricky": [
            ("Kingston Fury 16GB (2x8GB) DDR4 3200", "Zestaw dwóch kości po 8 GB, sprawne.", "ddr4_pc", "2"),
            ("Pamięć RAM DDR4 8GB 2666 - cena za sztukę", "Mam 4 sztuki, cena dotyczy jednej kości.", "ddr4_pc", "1"),
            ("4x4GB DDR3 1600 PC3-12800", "Cztery kości wyjęte z działającego komputera.", "ddr3", "4"),
            ("SODIMM DDR4 16GB 3200", "Z laptopa Lenovo, jedna kość.", "ddr4_laptop", "1"),
            ("RAM DDR4 32GB", "Komplet 2 x 16 GB do PC. To nie DDR3!", "ddr4_pc", "2"),
            ("Pamięć DDR5 2x16GB", "Jedna kość nie działa, druga OK - sprzedaję obie.", "uszkodzony", "2"),
        ],
    },
    "dyski": {
        "name": "dyski", "category": "storage", "title": None, "flags": PART_FLAGS, "quantity": True,
        "labels": {
            "ssd_nvme": "dysk SSD M.2 NVMe / PCIe, sprawny",
            "ssd_sata": "dysk SSD SATA (2,5\" albo M.2 SATA), sprawny",
            "hdd": "dysk talerzowy HDD, sprawny",
            "zewnetrzny": "dysk zewnętrzny / przenośny (USB), sprawny",
            "akcesorium": "sama obudowa / kieszeń / adapter / radiator - bez dysku",
            "uszkodzony": "dysk uszkodzony (bad sectory, błędy SMART, nie wykrywa się)",
            "inny": "inna rzecz albo nie da się ustalić",
        },
        "tricky": [
            ("Dyski SSD 512GB x3", "Trzy dyski Samsung 870 EVO, cena za całość.", "ssd_sata", "3"),
            ("Samsung 980 Pro 1TB NVMe", "Cena za sztukę, mam 2.", "ssd_nvme", "1"),
            ("Obudowa na dysk M.2 NVMe", "Sama kieszeń USB-C, dysku brak.", "akcesorium", "1"),
            ("WD Blue 1TB HDD", "Bad sectory, SMART pokazuje błędy.", "uszkodzony", "1"),
            ("Dysk 2TB", "Dwa dyski HDD po 1 TB w zestawie, sprawne.", "hdd", "2"),
        ],
    },
    "karty": {
        "name": "karty graficzne", "category": "gpu", "title": None, "flags": PART_FLAGS, "quantity": True,
        "labels": {
            "karta": "sprawna karta graficzna",
            "uszkodzona": "karta uszkodzona (brak obrazu, artefakty, czerwony / czarny ekran, nie działa, na części)",
            "chlodzenie": "samo chłodzenie / radiator / wentylatory / backplate - bez karty",
            "akcesorium": "riser, przejściówka, kabel, karta przechwytująca, inna część",
            "inny": "nie da się ustalić",
        },
        # Dwa pierwsze to prawdziwe oferty z 06.11 (opisy tłumaczone przez Vinted - w bazie w innym języku).
        "tricky": [
            ("rtx 2060 super", "Sprzedam kartę RTX 2060 Super Gigabyte WindForce. Sprzedawana jako uszkodzona, brak "
             "obrazu.", "uszkodzona", "1"),
            ("GTX 1070 ti 8gb", "Nie wiem, co się stało. Urządzenie wyświetla czerwony ekran, a wentylatory się "
             "kręcą.", "uszkodzona", "1"),
            ("RTX3060 Ti Heatsink with Fan", "Sam radiator z wentylatorem do karty, bez układu.", "chlodzenie", "1"),
            ("2x RX 580 8GB", "Dwie karty, obie sprawne.", "karta", "2"),
            ("GTX 1060 6GB", "Cena za sztukę, mam 3 sztuki, wszystkie sprawne.", "karta", "1"),
            ("RX 570 8GB", "W pełni sprawna, bez artefaktów, nie kopała.", "karta", "1"),
        ],
    },
    "procesory": {
        "name": "procesory", "category": "cpu", "title": None, "flags": PART_FLAGS, "quantity": True,
        "labels": {
            "procesor": "sam procesor, sprawny",
            "zestaw": "procesor z płytą główną (i ewentualnie RAM)",
            "uszkodzony": "procesor uszkodzony (wygięte / urwane piny, nie działa)",
            "chlodzenie": "samo chłodzenie procesora - bez procesora",
            "inny": "nie da się ustalić",
        },
        "tricky": [
            ("Intel i5-9400F", "Sam procesor, bez chłodzenia, sprawny.", "procesor", "1"),
            ("Ryzen 5 3600 + płyta B450", "Zestaw: procesor i płyta, działają.", "zestaw", "1"),
            ("Ryzen 7 2700X", "Wygięte 3 piny, nie testowany.", "uszkodzony", "1"),
            ("Chłodzenie do i7", "Sam cooler boxowy Intel, procesora brak.", "chlodzenie", "1"),
            ("Procesory Intel i3-6100 x2", "Dwie sztuki, cena za obie.", "procesor", "2"),
        ],
    },
})
FAMILIES["s23"].update(category="phone", flags=QUESTIONS_FLAGS, quantity=False)
FAMILIES["s23"]["tricky"] = [(t, d, e, None) for t, d, e in FAMILIES["s23"]["tricky"]]


# ---------------------------------------------------------------------------------------------- krok 2: próbka

_MANY = re.compile(r"\d\s*[x×]\s*\d|\b[x×]\s*\d\b|\d\s*[x×]\b|\bszt|zestaw|komplet|\bkit\b|\bdwie\b|\bdwa\b|"
                   r"\btrzy\b|\bcztery\b|za sztuk", re.I)


def _part_hint(title, description):
    t, d = title.lower(), (description or "").lower()
    if _MANY.search(t + " " + d):
        return "kilka sztuk?"
    if re.search(r"uszkodz|nie dzia|na cz[eę]ści|artefakt|brak obrazu|bad sector|wygi[eę]t|broken|defekt", t + " " + d):
        return "uszkodzenie?"
    if re.search(r"obudow|kiesze|adapter|radiator|heatsink|chłodzen|chlodzen|cooler|wentylator|riser", t):
        return "akcesorium?"
    if re.search(r"\bnie\b|\bbez\b|\bnot\b", d):
        return "zaprzeczenie w opisie"
    return "zwykły"


def _hint(title, description, family="s23"):
    """Grupa do losowania warstwowego (żeby w próbce były trudne przypadki, nie same „S23 Ultra 256 GB”)."""
    if family != "s23":
        return _part_hint(title, description)
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
             WHERE l.category = ? AND d.description IS NOT NULL"""
    groups = {}
    for r in conn.execute(sql, (fam["category"],)):
        if fam["title"] is not None and not fam["title"].search(r[1] or ""):
            continue
        groups.setdefault(_hint(r[1], r[6], family), []).append(r)
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

def state_text(offer, family="s23"):
    price = f"{offer['price']:.0f} zł" if offer.get("price") else "?"
    return (f"Ogłoszenie z Vinted (kategoria: {FAMILIES[family]['name']}).\nTytuł: {offer['title']}\nCena: {price}\n"
            f"Stan (formularz): {offer.get('condition') or '?'}\nOpis: {offer.get('description') or ''}")


def build_request(offer, family):
    fam = FAMILIES[family]
    questions = {
        "etykieta": {"type": "choice", "instructions": f"Co dokładnie jest sprzedawane? (rodzina: {fam['name']}). "
                     "Czytaj cały opis - zaprzeczenia („nie FE”, „nie uszkodzony”) zmieniają znaczenie.",
                     "criteria": fam["labels"]},
        **{k: {"type": "noul", "instructions": v} for k, v in fam["flags"].items()}}
    if fam.get("quantity"):
        questions["sztuk"] = {"type": "choice", "instructions": QUANTITY_QUESTION, "criteria": QUANTITY}
    return {"state": state_text(offer, family), "questions": questions}


_WORDS = {"dwie": 2, "dwa": 2, "dwóch": 2, "dwoch": 2, "trzy": 3, "cztery": 4}


def rule_quantity(offer):
    """Dla porównania: liczba sztuk z prostych reguł („2x8GB”, „x3”, „3 szt”, „dwie”, „cena za sztukę” = 1)."""
    text = f"{offer['title']} {offer.get('description') or ''}".lower()
    if re.search(r"za sztuk|za szt\b|za jedn", text):
        return "1"
    for pattern in (r"\b(\d)\s*[x×]\s*\d+\s*(?:gb|tb)", r"\b(\d)\s*[x×]\s", r"\b[x×]\s*(\d)\b",
                    r"\b(\d+)\s*(?:szt|sztuk)"):
        match = re.search(pattern, text)
        if match and int(match.group(1)) >= 1:
            n = int(match.group(1))
            return "5+" if n >= 5 else str(n)
    for word, n in _WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return str(n)
    return "1"


def rule_label(offer, family="s23"):
    """Dla porównania: co powiedziałyby same reguły (tylko telefony S23; podzespoły - None)."""
    if family != "s23":
        return None
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
    cases = [dict(r, expected=None, expected_qty=None) for r in rows]
    if with_tricky:
        cases += [{"id": f"test{i}", "title": t, "description": d, "price": None, "condition": None, "hint": "[test]",
                   "expected": e, "expected_qty": q} for i, (t, d, e, q) in enumerate(fam["tricky"], 1)]
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
            flags = {k: (answers.get(k) or {}).get("noul") for k in fam["flags"]}
            qty = (answers.get("sztuk") or {}).get("choice")
            qty_conf = (answers.get("sztuk") or {}).get("confidence")
            server_ms = (data.get("usage") or {}).get("latency_ms")
            now = vram_used()
            if now and (peak is None or now[0] > peak):
                peak = now[0]
            times.append(wall)
            rule = rule_label(offer, family)
            rule_qty = rule_quantity(offer) if fam.get("quantity") else None
            res = {"id": offer["id"], "title": offer["title"], "label": label, "confidence": conf, "flags": flags,
                   "quantity": qty, "quantity_confidence": qty_conf, "rule": rule, "rule_quantity": rule_qty,
                   "expected": offer["expected"], "expected_quantity": offer["expected_qty"], "ms": round(wall),
                   "server_ms": server_ms}
            results.append(res)
            marks = []
            if offer["expected"]:
                marks.append("OK" if label == offer["expected"] else f"BŁĄD (oczekiwane {offer['expected']})")
                if offer["expected_qty"]:
                    marks.append("sztuk OK" if qty == offer["expected_qty"] else
                                 f"sztuk BŁĄD (oczekiwane {offer['expected_qty']})")
            else:
                if rule is not None and rule != label:
                    marks.append(f"≠ reguły: {rule}")
                if rule_qty is not None and qty != rule_qty:
                    marks.append(f"sztuk ≠ reguły: {rule_qty}")
            head = f"{n:>3}. {offer['title'][:60]:<60} -> {label} -> {_pct(conf)}"
            if fam.get("quantity"):
                head += f" | sztuk: {qty} ({_pct(qty_conf)})"
            say(head)
            say(f"      {', '.join(f'{k.replace(chr(95), chr(32))} {_pct(v)}' for k, v in flags.items())} | "
                f"{wall:.0f} ms" + (f"  {'; '.join(marks)}" if marks else ""))
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
    }
    real = [r for r in results if not r["expected"]]
    if family == "s23":
        summary["zgodność z regułami"] = f"{sum(r['label'] == r['rule'] for r in real)}/{len(real)}"
    if fam.get("quantity"):
        with_qty = [r for r in tricky if r["expected_quantity"]]
        summary["sztuk_przypadki_testowe"] = (f"{sum(r['quantity'] == r['expected_quantity'] for r in with_qty)}/"
                                              f"{len(with_qty)}") if with_qty else None
        summary["sztuk_zgodność_z_regułami"] = f"{sum(r['quantity'] == r['rule_quantity'] for r in real)}/{len(real)}"
    return results, summary


def _pct(p):
    return "?" if p is None else f"{p:.0%}"


def save_results(results, summary, sample_path):
    path = Path(sample_path).with_name(Path(sample_path).stem + f"_wyniki_{datetime.now():%H%M}.json")
    path.write_text(json.dumps({"podsumowanie": summary, "wyniki": results}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path
