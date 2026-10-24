# PLAN_ANALIZY – co robić dalej i jak analizować dane

Ten plik wykonuje nowy czat po komendzie „wykonaj md”. Kroki A1–A6 to **kod**, który piszesz Ty (Claude): bez sieci,
z testami na atrapie. Kroki B1–B4 uruchamia **użytkownik** na serwerze; Ty dajesz mu gotowe komendy (Windows `cmd`)
i czekasz na wklejony wynik / plik. Kroki C1–C5 to **analiza** wyników, które przyśle użytkownik.
Stan 2026-10-24. Lista kontrolna na końcu – odhaczaj.

---

## 0. Skąd jesteśmy (stan danych, 2026-10-24)

Program `analyzer` od 2026-10-11 chodzi u użytkownika w trybie `watch` (co 10–14 h pełne przejście katalogów +
rozpoznanie zniknięć). Kategorie Vinted: laptopy 3580, telefony 3661, konsole 3025, tablety 3728 oraz mieszane
3582/3583/3584, z których klasyfikator (`analyzer/classify.py`) wyciąga `gpu`, `ram`, `storage` (SSD). Kolumna
`listings.category` = NASZA kategoria (`laptop|phone|console|tablet|gpu|ram|storage`), niezależna od `catalog_id`.

Ostatnie znane liczby od użytkownika:

* baza ~1,27 GB, kilkadziesiąt tysięcy ofert śledzonych; ~17 tys. laptopów ≥ 700 zł aktywnych naraz.
* **`recheck`** (naprawa stanów, 2026-10-24, 5,1 h, 78,6 MB): sprawdzono 13 841 ofert oznaczonych wcześniej
  `deleted` → **deleted 13 300, sold 454**, unlisted 53, active 23, hidden 2, błąd 9.
* **`html-details --random` na 200 losowych `deleted`**: 199 × strona oferty 404 (naprawdę nie istnieje), 1 błąd proxy.
* **`html-details` na sprzedanych (pierwsze 5)**: 2 z opisem, **3 × strona 404 → stan `blocked`** (oszustwa
  zablokowane przez Vinted – powtarzane „iPhone 16 Pro 512 GB za 519 zł”, „iPhone 15 Pro 900 zł, sprzedaż wyłącznie
  przez OLX/Allegro”).
* **`extract-report`** – pokrycie klucza konfiguracji (`features.config_key`): laptop 39% (38 283 wierszy, w tym
  `below_min` bez opisów – dla aktywnych z opisem dużo więcej), phone 90%, tablet 73%, console 66%, gpu 72%,
  ram 91%, storage 88%. Liczby sprzedanych na konfigurację są **małe** (pojedyncze sztuki).

### Najważniejsze zastrzeżenia do danych (MUSZĄ być w każdym raporcie)

1. **Sprzedaż jest niedoszacowana i nie da się jej w pełni odtworzyć wstecz.** Do ok. 2026-10-20 sidebar sprzedanej
   oferty dawał `item_closing_action=sold`; potem Vinted przebudował API – sidebar sprzedanej = 404/104, tak samo jak
   usuniętej. Przez ~2 tygodnie resolver oznaczał więc sprzedane jako `deleted`. `recheck` (`/services`: 200 = oferta
   istnieje → sprzedana; 404/104 = usunięta) odzyskał 454 sprzedane, ale **13 300 ofert naprawdę już nie istnieje**
   (strona 404). Użytkownik uważa (i to jest prawdopodobne), że **znaczna część tych `deleted` to sprzedane, które
   potem zniknęły** (sprzedawca usunął sprzedaną ofertę, Vinted usuwa/ukrywa sprzedane po pewnym czasie albo po
   zakończeniu transakcji, albo konto zostało usunięte). Dziś nie da się ich rozróżnić. ⇒
   * `sold` = **dolna granica** liczby sprzedaży; `sold + deleted` = górna granica „zniknięć z rynku”.
   * Liczyć wskaźniki w dwóch wariantach: „pewne sprzedane” i „sprzedane + usunięte” (widełki).
   * Od 2026-10-24 resolver w `watch` używa poprawnej logiki (`/services` + sidebar) → oferty znikające **od teraz**
     są klasyfikowane poprawnie, jeśli zostaną sprawdzone szybko (patrz C4 – eksperyment „czy sprzedane znikają”).
