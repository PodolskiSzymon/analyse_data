"""Automat w `watch` (PLAN_ANALIZY.md, E3) i alarm „brak sprzedaży”.

Automat - co `ANALYZER_AUTO_DAYS` (domyślnie 2 dni - prośba użytkownika 2026-10-30, wcześniej 3,5 dnia). Termin
liczy się od ostatniego UDANEGO automatu (`meta.auto_at` w analysis.db, zapis dopiero na końcu), więc restart albo
przerwanie watch go nie przesuwa; watch sprawdza go na starcie każdego cyklu (też zaraz po uruchomieniu - nie czeka
~3 h na koniec przejścia) i po resolve:
  1. flagi podejrzanych + relisty (analysis.db),
  2. stan techniczny przez AI tylko dla NOWYCH ofert ze wzmianką o usterce (najwyżej `ANALYZER_AUTO_AI_LIMIT`,
     3 zdjęcia - z archiwum na dysku, jeśli są), bez pytania o zgodę - koszt w powiadomieniu,
  3. `report` + `sniper-guide` → reports/<data>/,
  4. kopia wytycznych + catalogs.json (zakresy cen katalogów) do `ANALYZER_SNIPER_GUIDES_DIR` (Sniper od D5 czyta
     `sniper/guides/<kategoria>.md` i `SNIPER_CATALOGS=auto`; wczytuje pliki od nowa po zmianie) i opcjonalnie
     laptop.md do `ANALYZER_SNIPER_GUIDELINES_FILE` (stary Sniper bez D5; kopia poprzedniej wersji `.bak`),
  5. powiadomienie ntfy z podsumowaniem.
Główna baza tylko do odczytu (osobne połączenie mode=ro), wyniki w analysis.db i plikach.

Alarm „brak sprzedaży” (prośba użytkownika 2026-10-25): wśród ≥ `ANALYZER_SOLD_ALARM_MIN` zniknięć sprawdzonych przez
resolver w ostatnich `ANALYZER_SOLD_ALARM_HOURS` godzinach ani jednej sprzedanej (sold / blocked) → najpewniej Vinted
znów zmienił API (2026-10-20 sidebar sprzedanej zaczął zwracać 404/104 i przez 2 tygodnie sprzedane szły do deleted) →
powiadomienie ntfy (najwyżej raz na dobę); użytkownik zatrzymuje `watch` i zgłasza zmianę. Przy obecnym udziale
sprzedanych (~3% zniknięć) 0 na 300 to przypadek z prawdopodobieństwem ~0,01%.
"""
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import analysis

log = logging.getLogger("analyzer.auto")

GONE = ("sold", "blocked", "deleted", "closed")


def _now():
    return datetime.now(timezone.utc)


def _meta(aconn, key):
    row = aconn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return analysis.parse_ts(row[0]) if row else None


# ---------------------------------------------------------------------------------------------- alarm


def sold_check(conn, hours=72.0, minimum=300, now=None):
    """→ (alarm?, sprzedanych, usuniętych) wśród zniknięć sprawdzonych (services_at) w ostatnich `hours` godzinach."""
    since = ((now or _now()) - timedelta(hours=hours)).isoformat(timespec="milliseconds")
    counts = dict(conn.execute(f"SELECT state, COUNT(*) FROM listings WHERE services_at >= ? AND state IN "
                               f"({','.join('?' * len(GONE))}) GROUP BY state", (since, *GONE)).fetchall())
    sold = counts.get("sold", 0) + counts.get("blocked", 0)
    deleted = counts.get("deleted", 0) + counts.get("closed", 0)
    return sold == 0 and sold + deleted >= minimum, sold, deleted


async def sold_alarm(cfg, conn, aconn, now=None, send=None):
    """Sprawdza i - gdy trzeba - wysyła powiadomienie (najwyżej raz na 24 h). → True, gdy alarm."""
    from . import notify

    now = now or _now()
    alarm, sold, deleted = sold_check(conn, cfg.sold_alarm_hours, cfg.sold_alarm_min, now)
    if not alarm:
        log.info("[ALARM] Sprzedaże w ostatnich %.0f h: %d sprzedanych / %d usuniętych - OK.", cfg.sold_alarm_hours,
                 sold, deleted)
        return False
    log.error("[ALARM] %d zniknięć w ostatnich %.0f h i ANI JEDNEJ sprzedanej - pewnie Vinted zmienił API. Zatrzymaj "
              "watch (Ctrl+C) i sprawdź: python -m analyzer check <link sprzedanej oferty>.", deleted,
              cfg.sold_alarm_hours)
    last = _meta(aconn, "sold_alarm_at")
    if last is None or now - last >= timedelta(hours=24):
        await (send or notify.send)(
            "Analyzer: brak sprzedaży - zmiana API Vinted?",
            [f"{deleted} zniknięć w ostatnich {cfg.sold_alarm_hours:.0f} h, sprzedanych 0.",
             "Zatrzymaj watch (Ctrl+C) i sprawdź sprzedaną ofertę: python -m analyzer check <link>.",
             "Inaczej sprzedane trafiają do 'deleted' (jak 2026-10-20)."], priority=5, tags=("rotating_light",))
        with aconn:
            analysis.set_meta(aconn, "sold_alarm_at", now.isoformat())
    return True


