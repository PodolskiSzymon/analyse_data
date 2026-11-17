r"""Komputery stacjonarne pod gry (2026-11-17, prośba użytkownika): zestawy 2000-3000 zł z bazy analizatora, które
pociągną gry wyścigowe (Forza Horizon 5, F1, Assetto Corsa, NFS) na wysokich ustawieniach w 1080p, a po dołożeniu
RAM-u (do 32 GB) mają szansę na GTA 6 na niskich-średnich.

GTA 6 na PC: Rockstar nie podał wymagań (stan wiedzy: wersja PC później niż konsolowa) - poziom „GTA 6” to SZACUNEK
z wymagań gier na tym samym silniku i z konsol (PS5 ≈ RTX 2070 Super / RX 6700, 6 rdzeni Zen 2): karta co najmniej
RTX 3060 / RX 6600 XT / RTX 2070 Super (8+ GB VRAM), procesor 6 rdzeni / 12 wątków (Ryzen 5 3600 / i5-10400F
i nowsze), 16 GB RAM (z miejscem na 32), dysk SSD.

Tylko odczyt bazy, bez sieci. Specyfikacja z tytułu i opisu (te same reguły co analizator: analyzer/extract.py).
Użycie (na serwerze, w folderze analyse_data, gdy watch przejdzie katalog 3581):
  python narzedzia\pc_gry.py
  python narzedzia\pc_gry.py --od 2000 --do 3000 --limit 40
"""
import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Karty: (poziom 0-3, opis). 3 = GTA 6 nisko-średnio (szacunek) i wyścigi ultra, 2 = wyścigi wysoko, GTA 6 na
# granicy, 1 = wyścigi średnio, 0 = za słaba.
GPU_TIERS = [
    (r"rtx 40[67]0|rtx 30[78]0|rtx 3060 ti|rtx 2080|rx 6[789]\d0|rx 7[67]00|arc a7[57]0", 3),
    (r"rtx 3060|rtx 2070 super|rx 6600 xt|rx 6650 xt", 3),
    (r"rtx 2070|rtx 2060 super|rx 6600|rx 5700|arc a580|gtx 1080 ti", 2),
    (r"rtx 2060|gtx 1080|rx 5600|gtx 1070|rx 3050|rtx 3050", 1),
    (r"gtx 16\d0|rx 590|rx 580|gtx 1060", 1),
]
# Procesory: (wzór, poziom 0-2). 2 = 6 rdzeni / 12 wątków nowoczesne (GTA 6), 1 = wystarczy do wyścigów, 0 = słabe.
CPU_TIERS = [
    (r"ryzen [579] [57]\d{3}|ryzen [579] 9\d{3}|i[579]-1[2-5]\d{3}|ultra [579]", 2),
    (r"ryzen [579] 3\d{3}|ryzen 7 2700|i[579]-1[01]\d{3}|i7-[89]\d{3}|i9-9\d{3}|i5-11\d{3}", 2),
    (r"ryzen 5 2600|ryzen 5 1600|i5-[89]\d{3}|i7-[67]\d{3}|xeon e5-26[5-9]\d", 1),
]


def tier(table, name):
    name = (name or "").lower()
    for pattern, level in table:
        if re.search(pattern, name):
            return level
    return 0


