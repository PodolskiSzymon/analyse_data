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


def test_openai_api_llama_server():
    """llama.cpp llama-server: /v1/chat/completions, obrazy jako data URL, odpowiedź w ```json```."""
    rows = vision.sample(_conn(), "iphone", "phone", limit=1, max_photos=2)
    calls = []

    def handler(request):
        if request.url.host.startswith("images"):
            return httpx.Response(200, content=JPEG)
        calls.append((request.url.path, json.loads(request.content)))
        answer = {"box_visible": "no", "visible_text": "iPhone 13", "model": "iPhone 13", "storage_gb": 128,
                  "ram_gb": None, "network_5g": "unknown", "screen_damage": "no"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "```json\n" + json.dumps(answer)
                                                                  + "\n```"}}]})
    results, summary = vision.run_test(rows, "qwen", "http://x:8081", client=httpx.Client(
        transport=httpx.MockTransport(handler)), say=lambda _t: None, api="openai")
    path, body = calls[0]
    assert path == "/v1/chat/completions"
    images = [c for c in body["messages"][0]["content"] if c["type"] == "image_url"]
    assert len(images) == 2 and images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert summary["answered"] == 1 and results[0]["vision_storage"] == 128


def test_resume_after_interruption(tmp_path):
    """Długi przebieg: wynik każdej oferty od razu w pliku; ponowne uruchomienie pomija ocenione bez błędu."""
    rows = vision.sample(_conn(), "a17", "phone", limit=10, max_photos=1)
    progress = vision.results_path(tmp_path / "a17.jsonl", "qwen")
    answer = {"box_visible": "yes", "visible_text": "", "model": None, "storage_gb": None, "ram_gb": None,
              "network_5g": "unknown", "screen_damage": "no"}
    calls = []

    def handler(request):
        if request.url.host.startswith("images"):
            return httpx.Response(200, content=JPEG)
        calls.append(1)
        if len(calls) == 2:
            return httpx.Response(500, json={"error": "boom"})      # druga oferta - błąd
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    vision.run_test(rows, "qwen", "http://x", client=client, say=lambda _t: None, api="openai",
                    progress_path=progress)
    assert len(vision.load_results(progress)) == 3 and len(calls) == 3
    with open(progress, "a", encoding="utf-8") as f:
        f.write('{"id": 1, "urwane')                                   # zanik prądu w trakcie zapisu
    calls.clear()
    results, summary = vision.run_test(rows, "qwen", "http://x", client=client, say=lambda _t: None, api="openai",
                                       progress_path=progress)
    assert len(calls) == 1                                             # tylko oferta z błędem jeszcze raz
    assert summary["answered"] == 3 and len(vision.load_results(progress)) == 3


def test_sample_used_only_and_many_categories():
    conn = _conn()
    conn.execute("UPDATE listings SET status_label='Nowy z metką' WHERE id=1001")
    conn.execute("UPDATE listings SET category='tablet' WHERE id=1004")
    rows = vision.sample(conn, "", "phone,tablet", limit=10, used_only=True)
    assert {r["id"] for r in rows} == {1002, 1003, 1004}


def test_local_photos_archive_includes_sold(tmp_path):
    """2026-11-16: zdjęcia z lokalnego archiwum (D:\\photos) - także sprzedane; bez CDN."""
    from analyzer.photos import listing_dir
    conn = _conn()
    conn.execute("UPDATE listings SET state='sold' WHERE id=1001")
    for lid in (1001, 1003):                                          # 1002 bez zdjęć na dysku
        folder = listing_dir(tmp_path, lid)
        folder.mkdir(parents=True)
        for n in (1, 2, 3):
            (folder / f"0{n}.jpg").write_bytes(JPEG)
    assert {r["id"] for r in vision.sample(conn, "a17", "phone", limit=10)} == {1002, 1003}   # domyślnie żywe
    rows = vision.sample(conn, "a17", "phone", limit=10, states=None, photos_root=tmp_path)
    assert {r["id"] for r in rows} == {1001, 1003}
    assert {r["state"] for r in rows} == {"sold", "active"} and rows[0]["photo_source"] == "local"
    calls = []

    def handler(request):
        assert not request.url.host.startswith("images"), "nie powinno iść do CDN"
        calls.append(json.loads(request.content))
        answer = {"box_visible": "yes", "visible_text": "", "model": None, "storage_gb": None, "ram_gb": None,
                  "network_5g": "unknown", "screen_damage": "no"}
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(answer)}}]})
    results, summary = vision.run_test(rows, "qwen", "http://x", max_photos=2, say=lambda _t: None, api="openai",
                                       client=httpx.Client(transport=httpx.MockTransport(handler)),
                                       photos_root=tmp_path)
    assert summary["answered"] == 2 and all(r["photos"] == 2 for r in results)
    assert {r["state"] for r in results} == {"sold", "active"}


def test_stops_after_errors_in_row(tmp_path):
    """Serwer modelu padł → po N błędach z rzędu koniec (zamiast „przerobić” całą próbkę błędami); .bat restartuje."""
    rows = vision.sample(_conn(), "", "phone", limit=10, max_photos=1)

    def handler(request):
        if request.url.host.startswith("images"):
            return httpx.Response(200, content=JPEG)
        return httpx.Response(503)
    results, _ = vision.run_test(rows, "qwen", "http://x", client=httpx.Client(transport=httpx.MockTransport(handler)),
                                 say=lambda _t: None, api="openai", max_errors_in_row=2)
    assert len(results) == 2


