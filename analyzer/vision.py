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
def sample(conn, pattern, category=None, limit=40, max_photos=4, seed=7, progress=None):
    """Żywe oferty ze szczegółami, których tytuł pasuje do `pattern` (LIKE, małe litery) → lista słowników."""
    from .photos import urls_for

    say = progress or (lambda _t: None)
    like = f"%{pattern.lower()}%"
    sql = """SELECT l.id, l.title, l.photo_url, l.details_at, l.category, l.status_label, l.price_now,
                    d.description, d.attributes_json
             FROM listings l JOIN details d ON d.listing_id = l.id
             WHERE l.state IN ('active', 'reserved') AND lower(l.title) LIKE ?"""
    params = [like]
    if category:
        sql += " AND l.category = ?"
        params.append(category)
    rows = conn.execute(sql, params).fetchall()
    say(f"  ofert pasujących do „{pattern}”: {len(rows)}")
    random.Random(seed).shuffle(rows)
    out = []
    for r in rows:
        source, urls = urls_for(conn, {"id": r[0], "photo_url": r[2], "details_at": r[3]})
        if not urls:
            continue
        try:
            attrs = json.loads(r[8]) if r[8] else {}
        except ValueError:
            attrs = {}
        out.append({"id": r[0], "url": f"https://www.vinted.pl/items/{r[0]}", "title": r[1], "category": r[4],
                    "condition": r[5], "price": r[6], "description": redact((r[7] or "")[:800]),
                    "attributes": {k: v for k, v in attrs.items() if k not in ("upload_date",)},
                    "photos": urls[:max_photos], "photo_source": source})
        if len(out) >= limit:
            break
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


def fetch_photos(client, urls):
    images = []
    for url in urls:
        try:
            r = client.get(url, timeout=30)
            r.raise_for_status()
            images.append(base64.b64encode(_shrink(r.content)).decode())
        except Exception:
            continue
    return images


def ask(client, url, model, title, images):
    """→ (odpowiedź jako dict albo None, sekundy, błąd)."""
    body = {"model": model, "stream": False, "format": SCHEMA, "options": {"temperature": 0},
            "messages": [{"role": "user", "content": PROMPT.format(title=title), "images": images}]}
    started = time.monotonic()
    try:
        r = client.post(f"{url.rstrip('/')}/api/chat", json=body, timeout=600)
        r.raise_for_status()
        text = r.json().get("message", {}).get("content", "")
        return json.loads(text), time.monotonic() - started, None
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


def run_test(rows, model, url="http://127.0.0.1:11434", max_photos=4, client=None, say=print):
    import httpx

    own = client is None
    client = client or httpx.Client(trust_env=False, follow_redirects=True)
    results = []
    try:
        for i, row in enumerate(rows, 1):
            images = fetch_photos(client, row["photos"][:max_photos])
            if not images:
                say(f"  [{i}/{len(rows)}] {row['id']}: brak zdjęć (oferta usunięta?) - pomijam")
                continue
            answer, seconds, error = ask(client, url, model, row["title"], images)
            item = {"id": row["id"], "url": row["url"], "title": row["title"], "photos": len(images),
                    "seconds": round(seconds, 1), "error": error, "answer": answer, **compare(row, answer)}
            results.append(item)
            if error:
                say(f"  [{i}/{len(rows)}] {row['id']}: BŁĄD {error}")
            else:
                say(f"  [{i}/{len(rows)}] {row['id']} {seconds:.0f} s | pudełko: tekst {item['text_box'] or '?'}, "
                    f"zdjęcia {item.get('vision_box')} | pamięć: tytuł {item['title_storage'] or '?'}, "
                    f"zdjęcia {item.get('vision_storage') or '?'} | 5G: tytuł {'tak' if item['title_5g'] else '?'}, "
                    f"zdjęcia {item.get('vision_5g')} | {item.get('visible_text', '')[:60]}")
    finally:
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
    tag = re.sub(r"[^\w.-]+", "_", model)
    jsonl = sample_path.with_name(f"{sample_path.stem}_{tag}.jsonl")   # with_suffix psuł „qwen2.5vl” (kropka)
    txt = sample_path.with_name(f"{sample_path.stem}_{tag}.txt")
    with open(jsonl, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    text = report_text(results, summary, model, sample_path.name)
    txt.write_text(text + "\n", encoding="utf-8")
    return txt, text