2. **Cena sprzedaży = ostatnia cena wystawienia** (górna granica; „Zaproponuj cenę” niewidoczne). `sold_price` z
   `/services.original_asking_amount` (zł w chwili sprawdzenia; dla ofert zagranicznych + `seller_price` w walucie
   sprzedawcy).
3. **Czas sprzedaży**: `days_to_sell` liczone od `COALESCE(created_at, first_seen)`. Oferty z PIERWSZEGO przejścia
   danej kategorii (2026-10-11 dla laptopów, 2026-10-12 dla pozostałych) mają `first_seen` ≠ data wystawienia →
   bez `created_at` (z „Dodane” w details/html) **wykluczyć z mediany czasu sprzedaży**. „Dodane” jest przybliżone
   („3 mies.”), ⚠ nie wiadomo, czy podbicie zmienia datę.
4. **Dryf kursów**: oferty zagraniczne (`seller_currency` ≠ PLN: RON, EUR, HUF, CZK, SEK, DKK…) zmieniają cenę w zł
   co przejście. W `observations` stare wiersze dryfu z 2026-10-12 zostały – zmiany cen liczyć tylko przez
   `db.real_change` (PLN: każda zmiana; zagraniczne ≥ 1%). **Rozdzielać rynek krajowy i zagraniczny**
   (`listings.seller_currency` / `details.seller_currency`; przed details: ułamkowa cena = zagraniczna).
5. **Oszustwa**: stan `blocked` (sprzedana, strona 404) + podejrzane wzorce (patrz A3) – wykluczać ze statystyk cen.
6. **Ponowne wystawienia** (usuń + wystaw od nowa, żeby oferta była „nowa” w katalogu) mogą zawyżać `deleted`
   i zaniżać czas sprzedaży – patrz A4.
7. Rezerwacje na Vinted przestały działać (użytkownik) → `reserved` praktycznie nie występuje; nie analizować.
8. `below_min` = oferty tańsze niż próg kategorii (laptop 700, phone/console/tablet 300, gpu 150, ram/storage 100) –
   nie śledzone dokładnie, poza analizą.

### Schemat bazy (to, czego potrzebujesz do SQL; pełny w `analyzer/db.py`, migracje do v11)

* `listings` (1 wiersz = 1 oferta, klucz = ID Vinted): `id, catalog_id, category, category_src, title, brand, model,
  status_label` (stan z formularza: „Nowy z metką / Bardzo dobry / Dobry / Zadowalający…”), `currency, photo_url,
  created_at, first_seen, last_seen, last_run_id, missed_runs, state, state_at, sold_price, days_to_sell,
  details_at, content_hash, relist_of` (nieużywane – do wypełnienia w A4), `seller_hash` (zwykle NULL – sól pusta),
  `favourite_count, view_count, price_now, total_now` (bieżąca cena / z opłatą), `seller_country, services_at,
  seller_price, seller_currency`.
* `state`: `active, reserved, gone_pending, sold, deleted, closed, hidden, unlisted, below_min, ignored,
  unclassified, blocked`.
* `observations(listing_id, seen_at, price, total_price, is_reserved, favourite_count)` – wiersz przy pierwszym
  widzeniu i przy prawdziwej zmianie (od v5).
* `details(listing_id, fetched_at, description, attributes_json, upload_age, created_est, business,
  seller_currency, photo_count, is_localized, source)` – `source` = `sidebar` (API) albo `html` (strona oferty).
* `features(listing_id, category, version, extracted_at, fields_json, config_key, model, cpu, cpu_line, gpu, ram_gb,
  storage_gb, screen_in, refresh_hz, battery_pct, condition_grade, for_parts, locked, cracked, segment)` – wynik
  `extract.py` (reguły). `fields_json` = `{pole: {value, source, weight, evidence}}`.
* `raw(listing_id, kind, fetched_at, body)` – skompresowane surowe odpowiedzi (`catalog`, `sidebar`, `resolve`,
  `services`, `html`…), dekompresja `analyzer/rawstore.py`.
