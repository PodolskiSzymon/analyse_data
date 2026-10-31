"""Szafa sprzedawcy (2026-10-29, pomysł użytkownika): czy zniknięta oferta jest w szafie (sprzedana / dalej aktywna),
czy jej nie ma (usunięta), czy konta już nie ma (usunięte / zablokowane).

Adres z przeglądarki użytkownika: `GET www.vinted.pl/api/v2/wardrobe/{seller_id}/items?page=1&per_page=20` →
{"items": [{id, item_closing_action, is_closed, is_reserved, is_hidden, ...}], "pagination": {total_pages, ...}}.
⚠ NIEPOTWIERDZONE: czy sprzedane oferty są w tej liście (z item_closing_action="sold") i co zwraca szafa usuniętego
konta - dlatego najpierw komenda testowa:

    python -m analyzer szafa-test [--limit 20] [--pages 3]

Bierze ostatnio rozpoznane zniknięcia z zapisanym seller_id (zbierane od migracji v12, 29.10), pyta o szafy przez
proxy (jak resolver) i pokazuje: nasz stan → wynik w szafie, oraz ile KB kosztuje strona szafy. Bazy nie zmienia.
"""
import asyncio
import logging

log = logging.getLogger("analyzer.wardrobe")

WARDROBE_URL = "https://www.vinted.pl/api/v2/wardrobe/{seller_id}/items?page={page}&per_page={per_page}"


async def fetch_page(session, seller_id, page=1, per_page=20):
    """→ (status HTTP, odpowiedź JSON, bajty odpowiedzi). 401/403 = brak / wygasła sesja → jedno odświeżenie
    (przeglądarka przez proxy, jak resolver) i ponowienie."""
    url = WARDROBE_URL.format(seller_id=seller_id, page=page, per_page=per_page)
    for attempt in range(2):
        response = await session.client.get(url, headers={"referer": f"https://www.vinted.pl/member/{seller_id}"})
        session.traffic.add_http("details", response)
        if response.status_code not in (401, 403) or attempt:
            break
        await session.refresh()
    try:
        body = response.json()
    except ValueError:
        body = {"_text": response.text[:300]}
    return response.status_code, body, len(response.content or b"")


def verdict(item):
    """Stan oferty znalezionej w szafie."""
    action = item.get("item_closing_action")
    if action:
        return f"w szafie: {action}"
    for key, label in (("is_closed", "zamknięta"), ("is_reserved", "zarezerwowana"), ("is_hidden", "ukryta"),
                       ("is_draft", "szkic")):
        if item.get(key):
            return f"w szafie: {label}"
    return "w szafie: aktywna"


async def find(session, seller_id, item_id, pages=3, per_page=20, sleep=asyncio.sleep, delay=1.0):
    """→ (wynik, zapytań, bajtów). Szuka oferty na kolejnych stronach szafy (najwyżej `pages`)."""
    requests = size = 0
    for page in range(1, pages + 1):
        if page > 1:
            await sleep(delay)
        status, body, n = await fetch_page(session, seller_id, page, per_page)
        requests, size = requests + 1, size + n
        if status == 404:
            return "szafa 404 - konto usunięte / zablokowane?", requests, size
        if status != 200 or not isinstance(body, dict):
            return f"szafa HTTP {status}", requests, size
        for item in body.get("items") or []:
            if item.get("id") == item_id:
                return verdict(item), requests, size
        total = (body.get("pagination") or {}).get("total_pages") or 1
        if page >= total:
            return "brak w szafie", requests, size
    return f"brak na {pages} stronach (szafa większa)", requests, size


def candidates(conn, limit):
    return conn.execute(
        "SELECT id, seller_id, state, title, category, price_now FROM listings WHERE seller_id IS NOT NULL "
        "AND state IN ('deleted', 'sold', 'blocked', 'gone_pending', 'unlisted') ORDER BY state_at DESC LIMIT ?",
        (limit,)).fetchall()


def short(result):
    """„w szafie: sold” → „sold”, „brak na 3 stronach (…)” → „brak” - do licznika na pasku postępu."""
    text = result.split(" (")[0].split(" - ")[0]
    return text.replace("w szafie: ", "").replace("brak w szafie", "brak").split(" na ")[0]


async def run(session, rows, pages=3, per_page=20, sleep=asyncio.sleep, delay=(1.0, 2.0), progress=None, bar=None):
    """→ (wiersze [(row, wynik)], podsumowanie {(nasz stan, wynik): liczba}, zapytań, bajtów).
    bar - pasek postępu (progress.ConsoleBar): przed każdą ofertą „sprawdzam…”, po niej wynik i liczniki."""
    import random
    import time
    out, summary, requests, size = [], {}, 0, 0
    say = progress or (lambda _t: None)
    draw = bar or (lambda _ev: None)
    counts, started = {}, time.monotonic()

    def event(stage, n, row, key=None):
        done = n - (stage == "check")
        eta = (time.monotonic() - started) / done * (len(rows) - done) if done else None
        return {"stage": stage, "n": done, "total": len(rows), "row": row, "key": key, "counts": counts, "eta": eta}

    for n, row in enumerate(rows, 1):
        if n > 1:
            await sleep(random.uniform(*delay))
        draw(event("check", n, row))
        result, r, b = await find(session, row["seller_id"], row["id"], pages, per_page, sleep)
        requests, size = requests + r, size + b
        out.append((row, result))
        key = (row["state"], result.split(" (")[0].split(" - ")[0])
        summary[key] = summary.get(key, 0) + 1
        counts[short(result)] = counts.get(short(result), 0) + 1
        draw(event("done", n, row, short(result)))
        say(f"  [{n}/{len(rows)}] {row['id']} {row['state']:<12} → {result}")
    return out, summary, requests, size


def lines(out, summary, requests, size):
    text = ["", "nasz stan    → w szafie: ofert"]
    text += [f"  {state:<12} → {result}: {n}" for (state, result), n in sorted(summary.items())]
    text.append(f"Zapytań {requests}, {size / 1024:.0f} KB (śr. {size / max(requests, 1) / 1024:.1f} KB / stronę "
                f"szafy).")
    text.append("Przykłady (sprawdź w przeglądarce):")
    text += [f"  https://www.vinted.pl/items/{row['id']}  {row['state']:<12} {result}  {(row['title'] or '')[:40]}"
             for row, result in out[:15]]
    return text
