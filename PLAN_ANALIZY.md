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

### Gotowe komendy (stan po A1–A6, 2026-10-24)
Kod jest na gałęzi `claude/hopeful-faraday-n33quh` (sesja Claude pisze na swoją gałąź; `main` = sam zrzut).
```bat
cd C:\Users\szymo
git clone https://github.com/PodolskiSzymon/analyse_data
cd analyse_data
git checkout claude/hopeful-faraday-n33quh
pip install -r sniper\requirements.txt
copy ..\category_analyzer\sniper\.env sniper\.env
echo.>> sniper\.env
echo ANALYZER_DB=C:\Users\szymo\category_analyzer\data\analyzer.db>> sniper\.env
python -m analyzer status
python -m analyzer suspicious-diag
python -m analyzer relist-report
python -m analyzer report
```
(aktualizacja później: `git pull`). Wszystkie cztery komendy analizy czytają bazę tylko do odczytu – `watch` może
chodzić. Wyniki: `C:\Users\szymo\category_analyzer\data\reports\<data>\` (`suspicious_diag.txt`, `relists.txt`,
`summary.md`, `configs.csv`, `report.html`), wyniki pośrednie w `...\data\analysis.db`.
Jeśli `suspicious-diag` potwierdzi hipotezę (blocked ≫ reszta przy `photo.is_suspicious`): `report --photo-flag`.

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

## D. Sniper z wytycznymi z analizy (prośba użytkownika 2026-10-25)

Cel użytkownika: Sniper ocenia nowe oferty we WSZYSTKICH kategoriach analizatora i podaje: czy okazja, stan, cenę
sprzedaży w ≤ 7 dni (sprzedaje z 7-dniową promocją międzynarodową, nie mrozi gotówki) - dla kupujących świadomych
(porównują ceny) i nieświadomych - oraz szacowany zysk. Laptopy dziś: ~1 000 zł zysku/sztukę (najlepiej: zakup 1 200 zł,
sprzedaż w 2 dni, +900 zł). Dziś Sniper: jedna kategoria (`SNIPER_CATALOG`), ręczne `sniper/guidelines.md` (laptopy
wg GPU, „max zakup = sprzedaż − 1 150 zł”).

* D1. Tabele cen per konfiguracja z `report` (C2): p10/p25/mediana ofert, PL/zagr, sprawne/uszk. (AI stan) →
  progi okazji; weryfikacja progów z `sniper/guidelines.md`. Laptopy: grupy GPU × linia CPU × RAM (nie pełny klucz).
* D2. „Cena a tempo zniknięcia”: per konfiguracja odsetek ofert znikających w ≤ 7 dni wg pozycji ceny (ćwiartki) →
  cena szybkiej sprzedaży (zniknięcie = górna granica sprzedaży; zagranica = kupujący z promocji międzynarodowej).
* D3. (wymaga C4 – szybki resolver /services w `watch`) po 2–4 tyg. ceny SPRZEDAŻY i dni do sprzedaży per model.
* D4. Komenda `sniper-guide`: wytyczne per kategoria generowane z danych (tabele + stała część strategii
  użytkownika: zysk docelowy, koszty promocji/wysyłki, horyzont 7 dni), odświeżane co tydzień.
* D5. Sniper: wiele kategorii (także mieszane przez `classify.py`), ekstrakcja konfiguracji (`extract.py`) i „karta
  rynku” danej konfiguracji w zapytaniu do AI (zamiast całego pliku), odpowiedź: okazja / stan / cena sprzedaży
  świadomi–nieświadomi / zysk / pewność. Backtest na historycznych flipach użytkownika.
* Czekam od użytkownika: koszt promocji międzynarodowej 7 dni, wysyłka, opłaty; zysk docelowy per kategoria; lista
  dotychczasowych flipów (co, za ile kupione, za ile i w ile dni sprzedane); zgoda na C4; kolejność kategorii.

### Ustalenia użytkownika (2026-10-25) – wejście do D1–D5

* **Koszty sprzedaży**: Podbicie międzynarodowe 7 dni – użytkownik płacił **26 zł** za laptopy 1 200–3 700 zł (cena
  Podbicia zależy od ceny przedmiotu, długości 3/7 dni i zasięgu; można potem obniżyć cenę, nie podnieść). Wysyłka:
  PL ~15 zł, zza granicy zwykle ~20 zł, z daleka do 50 zł. Opłatę Vinted (zwykle 5% + 2,90 zł) i weryfikację
  elektroniki (20 zł) płaci KUPUJĄCY – nie zmniejszają przychodu, ale podnoszą cenę dla kupującego (konkurencyjność).
* **Cel = marża** (zysk / cena sprzedaży) **z dolnym limitem zysku w zł** (żeby nie tracić czasu na drobne):
  ~40% idealnie, ~30% bardzo dobrze, ~20% „na dopchanie”. Dolny limit (użytkownik 2026-10-25): 300 zł przy 40%,
  500 zł przy 35% → reguła (POTWIERDZONA 2026-10-25): +40 zł minimalnego zysku na każdy punkt marży mniej: ≥ 40% →
  300, 35% → 500, 30% → 700, 25% → 900, 20% → 1 100, < 20% → nie. Zysk liczony PO kosztach (Podbicie ~26 zł + wysyłka
  ~20 zł = 46 zł): TUF i MSI spełniają; Scar (4 700 − 3 660 − 46 = 994 zł, marża 21%, wymagane ~1 056) – o włos nie
  (max zakup 3 628 zł). Do decyzji użytkownika, czy tak ma zostać.
* **Flipy (laptopy, koszt bez wysyłki i Podbicia)**: ASUS TUF Gaming F15 1 350 → 2 375 zł (+1 025, marża 43%,
  sprzedany w 2 dni); MSI RTX 4060 2 500 → 3 650 (+1 150, 32%, 5 dni); ASUS ROG Scar 17 R9 5900HX RTX 3080
  3 660 → 4 700 (+1 040, 22%, 6 dni). Horyzont sprzedaży ≤ 7 dni (Podbicie 7 dni, bez mrożenia gotówki).
* **C4 – zgoda**: szybkie sprawdzanie zniknięć → `ANALYZER_GONE_AFTER_RUNS` domyślnie 1 (było 2). Odstęp przejść
  `watch` bez zmian (10–14 h; skrócenie = więcej transferu proxy – osobna decyzja).
* **Sniper**: docelowo WSZYSTKIE kategorie analizatora dodać do Snipera w repo `unreachable_sniper` (później – na
  razie tylko zapis w planie).
* `ai-condition` (pełny, 2026-10-25, flagged 8 739 ofert): working 4 165, minor_issues 3 832, for_parts 688,
  unknown 54. Reguły (v1) uznały 8 562 za uszkodzone, AI 1 697 → zgodność 21%; przykłady przyznają rację AI
  (zaprzeczenia lt/ro/hu, „Konsola w pełni sprawna”); AI wyłapuje też iCloud „bypass” i brak ekranu, których reguły
  nie widzą.

## E. Archiwum i automat (prośba użytkownika 2026-10-25; serwer ma ~400 GB wolnego)

* E1. **Szczegóły wszystkich ofert**: już zapisywane na stałe (details + raw sidebar z URL-ami zdjęć), ale pokrycie
  ~70% (tempo 2–5 s, proxy ~10–15 KB/ofertę; zaległość ~40 tys. ≈ 600 MB proxy). Przyspieszenie:
  `ANALYZER_DETAILS_DELAY_S=1-2` – decyzja użytkownika (budżet Evomi).
* E2. **Archiwum zdjęć** w `watch`: pobieranie z CDN Vinted BEZPOŚREDNIO (bez proxy, jak ai_classify
  `SNIPER_AI_PHOTOS=download`), np. 3 pierwsze (albo wszystkie) zdjęcia nowych ofert do `data/photos/<id>/`;
  ~150 KB/zdjęcie → obecne ~70 GB (3 zdj.) / ~150 GB (wszystkie), nowe ~1–2 GB/dzień. `ai-condition` bierze zdjęcia
  z dysku, gdy oferta zniknęła (dziś 404). Do potwierdzenia: liczba zdjęć, rozmiar, limit tempa na CDN.
* E3. **Automat w `watch`** (np. raz na dobę): `ai-condition` tylko dla NOWYCH ofert flagged → flagi + relisty →
  `sniper-guide` → zapis wytycznych do folderu Snipera (`ANALYZER_SNIPER_GUIDES_DIR`); Sniper wczytuje plik po zmianie
  bez restartu. Do D5 – tylko laptopy do `SNIPER_AI_GUIDELINES`. Koszt AI: nowe flagged ~kilka zł/dzień.
* Odpowiedź na pytanie: `watch` zapisuje tylko do lokalnej `analyzer.db`; z `unreachable_sniper` nie jest połączony.

## Lista kontrolna (odhaczaj `[x]`, commit + push po każdym kroku)

- [x] A1 testy zrzutu zielone (333 passed; test SDK uodporniony na `authorization: Bearer` z anthropic 2.x)
- [x] A2 atrapa rynku do testów analizy (`analyzer/tests/fake_market.py`, ~3 tys. ofert + scenariusze; pomocnicze `analyzer/analysis.py`)
- [x] A3 `suspicious.py` + `suspicious-report` (+ `suspicious-diag` zamiast `python -c` z B2 – w `cmd` cudzysłowy są kłopotliwe; `is_suspicious` tylko z `--photo-flag`)
- [x] A4 `relist.py` + `relist-report` (podobny tytuł tylko z podobnym opisem; bez opisu – identyczny tytuł)
- [x] A5 `stats.py` + `report.py` + `report` (atrapa ×90 ≈ 190 tys. ofert: 20 s, 195 MB RAM)
- [x] A6 `export-analysis`
- [x] B1 użytkownik sklonował repo, `status` działa z `ANALYZER_DB`
- [x] B2 wyniki diagnostyki (`is_suspicious`, relisty) wklejone i opisane tutaj (dziennik 2026-10-24, wieczór)
- [ ] B3 pierwszy `report` – `summary.md` od użytkownika
- [ ] C1 kontrola jakości – wnioski dopisane tutaj
- [ ] C2/C3 ceny i strategie – wnioski dopisane tutaj
- [ ] C4 rekomendacje zbierania – decyzje użytkownika dopisane tutaj
- [ ] C5 raport końcowy
- [x] D1 tabele cen + progi okazji (w `sniper-guide`; weryfikacja guidelines.md – po danych użytkownika)
- [ ] D2 cena a tempo zniknięcia (7 dni)
- [ ] D3 ceny sprzedaży per model (po C4, 2–4 tyg.)
- [x] D4 `sniper-guide` (wytyczne per kategoria z danych, wersja 1: ceny ofert/zniknięć; v2 po D3)
- [x] D5 Sniper: wiele kategorii, karta rynku, zysk w odpowiedzi AI (repo `unreachable_sniper`, gałąź `claude/hopeful-faraday-n33quh`; backtest – gdy będzie historia ocen z nowych wytycznych)
- [x] E1 szczegóły wszystkich ofert: `ANALYZER_DETAILS_DELAY_S` domyślnie 1–2 s (było 2–5; użytkownik ma 17 GB w Evomi)
- [x] E2 archiwum WSZYSTKICH zdjęć bez proxy (`photos.py`, w `watch` równolegle ze szczegółami; `ai-condition` bierze zdjęcia z dysku)
- [x] E3 automat co 3,5 dnia (`auto.py`): flagi, relisty, AI stanu nowych ofert (≤ 3 000), raport, wytyczne → `ANALYZER_SNIPER_GUIDES_DIR` / `ANALYZER_SNIPER_GUIDELINES_FILE`; + alarm ntfy „brak sprzedaży” (0 sold wśród ≥ 300 zniknięć w 72 h)

## Dziennik wyników (dopisuj tu ustalenia z danych użytkownika, z datą)

* 2026-10-24: recheck 13 841 → deleted 13 300 / sold 454 / unlisted 53 / active 23 / hidden 2 / błąd 9;
  199/200 losowych `deleted` = strona 404; 3/5 pierwszych sprzedanych = `blocked` (oszustwa iPhone).
  Uwaga użytkownika: część (prawdopodobnie większość) sprzedanych z okresu przebudowy API trafiła do `deleted`.
* 2026-10-24: A1–A6 gotowe (363 testy). Na atrapie ×90 (~190 tys. ofert) `report` 20 s / 195 MB RAM, eksport
  z opisami ~14 MB. Czekam na B1–B3 (wyniki `status`, `suspicious-diag`, `relist-report`, `summary.md`).
* 2026-10-24 (wieczór), B1/B2 od użytkownika:
  * `status`: aktywne laptop 17 606, phone 70 791, tablet 10 366, console 38 095, gpu 4 148, ram 5 914,
    storage 2 856; **sold razem tylko 307** (console 72, phone 157, laptop 36, tablet 18, ram 13, storage 9, gpu 2),
    **blocked 148**, deleted 13 328, unlisted 9 011, hidden 1 769, unclassified 11 016. Z recheck było 454 sold →
    ~148 przeszło w `blocked` (html-details: strona 404) → **1/3 „sprzedanych” to blocked** – do sprawdzenia, czy to
    oszustwa, czy Vinted usuwa stronę sprzedanej oferty (nowa tabelka „cena / mediana” w `suspicious-report` i
    `summary.md`). Telefony: partycja 1850–1914,94 zł brakuje 210 ofert (oversize 14) – sprawa zbierania (C4).
  * `suspicious-diag`: w pozycji katalogu **nie ma pola `photo.is_suspicious`** (są tylko photo.is_main,
    is_favourite, promoted, show_1st_time_seller_discount). Promowane: sold 3,9% / deleted 2,0% / active 0,7%
    (mała próbka sold 307). → diag rozszerzony o zapisane szczegóły (`sidebar`, `photos[].*`); flaga
    `--photo-flag` sprawdza oba źródła.
  * `relist-report` (stara reguła): 2 480 par, 15,2% deleted to relisty; przykłady z samego tytułu były
    ogólnikowe („Laptop”, „HP laptop”, przerwa +12 d) → **reguła tytułowa zaostrzona** (tytuł ≥ 4 słowa / ≥ 20 znaków,
    cena ±5%, przerwa ≤ 2 dni; opis do porównania ≥ 40 znaków). Mediana przerwy 0,5 d = jedno przejście `watch`.
* 2026-10-25, C1 (wstępnie, z `suspicious-diag`, `suspicious-report`, pierwszego `report` i `configs.csv`):
  * Skala: ~174 tys. ofert w stanach rynkowych, aktywnych ~150 tys.; pewne sprzedaże 307 + blocked 148 = **455
    (0,3%)**, deleted 13 328; grup konfiguracji 21 307, z ≥ 1 sprzedaną 198, z ≥ 3 – tylko 11. ⇒ ceny sprzedaży
    per konfiguracja tylko dla iPhone'ów i kilku konsol; reszta – ceny ofertowe + widełki.
  * **Zagranica 62–69% ofert w każdej kategorii** → rynek PL to ~1/3 (liczyć osobno – jest).
  * Klucz konfiguracji (po wykluczeniach): laptop 66%, phone 90%, tablet 72%, console 63%, gpu 77%, ram 91%,
    storage 87%. Błędy kluczy laptopów: „? / intel atom / ? / 1 / 128” (RAM 1 GB), „macbook air 2025 / m4 / 128 /
    512” (RAM = pojemność dysku) – do poprawy ekstrakcji (później).
  * `is_suspicious`: jest tylko w szczegółach (`sidebar`: photos[], plugins), **zawsze false** (sold 0/302, deleted
    0/1517, active 0/1353); blocked nie mają zapisanego sidebara → hipoteza nie do potwierdzenia, flaga bez użytku.
  * **blocked ≈ sold**: cena / mediana konfiguracji – mediana 0,94 vs 0,91, < 40%: 9% vs 7%, ≥ 90%: 56% vs 54%
    → blocked to w większości zwykłe sprzedane, których stronę Vinted usunął (liczone od teraz jako sold; flaga
    `blocked` tylko informacyjna). Pośrednio potwierdza zastrzeżenie 1: Vinted usuwa strony sprzedanych ofert.
  * Pierwsza tabela zwłoki bezużyteczna (recheck ustawił state_at = 10-24 wszystkim: 284 sold / 11 991 deleted,
    mediana zwłoki 7,4 d) → przebudowana na przedziały zwłoki (services_at − last_seen).
  * Ekstrakcja: „na części” łapała zaprzeczenia („bez defektów”, „no defects”, „nie jest uszkodzony”) → uszkodzone
    laptopy wychodziły tylko 17% taniej od sprawnych → **extract v2** (zaprzeczenia w tym samym fragmencie zdania).
  * Flagi: `shop_like` 25 268 i część `dup_title_price` (386) to ogólnikowe tytuły („Laptop” 700 zł ×8, „Nintendo
    2DS”) → liczone tylko dla tytułów konkretnych (≥ 4 słowa / ≥ 20 znaków). `too_cheap` (744) wycina też źle
    sklasyfikowane akcesoria (kierownica Thrustmaster w konsolach) i „na części” po estońsku („varuosadeks”) – OK.
  * Relisty (zaostrzona reguła): 1 513 par (opis 1 182, tytuł 331) ≈ 11% deleted – nie tłumaczą masy usuniętych.
  * Pierwsze ceny (PL, sprawne): iPhone 13 128 GB oferty 850 zł (p25 799 – p75 1 000), sprzedane 720 zł (n=5),
    usuniętych 145; iPhone 15 Pro 128 2 200 / 1 950 (n=3); iPhone 16 Pro Max 256 3 500 / 3 050 (n=4); PS4 550 / 464
    (n=4); Switch 800 / 649 (n=3) → sprzedane ~10–15% poniżej mediany ofert. ST górna: iPhone'y 16–36%, konsole 6–16%.
  * Telefony: partycja 1 850–1 914,94 zł – brakuje 210 ofert (oversize 14) – sprawa zbierania (C4).
  * Decyzja potrzebna (B1/C4): `watch` przenieść do `analyse_data` (extract v2 w cyklu `watch`; stary folder
    przeliczałby nowe oferty regułami v1).
* 2026-10-25, decyzja użytkownika (C4 – AI): stan techniczny („na części” / „bez defektów”, zaprzeczenia dalej niż
  słowo od usterki) rozstrzyga AI z opisu i zdjęć → `python -m analyzer ai-condition` (moduł `ai_condition.py`):
  zakres `flagged` (reguły: usterka albo jakakolwiek wzmianka o usterce) / `sold` / `all`, wszystkie zdjęcia oferty (`--photos N` ogranicza),
  szacunek kosztu i pytanie o zgodę przed wywołaniami, wyniki i cache w `analysis.db: ai_condition`, `report` używa
  stanu z AI zamiast reguł (uszkodzona = na części / zbity ekran / blokada). Raport zgodności AI vs reguły.
  Kolejność: `--estimate` → `--limit 50` (próba, sprawdzić przykłady w `ai_condition.txt`) → całość.
* 2026-10-25, `ai-condition --limit 50` (gemini-3.8-flash, wszystkie zdjęcia): 46 ocenionych, 4 × 404 (zdjęcia
  usuniętych ofert), śr. 7 840 / 97 tokenów na ofertę (≈ 1 090 tokenów / zdjęcie, 6,6 zdjęcia), $0,29. AI vs reguły
  (v1): zgodność 30% – 32 × reguły „uszkodzona”, AI sprawna/drobna usterka; przykłady przyznają rację AI (zaprzeczenia
  po litewsku „be jokių defektų”, rumuńsku „fără defecte”, „camera was broken but i fixed it”). Flagged = 8 739 ofert
  / 58 466 zdjęć → całość ~$55 ze wszystkimi zdjęciami, ~$29 z 3, ~$10 sam tekst. Zmiany: domyślnie 3 zdjęcia,
  404 zdjęcia → ponowienie samym tekstem (bez /services – zero ruchu przez proxy), klucz pamięci bez zdjęć.
* 2026-10-25: limity Tier 1 użytkownika (gemini-3.8-flash): 1 000 RPM, 2 mln TPM, 10 tys. RPD; pierwszy pełny
  `ai-condition` szedł 4 naraz (~55/min). → domyślnie 48 naraz + ogranicznik 900 RPM / 1,8 mln TPM (~450 ofert/min
  przy 3 zdjęciach), ponawianie 429/503/timeout (5–60 s). Uwaga: 10 tys. zapytań/dzień - większy przebieg w 2 dniach.
* 2026-10-25, `report` z AI (8 685 ofert stan z AI): zwłoka sprawdzenia zniknięcia 2–4 / 4–7 / 7–10 / ≥ 10 dni →
  % sold 3,2 / 3,1 / 3,7 / 3,8 – płasko; brak danych < 2 dni (recheck). ⇒ albo sprzedane znikają szybciej niż w 2 dni,
  albo większość deleted to usunięcia – rozstrzygnie `watch` z C4 (sprawdzenie po 1 przejściu). Poszlaka: cena
  usuniętych / mediana aktywnych tej samej konfiguracji ≈ cenie sprzedanych (telefony 0,91 vs 0,90, konsole 0,93 vs
  1,00). Uszkodzone (AI) vs sprawne, PL: telefony 64%, laptopy 73%, konsole 88%. `watch` u użytkownika stoi od kilku
  dni – zalecone uruchomienie z `analyse_data` (C4 już w kodzie), ceny sprzedaży 7 dni (D3) po 2–4 tyg.

* 2026-10-25, `sniper-guide` u użytkownika (laptop, phone, tablet, gpu, storage przejrzane): laptopy wg GPU zgodne z
  flipami (RTX 4060 max zakup ~2 450–2 500), iPhone 13+ sensowne progi (okazji 0–4% ofert), GPU/SSD/RAM przy min.
  300 zł prawie zawsze nieopłacalne. Poprawki: cena sprzedaży = wyższa z (mediana zniknięć, środek p25–med) – mediana
  zniknięć zaniżała (RTX 4060 3 358 vs sprzedaż użytkownika 3 650); wiersze nieopłacalne → jedna linia; nazwy GPU.
* 2026-10-25, decyzje użytkownika: wszystkie zdjęcia do archiwum, szybsze szczegóły (17 GB Evomi), automat 2× w
  tygodniu, najpierw E2+E3 (D5 – Sniper – potem). Alarm: brak sprzedaży przez dłuższy czas = zmiana API → ntfy, użytkownik
  zatrzymuje watch. Odpowiedzi: watch sprawdza zniknięcia przez /services + sidebar (resolver.resolve_item); opis
  KAŻDEJ oferty z 7 kategorii (active/reserved/unlisted, bez below_min) pobiera details/sidebar – katalog daje tylko
  tytuł, cenę, markę, stan z formularza i zdjęcie główne.
* 2026-10-25: Sniper (`unreachable_sniper`) był na komputerze użytkownika, analizator na serwerze → Sniper też na
  serwer (instrukcja `PILOT.md`) + **pilot z telefonu** przez ntfy (`python -m analyzer remote` / `remote.bat`,
  moduł `remote.py`): start / stop / restart / status / log dla watch i Snipera, strażnik podnosi program po awarii,
  plik .pid chroni przed dwoma `watch` naraz. Dopiero potem D5 (ulepszanie Snipera).
* 2026-10-25, D5 (Sniper na wszystkie kategorie, `unreachable_sniper` gałąź `claude/hopeful-faraday-n33quh`):
  `SNIPER_CATALOGS=auto` → katalogi i zakresy cen z `guides/catalogs.json` (analizator: od = 60% najniższego „max
  zakup” wśród opłacalnych grup, do = najwyższy × 1,15; katalog bez opłacalnych grup pomijany), skanowane po kolei
  (laptopy waga 3); mieszane katalogi – karta / RAM / dysk z tytułu, reszta bez szczegółów; wytyczne per kategoria
  (`guides/<kategoria>.md`), „karta rynku” (wiersze tabeli dopasowane po tytule) w zapytaniu, bramka ceny ×1,25 przed
  AI; odpowiedź AI z marżą, dniami do sprzedaży i `meets_profit_rule`; filtry słów per kategoria. Pilot „wytyczne”
  wysyła wszystkie kategorie w jednym pliku. Wzór `.env`: `ENV_SERWER.example`, instrukcja: `PILOT.md` 1a.
* 2026-10-25: `sniper-guide` u użytkownika – 7 kategorii skopiowanych do Snipera, `catalogs.json`: 3580:250-8400*3,
  3661:100-6500, 3728:100-4000, 3025:100-4900, 3582/3584:100-2900, 3583:100-1600. Ręczne `guidelines.md` (laptopy)
  łamało regułę zysku (RTX 4060 próg 2 700 przy sprzedaży 3 150 = marża 13%; 4070, 3070, 3080, 5060, 4050; premia za
  Polskę +50…+500 zł) → progi przeliczone regułą, premia zamieniona na wyższą ocenę; Sniper łączy laptop.md (dane) +
  guidelines.md (uzupełnienie). Grupy z dużym % ofert ≤ max (PS5 13%, DDR5 16 GB 24%, NVMe 4 TB 12%) = zawyżona cena
  sprzedaży niejednorodnej grupy – do poprawy w D2/D3. Pilot: polecenie `oceny` (oceny.html na telefon + Dysk).
* 2026-10-25, `sniper-guide` z regułą 30% / 150 zł: opłacalnych grup telefony 638/642, konsole 99/100, GPU 25/50, RAM
  18/48, SSD 9/22; `catalogs.json` od 50 zł. Grupy z > 10% ofert ≤ max zakup (laptopy „i5 · 16 GB” 14%, „i7 · 16 GB” 12%,
  DDR5 16 GB 29%, DDR4 DIMM 32 GB 16%, SATA 4 TB 15%) = mieszane → laptopy ze zintegrowaną grafiką dzielone wg
  generacji CPU (bez generacji pomijane), znak ⚠ w tabeli + zasada dla AI; nazwy konsol „Xbox One ones” → „Xbox One S”.
* 2026-10-26, decyzja użytkownika: zysk < 300 zł to za mało → reguła: zysk zawsze ≥ 300 zł, 40% → 300, 35% → 400,
  30% → 500, 25% → 600, 20% → 700 (+20 zł/pkt), < 20% nie; wyjątek 30% / 150 zł usunięty. Okazje od sprzedawców
  z Polski +1 do oceny w Sniperze (krótsza dostawa = szybszy obrót gotówką). Koszt zakupu w Sniperze z opłatą Vinted
  dla kupującego (5% + 2,90 zł).
* 2026-10-26 (koniec rozmowy): pełny stan projektu, reguły i lista niedoskonałości → **`STAN_PROJEKTU.md`**
  („wykonaj md” w nowej rozmowie). Reguła: zysk ≥ 300 zł, marża ≥ 30% (35% → 400, 30% → 500), Polska +1,
  program egzekwuje regułę po AI, podobne oferty z bazy (`comparables.db`), pilot, sprzęt testowy kupiony.
* 2026-10-27 (C4, `sold-report` na pełnej bazie): udział sold+blocked wśród zniknięć wg zwłoki rozpoznania –
  ≤ 12 h 3,2%, 12–24 h 16,9%, 1–3 dni 8,4%, > 3 dni 3,1% ⇒ sprzedane znikają (404) po kilku dniach; ≤ 24 h tylko 5%
  zniknięć (przerwy w `watch` 16–21 h). Szczegóły i wniosek: `PLAN_OCENY.md` §15.
* 2026-10-27 (C4 – decyzja użytkownika „sprawdzaj częściej”): resolver nie blokuje już cyklu (świeże zniknięcia od
  razu, ponowne sprawdzenia w tle do końca cyklu), odstęp resolvera 1–2,5 s, `ANALYZER_WATCH_HOURS` 5–7 h.
  `ANALYZER_GONE_AFTER_RUNS=1` było już od 25.10. Szczegóły: `PLAN_OCENY.md` §15.
