"""Test modelu wizyjnego (analyzer/vision.py): próbka z bazy, zapytanie do Ollamy (atrapa), porównanie z tekstem."""
import json

import httpx

from analyzer import db, rawstore, vision

JPEG = b"\xff\xd8\xff" + b"x" * 2000


def _conn():
    conn = db.connect(":memory:")
    for i, (title, desc) in enumerate([
            ("Samsung Galaxy A17 5G 128GB", "Sprzedam, w zestawie pudełko i ładowarka."),
            ("Samsung Galaxy A17", "Telefon sprawny, bez pudełka."),
            ("Samsung Galaxy A17 4/128", "Stan bardzo dobry."),
            ("iPhone 13 128GB", "Sprawny.")], 1):
        lid = 1000 + i
        conn.execute("INSERT INTO listings (id, catalog_id, title, photo_url, first_seen, last_seen, state, category, "
                     "price_now, details_at, status_label) VALUES (?, 3661, ?, ?, '2026-11-01', '2026-11-10', "
                     "'active', 'phone', 500, '2026-11-02', 'Bardzo dobry')",
                     (lid, title, f"https://images1.vinted.net/{lid}/main.jpg"))
        conn.execute("INSERT INTO details (listing_id, fetched_at, description, attributes_json) VALUES "
                     "(?, '2026-11-02', ?, ?)", (lid, desc, json.dumps({"internal_memory_capacity": "128 GB"})))
        body = {"item": {"photos": [{"full_size_url": f"https://images1.vinted.net/{lid}/{n}.jpg"}
                                    for n in range(1, 7)]}}
        conn.execute("INSERT INTO raw (listing_id, kind, fetched_at, body) VALUES (?, 'sidebar', '2026-11-02', ?)",
                     (lid, rawstore.compress(body)))
    conn.commit()
    return conn


def test_sample_from_db(tmp_path):
    rows = vision.sample(_conn(), "a17", "phone", limit=10, max_photos=3)
    assert len(rows) == 3 and all("a17" in r["title"].lower() for r in rows)
    assert all(len(r["photos"]) == 3 and r["photo_source"] == "sidebar" for r in rows)
    assert rows[0]["attributes"] == {"internal_memory_capacity": "128 GB"}
    path = vision.save_sample(rows, "a17", tmp_path)
    assert len(vision.load_sample(path)) == 3


def test_text_signals():
    assert vision.text_box("Samsung A17, bez pudełka") == "bez"
    assert vision.text_box("komplet z pudełkiem") == "jest"
    assert vision.text_box("stan bdb") is None
    assert vision.text_storage("Galaxy A17 128GB") == 128 and vision.text_storage("iPhone 1 TB") == 1024
    assert vision.text_storage("A17 4/128") is None


def _transport(answers, calls):
    def handler(request):
        if request.url.host.startswith("images"):
            return httpx.Response(200, content=JPEG)
        body = json.loads(request.content)
        calls.append(body)
        title = body["messages"][0]["content"]
        answer = next(a for key, a in answers.items() if key in title)
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}})
    return httpx.MockTransport(handler)


def test_run_test_and_report(tmp_path):
    rows = vision.sample(_conn(), "a17", "phone", limit=10, max_photos=2)
    answers = {
        "A17 5G 128GB": {"box_visible": "yes", "visible_text": "Galaxy A17 5G 128 GB", "model": "Galaxy A17 5G",
                         "storage_gb": 128, "ram_gb": 4, "network_5g": "yes", "screen_damage": "no"},
        "A17\"": {"box_visible": "no", "visible_text": "", "model": None, "storage_gb": 256, "ram_gb": None,
                  "network_5g": "yes", "screen_damage": "no"},
        "A17 4/128": {"box_visible": "yes", "visible_text": "SM-A175F 128GB", "model": "SM-A175F", "storage_gb": 128,
                      "ram_gb": 4, "network_5g": "no", "screen_damage": "unclear"},
    }
    calls = []
    client = httpx.Client(transport=_transport(answers, calls))
    results, summary = vision.run_test(rows, "qwen2.5vl:3b", client=client, say=lambda _t: None)
    assert len(calls) == 3
    assert calls[0]["model"] == "qwen2.5vl:3b" and calls[0]["format"]["required"]
    assert len(calls[0]["messages"][0]["images"]) == 2
    assert summary["answered"] == 3
    assert summary["box_text_known"] == 2 and summary["box_agree"] == 2       # „pudełko” → yes, „bez pudełka” → no
    assert summary["box_text_silent"] == 1 and summary["box_found_on_photos"] == 1
    assert summary["net5g_only_photos"] == 1                                   # „Samsung Galaxy A17” bez 5G w tytule
    assert summary["model_read"] == 2
    path, text = vision.save_results(results, summary, tmp_path / "a17.jsonl", "qwen2.5vl:3b")
    assert path.name == "a17_qwen2.5vl_3b.txt" and "Pudełko" in text and "vinted.pl/items/" in text


def test_ollama_error_is_reported(tmp_path):
    rows = vision.sample(_conn(), "iphone", "phone", limit=1, max_photos=1)

    def handler(request):
        if request.url.host.startswith("images"):
            return httpx.Response(200, content=JPEG)
        return httpx.Response(404, json={"error": "model not found"})
    results, summary = vision.run_test(rows, "brak:1b", client=httpx.Client(transport=httpx.MockTransport(handler)),
                                       say=lambda _t: None)
    assert results[0]["error"] and summary["answered"] == 0
