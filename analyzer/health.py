"""Kontrola zdrowia API Vinted (prośba użytkownika 2026-11-13): czy Vinted nie zmienił API / architektury strony.

Tło: 13.11 kontrola pokrycia pokazała w wielu partycjach ~100 ofert w bazie przy 500–960 według Vinted, a na kopii
z 07.11 braków nie było. Wcześniej (20.10) sidebar sprzedanej zaczął zwracać 404 i przez 2 tygodnie nikt tego nie
zauważył. Dlatego `watch` liczy w każdym cyklu, co odpowiada Vinted, i przy odchyleniu wysyła ntfy (każdy rodzaj
problemu najwyżej raz na `ANALYZER_HEALTH_REPEAT_H` godzin, domyślnie 12).

Co sprawdzamy (klucz problemu → znaczenie):
  katalog_struktura    odpowiedź katalogu bez listy `items` (inna budowa odpowiedzi),
  katalog_paginacja    brak `pagination.total_entries` (bez tego planowanie partycji zgaduje),
  katalog_nowe_pola    nowe klucze w odpowiedzi / paginacji (np. kursor zamiast numeru strony),
  katalog_pola         pozycje bez ceny / tytułu / zdjęcia / sprzedawcy / etykiety (zmiana pól pozycji),
  katalog_krotkie      krótka strona, choć total_entries mówi, że ofert jest więcej (limit stron / wyników),
  katalog_powtorki     kolejna strona zwraca te same oferty co poprzednia (paginacja przestała działać),
  katalog_puste        pierwsza strona pusta, choć total_entries > 0,
  katalog_per_page     Vinted zwraca mniej ofert na stronę, niż prosimy,
  katalog_filtr_ceny   dużo ofert spoza zakresu ceny z zapytania (filtr ceny ignorowany / zmieniony),
  katalog_bledy        dużo błędów HTTP katalogu (blokada, zmiana adresu, wygasła sesja),
  przejscie_spadek     przejście widzi wyraźnie mniej ofert niż poprzednie przejścia tej kategorii,
  przejscie_pokrycie   w wielu partycjach w bazie dużo mniej ofert niż total_entries Vinted,
  przejscie_brak_nowych  duże przejście bez ani jednej nowej oferty,
  szczegoly_struktura  sidebar 200 bez pluginów item_status / description / attributes,
  szczegoly_bledy      dużo nietypowych kodów HTTP przy szczegółach (nie 200 / 404 usuniętej),
  zdjecia_bledy        większość pobrań zdjęć z CDN kończy się błędem.
Alarm „brak sprzedaży” (auto.sold_alarm) działa jak dotąd, osobno.

Progi są celowo luźne (fałszywy alarm co cykl byłby gorszy niż jego brak); minimalne próbki chronią przed alarmem
z jednej strony.
"""
import logging
from bisect import bisect_left, bisect_right
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median

log = logging.getLogger("analyzer.health")

# Klucze, które znamy z prawdziwych odpowiedzi (probe 2026-10-11, fixtures). Nowe = ostrzeżenie (bez alarmu
# priorytetu 5), bo Vinted czasem dokłada pola bez zmiany zachowania.
KNOWN_TOP_KEYS = {"items", "pagination", "code", "dominant_brand", "search_tracking_params", "search_session_id",
                  "promoted_closets"}
KNOWN_PAGINATION_KEYS = {"current_page", "total_pages", "total_entries", "per_page", "time"}

# Pola pozycji katalogu, z których korzysta analizator (catalog.parse_item).
ITEM_FIELDS = {
    "tytuł": lambda it: bool(it.title),
    "cena": lambda it: it.price is not None,
    "waluta": lambda it: bool(it.currency),
    "zdjęcie": lambda it: bool(it.photo_url),
    "sprzedawca": lambda it: it.seller_id is not None,
    "stan/marka (item_box)": lambda it: bool(it.status_label or it.brand),
}
SIDEBAR_PLUGINS = ("item_status", "description", "attributes")


