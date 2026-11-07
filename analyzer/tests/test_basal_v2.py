"""Rodziny basala v2 (07.11): budowa, przypisanie oferty do rodziny, reguły, próbka z bazy, test na atrapie, raport."""
import json

import httpx

from analyzer import basal_families as B
from analyzer import basal_poc, basal_report, db

F = basal_poc.FAMILIES


def test_families_build_and_labels():
    v2 = {k: f for k, f in F.items() if f.get("v2")}
    assert len(v2) > 150 and {"iphone_13", "galaxy_s23", "ps5", "switch", "dell_latitude_3_5", "gpu_rtx30_niskie",
                              "ram_ddr4", "dysk_samsung", "cpu_intel_i5", "mobo_am4", "zestaw_plyta_cpu"} <= set(v2)
    assert not [d for d in B.DROPPED if d[3]]               # oczekiwana odpowiedź spoza listy istniejącego pytania
    for fid, fam in v2.items():
        assert fam["tricky"], fid
        keys = [v.key for v in fam["spec"]["variants"]]
        assert len(keys) == len(set(keys)), fid
        for name, q in fam["questions"].items():
            assert len(q["criteria"]) >= 2 and q["instructions"], (fid, name)
    assert {s["id"] for lst in B.specs().values() for s in lst} == set(v2)
    assert basal_poc.family_from_path("galaxy_s23_20261107.jsonl") == "galaxy_s23"
    assert basal_poc.family_from_path("s23_20261107_1226.jsonl") == "s23"
    assert basal_poc.family_from_path("gpu_rtx30_niskie_20261107.jsonl") == "gpu_rtx30_niskie"


CASES = [
    ("phone", "iPhone 13 Pro Max 256GB", "", {}, "iphone_13", {"model": "iphone_13_pro_max", "pamiec": "256gb"}),
    ("phone", "Samsung Galaxy S23 FE 128GB", "", {}, "galaxy_s23", {"model": "s_23_fe", "pamiec": "128gb"}),
    ("phone", "Samsung Galaxy S23", "Sprzedam S23 Ultra 12/512", {}, "galaxy_s23", {"model": "sprzeczne"}),
    ("phone", "Redmi Note 13 Pro 5G 8/256", "", {}, "redmi_note_13",
     {"model": "note_13_pro", "ram": "8gb", "pamiec": "256gb", "siec": "5g"}),
    ("phone", "Xiaomi Mi 11 Lite 5G NE", "", {}, "xiaomi_10_11", {"model": "xiaomi_11_lite_ne"}),
    ("phone", "iPhone 12", "Bateria 87%, blokada iCloud", {"internal_memory_capacity": "128 MB"}, "iphone_12",
     {"pamiec": "128gb", "bateria": "85_89", "blokada": "konto"}),
    ("phone", "Etui do iPhone 15 Pro", "", {}, "iphone_15", {"co": "akcesorium"}),
    ("phone", "Samsung Galaxy Z Flip", "", {}, "galaxy_z_flip", {"model": "nie_wiadomo"}),
    ("tablet", "iPad 9 generacji 64GB", "", {}, "ipad", {"model": "ipad_9", "pamiec": "64gb"}),
    ("tablet", "Galaxy Tab A 8.0", "", {}, "galaxy_tab_a", {"model": "tab_a_8_0"}),
    ("console", "PS5 Slim Digital 1TB", "", {}, "ps5", {"model": "ps5_slim", "naped": "bez_napedu", "pamiec": "1tb"}),
    ("console", "PS4 Pro 1TB + 2 pady + 5 gier", "", {}, "ps4", {"model": "ps4_pro", "pady": "2", "gry": "3_5"}),
    ("console", "Pad DualSense PS5", "", {}, "pady", {"model": "dualsense", "co": "tylko_pady"}),
    ("console", "Konsola + 2 pady", "", {"video_game_platform": "PlayStation 4"}, "ps4", {"pady": "2"}),
    ("console", "Nintendo Switch OLED", "Bez stacji dokującej", {}, "switch", {"model": "switch_oled", "dock": "nie"}),
    ("laptop", "Dell Latitude 5420 i5-1145G7 16GB 512GB SSD", "", {}, "dell_latitude_3_5",
     {"model": "latitude_5420", "procesor": "intel_i5_11gen", "ram": "16gb", "dysk": "512gb"}),
    ("laptop", "Asus TUF Gaming F15 i5-11400H RTX 3050", "", {}, "asus_tuf",
     {"model": "tuf_f_15", "karta": "rtx3050"}),
    ("laptop", "Laptop", "Hasło BIOS, nie znam", {"model_nav": "IdeaPad 3"}, "ideapad", {"blokada": "bios_haslo"}),
    ("laptop", "HP EliteBook 840 G5 i5-8350U", "", {}, "hp_elite_zbook", {"model": "elitebook_840", "generacja": "g5"}),
    ("gpu", "MSI RX 580 8GB 2048SP", "", {}, "gpu_rx400_500", {"model": "rx_580_2048sp", "vram": "8gb"}),
    ("gpu", "RTX 4070 Ti Super 16GB", "", {}, "gpu_rtx40", {"model": "rtx_4070_ti_super"}),
    ("gpu", "Gigabyte RTX 4070 Ti", "", {}, "gpu_rtx40", {"model": "rtx_4070_ti"}),
    ("gpu", "MSI RTX 3060 Ventus 2X 12G", "", {}, "gpu_rtx30_niskie", {"model": "rtx_3060", "sztuk": "1"}),
    ("cpu", "AMD Ryzen 7 5800X3D", "", {}, "cpu_ryzen_7_9", {"model": "r7_5800", "sufiks": "x3d"}),
    ("cpu", "Intel Core i5-9400F + płyta", "", {}, "cpu_intel_i5", {"sufiks": "f", "stan": "zestaw"}),
    ("motherboard", "Gigabyte B660M DS3H DDR4", "", {}, "mobo_lga1700_1851",
     {"chipset": "b660", "ddr": "ddr4", "format": "matx"}),
    ("ram", "Kingston Fury 2x8GB DDR4 3200MHz", "", {}, "ram_ddr4", {"pojemnosc": "16gb", "sztuk": "2", "mhz": "3200"}),
    ("storage", "WD Black SN850X 2TB", "", {}, "dysk_wd", {"model": "wd_black_sn850", "pojemnosc": "2tb"}),
    ("storage", "Samsung T7 Shield 1TB", "", {}, "dysk_zewnetrzny", {"typ": "zewnetrzny"}),
    ("bundle", "Kit i5-9400F + ASRock B365 + 16GB DDR4", "", {}, "zestaw_plyta_cpu",
     {"procesor": "intel_i5_9gen", "ram": "16gb", "co": "plyta_procesor_ram"}),
]