def score(spec):
    """(ocena 0-10, uwagi) - im wyżej, tym lepiej pod wyścigi wysoko i GTA 6 po dołożeniu RAM."""
    notes = []
    gpu, cpu = tier(GPU_TIERS, spec.get("gpu")), tier(CPU_TIERS, spec.get("cpu"))
    ram, ssd = spec.get("ram_gb"), spec.get("storage_gb")
    points = gpu * 2 + cpu * 1.5                     # karta najważniejsza
    if not spec.get("gpu") or spec.get("gpu") == "integrated":
        notes.append("brak karty graficznej w opisie")
    elif gpu < 2:
        notes.append("karta za słaba na GTA 6")
    if not spec.get("cpu"):
        notes.append("procesor nieznany")
    elif cpu < 2:
        notes.append("procesor słabszy niż 6 rdzeni / 12 wątków nowej generacji")
    if ram:
        points += 1 if ram >= 16 else 0
        if ram < 16:
            notes.append(f"RAM {ram} GB - dokup do 32")
        elif ram < 32:
            notes.append(f"RAM {ram} GB - pod GTA 6 dołożyć do 32 GB")
    else:
        notes.append("RAM nieznany")
    if ssd:
        points += 1
    else:
        notes.append("dysk nieznany (potrzebny SSD)")
    if spec.get("psu_w") and spec["psu_w"] < 500 and gpu >= 2:
        notes.append(f"zasilacz {spec['psu_w']} W - słaby pod tę kartę")
    return round(min(points, 10.0), 1), notes


def main():
    from analyzer import extract

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baza", default=os.getenv("ANALYZER_DB", r"C:\Users\szymo\category_analyzer\data\analyzer.db"))
    ap.add_argument("--od", type=float, default=2000)
    ap.add_argument("--do", type=float, default=3000)
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument("--wszystkie", action="store_true", help="także zestawy, które nie spełniają wymagań GTA 6")
    a = ap.parse_args()
    conn = sqlite3.connect(f"file:{a.baza}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""SELECT l.id, l.title, l.price_now, l.status_label, l.first_seen, d.description,
                                  d.attributes_json
                           FROM listings l LEFT JOIN details d ON d.listing_id = l.id
                           WHERE l.catalog_id = 3581 AND l.state IN ('active', 'reserved')
                             AND l.price_now BETWEEN ? AND ?""", (a.od, a.do)).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM listings WHERE catalog_id = 3581").fetchone()[0]
    print(f"Komputery w bazie: {total}; aktywne {a.od:.0f}-{a.do:.0f} zł: {len(rows)} "
          f"(ze szczegółami: {sum(1 for r in rows if r['description'] is not None)})", flush=True)
    import json
    found = []
    for r in rows:
        try:
            attrs = json.loads(r["attributes_json"]) if r["attributes_json"] else {}
        except ValueError:
            attrs = {}
        fields, _key = extract.extract("desktop", r["title"], r["description"] or "", attrs)
        spec = {k: v["value"] for k, v in (fields or {}).items()}
        if spec.get("for_parts") or spec.get("locked"):
            continue
        points, notes = score(spec)
        ok = tier(GPU_TIERS, spec.get("gpu")) >= 2 and tier(CPU_TIERS, spec.get("cpu")) >= 1
        if ok or a.wszystkie:
            found.append((points, r, spec, notes))
    found.sort(key=lambda x: (-x[0], x[1]["price_now"]))
    print(f"Spełnia minimum (karta poziomu RTX 2070 / RX 6600 i lepsza, sensowny procesor): "
          f"{sum(1 for f in found if tier(GPU_TIERS, f[2].get('gpu')) >= 2)}\n")
    for points, r, spec, notes in found[:a.limit]:
        parts = [spec.get("cpu"), spec.get("gpu"), f"{spec['ram_gb']} GB RAM" if spec.get("ram_gb") else None,
                 f"dysk {spec['storage_gb']} GB" if spec.get("storage_gb") else None,
                 f"zasilacz {spec['psu_w']} W" if spec.get("psu_w") else None]
        print(f"{points:4.1f}/10  {r['price_now']:6.0f} zł  {', '.join(p for p in parts if p) or '?'}")
        print(f"          {(r['title'] or '')[:70]}  https://www.vinted.pl/items/{r['id']}")
        if notes:
            print(f"          uwagi: {'; '.join(notes)}")
    if not rows:
        print("Brak ofert - watch jeszcze nie przeszedł katalogu 3581 (zrób git pull i restart watch, odczekaj "
              "jedno przejście).")


if __name__ == "__main__":
    main()