* `crawl_runs` – przejścia (start, koniec, zapytania, bajty, nowe, zmienione, zniknięte) → kiedy był pierwszy run
  kategorii: `SELECT catalog_id, MIN(started_at) FROM crawl_runs GROUP BY catalog_id`.

**Zasada dla kodu analizy: baza jest współdzielona z działającym `watch`.** Czytaj przez połączenie tylko do odczytu
(`sqlite3.connect("file:...?mode=ro", uri=True)`), **nie dodawaj migracji** i nie pisz do `analyzer.db` z komend
analizy. Wyniki pośrednie (flagi podejrzanych, relisty) zapisuj do osobnej bazy `data/analysis.db` (tworzona przez
`report`, można ją `ATTACH`) albo do plików w `data/reports/<data>/`. Wyjątek: jeśli coś MUSI trafić do głównej bazy,
to przez migrację v12 w `db.py` – i wtedy użytkownik musi uruchamiać `watch` z TEGO repo (patrz B1).

---

## A. Kod (Ty, bez sieci) – w tej kolejności

### A1. Sprawdź zrzut
`python -m pytest analyzer/tests sniper/tests -q` → ma być 333 passed. Jeśli brakuje zależności: `pip install -r
sniper/requirements.txt` (+ `zstandard` opcjonalnie).

### A2. Atrapa bazy do testów analizy – `analyzer/tests/fake_market.py`
Funkcja budująca syntetyczną bazę (schemat przez `db.connect` + migracje) z ~2–5 tys. ofert w kilku kategoriach:
różne `config_key`, stany (active/sold/deleted/blocked/below_min), ceny PLN i zagraniczne (ułamkowe), `created_at`
dla części, kilka obniżek ceny w `observations`, dryf kursu, oszustwa (ten sam tytuł + cena 10×, cena 20% mediany,
„tylko OLX” w opisie), relisty (usunięta + identyczny tytuł/cena/model pojawia się 0–3 dni później z nowym ID),
oferty z pierwszego przejścia bez `created_at`. Wartości oczekiwane mają być policzalne ręcznie w teście.

### A3. Flagi podejrzanych – `analyzer/suspicious.py`
Bez sieci, czytanie bazy tylko do odczytu, wynik do `data/analysis.db` tabela `flags(listing_id, flag, detail)`.
Flagi (każda osobno, raport pokazuje ile ofert każda wyklucza):
* `blocked` – stan `blocked`.
* `dup_title_price` – ten sam znormalizowany tytuł (lowercase, bez znaków, zwinięte spacje) i ta sama cena
  (±1 zł) u ≥ 3 ofert w 30 dni, i to cena < 60% mediany konfiguracji (żeby nie łapać sklepów z jednakowymi
  ofertami po rynkowej cenie – te oznaczyć `shop_like`, nie wykluczać).
* `offsite` – w opisie/tytule: olx, allegro, whatsapp, telegram, „kontakt poza”, „tylko odbiór osobisty i przelew”,
  numer telefonu/e-mail (wykrywanie jak w `sample.redact`), w ~10 językach jak w `classify.py`.
* `too_cheap` – cena < 40% mediany tej samej konfiguracji (min. 8 ofert w grupie) i nie `for_parts`.
* `is_suspicious` – ⚠ hipoteza użytkownika: pole `photo.is_suspicious` w surowej pozycji katalogu (`raw` kind
  `catalog`). Najpierw daj użytkownikowi komendę diagnostyczną (B2), dopiero po wyniku włącz flagę.
Tryb `python -m analyzer suspicious-report` – liczby per flaga i kategoria + 10 przykładowych linków
`https://www.vinted.pl/items/<id>` per flaga (użytkownik sprawdza w przeglądarce).

