"""Test lokalnego modelu wizyjnego na zdjęciach ofert (prośba użytkownika 2026-11-15).

Pytanie: czy mały model widzący obraz (Ollama na PC z GTX 1060 6 GB, np. qwen2.5vl:3b, gemma3:4b) odczyta ze zdjęć to,
czego brakuje w tytule - wariant (5G, pamięć, RAM, dokładny model ze zrzutu ustawień / pudełka / naklejki) - i czy
rozpozna, że w zestawie jest PUDEŁKO (na kopii bazy używane „bez pudełka” są ~10-20% tańsze, z pudełkiem schodzą
szybciej). Darmowe, lokalne, bez API.

Dwa kroki (baza jest na serwerze, karta graficzna na PC):
  1. serwer:  python -m analyzer vision-sample --szukaj "a17" --kategoria phone --limit 40
             → data/vision/<nazwa>.jsonl (tytuł, opis, formularz, adresy zdjęć; bez danych sprzedawcy)
  2. PC:      python -m analyzer vision-test --plik data/vision/<nazwa>.jsonl --model qwen2.5vl:3b
             → zdjęcia prosto z CDN Vinted (bez proxy), pytanie do Ollamy (http://127.0.0.1:11434),
               raport <nazwa>_<model>.txt + .jsonl: zgodność z tytułem (pamięć, 5G), pudełko vs tekst ogłoszenia,
               czas na ofertę.
"""
import base64
import json
import random
import re
import time
from pathlib import Path

from .sample import redact

PROMPT = """You see photos from a second-hand marketplace listing (Vinted). Listing title: "{title}".
Look at ALL photos carefully and answer only from what is VISIBLE (screens with settings / "About phone", the retail box,
stickers, labels). Do not guess from the title.
- box_visible: "yes" if the original retail box / packaging of the product is visible in any photo, "no" if not, \
"unclear" if you cannot tell.
- visible_text: copy the text you can read that identifies the product: model name or number, storage (GB), RAM, \
"5G", colour, from the screen, box or stickers. Empty string if none.
- model: exact model you can read (e.g. "Galaxy A17 5G", "SM-A176B", "iPhone 13"), null if not readable.
- storage_gb / ram_gb: numbers read from photos, null if not visible.
- network_5g: "yes" if "5G" is printed on the box / screen / back of the device, "no" if a visible model name clearly \
has no 5G, "unknown" otherwise.
- screen_damage: "yes" if a cracked or damaged screen is visible, "no" if the screen is visible and intact, "unclear".
"""
SCHEMA = {
    "type": "object",
    "properties": {
        "box_visible": {"type": "string", "enum": ["yes", "no", "unclear"]},
        "visible_text": {"type": "string"},
        "model": {"type": ["string", "null"]},
        "storage_gb": {"type": ["integer", "null"]},
        "ram_gb": {"type": ["integer", "null"]},
        "network_5g": {"type": "string", "enum": ["yes", "no", "unknown"]},
        "screen_damage": {"type": "string", "enum": ["yes", "no", "unclear"]},
    },
    "required": ["box_visible", "visible_text", "model", "storage_gb", "ram_gb", "network_5g", "screen_damage"],
}

# 2026-11-19 (test 5118 ofert, Qwen2.5-VL-3B): pamięć i 5G model przepisuje z tytułu / zgaduje z nazwy (pamięć zgodna
# w 99%, ale w 88% z nich pojemność była w tytule; iPhone 11 z „5G” 105 razy; visible_text = tytuł w 32%), a pudełko
# widzi trafnie (użytkownik sprawdził próbkę: „jest” ~100% trafnie; tekst „bez pudełka” → „nie” w 96%), tylko gubi
# pudełko na dalszych zdjęciach (dostawał 3). Tryb „tylko pudełko”: bez tytułu w poleceniu, jedno pole w odpowiedzi,
# więcej zdjęć w mniejszej rozdzielczości (BOX_SIZE px - pudełko to duży obiekt).
BOX_PROMPT = """You see photos from a second-hand marketplace listing (Vinted). Is the original retail box / packaging \
of the product (phone or tablet) visible in ANY of the photos? Answer "yes", "no", or "unclear" if you cannot tell."""
BOX_SCHEMA = {"type": "object", "properties": {"box_visible": {"type": "string", "enum": ["yes", "no", "unclear"]}},
              "required": ["box_visible"]}