def test_box_only_mode_carries_earlier_boxes(tmp_path):
    """19.11: tryb „tylko pudełko” - bez tytułu w poleceniu, jedno pole w odpowiedzi, zdjęcia 512 px, osobny plik
    wyników; oferty, w których pełny test widział pudełko, przechodzą bez ponownego pytania."""
    rows = vision.sample(_conn(), "a17", "phone", limit=10, max_photos=4)
    assert len(rows) >= 3
    earlier = vision.results_path(tmp_path / "a17.jsonl", "qwen")
    with open(earlier, "w", encoding="utf-8") as f:                    # pełny test: pierwsza oferta z pudełkiem
        f.write(json.dumps({"id": rows[0]["id"], "url": rows[0]["url"], "title": rows[0]["title"], "error": None,
                            "seconds": 50, "answer": {"box_visible": "yes"}, "text_box": None,
                            "title_storage": None, "title_5g": False, "vision_box": "yes"}) + "\n")
        f.write(json.dumps({"id": rows[1]["id"], "url": rows[1]["url"], "title": rows[1]["title"], "error": None,
                            "seconds": 50, "answer": {"box_visible": "no"}, "text_box": None,
                            "title_storage": None, "title_5g": False, "vision_box": "no"}) + "\n")
    bodies = []

    def handler(request):
        if request.url.host.startswith("images"):
            return httpx.Response(200, content=JPEG)
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"box_visible": "yes"}'}}]})
    progress = vision.results_path(tmp_path / "a17.jsonl", "qwen", box_only=True)
    assert progress.name == "a17_qwen_pudelko.jsonl"
    results, summary = vision.run_test(rows, "qwen", "http://x", client=httpx.Client(
        transport=httpx.MockTransport(handler)), say=lambda _t: None, api="openai", progress_path=progress,
        box_only=True, earlier_path=earlier, max_photos=6)
    assert len(bodies) == len(rows) - 1                                 # pierwsza przeniesiona, druga pytana ponownie
    text = bodies[0]["messages"][0]["content"][0]["text"]
    assert rows[1]["title"] not in text and "box" in text
    assert bodies[0]["max_tokens"] == 30
    assert list(bodies[0]["response_format"]["schema"]["properties"]) == ["box_visible"]
    assert summary["answered"] == len(rows) and all(r["vision_box"] == "yes" for r in results)


def test_compare_box_modes_and_carry_all(tmp_path):
    """vision-porownaj: tryb „tylko pudełko” przy kilku rozmiarach na ofertach z pełnego testu; --przenies wszystkie."""
    rows = vision.sample(_conn(), "a17", "phone", limit=10, max_photos=4)
    sample = tmp_path / "a17.jsonl"
    vision.save_sample(rows, "a17", tmp_path)
    full = vision.results_path(sample, "qwen")
    with open(full, "w", encoding="utf-8") as f:
        for i, r in enumerate(rows):
            f.write(json.dumps({"id": r["id"], "url": r["url"], "title": r["title"], "error": None, "seconds": 50.0,
                                "answer": {}, "text_box": "bez" if i % 2 else None, "title_storage": None,
                                "title_5g": False, "vision_box": "no" if i % 2 else "yes"}) + "\n")
    sizes_seen = []

    def handler(request):
        if request.url.host.startswith("images"):
            return httpx.Response(200, content=JPEG)
        body = json.loads(request.content)
        sizes_seen.append(len(body["messages"][0]["content"]) - 1)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"box_visible": "yes"}'}}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    n_pos, n_neg = (len(rows) + 1) // 2, len(rows) // 2
    assert n_neg >= 1
    table, text, out = vision.compare_box_modes(sample, "qwen", sizes=(512, 320), n_pos=n_pos, n_neg=n_neg,
                                                url="http://x", client=client, say=lambda _t: None)
    assert out.exists() and "320 px" in text and len(table) == 3
    assert table[0]["found"] == n_pos and table[0]["false"] == 0       # pełny test
    assert table[1]["found"] == n_pos and table[1]["false"] == n_neg and table[1]["n"] == len(rows)
    assert (tmp_path / "a17_qwen_pudelko_test320.jsonl").exists()
    # --przenies wszystkie: nic nie pytane ponownie
    calls = len(sizes_seen)
    results, _s = vision.run_test(vision.load_sample(sample), "qwen", "http://x", client=client, say=lambda _t: None,
                                  api="openai", progress_path=vision.results_path(sample, "qwen", True),
                                  box_only=True, earlier_path=full, carry="all")
    assert len(sizes_seen) == calls and len(results) == len(rows)


def test_logging_without_access_to_db_folder(tmp_path, monkeypatch, capsys):
    """19.11: PC bez ANALYZER_DB - folder logu niedostępny; polecenie ma działać dalej (log tylko w konsoli)."""
    import logging

    from analyzer import __main__ as cli

    def deny(*_a, **_k):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(logging, "FileHandler", deny)
    cli.setup_logging(tmp_path / "x" / "analyzer.db")
    assert "log tylko w konsoli" in capsys.readouterr().out


def test_error_shows_server_message():
    """19.11: błąd 400 z llama-server - w logu treść odpowiedzi serwera (np. przekroczony kontekst)."""
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "the request exceeds the available context size"}})
    answer, _s, error = vision.ask(httpx.Client(transport=httpx.MockTransport(handler)), "http://x", "qwen", "t",
                                   ["AAAA"], api="openai", box_only=True)
    assert answer is None and "exceeds the available context size" in error