### A4. Ponowne wystawienia – `analyzer/relist.py`
Oferta B jest relistem A, gdy: ta sama `category`, ten sam znormalizowany tytuł (albo podobieństwo ≥ 0,9 – `difflib`
na krótkich tytułach wystarczy, z blokowaniem po `brand`+`config_key`, żeby nie liczyć O(n²)), ta sama marka/model,
cena B w ±15% ceny A, B `first_seen` w [A `last_seen` − 1 dzień; A `last_seen` + 14 dni], A zniknęła (`deleted`/
`sold`/`unlisted`). Zdjęcia nie pobieramy (koszt) – ewentualnie później pHash miniatury.
Wynik do `analysis.db: relists(old_id, new_id, score)`. Skutki w statystykach:
* A oznaczone jako relist → **nie liczyć jako zniknięcie ani sprzedaż**; łańcuch A→B→C = jedna „oferta logiczna”
  z czasem życia od pierwszego `first_seen` (prawdziwy czas na rynku).
* `relist-report`: ile `deleted` to relisty (%), per kategoria, przykłady linków.
To bezpośrednio odpowiada na pytanie użytkownika, czemu „usuniętych” jest tak dużo.

### A5. Statystyki i raport – `analyzer/stats.py` + `analyzer/report.py`, CLI `python -m analyzer report`
Wejście: baza (ro) + `analysis.db` (flagi, relisty). Wyjście do `data/reports/<YYYY-MM-DD>/`:
* `summary.md` – **krótkie** (≤ ~150 linii) zestawienie do wklejenia w czat / dla dużego modelu (nie surowe wiersze).
* `configs.csv` – pełna tabela per (category, config_key, rynek PL/zagr.).
* `report.html` – jeden plik, tabele + proste wykresy (inline SVG albo bez wykresów; bez zewnętrznych CDN-ów
  wymagających internetu nie ma potrzeby – ale wolno).
Miary per grupa (category, config_key; osobno rynek krajowy / zagraniczny; wykluczone flagi A3 i relisty A4):
* `n_active`, mediana / p25 / p75 ceny ofertowej aktywnych (`price_now`),
* `n_sold`, mediana / p25 / p75 `sold_price` (z dopiskiem „górna granica”),
* `n_deleted` (bez relistów) i **sell-through w widełkach**: dolna = sold / (sold + deleted + active_starsze_niż_X),
  górna = (sold + deleted) / (…) – opisz wzór w `summary.md`,
* mediana `days_to_sell` – tylko oferty z `created_at` albo `first_seen` > pierwszy run kategorii (zastrz. 3);
  pokaż `n` z którego liczona,
* obniżki: % ofert z ≥ 1 prawdziwą obniżką (`real_change`), mediana obniżki %, mediana dni do pierwszej obniżki,
  czy oferty po obniżce sprzedają się częściej,
* popyt: mediana `favourite_count` / `view_count` aktywnych vs sprzedanych,
* „spread”: mediana ceny sprzedanych / mediana ceny aktywnych (ile poniżej wystawionych schodzą sprzedane).
Grupy z `n_sold < 3` raportować, ale z flagą „mało danych”; dla konfiguracji z małą liczbą sprzedaży dawać także
poziom wyżej (np. laptop: `cpu_line + ram_gb`, bez dysku; telefon: model bez pojemności) – hierarchia kluczy
w `extract.py` / `EKSTRAKCJA.md`.
Wymagania techniczne: SQL z agregacją + Python `statistics` / własny percentyl, czytanie strumieniowe; czas na
serwerze użytkownika < ~5 min przy ~200 tys. ofert; pasek postępu (`analyzer/progress.py`); test na atrapie A2
sprawdzający liczby co do sztuki.

### A6. Eksport do analizy w czacie – `python -m analyzer export-analysis [--with-descriptions]`
Bo Ty nie masz dostępu do bazy, a `summary.md` czasem nie wystarczy. → `data/export/<data>/`:
`listings.csv.gz` (bez `seller_hash`, bez `photo_url`), `features.csv.gz`, `observations_real.csv.gz` (tylko
prawdziwe zmiany), `crawl_runs.csv`, opcjonalnie `descriptions.jsonl.gz` (opis przez `sample.redact`, obcięty do
2000 znaków). Na końcu wypisz rozmiary plików; cel: < ~50 MB łącznie (użytkownik wrzuca je do czatu). Bez danych
sprzedawców (RODO).

Po A1–A6: testy zielone → commit (trailer jak w ustawieniach sesji) → push `main` → przejdź do B.

---