BOX_SIZE = 512
BOX_TAG = "pudelko"

# Tekst ogłoszenia - te same reguły co Sniper (sniper/market.py) i mediany (5G, pojemność).
NO_BOX = re.compile(
    r"bez\s+(?:oryginalnego\s+|org\.?\s+)?(?:pude[łl]k|opakowani|kartonu|boxa?\b)|\bno\s+box\b|without\s+(?:the\s+)?box"
    r"|(?:nie\s+mam|nie\s+posiadam|brak|brakuje)\s+(?:oryginalnego\s+)?(?:pude[łl]k|opakowani|kartonu)"
    r"|ohne\s+(?:ovp|verpackung|karton)|f[aă]r[aă]\s+cutie|bez\s+krabice|doboz\s+n[ée]lk[üu]l|nincs\s+doboz"
    r"|be\s+d[ėe][žz]ut|utan\s+(?:kartong|förpackning|låda)", re.I)
BOX = re.compile(
    r"pude[łl]k|\bbox(?:ie|em)?\b|full\s?box|karton|oryginalne\s+opakowanie|w\s+opakowaniu|\bkomplet\b|\bovp\b"
    r"|originalverpackung|\bcutie\b|krabic|doboz|d[ėe][žz]ut|kartong|förpackning|scatola|emballage", re.I)
STORAGE = re.compile(r"(?<![\d.,])(32|64|128|256|512|1024)\s?gb\b|(?<![\d.,])1\s?tb\b", re.I)
NET5 = re.compile(r"(?<![\d.,])5\s?g(?![^\W\d_])", re.I)


def text_box(text):
    if NO_BOX.search(text or ""):
        return "bez"
    if BOX.search(text or ""):
        return "jest"
    return None


def text_storage(text):
    m = STORAGE.search(text or "")
    if not m:
        return None
    return int(m.group(1)) if m.group(1) else 1024


# ---------------------------------------------------------------------------------------------- krok 1: próbka
ALIVE = ("active", "reserved")


def sample(conn, pattern, category=None, limit=40, max_photos=4, seed=7, progress=None, used_only=False,
           states=ALIVE, photos_root=None):
    """Oferty ze szczegółami, których tytuł pasuje do `pattern` (LIKE, małe litery) → lista słowników.

    states: domyślnie żywe (zdjęcia jeszcze na CDN); z `photos_root` (lokalne archiwum zdjęć, 2026-11-16) także
    sprzedane / usunięte - tylko oferty, które mają zdjęcia na dysku (do median pudełko / bez pudełka liczą się
    właśnie zniknięte)."""
    from .photos import local_photos, urls_for

    say = progress or (lambda _t: None)
    like = f"%{pattern.lower()}%"
    sql = """SELECT l.id, l.title, l.photo_url, l.details_at, l.category, l.status_label, l.price_now,
                    d.description, d.attributes_json, l.state
             FROM listings l JOIN details d ON d.listing_id = l.id
             WHERE lower(l.title) LIKE ?"""
    params = [like]
    if states:
        sql += f" AND l.state IN ({','.join('?' * len(states))})"
        params.extend(states)
    if category:
        cats = [c.strip() for c in category.split(",") if c.strip()]
        sql += f" AND l.category IN ({','.join('?' * len(cats))})"
        params.extend(cats)
    if used_only:
        # nowe z metką prawie zawsze mają pudełko - o pudełku / wariancie rozstrzyga głównie rynek używanych
        sql += " AND COALESCE(l.status_label, '') NOT LIKE 'Nowy%' AND COALESCE(l.status_label, '') NOT LIKE 'New%'"
    rows = conn.execute(sql, params).fetchall()
    say(f"  ofert pasujących do „{pattern}”: {len(rows)}")
    random.Random(seed).shuffle(rows)
    out, no_local = [], 0
    for r in rows:
        if photos_root is not None and not local_photos(photos_root, r[0]):
            no_local += 1                                     # najpierw dysk - bez rozpakowywania raw
            continue
        source, urls = urls_for(conn, {"id": r[0], "photo_url": r[2], "details_at": r[3]})
        if photos_root is not None:
            source = "local"
        elif not urls:
            continue
        try:
            attrs = json.loads(r[8]) if r[8] else {}
        except ValueError:
            attrs = {}
        out.append({"id": r[0], "url": f"https://www.vinted.pl/items/{r[0]}", "title": r[1], "category": r[4],
                    "condition": r[5], "price": r[6], "description": redact((r[7] or "")[:800]),
                    "attributes": {k: v for k, v in attrs.items() if k not in ("upload_date",)},
                    "photos": urls[:max_photos], "photo_source": source, "state": r[9]})
        if len(out) % 1000 == 0:
            say(f"  ... {len(out)} ofert w próbce")
        if len(out) >= limit:
            break
    if photos_root is not None:
        say(f"  pominięte bez zdjęć na dysku: {no_local}")
    return out


