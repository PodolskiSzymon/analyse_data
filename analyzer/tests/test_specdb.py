"""Baza modeli laptopów (2026-11-20): kody modeli, nauka z ogłoszeń, spokojne pobieranie stron, mapa do wyceny."""
import json
import sqlite3

import httpx

from analyzer import specdb

# Te same przypadki w unreachable_sniper/sniper/tests/test_specs.py (MODEL_CODE_PARITY).
MODEL_CODE_PARITY = [
    ("Lenovo IdeaPad 3 15ITL6 i5", ["15itl6"]),
    ("Asus X515MA Celeron", ["x515ma"]),
    ("Acer Nitro 5 AN515-58 RTX 3050", ["an515-58"]),
    ("Dell Latitude 5320 i5", ["latitude5320"]),
    ("HP EliteBook 840 G5", ["elitebook840g5"]),
    ("HP 250 G8 i3", ["250g8"]),
    ("Lenovo ThinkPad T480", ["thinkpadt480"]),
    ("Asus TUF FX506HC RTX3050 16GB 512GB", ["fx506hc"]),
    ("Laptop RTX 3060 16 GB 512gb i7-12700h", []),
]


def test_model_codes():
    for text, expected in MODEL_CODE_PARITY:
        assert specdb.model_codes(text) == expected, text


def _ads_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript("""CREATE TABLE listings (id INTEGER, title TEXT, category TEXT);
                          CREATE TABLE features (listing_id INTEGER, cpu TEXT, gpu TEXT);
                          CREATE TABLE details (listing_id INTEGER, description TEXT);""")
    rows = [(i, "Lenovo IdeaPad 3 15ACH6 RTX 3050", "laptop", "ryzen 5 5600h", "rtx 3050") for i in range(4)]
    rows += [(10, "Lenovo 15ACH6 Ryzen 7", "laptop", "ryzen 7 5800h", "rtx 3050")]          # inna linia - 4/5 = 80%
    rows += [(20 + i, "HP EliteBook 840", "laptop", cpu, None) for i, cpu in
             enumerate(("i5-8250u", "i5-6200u", "i5-10210u", "i5-1135g7"))]                # różne generacje
    for lid, title, cat, cpu, gpu in rows:
        conn.execute("INSERT INTO listings VALUES (?, ?, ?)", (lid, title, cat))
        conn.execute("INSERT INTO features VALUES (?, ?, ?)", (lid, cpu, gpu))
    return conn


def test_learn_and_code_map(tmp_path):
    spec = specdb.open_db(tmp_path / "specdb.sqlite")
    assert specdb.learn(_ads_db(), spec) == 1                       # 15ach6 pewny, elitebook840 - mieszane generacje
    codes = specdb.code_map(spec)
    assert codes["15ach6"]["cpu"] == "ryzen 5 5600h" and codes["15ach6"]["gpu"] == "rtx 3050"
    assert specdb.lookup(codes, "Laptop Lenovo 15ACH6 16GB")["code"] == "15ach6"
    assert specdb.lookup(codes, "HP EliteBook 840") is None
    assert "pewnych kodów do wyceny" in specdb.status(spec)


def test_crawl_slowly_with_robots_cache_and_stop(tmp_path):
    spec = specdb.open_db(tmp_path / "specdb.sqlite")
    product = {"@context": "https://schema.org", "@type": "Product", "name": "Lenovo IdeaPad 3 15ITL6",
               "description": "Intel Core i5-1135G7, 8 GB RAM, SSD 512 GB, Intel Iris Xe"}
    pages = {"/robots.txt": "User-agent: *\nDisallow: /prywatne/",
             "/lista": '<a href="/model/1">1</a><a href="/prywatne/2">2</a><a href="/model/3">3</a>',
             "/model/1": f'<script type="application/ld+json">{json.dumps(product)}</script>'}
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/model/3":
            return httpx.Response(429)
        return httpx.Response(200, text=pages.get(request.url.path, "<html></html>"))
    specdb.SITES["test"] = {"list": lambda html, base: __import__("re").findall(r'href="([^"]+)"', html),
                            "model": specdb.SITES["jsonld"]["model"]}
    slept = []
    fetcher = specdb.Fetcher(spec, "test", client=httpx.Client(transport=httpx.MockTransport(handler)),
                             sleep=slept.append, say=lambda _t: None)
    n_pages, configs = specdb.crawl(spec, "test", ["https://x.test/lista"], 10, fetcher, say=lambda _t: None)
    assert configs == 1 and "/prywatne/2" not in calls                # robots.txt respektowany
    assert all(25 <= s <= 90 for s in slept) and len(slept) >= 1       # przerwy między stronami
    row = spec.execute("SELECT code, cpu FROM model_specs WHERE source = 'test'").fetchone()
    assert tuple(row) == ("15itl6", "i5-1135g7")
    assert spec.execute("SELECT error FROM pages WHERE url LIKE '%/model/3'").fetchone()[0] == "blokada"
    # drugi przebieg: strony z pamięci, nic nie pobiera ponownie (poza robots.txt)
    calls.clear()
    specdb.crawl(spec, "test", ["https://x.test/lista"], 10, specdb.Fetcher(
        spec, "test", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=slept.append,
        say=lambda _t: None), say=lambda _t: None)
    assert "/model/1" not in calls and "/lista" not in calls
    del specdb.SITES["test"]


# Te same przypadki w unreachable_sniper/sniper/tests/test_specs.py (CODE_FILL_PARITY): uzupełnianie specyfikacji z kodu.
CODE_FILL_PARITY = [
    ("Lenovo IdeaPad 3 15ITL6 8GB 512GB", {"cpu": "i5-1135g7", "gpu": None, "code": "15itl6"},
     {"gpu": None, "cpu_line": "intel core i5", "cpu_gen": "10–11 gen.", "chip": None, "line": None, "ram": 8,
      "ssd": 512}),
    ("Asus TUF FX506HC 16GB", {"cpu": "i5-11400h", "gpu": "rtx 3050", "code": "fx506hc"},
     {"gpu": "rtx 3050", "cpu_line": "intel core i5", "cpu_gen": "10–11 gen.", "chip": None, "line": None, "ram": None,
      "ssd": None}),                                              # samo „16GB” bez dysku - nie wiadomo, czy RAM
    ("Lenovo Legion 5 i7-10750H RTX 2060 16GB", {"cpu": "i5-1135g7", "gpu": None, "code": "x"},     # tekst wystarcza
     {"gpu": "rtx 2060", "cpu_line": "intel core i7", "cpu_gen": "10–11 gen.", "chip": None, "line": None, "ram": None,
      "ssd": None}),
]


def test_code_fill_parity_with_sniper():
    from analyzer.comparables import laptop_spec, with_code
    from analyzer.extract import extract
    for title, hint, expected in CODE_FILL_PARITY:
        fields, _ = extract("laptop", title, "", {})
        raw = tuple((fields.get(k) or {}).get("value") for k in ("model", "cpu", "cpu_line", "gpu", "ram_gb",
                                                                 "storage_gb"))
        assert with_code(laptop_spec(*raw), raw, hint) == expected, title