## B. Użytkownik (serwer) – daj mu dokładnie te komendy

### B1. Przełączenie na to repo (raz)
Komendy z `CLAUDE.md` („Uruchomienie”). `watch` może dalej chodzić ze starego folderu `category_analyzer` – kod
analizy tylko czyta bazę. Jeśli kiedyś dodasz migrację do `analyzer.db` albo zmienisz zbieranie danych (C4),
użytkownik musi: zatrzymać `watch` w starym folderze (Ctrl+C), uruchomić `watch` z `analyse_data` (`watch.bat`
albo `python -m analyzer watch`) z tym samym `ANALYZER_DB`. Nigdy dwa `watch` naraz na jednej bazie.

### B2. Diagnostyka (krótkie wyniki do wklejenia)
* `python -m analyzer status`
* test `is_suspicious` – daj jednolinijkowy skrypt (`python -c` …), który z `raw` kind `catalog` (`rawstore.decompress`)
  liczy rozkład `photo.is_suspicious` (i innych pól `photo.*` z wartością bool) osobno dla `blocked`, `sold`,
  `deleted`, `active` (próbka po 2000 na stan, ro). Hipoteza użytkownika: oszustwa mają `is_suspicious=true`.
* relisty – po A4: `python -m analyzer relist-report`.

### B3. Raport
`python -m analyzer suspicious-report`, `python -m analyzer report` → użytkownik wkleja `summary.md` (albo wysyła
plik) i ewentualnie `report.html`.

### B4. Opcjonalnie eksport
`python -m analyzer export-analysis --with-descriptions` → wysyła pliki do czatu, jeśli potrzebujesz głębszej analizy.

---

## C. Analiza (Ty, na wynikach od użytkownika)

### C1. Kontrola jakości danych (zanim padną jakiekolwiek wnioski o cenach)
* Ile ofert per kategoria/stan; ile ma `config_key`; ile wykluczają flagi i relisty; udział rynku zagranicznego.
* Rozkład `state_at − last_seen` dla `sold`/`deleted` (jak szybko resolver sprawdził zniknięcie) – rozdziel
  zniknięcia sprzed 2026-10-24 (stara logika, potem `recheck`) i po (nowa logika).
* Czy `sold` ma sensowne ceny (vs mediana aktywnych tej konfiguracji) – za tanie sprzedane = oszustwa do flag.

### C2. Ceny rynkowe per konfiguracja
Tabela „konfiguracja → mediana ceny ofertowej, mediana ceny sprzedaży (górna granica), widełki sell-through,
mediana dni do sprzedaży, n”. Osobno PL / zagranica. Najpierw grupy z największą liczbą sprzedaży; dla rzadkich –
poziom wyżej w hierarchii kluczy. Wnioski typu: „ThinkPad T480 i5 16 GB 256 GB: oferty 1100–1300 zł, sprzedane
~1050 zł, sprzedaje się w ~6 dni”.

### C3. Strategie użytkownika
* **Okazje dla Snipera** (`sniper/guidelines.md` ma dziś ręczne progi): próg okazji = np. p25 ceny sprzedaży
  konfiguracji minus koszt wysyłki/opłaty; które konfiguracje rotują najszybciej (najmniej dni, największy
  sell-through) – tam opłaca się kupować pod odsprzedaż. Przygotuj propozycję tabeli progów do wklejenia w
  `sniper/guidelines.md` (Etap 5 w `ARCHITEKTURA.md`: integracja ze Sniperem – docelowo Sniper czyta ceny z bazy).
* **Rozbiórka** (`ATRYBUTY.md` §6, `ATRYBUTY_KONSOLE.md` §16): z = x + y − zakup − c – laptop z dużym RAM/SSD
  kupiony, RAM/dysk sprzedane osobno (ceny z kategorii `ram`/`storage`), laptop z mniejszymi częściami; policz,
  dla których konfiguracji wychodzi z > 0 (ceny części z mediany sprzedanych, jeśli n małe – z ofertowych z dyskontem).
* **Obniżki**: po ilu dniach bez sprzedaży sprzedawcy obniżają i o ile; czy obniżka przyspiesza sprzedaż.
* **Stan** (`status_label`, `condition_grade`), uszkodzone (`for_parts`, `cracked`, `locked`) – różnica cen.