@dataclass
class Problem:
    key: str
    title: str
    lines: list
    severe: bool = True          # False = tylko log + ntfy priorytet 3 (np. nowe pola)


@dataclass
class Health:
    """Liczniki jednego cyklu watch. Crawler / szczegóły / zdjęcia dopisują, `evaluate_*` zamienia na problemy."""
    pages: int = 0
    pages_without_items_key: int = 0
    pages_without_total: int = 0
    new_top_keys: Counter = field(default_factory=Counter)
    new_pagination_keys: Counter = field(default_factory=Counter)
    items: int = 0
    missing: Counter = field(default_factory=Counter)
    short_pages: list = field(default_factory=list)       # (kategoria, zakres, strona, ofert, total, zebrane)
    repeated_pages: list = field(default_factory=list)    # (kategoria, zakres, strona, powtórzonych, ofert)
    empty_first: list = field(default_factory=list)
    small_per_page: Counter = field(default_factory=Counter)   # zwrócone per_page -> liczba stron
    priced: int = 0
    outside_price: int = 0
    requests: int = 0
    errors: Counter = field(default_factory=Counter)      # rodzaj błędu -> liczba
    finished_runs: list = field(default_factory=list)     # (catalog_id, run_id)
    sidebars: int = 0
    sidebar_missing: Counter = field(default_factory=Counter)
    details_codes: Counter = field(default_factory=Counter)
    photos_tried: int = 0
    photos_failed: int = 0
    partition_ids: dict = field(default_factory=dict, repr=False)   # id partycji -> ID ofert z jej stron

    # ------------------------------------------------------------------ katalog
    def page(self, catalog_id, partition, page, per_page, result, price_range=None, collected_before=0):
        """Jedna strona katalogu. partition - (id, etykieta zakresu); price_range - (od, do) z marginesem."""
        self.pages += 1
        self.requests += 1
        keys = set(getattr(result, "raw_keys", ()) or ())
        if keys and "items" not in keys:
            self.pages_without_items_key += 1
        for key in keys - KNOWN_TOP_KEYS:
            self.new_top_keys[key] += 1
        for key in set(getattr(result, "pagination_keys", ()) or ()) - KNOWN_PAGINATION_KEYS:
            self.new_pagination_keys[key] += 1
        if result.total_entries is None:
            self.pages_without_total += 1
        part_id, label = partition
        n = len(result.items)
        for item in result.items:
            self.items += 1
            for name, present in ITEM_FIELDS.items():
                if not present(item):
                    self.missing[name] += 1
            if price_range is not None and item.price is not None:
                self.priced += 1
                low, high = price_range
                tol = max(1.0, (high or item.price) * 0.03)
                if (low is not None and item.price < low - tol) or (high is not None and item.price > high + tol):
                    self.outside_price += 1
        if result.per_page is not None and result.per_page < per_page:
            self.small_per_page[result.per_page] += 1
        if page == 1 and n == 0 and (result.total_entries or 0) > 0:
            self.empty_first.append((catalog_id, label, result.total_entries))
        seen = self.partition_ids.setdefault(part_id, set())
        ids = {it.id for it in result.items}
        if page > 1 and ids:
            again = len(ids & seen)
            if again >= max(1, len(ids) // 2):
                self.repeated_pages.append((catalog_id, label, page, again, len(ids)))
        seen |= ids
        total = result.total_entries
        if 0 < n < per_page and total is not None and collected_before + n < total * 0.95:
            self.short_pages.append((catalog_id, label, page, n, total, collected_before + n))

    def partition_done(self, part_id):
        self.partition_ids.pop(part_id, None)

    def request_error(self, kind):
        self.requests += 1
        self.errors[kind] += 1

    def run_finished(self, catalog_id, run_id):
        self.finished_runs.append((catalog_id, run_id))

    # ------------------------------------------------------------------ szczegóły / zdjęcia
    def sidebar(self, status_code, body):
        self.details_codes[str(status_code)] += 1
        if status_code != 200 or not isinstance(body, dict) or body.get("code", 0) != 0:
            return
        self.sidebars += 1
        sidebar = body.get("item", body)
        names = {p.get("name") for p in (sidebar.get("plugins") or []) if isinstance(p, dict)}
        for name in SIDEBAR_PLUGINS:
            if name not in names:
                self.sidebar_missing[name] += 1

    def details_error(self, kind):
        self.details_codes[kind] += 1

    def photos(self, stats):
        """Statystyki z photos.archive (zdjęcia zapisane / błędy)."""
        if not stats:
            return
        self.photos_tried += stats.get("photos", 0) + stats.get("errors", 0)
        self.photos_failed += stats.get("errors", 0)

    # ------------------------------------------------------------------ ocena
    def evaluate_catalog(self, conn=None):
        problems = []
        if self.pages >= 3 and self.pages_without_items_key >= max(2, self.pages * 0.2):
            problems.append(Problem("katalog_struktura", "Vinted: zmieniona odpowiedź katalogu",
                                    [f"{self.pages_without_items_key}/{self.pages} stron katalogu bez listy 'items'."]))
        if self.pages >= 5 and self.pages_without_total >= self.pages * 0.5:
            problems.append(Problem("katalog_paginacja", "Vinted: brak total_entries w katalogu",
                                    [f"{self.pages_without_total}/{self.pages} stron bez pagination.total_entries.",
                                     "Planowanie partycji działa wtedy na ślepo - zgłoś to."]))
        if self.new_top_keys or self.new_pagination_keys:
            lines = []
            if self.new_top_keys:
                lines.append("Nowe klucze odpowiedzi: " + ", ".join(sorted(self.new_top_keys)))
            if self.new_pagination_keys:
                lines.append("Nowe klucze paginacji: " + ", ".join(sorted(self.new_pagination_keys)))
            problems.append(Problem("katalog_nowe_pola", "Vinted: nowe pola w katalogu", lines, severe=False))
        if self.items >= 200:
            bad = {k: v for k, v in self.missing.items() if v >= self.items * 0.2}
            if bad:
                problems.append(Problem("katalog_pola", "Vinted: brak pól w ofertach katalogu",
                                        [f"{k}: brak w {v}/{self.items} ofert ({v / self.items:.0%})"
                                         for k, v in sorted(bad.items())]))
        if len(self.short_pages) >= 3:
            worst = sorted(self.short_pages, key=lambda s: s[4] - s[5], reverse=True)[:4]
            problems.append(Problem("katalog_krotkie", "Vinted: krótkie strony katalogu",
                                    [f"{len(self.short_pages)} stron krótszych niż per_page, choć total_entries "
                                     "mówi o większej liczbie ofert (limit stron/wyników?):"] +
                                    [f"kat. {c} {lab}: strona {p} = {n} ofert, total {t}, zebrane {got}"
                                     for c, lab, p, n, t, got in worst]))
        if len(self.repeated_pages) >= 2:
            problems.append(Problem("katalog_powtorki", "Vinted: kolejne strony powtarzają oferty",
                                    [f"{len(self.repeated_pages)} stron zwraca oferty z poprzednich stron "
                                     "(paginacja zmieniona? np. kursor zamiast numeru strony):"] +
                                    [f"kat. {c} {lab}: strona {p}: {a}/{n} powtórzonych"
                                     for c, lab, p, a, n in self.repeated_pages[:4]]))
        if len(self.empty_first) >= 2:
            problems.append(Problem("katalog_puste", "Vinted: puste strony katalogu",
                                    [f"{len(self.empty_first)} partycji: strona 1 pusta, choć total_entries > 0."] +
                                    [f"kat. {c} {lab}: total {t}" for c, lab, t in self.empty_first[:4]]))
        if sum(self.small_per_page.values()) >= 3:
            problems.append(Problem("katalog_per_page", "Vinted: mniej ofert na stronę",
                                    ["Vinted zwraca per_page mniejsze niż prosimy: " +
                                     ", ".join(f"{k} ({v} stron)" for k, v in self.small_per_page.most_common(3))]))
        if self.priced >= 200 and self.outside_price >= self.priced * 0.3:
            problems.append(Problem("katalog_filtr_ceny", "Vinted: filtr ceny nie działa",
                                    [f"{self.outside_price}/{self.priced} ofert spoza zakresu ceny z zapytania."]))
        errors = sum(self.errors.values())
        if self.requests >= 20 and errors >= self.requests * 0.2:
            problems.append(Problem("katalog_bledy", "Vinted: dużo błędów katalogu",
                                    [f"{errors}/{self.requests} zapytań katalogu z błędem: " +
                                     ", ".join(f"{k} {v}" for k, v in self.errors.most_common(4))]))
        if conn is not None:
            for catalog_id, run_id in self.finished_runs:
                problems += run_problems(conn, catalog_id, run_id)
        return problems

    def evaluate_background(self):
        problems = []
        if self.sidebars >= 30:
            bad = {k: v for k, v in self.sidebar_missing.items() if v >= self.sidebars * 0.3}
            if bad:
                problems.append(Problem("szczegoly_struktura", "Vinted: zmieniona odpowiedź szczegółów",
                                        [f"plugin {k}: brak w {v}/{self.sidebars} odpowiedzi 200" for k, v in
                                         sorted(bad.items())]))
        total = sum(self.details_codes.values())
        odd = sum(v for k, v in self.details_codes.items() if k not in ("200", "404"))
        if total >= 30 and odd >= total * 0.3:
            problems.append(Problem("szczegoly_bledy", "Vinted: dużo błędów szczegółów",
                                    [f"{odd}/{total} odpowiedzi szczegółów nietypowych: " +
                                     ", ".join(f"{k} {v}" for k, v in self.details_codes.most_common(5))]))
        if self.photos_tried >= 50 and self.photos_failed >= self.photos_tried * 0.5:
            problems.append(Problem("zdjecia_bledy", "Vinted: zdjęcia się nie pobierają",
                                    [f"{self.photos_failed}/{self.photos_tried} pobrań zdjęć z CDN z błędem."]))
        return problems


# ---------------------------------------------------------------------------------------------- przejście w bazie
def partition_coverage(conn, catalog_id, run_id, tolerance=1.0, tolerance_pct=1.5):
    """[(etykieta, total Vinted, w bazie)] dla partycji ukończonych w przejściu run_id (jak status: kontrola pokrycia)."""
    prices = sorted(r[0] for r in conn.execute(
        "SELECT price_now FROM listings WHERE catalog_id=? AND last_run_id=? AND price_now IS NOT NULL",
        (catalog_id, run_id)))
    out = []
    for row in conn.execute("SELECT price_from, price_to, last_total FROM partitions WHERE catalog_id=? AND active=1 "
                            "AND done_run_id=? AND last_total IS NOT NULL", (catalog_id, run_id)):
        lo = row[0] - max(tolerance, row[0] * tolerance_pct / 100)
        hi = row[1] + max(tolerance, row[1] * tolerance_pct / 100) if row[1] is not None else 1e12
        have = bisect_right(prices, hi) - bisect_left(prices, lo)
        label = f"{row[0]:g}-{'∞' if row[1] is None else format(row[1], 'g')} zł"
        out.append((label, row[2], have))
    return out


def run_problems(conn, catalog_id, run_id, history=5):
    from .config import catalog_label

    problems = []
    run = conn.execute("SELECT * FROM crawl_runs WHERE id=?", (run_id,)).fetchone()
    if run is None:
        return problems
    name = catalog_label(catalog_id)
    unique = conn.execute("SELECT COUNT(*) FROM listings WHERE catalog_id=? AND last_run_id=?",
                          (catalog_id, run_id)).fetchone()[0]
    previous = [r[0] for r in conn.execute(
        "SELECT seen FROM crawl_runs WHERE catalog_id=? AND kind='crawl' AND finished_at IS NOT NULL AND id<? "
        "AND seen > 0 ORDER BY id DESC LIMIT ?", (catalog_id, run_id, history))]
    seen = run["seen"] or 0
    if len(previous) >= 3 and median(previous) >= 500 and seen < 0.7 * median(previous):
        problems.append(Problem(f"przejscie_spadek_{catalog_id}", f"Vinted: mniej ofert w kategorii {catalog_id}",
                                [f"Kategoria {name}: przejście #{run_id} widziało {seen} ofert, poprzednie "
                                 f"(mediana z {len(previous)}) {median(previous):.0f}."]))
    coverage = partition_coverage(conn, catalog_id, run_id)
    short = [c for c in coverage if c[1] >= 100 and c[2] < 0.8 * c[1]]
    if len(coverage) >= 3 and len(short) >= max(2, len(coverage) * 0.1):
        short.sort(key=lambda c: c[1] - c[2], reverse=True)
        problems.append(Problem(f"przejscie_pokrycie_{catalog_id}", f"Vinted: dziury w kategorii {catalog_id}",
                                [f"Kategoria {name}: {len(short)}/{len(coverage)} partycji z dużymi brakami "
                                 f"(w bazie < 80% total_entries), unikalnych ofert {unique}:"] +
                                [f"{lab}: Vinted {t}, w bazie {h}" for lab, t, h in short[:4]]))
    if seen >= 3000 and (run["new_ids"] or 0) == 0:
        problems.append(Problem(f"przejscie_brak_nowych_{catalog_id}", f"Vinted: 0 nowych ofert w {catalog_id}",
                                [f"Kategoria {name}: przejście #{run_id} widziało {seen} ofert i ani jednej nowej."]))
    return problems


# ---------------------------------------------------------------------------------------------- powiadomienia
async def report(cfg, problems, aconn=None, now=None, send=None):
    """Log + ntfy (każdy klucz najwyżej raz na cfg.health_repeat_hours, termin w analysis.db). → wysłane klucze."""
    from . import analysis, notify

    now = now or datetime.now(timezone.utc)
    repeat = timedelta(hours=getattr(cfg, "health_repeat_hours", 12.0))
    sent = []
    for p in problems:
        (log.error if p.severe else log.warning)("[HEALTH] %s: %s", p.title, " | ".join(p.lines))
    if not getattr(cfg, "health_notify", True):
        return sent
    due = []
    for p in problems:
        last = None
        if aconn is not None:
            row = aconn.execute("SELECT value FROM meta WHERE key=?", (f"health_{p.key}",)).fetchone()
            last = analysis.parse_ts(row[0]) if row else None
        if last is None or now - last >= repeat:
            due.append(p)
    if not due:
        return sent
    severe = any(p.severe for p in due)
    title = (due[0].title if len(due) == 1 else f"Vinted: {len(due)} problemy z API") + " (analyzer)"
    lines = []
    for p in due:
        lines.append(f"• {p.title}")
        lines += [f"  {x}" for x in p.lines]
    lines.append("Sprawdź: python -m analyzer api-test i wyślij wynik. Analizator działa dalej.")
    ok = await (send or notify.send)(title, lines, priority=5 if severe else 3,
                                     tags=("rotating_light",) if severe else ("warning",))
    if ok and aconn is not None:
        with aconn:
            for p in due:
                analysis.set_meta(aconn, f"health_{p.key}", now.isoformat())
    if ok:
        sent = [p.key for p in due]
    return sent