def test_assign_and_rules():
    for cat, title, desc, form, fid, want in CASES:
        assert B.assign(cat, title, form) == fid, title
        got = F[fid]["rules"](title, desc, form)
        for k, v in want.items():
            assert got[k] == v, (title, k, got[k])


def test_form_traps_and_state_text():
    fam = F["iphone_13"]
    signals = B.form_signals(fam, "iPhone 13 Pro", "", {"internal_memory_capacity": "256 MB", "model_nav": "iPhone 13"})
    assert "formularz: pamięć w MB" in signals and "formularz ≠ tytuł: model" in signals
    text = basal_poc.state_text({"title": "iPhone 13", "price": 1500, "condition": "Bardzo dobry",
                                 "form": {"model_nav": "iPhone 13", "internal_memory_capacity": "256 MB"},
                                 "description": "Sprawny."}, "iphone_13")
    assert "Formularz Vinted (wypełnia sprzedawca, bywa błędny): model: iPhone 13; pamięć: 256 MB" in text


def _db(tmp_path):
    conn = db.connect(tmp_path / "a.db")
    rows = [(1, "phone", "iPhone 13 Pro 256GB", "Apple", {"model_nav": "iPhone 13 Pro", "internal_memory_capacity":
                                                          "256 GB", "status": "Bardzo dobry"}, "Sprawny, bateria 90%"),
            (2, "phone", "iPhone 13", "Apple", {"model_nav": "iPhone 13 mini", "internal_memory_capacity": "128 MB"},
             "Wersja mini, 128 GB"),
            (3, "phone", "iPhone 13 mini", "Apple", {"model_nav": "iPhone 13 mini"}, "Zbity ekran, działa"),
            (4, "console", "PS5 Slim", None, {"video_game_platform": "PlayStation 5"}, "Digital, 1 TB, pad"),
            (5, "console", "Konsola", None, {"video_game_platform": "PlayStation 5"}, "Wersja z napędem")]
    with conn:
        for lid, cat, title, brand, form, desc in rows:
            conn.execute("INSERT INTO listings (id, catalog_id, category, title, brand, first_seen, last_seen, state, "
                         "price_now, status_label) VALUES (?, 1, ?, ?, ?, '2026-11-01', '2026-11-01', 'active', 1000, "
                         "'Bardzo dobry')", (lid, cat, title, brand))
            conn.execute("INSERT INTO details (listing_id, fetched_at, description, attributes_json) "
                         "VALUES (?, '2026-11-01', ?, ?)", (lid, desc, json.dumps(form)))
    return conn


def test_sample_all_test_and_report(tmp_path):
    conn = _db(tmp_path)
    samples = B.sample_all(conn, limit=5, only=["iphone_13", "ps5"], say=lambda _t: None)
    conn.close()
    assert len(samples["iphone_13"][0]) == 3 and len(samples["ps5"][0]) == 2
    row = next(r for r in samples["iphone_13"][0] if r["id"] == 2)
    assert row["form"]["internal_memory_capacity"] == "128 MB" and "formularz: pamięć w MB" in row["hint"]
    paths = B.save_all(samples, tmp_path / "v2", stamp="20261107")
    assert sorted(p.name for p in paths) == ["iphone_13_20261107.jsonl", "ps5_20261107.jsonl"]
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        return httpx.Response(200, json={"answers": {
            name: ({"choice": next(iter(q["criteria"])), "confidence": 0.9} if q["type"] == "choice" else {"noul": 0.1})
            for name, q in body["questions"].items()}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    rows = basal_poc.load_sample(paths[0])
    results, summary = basal_poc.run_test(rows, "iphone_13", url="http://basal", client=client, say=lambda _t: None)
    assert len(results) == 3 + len(F["iphone_13"]["tricky"])
    assert any("Formularz Vinted" in b["state"] for b in sent)
    assert "czesci_nieoryginalne" in sent[0]["questions"] and sent[0]["questions"]["model"]["type"] == "choice"
    assert results[0]["rules_all"]["model"] in ("iphone_13_pro", "iphone_13_mini", "iphone_13", "sprzeczne")
    out = basal_poc.save_results(results, {"czas_ms": {"mediana": 900}, **summary}, paths[0], "45b")
    assert "_wyniki_45b_" in out.name
    text, report = basal_report.write(tmp_path / "v2", "45b")
    assert report.exists() and "iphone_13" in text and "Zbiorczo per pytanie" in text
    data = json.loads((tmp_path / "v2" / "raport_45b.json").read_text(encoding="utf-8"))
    assert data["rodziny"]["iphone_13"]["ofert"] == len(results) and "model" in data["pytania"]
