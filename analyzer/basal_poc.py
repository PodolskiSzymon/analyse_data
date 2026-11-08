"""Test (proof of concept) lokalnego modelu decyzyjnego basal jako „bramkarza” przed medianami
(2026-11-06, plan użytkownika: regex → mały model na GPU → mediany; krok 1 w BASAL_GPU.md).

    python -m analyzer basal-sample --rodzina gtx1060 --limit 30   # krok 2: próbka z bazy → data/basal/*.jsonl
    python -m analyzer basal-test --rodzina gtx1060 --plik data/basal/gtx1060_....jsonl   # krok 3: basal → odpowiedzi

Sedno (07.11, użytkownik): rozróżnianie WARIANTÓW jednego modelu, gdy tytuł bywa zbyt ogólny albo myli - jak przy S23
(Ultra / FE / Plus): GTX 1060 3 / 6 GB, RTX 3060 / 3060 Ti / 8 / 12 GB, RAM DDR3 / DDR4 i taktowanie (2133 ≠ 3200),
procesor z „F” / „K” / „KF” albo bez, Samsung 970 EVO / EVO Plus / 980 PRO i pojemność. Każda rodzina ma pytania
(basal wybiera jedną odpowiedź z listy, z pewnością), reguły regex jako porównanie (z samego tytułu i z tytułu +
opisu) i krótkie przypadki testowe z oczekiwanymi odpowiedziami (zaprzeczenia, „jak GTX 1060”, „PC4-21300”,
„pracowały na 2133”, „i5 9400 f”).

Próbka (`sample`): oferty rodziny z opisem, najpierw te, gdzie tytuł nie mówi wariantu, opis go zmienia albo mówi coś
innego niż tytuł, potem pułapki językowe (zaprzeczenia, cena za sztukę, zestawy, obcy język...).

basal (github.com/rkinas/basal) NIE generuje tekstu: dostaje stan (ogłoszenie) i pytania z listą dozwolonych
odpowiedzi, zwraca skalibrowane prawdopodobieństwa (POST /v1/systemone). Baza użytkownika to SQLite (analyzer.db).
Bez danych sprzedawców; e-mail / telefon / linki w opisach maskowane (sample.redact).
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

DESCRIPTION_CHARS = 1200
UNKNOWN = "nie_wiadomo"


def _q(instructions, criteria):
    return {"instructions": instructions, "criteria": criteria}


# ---------------------------------------------------------------------------------------------- pytania wspólne

CONDITION_PART = _q("Co dokładnie jest sprzedawane i w jakim stanie? Czytaj cały opis - zaprzeczenia („bez "
                    "artefaktów”, „nie uszkodzona”) zmieniają znaczenie.", {
                        "sprawna": "sprawna rzecz (karta / pamięć / dysk / procesor) - działa",
                        "uszkodzona": "uszkodzona, nie działa, nie jest wykrywana, artefakty, brak obrazu, błędy, "
                                      "na części",
                        "czesc": "tylko część / akcesorium / pudełko / chłodzenie / sam wiatrak lub wentylator / "
                                 "adapter - bez samej rzeczy",
                        "zestaw": "razem z inną DUŻĄ częścią (procesor + płyta główna, karta w całym komputerze, "
                                  "kilka różnych rzeczy w pakiecie). Dodatek jak chłodzenie BOX czy etui to NIE zestaw",
                        "inna_rzecz": "to nie jest sprzedaż tej rzeczy: kupię / zamienię / nazwa tylko dla porównania "
                                      "albo przedmiot spoza kategorii. Inny wariant tej samej rzeczy (inny typ pamięci, "
                                      "inny model karty) to NIE inna_rzecz - oceń jego stan",
                    })
# 08.11: basal na „Dwie karty, cena za sztukę” odpowiadał 2 (80% pewności) - liczy sztuki sprzedawcy, nie „za cenę”.
# Dlatego osobna odpowiedź „cena_za_sztuke”: cena dotyczy jednej z kilku sztuk (do mediany = 1 sztuka).
QUANTITY = _q("Ile sztuk (kości, dysków, kart, procesorów) obejmuje PODANA cena? Zestaw 2 x … GB = 2 kości. Gdy "
              "sprzedawca ma kilka sztuk, ale cena dotyczy jednej („cena za sztukę”, „mam 4, cena za 1”) - wybierz "
              "cena_za_sztuke. To NIE liczba sztuk: „Dual”, „Twin”, „2X”, „3X” w nazwie karty (ASUS Dual, MSI Ventus 2X, "
              "Gigabyte WINDFORCE 3X - liczba wentylatorów), „PCIe x4”, „x16”, „Gen4 x4”, „AGP 8x”, „4x mini-DP” "
              "(złącza), „4x3.6 GHz”, „6 rdzeni” (rdzenie procesora), „1Rx8”, „2Rx8” (budowa kości). Bez żadnej "
              "wzmianki o kilku sztukach = 1.", {
                  "1": "jedna sztuka", "2": "dwie sztuki razem za tę cenę", "3": "trzy sztuki razem",
                  "4": "cztery sztuki razem", "5+": "pięć lub więcej razem",
                  "cena_za_sztuke": "sprzedawca ma kilka sztuk, ale podana cena dotyczy JEDNEJ",
                  UNKNOWN: "nie da się ustalić"})
PART_FLAGS = {
    "cena_za_sztuke": "Czy podana cena dotyczy JEDNEJ sztuki z kilku, które ma sprzedawca (np. „cena za sztukę”, "
                      "„mam 5 sztuk”, „cena za jedną kość”)?",
}
PHONE_FLAGS = {
    "uszkodzony": "Czy z ogłoszenia wynika, że telefon jest uszkodzony, zbity, na części, nie działa albo zablokowany? "
                  "Uwaga na zaprzeczenia: „nie uszkodzony”, „bez rys” = sprawny.",
    "akcesorium": "Czy sprzedawane jest TYLKO akcesorium albo część (etui, szkło, ładowarka, pudełko) zamiast telefonu? "
                  "Etui dodane gratis do telefonu = nie.",
}

# ---------------------------------------------------------------------------------------------- reguły (porównanie)


def _gb(text, allowed):
    found = [int(m.group(1)) for m in re.finditer(r"(?<![\d.,])(\d{1,2})\s?(?:gb|g)\b", text)]
    found += [round(int(m.group(1)) / 1024) for m in re.finditer(r"(?<![\d.,])(\d{4,5})\s?mb\b", text)]   # 3072MB
    found = [x for x in found if x in allowed]
    return f"{found[0]}gb" if len(set(found)) == 1 else (UNKNOWN if not found else "sprzeczne")


def rules_gtx1060(text):
    t = text.lower()
    model = "gtx1060" if re.search(r"1060", t) else UNKNOWN
    return {"model": model, "vram": _gb(t, {3, 5, 6})}


def rules_rtx3060(text):
    t = text.lower()
    model = "rtx3060ti" if re.search(r"3060\s?-?\s?ti\b", t) else "rtx3060" if "3060" in t else UNKNOWN
    vram = _gb(t, {8, 12})
    if model == "rtx3060ti" and vram == UNKNOWN:
        vram = "8gb"                                     # 3060 Ti ma zawsze 8 GB
    return {"model": model, "vram": vram}


# Taktowania znamionowe (MT/s) jako odpowiedzi: DDR2 / DDR3 / DDR4 / DDR5 (07.11: było tylko DDR4).
RAM_SPEEDS = ("1600", "1866", "2133", "2400", "2666", "2933", "3000", "3200", "3600", "4800", "5200", "5600")
SPEED_LABELS = {"667_i_mniej": "667 MHz lub mniej (DDR2-667, DDR-400 i starsze)", "800": "800 MHz (DDR2-800, PC2-6400)",
                "1066": "1066 MHz (DDR2-1066, DDR3-1066)", "1333": "1333 MHz (DDR3-1333, PC3-10600)",
                **{s: f"{s} MHz" for s in RAM_SPEEDS[:9]}, "3733_4600": "od 3733 do 4600 MHz (szybkie DDR4)",
                **{s: f"{s} MHz" for s in RAM_SPEEDS[9:]}, "6000+": "6000 MHz lub więcej (DDR5)"}
KNOWN_MTS = {266, 333, 400, 533, 667, 800, 1066, 1333, 1600, 1866, 2133, 2400, 2666, 2800, 2933, 3000, 3200, 3333,
             3466, 3600, 3733, 3866, 4000, 4133, 4266, 4400, 4600, 4800, 5200, 5600, 6000, 6200, 6400, 6800, 7200, 8000}
OLD_RAM = re.compile(r"\bsimm\b|\bedo\b|\bfpm\b|\bddr\s?-?\s?(?:1|[234]00|333|266)\b|\bpc2-|\bpc-?(?:100|133)\b")


def speed_label(mts):
    """MT/s → odpowiedź pytania „mhz” (1333 i mniej razem, 3733-4600 razem, 6000+ razem, reszta - najbliższa)."""
    if mts <= 700:
        return "667_i_mniej"
    if mts <= 1400:
        return min(("800", "1066", "1333"), key=lambda s: abs(int(s) - mts))
    if 3700 <= mts <= 4650:
        return "3733_4600"
    if mts >= 5900:
        return "6000+"
    return min(RAM_SPEEDS, key=lambda s: abs(int(s) - mts))


def rules_ddr4(text):
    """Pamięć RAM dowolnego typu (nazwa rodziny „ddr4” została dla zgodności komend)."""
    t = text.lower()
    types = {f"ddr{x}" for x in re.findall(r"\bddr\s?-?\s?([2345])l?\b", t)}
    types |= {f"ddr{x}" for x in re.findall(r"\bpc([345])l?-", t)}
    types = {"ddr2_starsza" if x == "ddr2" else x for x in types}
    if OLD_RAM.search(t):
        types.add("ddr2_starsza")
    if not types and re.search(r"\bsd-?ram\b|\bddr\b(?![\s-]?\d)", t):    # „SDRAM”, samo „DDR” (DDR4 SDRAM = DDR4)
        types.add("ddr2_starsza")
    typ = types.pop() if len(types) == 1 else (UNKNOWN if not types else "sprzeczne")
    speeds = {int(m) for m in re.findall(r"\b(\d{3,4})\s?(?:mhz|mt/?s)\b", t) if 300 <= int(m) <= 9000}
    speeds |= {int(m) for m in re.findall(r"\bddr[2345]?l?\s?-?\s?(\d{3,4})\b", t) if int(m) in KNOWN_MTS}  # DDR4 2666
    speeds |= {int(m) // 8 for m in re.findall(r"\bpc[23]l?-(\d{4,5})", t)}             # PC2-6400, PC3L-12800S
    speeds |= {int(m) // 8 for m in re.findall(r"\bpc[45]-(\d{5})", t)}                 # PC4-21300, PC5-38400
    speeds |= {int(m) for m in re.findall(r"\bpc[45]-(\d{4})[a-z]", t)}                              # PC4-3200AA
    labels = {speed_label(x) for x in speeds}
    mhz = labels.pop() if len(labels) == 1 else (UNKNOWN if not labels else "sprzeczne")
    t = re.sub(r"(?:not for|nie do|nie dla|nie pasuje do|nie nadaje si[eę] do)\s+(?:\w+\s+)?(?:laptop|notebook)\w*",
               " ", t)                                                    # „Not for laptops” ≠ laptop
    if re.search(r"\b(?:u-?dimm|desktop)\b", t):                        # „desktop … not for laptops (SO-DIMM)”
        t = re.sub(r"so-?\s?dimm", " ", t)
    forma = ("laptop" if re.search(r"so-?\s?dimm|laptop|notebook|\bpc[345]l?-\d{4,5}[a-z]{0,2}-s|\bpc3l?-\d{4,5}s\b",
                                   t) else
             "serwer" if re.search(r"(?<!non-)(?<!non )\becc\b|rdimm|(?<!un)registered|\breg\b", t) else
             "pc" if re.search(r"\b(?:u-?)?dimm\b|desktop|stacjonar|\bpc[345]l?-\d{4,5}[a-z]{0,2}-u|"
                               r"\bpc3l?-\d{4,5}u\b", t) else UNKNOWN)
    return {"typ": typ, "mhz": mhz, "forma": forma, "sztuk": rule_quantity({"title": text, "description": ""})}


NVME_MODELS = (("990evoplus", r"990\s?evo\s?(?:plus|\+)"), ("990evo", r"990\s?evo"), ("990pro", r"990\s?pro"), ("980pro", r"980\s?pro"),
               ("970evoplus", r"970\s?evo\s?(?:plus|\+)"), ("970pro", r"970\s?pro"), ("970evo", r"970\s?evo"),
               ("980", r"\b980\b"))


def rules_nvme(text):
    t = text.lower()
    model = next((k for k, p in NVME_MODELS if re.search(p, t)), UNKNOWN)
    caps = set()
    for n, unit in re.findall(r"(?<![\d.,])(\d{1,4})\s?(gb|tb)\b", t):
        value = int(n) * (1000 if unit == "tb" else 1)
        if value in (250, 500, 1000, 2000, 4000):
            caps.add({250: "250gb", 500: "500gb", 1000: "1tb", 2000: "2tb", 4000: "4tb"}[value])
    cap = caps.pop() if len(caps) == 1 else (UNKNOWN if not caps else "sprzeczne")
    return {"model": model, "pojemnosc": cap, "sztuk": rule_quantity({"title": text, "description": ""})}


# Desktopowe i5 2.-14. generacji (07.11: w próbce 17 z 30 ofert było spoza dawnej listy 8400-14600).
I5_MODELS = ("2400", "2500", "3470", "3570", "4460", "4570", "4590", "4690", "6400", "6500", "6600", "7400", "7500",
             "7600", "8400", "8500", "8600", "9400", "9500", "9600", "10400", "10500", "10600", "11400", "11500",
             "11600", "12400", "12500", "12600", "13400", "13500", "13600", "14400", "14500", "14600")
I5_SUFFIXES = {"": "brak", "f": "f", "k": "k", "kf": "kf", "t": "t", "s": "s"}


def rules_i5(text):
    t = text.lower()
    found = re.findall(r"\bi5\s?-?\s?(\d{4,5})\s?([a-z]{0,2})\b", t)
    models = {m for m, _s in found if m in I5_MODELS}
    model = models.pop() if len(models) == 1 else (UNKNOWN if not models else "sprzeczne")
    suffixes = {s for m, s in found if m in I5_MODELS}
    suffix = I5_SUFFIXES.get(suffixes.pop(), UNKNOWN) \
        if len(suffixes) == 1 else (UNKNOWN if not suffixes else "sprzeczne")
    return {"model": model, "sufiks": suffix, "sztuk": rule_quantity({"title": text, "description": ""})}


def rules_s23(text):
    t = text.lower()
    title = t.split("\n", 1)[0]       # akcesorium tylko z tytułu (07.11: „etui gratis” w opisie ≠ akcesorium)
    if re.search(r"\b(etui|case|husa|szk[lł]o|folia)\b", title) and not re.search(r"\d{2,3}\s*gb|telefon|smartfon",
                                                                                 title):
        return {"etykieta": "akcesorium"}
    if re.search(r"\bfe\b|s23\s?fe", t):
        return {"etykieta": "s23_fe"}
    if "ultra" in t:
        return {"etykieta": "s23_ultra"}
    if re.search(r"s\s?23\s?(?:plus|\+(?!\s*[a-ząćęłńóśźż]))", t):     # „S23 + etui” ≠ S23+
        return {"etykieta": "s23_plus"}
    return {"etykieta": "s23_base"}


_WORDS = {"dwie": 2, "dwa": 2, "dwóch": 2, "dwoch": 2, "trzy": 3, "cztery": 4}
# „x4” / „2X” / „1Rx8”, które NIE są liczbą sztuk (07.11: 17 z 30 dysków NVMe reguły liczyły jako 4 sztuki).
_NOT_QUANTITY = re.compile(
    r"pci-?e?\w*[\s.\d,/-]{0,12}?(?:gen\s*\d\s*)?[x×]\s*\d+|"                 # PCIe 3.0 x4, PCI-E x16
    r"\b(?:gen|nvme|lanes?|interfejs\w*|express)\s*\d?(?:\.\d)?\s*[x×]\s*\d+|"    # Gen4 x4, NVMe x4
    r"\b[2-6]\.0\s*[x×]\s*\d+|"                                                     # „4.0 x4 / 5.0 x2”
    r"\b[x×]\s*(?:1|4|8|16)\s*(?:pci|gen|lane|nvme)|"                            # x4 PCIe
    r"\b(?:ventus|windforce|twin|dual|eagle|gaming|frozr|torx|jetstream|phoenix|aero|pegasus|vision|turbo|storm|"
    r"ichill|mech|pulse|nitro|amp|aorus)\s*\d\s*[x×]|"                              # MSI Ventus 2X, WINDFORCE 3X
    r"\b\d\s*[x×]\s*(?:fan|wentylator|went|hdmi|dp\b|displayport|dvi|vga|usb|m\.?2|sata|\d?-?pin|nvme|slot|"
    r"z[lł][aą]cz|port|wiatrak)\w*|"                                              # 3x wentylator, 2x HDMI
    r"\b\d+\s*[x×]\s*\d+\s*(?:mm|cm)\b|\b\d+rx\d+\b|\b\d+[mg]\s*x\s*\d+-?bit|"  # 120x120mm, 1Rx8
    # 08.11 (porównanie z basalem): „4x3.6GHz” (rdzenie), „AGP 8x”, „4xMini-DP”, „Twin X2”, „Crucial X8”, „2x2 GB vram”
    # podwójnej karty, „x8 Micron” (szyna), „8x DVD”
    r"\b\d+\s*[x×]\s*\d(?:[.,]\d+)?\s*ghz|\b\d+\s*(?:rdzen\w*|cores?|threads?|watk\w*)|\bagp\s*\d+\s*[x×]?|"
    r"\b\d\s*[x×]\s*mini|\btwin\s*(?:oc\s*)?[x×]\s*\d|\b(?:crucial|sandisk|samsung|lexar|kingston)\s*[x×]\s*\d+|"
    r"\b\d+\s*[x×]\s*(?:dvd|cd|blu)", re.I)


def rule_quantity(offer):
    """Liczba sztuk z prostych reguł („2x8GB”, „x3”, „3 szt”, „dwie”; „cena za sztukę” → cena_za_sztuke)."""
    text = _NOT_QUANTITY.sub(" ", f"{offer['title']} {offer.get('description') or ''}".lower())
    if re.search(r"za sztuk|za szt\b|za jedn|za 1 ?szt|per (?:piece|unit|stick)|price (?:is )?for one\b", text):
        return "cena_za_sztuke"
    for pattern in (r"\b(\d+)\s*(?:szt|sztuk)", r"\b(\d)\s*[x×]\s*\d+\s*(?:gb|tb)", r"\b(\d)\s*[x×]\s*\d{1,2}\b", r"\b(\d)\s*[x×]\s",
                    r"\b[x×]\s*(\d)\b"):
        match = re.search(pattern, text)
        if match and int(match.group(1)) >= 1:
            n = int(match.group(1))
            return "5+" if n >= 5 else str(n)
    for word, n in _WORDS.items():
        if re.search(rf"\b{word}\b", text):
            return str(n)
    return "1"


# ---------------------------------------------------------------------------------------------- rodziny

FAMILIES = {
    "s23": {
        "name": "Samsung Galaxy S23 (telefony)", "category": "phone",
        "title": re.compile(r"(?<![a-z0-9])s\s?23(?!\d)", re.I), "rules": rules_s23, "flags": PHONE_FLAGS,
        "price": 1500,
        "questions": {"etykieta": _q("Co dokładnie jest sprzedawane? Czytaj cały opis - zaprzeczenia („nie FE”, "
                                     "„nie uszkodzony”) zmieniają znaczenie.", {
            "s23_base": "Samsung Galaxy S23 - podstawowy model (nie FE, nie Plus, nie Ultra), sprawny telefon",
            "s23_plus": "Samsung Galaxy S23+ / S23 Plus, sprawny telefon",
            "s23_ultra": "Samsung Galaxy S23 Ultra, sprawny telefon",
            "s23_fe": "Samsung Galaxy S23 FE (Fan Edition, tańsza wersja), sprawny telefon",
            "uszkodzony": "telefon S23 dowolnej wersji, ale uszkodzony, zbity, na części, nie działa albo zablokowany",
            "akcesorium": "nie telefon, tylko akcesorium albo część: etui, szkło, ładowarka, pudełko, obudowa",
            "podrobka": "podróbka / klon / replika („Ultra Mod”, nieznany producent), nie oryginalny Samsung",
            "inny": "inny telefon albo nie da się ustalić"})},
        "tricky": [
            ("Samsung Galaxy S23 128GB (nie FE!)", "Oryginalny S23, nie wersja FE. Bez rys, sprawny.",
             {"etykieta": "s23_base"}),
            ("Samsung S23 256GB", "Zbita szybka z tyłu, ekran pęknięty w rogu, działa.", {"etykieta": "uszkodzony"},
             700),
            ("Etui do Samsung S23 Ultra", "Sprzedam etui silikonowe, telefon niedostępny.", {"etykieta": "akcesorium"},
             25),
            ("Samsung Galaxy S23 FE 128GB", "Sprzedaję S23 FE zamiast zwykłego S23 - pomyłka.", {"etykieta": "s23_fe"}),
            ("Samsung s23 + etui", "Telefon S23 z etui w zestawie, sprawny.", {"etykieta": "s23_base"}),
            ("Samsung S23 Ultra Mod 16/512", "Dual SIM, to nie jest oryginał Samsunga.", {"etykieta": "podrobka"}, 450),
        ],
    },
    "gtx1060": {
        "name": "karty graficzne - GeForce GTX 1060", "category": "gpu", "title": re.compile(r"1060"),
        "rules": rules_gtx1060, "flags": PART_FLAGS, "price": 300,
        "questions": {
            "model": _q("Jaka karta jest sprzedawana? Uwaga: „wydajność jak GTX 1060” w opisie innej karty = inna "
                        "karta.", {"gtx1060": "GeForce GTX 1060 (desktop)",
                                   "inna": "inna karta albo inna rzecz (GTX 1060 tylko dla porównania)",
                                   UNKNOWN: "nie da się ustalić"}),
            "vram": _q("Ile pamięci (VRAM) ma TA karta? GTX 1060 występuje jako 3 GB, 5 GB i 6 GB. Szukaj w opisie, "
                       "naklejkach (np. „GTX 1060 3G”, „6G”, „GV-N1060…6GD”), nazwach modeli. Gdy nie wiadomo - "
                       "nie zgaduj.", {"3gb": "3 GB", "5gb": "5 GB", "6gb": "6 GB", UNKNOWN: "nie da się ustalić"}),
            "stan": CONDITION_PART, "sztuk": QUANTITY},
        "tricky": [
            ("GTX 1060", "Karta MSI GTX 1060 Gaming X, 6 GB GDDR5, sprawna.", {"vram": "6gb", "stan": "sprawna"}),
            ("GTX 1060 6GB", "Pomyłka w tytule - to wersja 3 GB (naklejka GTX 1060 3G).", {"vram": "3gb"}),
            ("Karta graficzna GTX 970", "Wydajność podobna do GTX 1060 6GB, w pełni sprawna.", {"model": "inna"}),
            ("GTX 1060", "Sprawna karta, wymieniłem na nowszą.", {"vram": UNKNOWN}),
            ("GTX 1060 6GB x2", "Dwie karty, cena za sztukę.", {"vram": "6gb", "sztuk": "cena_za_sztuke"}),
            ("GTX 1060 3GB", "Brak obrazu, wentylatory się kręcą.", {"vram": "3gb", "stan": "uszkodzona"}, 120),
            ("Chłodzenie GTX 1060", "Sam radiator z wentylatorami, karty brak.", {"stan": "czesc"}, 40),
            ("MSI GTX 1060 Gaming X 6G", "Karta do gier, chłodzenie Twin Frozr, 2X wentylatory.", {"sztuk": "1"}),
        ],
    },
    "rtx3060": {
        "name": "karty graficzne - GeForce RTX 3060 / 3060 Ti", "category": "gpu", "title": re.compile(r"3060"),
        "rules": rules_rtx3060, "flags": PART_FLAGS, "price": 950,
        "questions": {
            "model": _q("Który dokładnie model? RTX 3060 i RTX 3060 Ti to różne karty (Ti szybsza i droższa). Nazwa "
                        "„RTX 3060” bez „Ti” (także z dopiskami OC, Gaming, Ventus, 12G) = zwykła RTX 3060 - nie "
                        "trzeba pisać „bez Ti”.",
                        {"rtx3060": "GeForce RTX 3060 (bez Ti)", "rtx3060ti": "GeForce RTX 3060 Ti",
                         "inna": "inna karta albo inna rzecz", UNKNOWN: "nie da się ustalić"}),
            "vram": _q("Ile pamięci (VRAM) ma TA karta? RTX 3060: 12 GB albo 8 GB; RTX 3060 Ti: 8 GB. Gdy nie "
                       "wiadomo - nie zgaduj.", {"8gb": "8 GB", "12gb": "12 GB", UNKNOWN: "nie da się ustalić"}),
            "stan": CONDITION_PART, "sztuk": QUANTITY},
        "tricky": [
            ("RTX 3060", "Gigabyte RTX 3060 Eagle 12G, sprawna, nie kopała.", {"model": "rtx3060", "vram": "12gb"}),
            ("RTX 3060 Ti", "Uwaga: to zwykła RTX 3060 8GB, nie Ti - pomyliłem się w tytule.",
             {"model": "rtx3060", "vram": "8gb"}),
            ("RTX 3060 12GB", "Karta w pełni sprawna, bez artefaktów.", {"model": "rtx3060", "stan": "sprawna"}),
            ("RTX 3060", "Sprawna, używana do gier.", {"vram": UNKNOWN}),
            ("RTX3060 Ti Heatsink with Fan", "Sam radiator z wentylatorem, bez układu.", {"stan": "czesc"}, 60),
            ("Komputer gamingowy RTX 3060 Ryzen 5", "Cały zestaw PC.", {"stan": "zestaw"}, 2800),
            ("MSI RTX 3060 Ventus 2X 12G OC", "Sprawna, złącze PCIe 4.0 x16.", {"vram": "12gb", "sztuk": "1"}),
            ("Asus Dual RTX 3060 Ti", "Grafikminne 8GB GDDR6, fungerar perfekt.", {"model": "rtx3060ti", "vram": "8gb"}),
        ],
    },
    "ddr4": {
        "name": "pamięć RAM (wszystkie typy: DDR2 i starsze, DDR3, DDR4, DDR5)", "category": "ram",
        "title": re.compile(r"ddr|ram|pc[2345]|simm|dimm", re.I), "rules": rules_ddr4, "flags": PART_FLAGS,
        "price": 150,
        "questions": {
            "typ": _q("Jaki typ pamięci? Uwaga: „to nie DDR3”; „PC2” = DDR2, „PC3” / „PC3L” = DDR3, „PC4” = DDR4, "
                      "„PC5” = DDR5; SIMM, EDO, SDRAM (bez DDR) i samo „DDR” = stare.",
                      {"ddr2_starsza": "DDR2 albo starsza (DDR, SDRAM, SIMM, EDO)", "ddr3": "DDR3 / DDR3L",
                       "ddr4": "DDR4", "ddr5": "DDR5", UNKNOWN: "nie da się ustalić"}),
            "mhz": _q("Jakie jest ZNAMIONOWE taktowanie kości (z naklejki / specyfikacji / XMP), nie to, na którym "
                      "pracowały w komputerze? Kod z naklejki: liczba / 8, np. PC3-12800 = 1600, PC4-17000 = 2133, "
                      "PC4-21300 = 2666, PC4-25600 = 3200, PC5-38400 = 4800; „PC4-3200AA” = 3200, "
                      "„DDR4-2400” = 2400. Gdy nie wiadomo - nie zgaduj.", {**SPEED_LABELS, UNKNOWN: "nie da się ustalić"}),
            "forma": _q("Do czego jest pamięć? Kość do laptopa (SO-DIMM) jest krótka, kod naklejki PC4-…-S; do PC "
                        "(DIMM) długa, PC4-…-U; serwerowa ECC / registered.",
                        {"pc": "do komputera stacjonarnego (DIMM)", "laptop": "do laptopa (SO-DIMM)",
                         "serwer": "serwerowa (ECC / registered)", UNKNOWN: "nie da się ustalić"}),
            "stan": CONDITION_PART, "sztuk": QUANTITY},
        "tricky": [
            ("Pamięć RAM 16GB DDR4", "Kości 3200 MHz, w moim komputerze pracowały na 2133.", {"mhz": "3200"}),
            ("Pamięć RAM 2x16 MB EDO", "Stare kości SIMM do komputera retro.", {"typ": "ddr2_starsza"}, 40),
            ("Hynix 4GB PC3L-12800S", "Z laptopa, sprawna.", {"typ": "ddr3", "mhz": "1600", "forma": "laptop"}, 30),
            ("Pamięć 8GB DDR4 2666", "Not for laptops - desktop DIMM.", {"forma": "pc"}),
            ("Kingston HyperX DDR2 4x1GB", "Komplet 4 kości 1066 MHz.", {"typ": "ddr2_starsza", "mhz": "1066",
                                                                       "sztuk": "4"}, 60),
            ("RAM 8GB 1600MHz", "Pamięć DDR3, nie DDR4 - uwaga przy zakupie.", {"typ": "ddr3"}),
            ("Kingston 8GB PC4-21300", "Do PC, jedna kość.", {"typ": "ddr4", "mhz": "2666", "forma": "pc"}),
            ("RAM DDR4 16GB 2x8", "Kości SO-DIMM z laptopa Dell, 2400 MHz.", {"forma": "laptop", "mhz": "2400",
                                                                           "sztuk": "2"}),
            ("Pamięć DDR4 3200", "Opis z naklejki: PC4-2133P-UA0. Działa.", {"mhz": "2133"}),
            ("RAM DDR4 8GB", "Cena za sztukę, mam 4 kości.", {"sztuk": "cena_za_sztuke"}),
            ("Corsair Vengeance 16GB", "Zestaw 2x8 GB DDR4, XMP 3600, bez XMP 2133.", {"mhz": "3600", "sztuk": "2"}),
            ("Kość SK Hynix 8GB DDR4 2400MHz 1Rx8", "Jedna kość, sprawna.", {"mhz": "2400", "sztuk": "1"}),
            ("Samsung 16GB DDR4 ECC", "Serwerowa, registered.", {"forma": "serwer"}),
        ],
    },
    "nvme": {
        "name": "dyski - Samsung 970 / 980 / 990", "category": "storage", "title": re.compile(r"\b9[789]0\b"),
        "rules": rules_nvme, "flags": PART_FLAGS, "price": 300,
        "questions": {
            "model": _q("Który dokładnie model dysku Samsung? 970 EVO, 970 EVO Plus, 980, 980 PRO, 990 EVO, 990 EVO Plus "
                        "i 990 PRO to różne dyski. Samego „990” (bez PRO / EVO) nie ma - wtedy nie zgaduj.",
                        {"970evo": "970 EVO (bez Plus)", "970evoplus": "970 EVO Plus", "970pro": "970 PRO",
                         "980": "980 (bez PRO)", "980pro": "980 PRO", "990pro": "990 PRO",
                         "990evo": "990 EVO (bez Plus)", "990evoplus": "990 EVO Plus",
                         "inny": "inny dysk albo inna rzecz", UNKNOWN: "nie da się ustalić"}),
            "pojemnosc": _q("Jaka pojemność TEGO dysku? Gdy nie wiadomo - nie zgaduj.",
                            {"250gb": "250 GB", "500gb": "500 GB", "1tb": "1 TB", "2tb": "2 TB", "4tb": "4 TB",
                             UNKNOWN: "nie da się ustalić"}),
            "stan": CONDITION_PART, "sztuk": QUANTITY},
        "tricky": [
            ("Samsung 970 EVO 1TB", "Wersja Plus, kupiona w 2021, zdrowie 98%.", {"model": "970evoplus",
                                                                                "pojemnosc": "1tb"}),
            ("Samsung 980 Pro 1TB", "To zwykły 980 (bez PRO), pomyłka w tytule.", {"model": "980"}),
            ("Dysk Samsung 980 PRO", "Pojemność 2 TB, sprawny.", {"pojemnosc": "2tb", "stan": "sprawna"}),
            ("Samsung 970 EVO Plus 500GB", "Dysk nie jest wykrywany przez BIOS.", {"stan": "uszkodzona"}, 60),
            ("Radiator do Samsung 980 PRO", "Sam radiator, dysku brak.", {"stan": "czesc"}, 30),
            ("Samsung 990 PRO 2TB x2", "Dwa dyski, cena za całość.", {"sztuk": "2"}, 1100),
            ("Samsung 990 EVO Plus 1TB", "Nowy, PCIe 4.0 x4 / 5.0 x2.", {"model": "990evoplus", "sztuk": "1"}),
        ],
    },
    "i5": {
        "name": "procesory - Intel Core i5", "category": "cpu", "title": re.compile(r"\bi5", re.I),
        "rules": rules_i5, "flags": PART_FLAGS, "price": 350,
        "questions": {
            "model": _q("Który model procesora Intel Core i5 (numer)? Gdy nie wiadomo - nie zgaduj.",
                        {**{m: f"i5-{m}" for m in I5_MODELS},
                         "inny": "inny procesor (i5 spoza listy, i3, i7, AMD) albo inna rzecz",
                         UNKNOWN: "nie da się ustalić"}),
            "sufiks": _q("Jaka litera stoi BEZPOŚREDNIO po numerze modelu SPRZEDAWANEGO procesora? Liczy się tylko "
                         "ten numer - nie procesory wymienione dla porównania i nie litery w innych słowach („CPU-k”, "
                         "„OC”). „i5 9400 f” = F; „wersja F”, „bez grafiki zintegrowanej” = F; „nie F”, „ma grafikę” "
                         "= bez litery. Numer podany bez litery i nic o F / K = bez litery.",
                         {"brak": "bez litery po numerze (np. i5-12400, i5-6500) - zwykły, z grafiką",
                          "f": "F po numerze (np. i5-10400F, i5-9400F) - bez grafiki",
                          "k": "K po numerze (np. i5-9600K, i5-6600K) - odblokowany",
                          "kf": "KF po numerze (np. i5-12600KF) - odblokowany, bez grafiki",
                          "t": "T po numerze (np. i5-8500T) - energooszczędny",
                          "s": "S po numerze (np. i5-4570S) - obniżony pobór",
                          UNKNOWN: "nie da się ustalić (np. nie wiadomo nawet, który to model)"}),
            "stan": CONDITION_PART, "sztuk": QUANTITY},
        "tricky": [
            ("Intel i5 9400 f", "Sam procesor, sprawny.", {"model": "9400", "sufiks": "f"}),
            ("Intel Core i5-9400", "Wersja F, czyli bez grafiki - potrzebna karta.", {"model": "9400", "sufiks": "f"}),
            ("i5-10400F", "Uwaga: to nie F - ma grafikę, w tytule pomyłka.", {"model": "10400", "sufiks": "brak"}),
            ("Procesor i5 12400", "Sprawny, z boxowym chłodzeniem.", {"model": "12400", "sufiks": "brak",
                                                                     "stan": "sprawna"}),
            ("i5-9600K + płyta Z390", "Zestaw procesor i płyta, działają.", {"model": "9600", "sufiks": "k",
                                                                            "stan": "zestaw"}, 600),
            ("Intel i5 8. generacji", "Procesor desktop, model 8400.", {"model": "8400"}),
            ("Chłodzenie do i5", "Sam cooler, procesora brak.", {"stan": "czesc"}, 30),
            ("Intel core i5 (sam wiatrak)", "Wiatrak do procesora i5, nowy.", {"stan": "czesc"}, 30),
            ("Intel Core i5-6500", "Sprawny, z chłodzeniem BOX gratis.", {"model": "6500", "sufiks": "brak",
                                                                          "stan": "sprawna"}, 110),
            ("I5-8600K", "Wydajność jak i5-10400F, sprawny.", {"model": "8600", "sufiks": "k"}, 220),
        ],
    },
}

# ---------------------------------------------------------------------------------------------- pułapki językowe

_DAMAGE = (r"uszkodz|nie dzia|niedzia|na cz[eę][sś]ci|artefakt|brak obrazu|czarny ekran|czerwony ekran|bad ?sector|"
           r"smart\W{0,3}(?:\d|status|b[lł][eę]d|error|warn|ostrze)|wygi[eę]t|nie wykrywa|nie odpala|nie w[lł][aą]cza|"
           r"nie startuje|zbit|p[eę]kni|broken|defekt|faulty|not working|for parts|nefunk|nem m[uű]k|nu func")
SIGNALS = {
    "zaprzeczenie": re.compile(
        r"\b(?:nie|bez|brak|[zż]adn\w*|zero|no|not|nicht|nem|fara)\W+(?:\w+\W+){0,3}?"
        r"(?:uszkodz|artefakt|wad|problem|b[lł][eę]d|rys|p[eę]kni|zbit|kopan|koparc|damage|issue|ddr\d|ti\b|f\b|"
        r"pro\b|plus|fe\b)", re.I),
    "uszkodzenie / niepewny stan": re.compile(_DAMAGE + r"|nie testowan|nietestowan|niesprawdzon|stan nieznany|"
                                              r"jak jest|as is", re.I),
    "cena za sztukę": re.compile(r"za sztuk|za szt\b|za szt\.|za jedn|cena za 1|za ko[sś][cć]|per piece|each\b|darab",
                                 re.I),
    "kilka sztuk / zestaw": re.compile(r"\d\s*[x×]\s*\d|\b[x×]\s*\d\b|\d\s*[x×]\b|\b\d+\s*szt|komplet|\bkit\b|"
                                       r"\bdwie\b|\bdwa\b|\btrzy\b|\bcztery\b", re.I),
    "część / akcesorium": re.compile(r"radiator|heatsink|ch[lł]odzeni|wentylator|backplate|obudow|kiesze[nń]|adapter|"
                                     r"riser|pude[lł]k|\bbox\b|bez karty|bez dysku|bez procesora", re.I),
    "porównanie z innym modelem": re.compile(r"\bjak\b|podobn|odpowiednik|lepsz\w* ni[zż]|wydajno[sś][cć]|"
                                             r"zamiast|vs\.?\b|\bniż\b", re.I),
    "pomyłka / korekta": re.compile(r"pomy[lł]|b[lł][aą]d w tytule|w tytule|tak naprawd|uwaga|sprostow|w rzeczywisto",
                                    re.I),
    "taktowanie inne niż znamionowe": re.compile(r"pracowa[lł]\w* na|dzia[lł]a\w* na|\bxmp\b|podkr[eę]c|\boc\b|"
                                                 r"overclock", re.I),
    "zamiana / kupię": re.compile(r"zamian|zamieni|kupi[eę]|szukam|swap|\bwtb\b", re.I),
}
_POLISH = re.compile(r"\b(?:jest|nie|się|sie|bardzo|stan|sprzedam|karta|dysk|pami[eę][cć]|procesor|telefon|dzia[lł]a)\b",
                     re.I)


def variant_signals(title, description, family):
    """Pułapki wariantu: tytuł nie mówi X / opis zmienia X (reguły rodziny z tytułu vs z tytułu + opisu)."""
    rules = FAMILIES[family]["rules"]
    by_title = rules(title or "")
    by_all = rules(f"{title or ''}\n{description or ''}")
    out = []
    for key, value in by_title.items():
        full = by_all.get(key)
        if key == "sztuk":
            if rule_quantity({"title": title or "", "description": description or ""}) != value:
                out.append("liczba sztuk z opisu")
            continue
        if value == UNKNOWN and full not in (UNKNOWN, None):
            out.append(f"tytuł bez: {key} (jest w opisie)")
        elif value == UNKNOWN:
            out.append(f"tytuł bez: {key} (nigdzie)")
        elif full != value:
            out.append(f"opis zmienia: {key}")
    return out


def language_signals(title, description, family):
    text = f"{title or ''}\n{description or ''}"
    found = [name for name, pattern in SIGNALS.items() if pattern.search(text)]
    if description and len(description) > 40 and not _POLISH.search(description):
        found.append("opis po obcemu")
    return found


# ---------------------------------------------------------------------------------------------- krok 2: próbka

def _is_variant(group):
    return group.startswith(("tytuł bez", "opis zmienia", "liczba sztuk"))


def sample(conn, family="gtx1060", limit=30, seed=7, hard=True):
    """Oferty rodziny z opisem → (lista słowników, liczby ofert na pułapkę).
    hard=True: tylko oferty z pułapką; najpierw pułapki WARIANTU (tytuł bez wariantu, opis zmienia wariant), potem
    językowe; po kolei z każdego rodzaju, w obrębie rodzaju - najwięcej pułapek naraz. hard=False - losowo."""
    fam = FAMILIES[family]
    sql = """SELECT l.id, l.title, l.price_now, l.sold_price, l.state, l.status_label, d.description
             FROM listings l JOIN details d ON d.listing_id = l.id
             WHERE l.category = ? AND d.description IS NOT NULL"""
    groups, signals_of = {}, {}
    for r in conn.execute(sql, (fam["category"],)):
        if fam["title"] is not None and not fam["title"].search(r[1] or ""):
            continue
        variant = variant_signals(r[1], r[6], family)
        found = variant + language_signals(r[1], r[6], family)
        if hard and not found:
            continue
        signals_of[r[0]] = (variant, found)
        for name in (found if hard else ["losowo"]):
            groups.setdefault(name, []).append(r)
    rnd = random.Random(seed)
    for rows in groups.values():
        rnd.shuffle(rows)
        rows.sort(key=lambda r: (-len(signals_of[r[0]][0]), -len(signals_of[r[0]][1])))
    order = sorted(groups, key=lambda g: (not _is_variant(g), g))
    picked, seen, i = [], set(), 0
    while len(picked) < limit and any(i < len(groups[g]) for g in order):
        for name in order:
            if i < len(groups[name]) and len(picked) < limit and groups[name][i][0] not in seen:
                seen.add(groups[name][i][0])
                picked.append(groups[name][i])
        i += 1
    out = []
    for r in picked:
        price = r[3] if r[4] == "sold" and r[3] else r[2]
        out.append({"id": r[0], "title": r[1], "price": price, "state": r[4], "condition": r[5],
                    "hint": " + ".join(signals_of[r[0]][1]) or "losowo",
                    "description": redact((r[6] or "")[:DESCRIPTION_CHARS])})
    return out, {k: len(v) for k, v in groups.items()}


def print_sample(rows, counts):
    print("Pułapki w bazie (ofert): " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    for n, r in enumerate(rows, 1):
        desc = " ".join(r["description"].split())[:160]
        price = f"{r['price']:.0f} zł" if r["price"] else "? zł"
        print(f"\n{n:>3}. {r['title']} | {price} | {r['condition'] or '?'} | {r['state']}")
        print(f"     [{r['hint']}]")
        print(f"     {desc}")


def save_sample(rows, family, out_dir):
    path = Path(out_dir) / "basal" / f"{family}_{datetime.now():%Y%m%d_%H%M}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(dumps_line(r) + "\n" for r in rows), encoding="utf-8")
    return path


_LINE_BREAKS = {"\u2028": "\\u2028", "\u2029": "\\u2029", "\x85": "\\u0085"}


def dumps_line(row):
    """JSON w jednej linii także dla edytorów i splitlines() (znaki U+2028 / U+2029 / U+0085 jako \\uXXXX)."""
    text = json.dumps(row, ensure_ascii=False)
    for char, escaped in _LINE_BREAKS.items():
        text = text.replace(char, escaped)
    return text


def load_sample(path):
    """Próbka JSONL → lista słowników. Dzieli tylko po \\n (stare próbki mają w opisach U+2028 bez ucieczki)."""
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").split("\n") if line.strip()]


# ---------------------------------------------------------------------------------------------- krok 3: test basal

# Kategoria w treści dla basala - ogólna, nie nazwa rodziny. 08.11: „Kingston 8GB PC4-21300, do PC” w rodzinie
# „RAM DDR4 SO-DIMM (laptop)” basal oceniał na laptop (93%), w rodzinie DDR5 - na DDR5 (98%): nazwa rodziny
# (przypisanej z tytułu regexem, więc czasem błędnie) podpowiadała odpowiedź.
CATEGORY_LABELS = {"phone": "telefony komórkowe", "tablet": "tablety i czytniki e-booków",
                   "console": "konsole i akcesoria do gier", "laptop": "laptopy", "gpu": "karty graficzne",
                   "ram": "pamięć RAM", "storage": "dyski i nośniki danych", "cpu": "procesory",
                   "motherboard": "płyty główne", "bundle": "zestawy podzespołów komputerowych"}


def state_text(offer, family):
    """Stan dla basala. Rodziny v2: także pola formularza Vinted (model, pamięć, bateria, RAM / dysk laptopa,
    platforma) z ostrzeżeniem, że bywają błędne („256 MB”, RAM w polu dysku)."""
    from .basal_families import form_text
    price = f"{offer['price']:.0f} zł" if offer.get("price") else "?"
    form = form_text(offer.get("form") or {})
    form = f"Formularz Vinted (wypełnia sprzedawca, bywa błędny): {form}\n" if form else ""
    fam = FAMILIES[family]
    kind = CATEGORY_LABELS.get(fam.get("category")) or fam["name"]
    return (f"Ogłoszenie z Vinted (kategoria: {kind}).\nTytuł: {offer['title']}\nCena: {price}\n"
            f"Stan (formularz): {offer.get('condition') or '?'}\n{form}Opis: {offer.get('description') or ''}")


def build_request(offer, family):
    fam = FAMILIES[family]
    questions = {name: {"type": "choice", **q} for name, q in fam["questions"].items()}
    questions.update({k: {"type": "noul", "instructions": v} for k, v in fam["flags"].items()})
    return {"state": state_text(offer, family), "questions": questions}


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


def _pct(p):
    return "?" if p is None else f"{p:.0%}"


TEST_CONDITION = "Bardzo dobry"      # stan z formularza dla przypadków testowych (jak w prawdziwych ofertach)
CONFIDENT = 0.7                     # próg pewności bramkarza (podsumowanie: trafność powyżej / poniżej)


def _ask(client, url, offer, family):
    started = time.perf_counter()
    response = client.post(f"{url.rstrip('/')}/v1/systemone", json=build_request(offer, family))
    response.raise_for_status()
    return response.json().get("answers") or {}, (time.perf_counter() - started) * 1000


def run_test(rows, family="gtx1060", url="http://127.0.0.1:8000", client=None, with_tricky=True, say=print,
             parallel=1):
    """Każda oferta → POST /v1/systemone. → (wyniki, podsumowanie). Rzuca httpx.HTTPError przy braku serwera.
    parallel > 1: tyle ofert naraz (llama-server -np N, basal-serve --http-parallel N) - więcej pracy dla karty."""
    import httpx
    from concurrent.futures import ThreadPoolExecutor
    fam = FAMILIES[family]
    cases = [dict(r, expected={}) for r in rows]
    if with_tricky:
        for i, case in enumerate(fam["tricky"], 1):
            if isinstance(case, dict):              # rodziny v2: słownik z formularzem
                cases.append({"id": f"test{i}", "title": case["title"], "description": case["description"],
                              "price": case.get("price") or fam["price"],
                              "condition": (case.get("form") or {}).get("status") or TEST_CONDITION,
                              "form": case.get("form") or {}, "hint": "[test]", "expected": case["expected"]})
                continue
            title, desc, expected, *price = case
            cases.append({"id": f"test{i}", "title": title, "description": desc, "price": (price or [fam["price"]])[0],
                          "condition": TEST_CONDITION, "hint": "[test]", "expected": expected})
    own = client is None
    client = client or httpx.Client(timeout=120.0, trust_env=False)
    before = vram_used()
    peak = before[0] if before else None
    results, times = [], []
    started_all = time.perf_counter()
    pool = ThreadPoolExecutor(max_workers=max(1, parallel))
    try:
        replies = pool.map(lambda offer: _ask(client, url, offer, family), cases)
        for n, (offer, (answers, wall)) in enumerate(zip(cases, replies), 1):
            if n % 10 == 0 or n == len(cases):
                now = vram_used()
                if now and (peak is None or now[0] > peak):
                    peak = now[0]
            times.append(wall)
            got = {q: (answers.get(q) or {}).get("choice") for q in fam["questions"]}
            conf = {q: (answers.get(q) or {}).get("confidence") for q in fam["questions"]}
            flags = {k: (answers.get(k) or {}).get("noul") for k in fam["flags"]}
            if fam.get("v2"):
                by_title = fam["rules"](offer["title"])
                by_all = fam["rules"](offer["title"], offer.get("description") or "", offer.get("form") or {})
            else:
                by_title = fam["rules"](offer["title"])
                by_all = fam["rules"](f"{offer['title']}\n{offer.get('description') or ''}")
                if "sztuk" in fam["questions"]:
                    by_all["sztuk"] = rule_quantity(offer)
            results.append({"id": offer["id"], "title": offer["title"], "answers": got, "confidence": conf,
                            "flags": flags, "rules_title": by_title, "rules_all": by_all,
                            "expected": offer["expected"], "ms": round(wall)})
            say(f"{n:>3}. {offer['title'][:70]}")
            say("      " + " | ".join(f"{q}: {got[q]} ({_pct(conf[q])})" for q in fam["questions"]) +
                (" | " + ", ".join(f"{k.replace('_', ' ')} {_pct(v)}" for k, v in flags.items()) if flags else "") +
                f" | {wall:.0f} ms")
            marks = [f"{q} OK" if got.get(q) == want else f"{q} BŁĄD (oczekiwane {want})"
                     for q, want in offer["expected"].items()]
            if not offer["expected"]:
                for q in fam["questions"]:
                    rule = by_all.get(q)
                    if rule not in (None, UNKNOWN, "sprzeczne") and got[q] != rule:
                        marks.append(f"{q} ≠ reguły: {rule}")
                    elif rule in (None, UNKNOWN, "sprzeczne") and got[q] not in (None, UNKNOWN) and q in by_title:
                        marks.append(f"{q}: basal wie ({got[q]}), reguły nie")
            if marks:
                say("      " + "; ".join(marks))
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        if own:
            client.close()
    elapsed = time.perf_counter() - started_all
    summary = {"ofert": len(results),
               "czas_ms": {"średnio": round(statistics.mean(times)), "mediana": round(statistics.median(times)),
                           "max": round(max(times)), "pierwsza (z rozgrzewką)": round(times[0]),
                           "ofert na minutę": round(len(results) / elapsed * 60), "naraz": parallel}
               if times else {},
               "vram_mb": {"przed": before[0] if before else None, "szczyt": peak,
                           "karta": before[2] if before else None, "razem_mb": before[1] if before else None},
               "przypadki_testowe": {}, "zgodność z regułami (tytuł + opis)": {}}
    for q in fam["questions"]:
        tested = [r for r in results if q in r["expected"]]
        if tested:
            summary["przypadki_testowe"][q] = f"{sum(r['answers'][q] == r['expected'][q] for r in tested)}/{len(tested)}"
        known = [r for r in results if not r["expected"] and r["rules_all"].get(q) not in (None, UNKNOWN, "sprzeczne")]
        if known:
            summary["zgodność z regułami (tytuł + opis)"][q] = \
                f"{sum(r['answers'][q] == r['rules_all'][q] for r in known)}/{len(known)}"
    summary[f"pewność ≥ {CONFIDENT:.0%} (wzorzec: oczekiwane, inaczej reguły)"] = confidence_split(results, fam)
    return results, summary


def confidence_split(results, fam, threshold=CONFIDENT):
    """Per pytanie: ile odpowiedzi pewnych (≥ progu) i ile z nich zgodnych ze wzorcem, to samo dla niepewnych.
    Wzorzec = oczekiwana odpowiedź przypadku testowego, a dla prawdziwych ofert reguły z tytułu + opisu (gdy znane)."""
    out = {}
    for q in fam["questions"]:
        sure, unsure = [0, 0], [0, 0]
        for r in results:
            want = r["expected"].get(q) if r["expected"] else r["rules_all"].get(q)
            if want in (None, UNKNOWN, "sprzeczne") and q not in r["expected"]:
                continue
            bucket = sure if (r["confidence"].get(q) or 0) >= threshold else unsure
            bucket[0] += r["answers"].get(q) == want
            bucket[1] += 1
        if sure[1] or unsure[1]:
            out[q] = f"pewne {sure[0]}/{sure[1]} zgodnych, niepewne {unsure[0]}/{unsure[1]}"
    return out


def family_from_path(path):
    """gtx1060_20261107_1225.jsonl → gtx1060, galaxy_s23_20261107.jsonl → galaxy_s23 (najdłuższa nazwa rodziny
    z początku nazwy pliku, przed „_<cyfry>”); None, gdy nie pasuje."""
    name = Path(path).name
    hits = [f for f in FAMILIES if re.match(rf"{re.escape(f)}_\d", name)]
    return max(hits, key=len) if hits else None


def save_results(results, summary, sample_path, label=""):
    tag = f"{label}_" if label else ""
    path = Path(sample_path).with_name(Path(sample_path).stem + f"_wyniki_{tag}{datetime.now():%H%M}.json")
    path.write_text(json.dumps({"podsumowanie": summary, "wyniki": results}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------------------------------------- rodziny v2

from .basal_families import build_families as _build_v2  # noqa: E402

FAMILIES.update(_build_v2())