def save_sample(rows, name, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def load_sample(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# ---------------------------------------------------------------------------------------------- krok 2: test
def _shrink(data, size=1024):
    """Zdjęcie do ~1024 px (szybciej, mniej VRAM); bez Pillow - oryginał."""
    try:
        from io import BytesIO

        from PIL import Image
        img = Image.open(BytesIO(data))
        img.thumbnail((size, size))
        buf = BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        return buf.getvalue()
    except Exception:
        return data


def read_local(photos_root, listing_id, max_photos, size=1024):
    """Zdjęcia z lokalnego archiwum (photos.py: <root>/<id // 1e6>/<id>/01.jpg ...) → base64; [] gdy brak."""
    from .photos import local_photos

    images = []
    for path in local_photos(photos_root, listing_id)[:max_photos]:
        try:
            images.append(base64.b64encode(_shrink(path.read_bytes(), size)).decode())
        except OSError:
            continue
    return images


def fetch_photos(client, urls, size=1024):
    images = []
    for url in urls:
        try:
            r = client.get(url, timeout=30)
            r.raise_for_status()
            images.append(base64.b64encode(_shrink(r.content, size)).decode())
        except Exception:
            continue
    return images


def _json(text):
    """JSON z odpowiedzi (czasem w ```json ... ```)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    start, end = text.find("{"), text.rfind("}")
    return json.loads(text[start:end + 1] if start >= 0 else text)


def ask(client, url, model, title, images, api="ollama", box_only=False):
    """→ (odpowiedź jako dict albo None, sekundy, błąd). api: ollama (/api/chat) albo openai (llama.cpp
    llama-server: /v1/chat/completions - 2026-11-15, Ollama 0.40 nie widziała GTX 1060, a llama.cpp CUDA 12 tak).
    box_only: samo pudełko (BOX_PROMPT, bez tytułu, krótka odpowiedź)."""
    prompt, schema = (BOX_PROMPT, BOX_SCHEMA) if box_only else (PROMPT.format(title=title), SCHEMA)
    if api == "openai":
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in images]
        body = {"model": model, "temperature": 0, "messages": [{"role": "user", "content": content}],
                "response_format": {"type": "json_object", "schema": schema}}
        if box_only:
            body["max_tokens"] = 30
        path = "/v1/chat/completions"
    else:
        body = {"model": model, "stream": False, "format": schema,
                "options": {"temperature": 0, **({"num_predict": 30} if box_only else {})},
                "messages": [{"role": "user", "content": prompt, "images": images}]}
        path = "/api/chat"
    started = time.monotonic()
    try:
        r = client.post(f"{url.rstrip('/')}{path}", json=body, timeout=1200)
        r.raise_for_status()
        data = r.json()
        text = (data["choices"][0]["message"]["content"] if api == "openai"
                else data.get("message", {}).get("content", ""))
        return _json(text), time.monotonic() - started, None
    except Exception as exc:
        return None, time.monotonic() - started, f"{type(exc).__name__}: {str(exc)[:150]}"


def compare(row, answer):
    """Porównanie odpowiedzi modelu z tekstem ogłoszenia."""
    text = f"{row['title']}\n{row.get('description') or ''}"
    form = " ".join(str(v) for v in (row.get("attributes") or {}).values())
    title_storage = text_storage(row["title"]) or text_storage(form)
    title_5g = bool(NET5.search(row["title"]))
    out = {"text_box": text_box(text), "title_storage": title_storage, "title_5g": title_5g}
    if answer:
        out.update(vision_box=answer.get("box_visible"), vision_storage=answer.get("storage_gb"),
                   vision_5g=answer.get("network_5g"), vision_model=answer.get("model"),
                   visible_text=(answer.get("visible_text") or "")[:200], screen_damage=answer.get("screen_damage"))
    return out


def results_path(sample_path, model, box_only=False):
    tag = re.sub(r"[^\w.-]+", "_", model) + (f"_{BOX_TAG}" if box_only else "")
    sample_path = Path(sample_path)
    return sample_path.with_name(f"{sample_path.stem}_{tag}.jsonl")   # with_suffix psuł „qwen2.5vl” (kropka)


def load_results(path):
    path = Path(path)
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue                          # urwana ostatnia linia (zanik prądu) - ta oferta pójdzie jeszcze raz
    return out


def run_test(rows, model, url="http://127.0.0.1:11434", max_photos=4, client=None, say=print, api="ollama",
             progress_path=None, photos_root=None, max_errors_in_row=20, box_only=False, earlier_path=None,
             carry="boxes", size=None):
    """progress_path: wynik każdej oferty dopisywany od razu (długi przebieg na kilka dni); przy ponownym
    uruchomieniu oferty już ocenione bez błędu są pomijane (wznawianie po restarcie / zaniku prądu).
    box_only: samo pudełko, zdjęcia BOX_SIZE px; earlier_path: wyniki pełnego testu - oferty, w których model już
    zobaczył pudełko („yes” było ~100% trafne), są przenoszone bez ponownego pytania (2026-11-19); carry="all" -
    przenoszone wszystkie odpowiedzi pełnego testu (bez powtarzania ofert z 3 zdjęć). size: rozmiar zdjęć w px."""
    import httpx

    own = client is None
    client = client or httpx.Client(trust_env=False, follow_redirects=True)
    size = size or (BOX_SIZE if box_only else 1024)
    results = [r for r in load_results(progress_path) if not r.get("error")] if progress_path else []
    done = {r["id"] for r in results}
    if done:
        say(f"  wznawiam: {len(done)} ofert już ocenionych - pomijam je")
    if box_only and earlier_path:
        carried = [r for r in load_results(earlier_path)
                   if not r.get("error") and r["id"] not in done
                   and (carry == "all" or r.get("vision_box") == "yes")]
        if carried:
            what = "ocenionych" if carry == "all" else "z pudełkiem na zdjęciach"
            say(f"  z wcześniejszego testu: {len(carried)} ofert {what} - bez ponownego pytania")
            results += carried
            done |= {r["id"] for r in carried}
    sink = open(progress_path, "w", encoding="utf-8") if progress_path else None
    if sink:
        for r in results:
            sink.write(json.dumps(r, ensure_ascii=False) + "\n")
        sink.flush()
    in_row = 0
    try:
        for i, row in enumerate(rows, 1):
            if row["id"] in done:
                continue
            images = read_local(photos_root, row["id"], max_photos, size) if photos_root is not None else []
            if not images:                                    # brak na dysku → CDN (żywa oferta)
                images = fetch_photos(client, row["photos"][:max_photos], size)
            if not images:
                say(f"  [{i}/{len(rows)}] {row['id']}: brak zdjęć (oferta usunięta?) - pomijam")
                continue
            answer, seconds, error = ask(client, url, model, row["title"], images, api, box_only)
            item = {"id": row["id"], "url": row["url"], "title": row["title"], "photos": len(images),
                    "state": row.get("state"), "price": row.get("price"), "condition": row.get("condition"),
                    "seconds": round(seconds, 1), "error": error, "answer": answer, **compare(row, answer)}
            results.append(item)
            if sink:
                sink.write(json.dumps(item, ensure_ascii=False) + "\n")
                sink.flush()
            if error:
                say(f"  [{i}/{len(rows)}] {row['id']}: BŁĄD {error}")
                in_row += 1
                if max_errors_in_row and in_row >= max_errors_in_row:
                    say(f"  {in_row} błędów z rzędu - serwer modelu padł? Przerywam (.bat uruchomi go ponownie).")
                    break
                continue
            in_row = 0
            if box_only:
                say(f"  [{i}/{len(rows)}] {row['id']} {seconds:.0f} s, {len(images)} zdj. | pudełko: tekst "
                    f"{item['text_box'] or '?'}, zdjęcia {item.get('vision_box')} | {row['title'][:50]}")
                continue
            say(f"  [{i}/{len(rows)}] {row['id']} {seconds:.0f} s | pudełko: tekst {item['text_box'] or '?'}, "
                f"zdjęcia {item.get('vision_box')} | pamięć: tytuł {item['title_storage'] or '?'}, "
                f"zdjęcia {item.get('vision_storage') or '?'} | 5G: tytuł {'tak' if item['title_5g'] else '?'}, "
                f"zdjęcia {item.get('vision_5g')} | {item.get('visible_text', '')[:60]}")
    finally:
        if sink:
            sink.close()
        if own:
            client.close()
    return results, summarize(results)


def summarize(results):
    ok = [r for r in results if not r["error"] and r.get("answer")]
    s = {"offers": len(results), "answered": len(ok),
         "avg_seconds": round(sum(r["seconds"] for r in ok) / len(ok), 1) if ok else None}
    # pudełko: zgodność z tekstem tam, gdzie tekst coś mówi; nowa informacja, gdzie tekst milczy
    said = [r for r in ok if r["text_box"] in ("jest", "bez")]
    s["box_text_known"] = len(said)
    s["box_agree"] = sum(1 for r in said if (r["text_box"] == "jest") == (r["vision_box"] == "yes")
                         and r["vision_box"] != "unclear")
    silent = [r for r in ok if r["text_box"] is None]
    s["box_text_silent"] = len(silent)
    s["box_found_on_photos"] = sum(1 for r in silent if r["vision_box"] == "yes")
    # pamięć: zgodność, gdy tytuł / formularz ją podaje; nowa informacja, gdy nie
    known = [r for r in ok if r["title_storage"] and r.get("vision_storage")]
    s["storage_both"] = len(known)
    s["storage_agree"] = sum(1 for r in known if r["title_storage"] == r["vision_storage"])
    s["storage_only_photos"] = sum(1 for r in ok if not r["title_storage"] and r.get("vision_storage"))
    s["net5g_only_photos"] = sum(1 for r in ok if not r["title_5g"] and r.get("vision_5g") == "yes")
    s["model_read"] = sum(1 for r in ok if r.get("vision_model"))
    return s


def report_text(results, summary, model, sample_name):
    s = summary
    pct = lambda a, b: f"{a}/{b}" + (f" ({a / b * 100:.0f}%)" if b else "")  # noqa: E731
    lines = [f"Test modelu wizyjnego {model} na próbce {sample_name}",
             f"Oferty: {s['offers']}, odpowiedzi: {s['answered']}, średnio {s['avg_seconds']} s na ofertę",
             "",
             f"Pudełko - zgodność ze słowami w ogłoszeniu: {pct(s['box_agree'], s['box_text_known'])}",
             f"Pudełko - ogłoszenie milczy, model widzi pudełko: {pct(s['box_found_on_photos'], s['box_text_silent'])}",
             f"Pamięć - zgodność z tytułem / formularzem: {pct(s['storage_agree'], s['storage_both'])}",
             f"Pamięć odczytana tylko ze zdjęć (brak w tytule): {s['storage_only_photos']}",
             f"5G odczytane tylko ze zdjęć (brak w tytule): {s['net5g_only_photos']}",
             f"Model odczytany ze zdjęć: {s['model_read']}",
             "",
             "Do ręcznego sprawdzenia (otwórz link i porównaj):"]
    for r in results:
        if r["error"]:
            lines.append(f"- {r['url']} BŁĄD {r['error']}")
            continue
        lines.append(f"- {r['url']} | {r['title'][:50]} | pudełko tekst={r['text_box'] or '?'} zdjęcia="
                     f"{r.get('vision_box')} | pamięć tytuł={r['title_storage'] or '?'} zdjęcia="
                     f"{r.get('vision_storage') or '?'} | 5G={r.get('vision_5g')} | model={r.get('vision_model') or '?'}"
                     f" | „{r.get('visible_text', '')[:80]}” | {r['seconds']} s")
    return "\n".join(lines)


def save_results(results, summary, sample_path, model):
    sample_path = Path(sample_path)
    jsonl = results_path(sample_path, model)
    txt = jsonl.with_name(jsonl.name[:-len(".jsonl")] + ".txt")
    with open(jsonl, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    text = report_text(results, summary, model, sample_path.name)
    txt.write_text(text + "\n", encoding="utf-8")
    return txt, text


# ------------------------------------------------------------------------- porównanie trybu „tylko pudełko” (19.11)
def compare_box_modes(sample_path, model, sizes=(512, 384, 320), max_photos=6, n_pos=100, n_neg=40, url=None,
                      api="openai", photos_root=None, client=None, say=print, seed=7):
    """Tryb „tylko pudełko” przy kilku rozmiarach zdjęć na ofertach z pełnego testu: n_pos, w których model widział
    pudełko (pełny test był tu ~100% trafny - sprawdzone ręcznie), i n_neg z tekstem „bez pudełka” (prawda = brak).
    Wyniki per rozmiar w *_<model>_pudelko_test<rozmiar>.jsonl (wznawialne). → (wiersze tabeli, tekst raportu)."""
    import random

    rows = {r["id"]: r for r in load_sample(sample_path)}
    full = [r for r in load_results(results_path(sample_path, model)) if not r.get("error") and r["id"] in rows]
    rnd = random.Random(seed)
    pos = [r for r in full if r.get("vision_box") == "yes"]
    neg = [r for r in full if r.get("text_box") == "bez"]
    pos, neg = rnd.sample(pos, min(n_pos, len(pos))), rnd.sample(neg, min(n_neg, len(neg)))
    truth = {**{r["id"]: True for r in pos}, **{r["id"]: False for r in neg}}
    picked = [rows[i] for i in truth]
    rnd.shuffle(picked)
    say(f"Porównanie: {len(pos)} ofert z pudełkiem (pełny test), {len(neg)} z tekstem „bez pudełka”; "
        f"rozmiary {', '.join(map(str, sizes))} px, do {max_photos} zdjęć")
    base = [r for r in full if r["id"] in truth]
    table = [{"mode": "pełny test (3 zdj. po 1024 px)", "n": len(base),
              "found": sum(1 for r in base if truth[r["id"]] and r.get("vision_box") == "yes"),
              "false": sum(1 for r in base if not truth[r["id"]] and r.get("vision_box") == "yes"),
              "seconds": sum(r["seconds"] for r in base) / len(base) if base else None}]
    for size in sizes:
        say(f"\n=== {size} px ===")
        box_file = results_path(sample_path, model, box_only=True)
        progress = box_file.with_name(f"{box_file.stem}_test{size}.jsonl")
        res, _ = run_test(picked, model, url or "http://127.0.0.1:8081", max_photos, client=client, say=say, api=api,
                          progress_path=progress, photos_root=photos_root, box_only=True, size=size)
        ok = [r for r in res if not r.get("error") and r["id"] in truth]
        table.append({"mode": f"tylko pudełko, {max_photos} zdj. po {size} px", "n": len(ok),
                      "found": sum(1 for r in ok if truth[r["id"]] and r.get("vision_box") == "yes"),
                      "false": sum(1 for r in ok if not truth[r["id"]] and r.get("vision_box") == "yes"),
                      "seconds": sum(r["seconds"] for r in ok) / len(ok) if ok else None})
    n_p, n_n = len(pos), len(neg)
    lines = [f"Porównanie trybów pudełka - {Path(sample_path).name}, model {model}",
             f"{n_p} ofert, w których pełny test widział pudełko (trafne ~100%), {n_n} z tekstem „bez pudełka”.", "",
             f"{'tryb':38} {'s / ofertę':>10} {'pudełko znalezione':>19} {'fałszywe „jest”':>16}"]
    for t in table:
        lines.append(f"{t['mode']:38} {t['seconds'] or 0:10.1f} {t['found']:>8} / {n_p:<4} ({t['found'] / max(n_p, 1):4.0%})"
                     f" {t['false']:>6} / {n_n:<4}")
    lines += ["", "Pełny test widział tylko 3 pierwsze zdjęcia - tryb z 6 zdjęciami może znaleźć pudełka, których on "
              "nie widział (te nie są w tej próbce, bo liczymy tylko oferty, w których pełny test pudełko znalazł)."]
    text = "\n".join(lines)
    out = results_path(sample_path, model).with_name(f"{results_path(sample_path, model).stem}_porownanie.txt")
    out.write_text(text + "\n", encoding="utf-8")
    return table, text, out