### C4. Rekomendacje zbierania danych (zmiany w kodzie `watch` – dopiero po zgodzie użytkownika)
* **Eksperyment „czy sprzedane znikają”**: porównaj udział `sold` wśród zniknięć sprawdzonych szybko (nowa logika,
  `state_at − last_seen` < 1 dzień) i sprawdzonych późno (`recheck`, kilka–kilkanaście dni). Jeśli wśród szybko
  sprawdzonych `sold` jest dużo więcej → sprzedane oferty znikają z Vinted po kilku dniach (strona 404) → resolver
  musi sprawdzać szybciej: `ANALYZER_GONE_AFTER_RUNS=1` (dziś 2) i/lub krótszy `ANALYZER_WATCH_HOURS`, albo
  dodatkowe tanie sprawdzanie `/services` (~1,3 KB) dla ofert, które zniknęły w ostatnim przejściu. Policz koszt
  transferu (katalog ~38 KB/stronę, `/services` ~1,3 KB + TLS) i daj użytkownikowi wybór.
* Śledzić długość nieobecności (oferta znika na 1 przejście i wraca – fałszywe zniknięcia, MacBook 10292094832).
* AI tylko dla braków ekstrakcji (pola istotne dla `config_key`), wsadowo (batch API ~50% taniej), cache po
  `content_hash` (`ai_cache`), tylko oferty `sold` + aktywne w grupach, gdzie brakuje danych; najpierw policz koszt
  (≈ liczba ofert × ~1–2 tys. tokenów) i zapytaj użytkownika.
* Laptopy `below_min` / bez opisu → nie dociągać opisów (koszt proxy), chyba że użytkownik zdecyduje inaczej.

### C5. Raport końcowy dla użytkownika
Krótki tekst po polsku: co wiemy na pewno, co w widełkach (zastrzeżenie 1), 10 najciekawszych konfiguracji
(najszybsza rotacja, największy spread, najlepsza rozbiórka), propozycja progów dla Snipera, rekomendacje z C4.
Jeśli raport ma być do udostępnienia – opublikuj jako stronę (Artifact) i podaj link.

---

## Lista kontrolna (odhaczaj `[x]`, commit + push po każdym kroku)

- [x] A1 testy zrzutu zielone (333 passed; test SDK uodporniony na `authorization: Bearer` z anthropic 2.x)
- [x] A2 atrapa rynku do testów analizy (`analyzer/tests/fake_market.py`, ~3 tys. ofert + scenariusze; pomocnicze `analyzer/analysis.py`)
- [x] A3 `suspicious.py` + `suspicious-report` (+ `suspicious-diag` zamiast `python -c` z B2 – w `cmd` cudzysłowy są kłopotliwe; `is_suspicious` tylko z `--photo-flag`)
- [x] A4 `relist.py` + `relist-report` (podobny tytuł tylko z podobnym opisem; bez opisu – identyczny tytuł)
- [ ] A5 `stats.py` + `report.py` + `report`
- [ ] A6 `export-analysis`
- [ ] B1 użytkownik sklonował repo, `status` działa z `ANALYZER_DB`
- [ ] B2 wyniki diagnostyki (`is_suspicious`, relisty) wklejone i opisane tutaj
- [ ] B3 pierwszy `report` – `summary.md` od użytkownika
- [ ] C1 kontrola jakości – wnioski dopisane tutaj
- [ ] C2/C3 ceny i strategie – wnioski dopisane tutaj
- [ ] C4 rekomendacje zbierania – decyzje użytkownika dopisane tutaj
- [ ] C5 raport końcowy

## Dziennik wyników (dopisuj tu ustalenia z danych użytkownika, z datą)

* 2026-10-24: recheck 13 841 → deleted 13 300 / sold 454 / unlisted 53 / active 23 / hidden 2 / błąd 9;
  199/200 losowych `deleted` = strona 404; 3/5 pierwszych sprzedanych = `blocked` (oszustwa iPhone).
  Uwaga użytkownika: część (prawdopodobnie większość) sprzedanych z okresu przebudowy API trafiła do `deleted`.