# ---------------------------------------------------------------------------------------------- automat


def due(aconn, days, now=None):
    last = _meta(aconn, "auto_at")
    return last is None or (now or _now()) - last >= timedelta(days=days)


def publish(cfg, guides):
    """Kopie wytycznych do Snipera → lista skopiowanych plików."""
    copied = []
    if cfg.sniper_guides_dir:
        target = Path(cfg.sniper_guides_dir)
        target.mkdir(parents=True, exist_ok=True)
        for path, _rows in guides.values():
            shutil.copy2(path, target / path.name)
            copied.append(str(target / path.name))
        # Zakresy cen katalogów (Sniper: SNIPER_CATALOGS=auto) - z tego samego folderu co wytyczne.
        folder = next(iter(guides.values()))[0].parent if guides else None
        for name in ("catalogs.json", "comparables.db"):      # zakresy cen katalogów, porównywalne oferty
            extra = folder / name if folder else None
            if extra is not None and extra.exists():
                tmp = target / (name + ".tmp")
                shutil.copy2(extra, tmp)
                tmp.replace(target / name)                      # Sniper nie czyta pliku w połowie kopiowania
                copied.append(str(target / name))
    if cfg.sniper_guidelines_file and "laptop" in guides:
        target = Path(cfg.sniper_guidelines_file)
        if target.exists():
            shutil.copy2(target, target.with_name(target.name + ".bak"))
        shutil.copy2(guides["laptop"][0], target)
        copied.append(str(target))
    return copied


async def run(cfg, backend=None, now=None, send=None, force=False, progress=None):
    """Jeden automat, gdy minęło `auto_days` od poprzedniego (force - zawsze). → podsumowanie (dict) albo None."""
    from . import ai_condition, guide, notify, relist, report, suspicious
    from .photos import photos_dir

    say = progress or (lambda t: log.info("[AUTO] %s", t))
    aconn = analysis.open_analysis(cfg.db_path)
    try:
        if not force and not due(aconn, cfg.auto_days, now):
            return None
        conn = analysis.open_ro(cfg.db_path)
        try:
            say("flagi podejrzanych i relisty...")
            suspicious.run(conn, aconn, progress=say)       # 31.10: bez postępu wyglądało na zawieszone
            relist.run(conn, aconn, progress=say)
            ai = {"done": 0, "failed": 0, "tokens_in": 0, "tokens_out": 0, "cost": None}
            items = ai_condition.candidates(conn, aconn, ("flagged",), cfg.auto_ai_limit, 3, photos_root=photos_dir(cfg))
            if items:
                own = backend is None
                if own:
                    from sniper.config import AiConfig

                    from .ai_classify import DEFAULT_MODELS, Backend
                    ai_cfg = AiConfig()
                    if ai_cfg.api_key:
                        backend = Backend(ai_cfg, cfg.ai_model or DEFAULT_MODELS.get(ai_cfg.provider, ai_cfg.model))
                        price = ai_condition.prices(ai_cfg, backend.model)
                    else:
                        say(f"{len(items)} ofert czeka na ocenę stanu, ale brak klucza AI - pomijam.")
                        price = None
                else:
                    price = None
                if backend is not None:
                    say(f"AI stan dla {len(items)} nowych ofert...")
                    try:
                        st = await ai_condition.run(aconn, items, backend, progress=progress is not None)
                    finally:
                        if own:
                            await backend.close()
                    ai.update({k: st[k] for k in ("done", "failed", "tokens_in", "tokens_out")})
                    if price:
                        ai["cost"] = (st["tokens_in"] * price[0] + st["tokens_out"] * price[1]) / 1e6
            # 31.10: „raport i wytyczne…” stało bez znaku życia (duża baza, 4 GB RAM) - teraz każdy etap pisze, co robi;
            # z linii poleceń (auto --force) także pasek postępu statystyk.
            out = analysis.out_dir(cfg.db_path)
            say("raport (statystyki rynku)...")
            paths, lines, _ = report.build(conn, aconn, out, recompute=False, progress=say, bar=progress is not None)
            say("wytyczne Snipera i mediany (comparables.db)...")
            guides = guide.build(conn, aconn, out / "guides", progress=say)
            copied = publish(cfg, guides)
        finally:
            conn.close()
        stamp = (now or _now()).isoformat()
        with aconn:
            analysis.set_meta(aconn, "auto_at", stamp)
        summary = {"ai": ai, "report": str(paths["summary"]), "guides": {k: len(v[1]) for k, v in guides.items()},
                   "copied": copied}
        cost = f", koszt ~${ai['cost']:.2f}" if ai.get("cost") is not None else ""
        await (send or notify.send)(
            "Analyzer: automat - nowe wytyczne Snipera",
            [f"AI stan: {ai['done']} ofert (błędy {ai['failed']}){cost}",
             "Wytyczne: " + ", ".join(f"{k} {n} grup" for k, n in summary["guides"].items()),
             ("Skopiowano do Snipera: " + ", ".join(Path(c).name for c in copied)) if copied
             else "Nie skopiowano do Snipera (ustaw ANALYZER_SNIPER_GUIDES_DIR / ANALYZER_SNIPER_GUIDELINES_FILE)",
             f"Raport: {paths['summary']}"])
        say(f"gotowe: {summary}")
        return summary
    finally:
        aconn.close()
