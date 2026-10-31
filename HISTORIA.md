# HISTORIA – archiwum decyzji i wyników (NIE czytać w całości)

> Archiwum przeniesione 2026-10-30 przy porządkowaniu dokumentacji. Aktualny stan i kolejne kroki są w
> `STAN_PROJEKTU.md` – tu sięgaj tylko po szczegóły (szukaj `grep -n` po dacie albo temacie, np. „2026-10-27”,
> „eksperyment”, „sold-report”, „Wii”). Treść skopiowana bez zmian.
>
> * Część A – dawny `STAN_PROJEKTU.md` (stan 26–29.10: infrastruktura, reguły w wersjach, przepływ Snipera,
>   co wyszło w praktyce 26.10, eksperyment 6a, dawna lista niedoskonałości).
> * Część B – dawny dziennik `PLAN_OCENY.md` §15 (wyniki z danych użytkownika 26–29.10 z liczbami: eksperyment
>   mediany/model, `sold-report`, przebudowa `watch`, koszty AI, basal, dni testowe, fałszywe 404 / szafa).
> * Starsze: dziennik `PLAN_ANALIZY.md` (do 25.10), `KONTEKST_CATEGORY_ANALYZER.md` (API Vinted, decyzje do 24.10),
>   `unreachable_sniper/sniper/HISTORIA_SNIPERA.md` (sesja konta, auto-zakup, API Vinted od strony Snipera).

---

# Część A – dawny STAN_PROJEKTU.md (2026-10-26 … 29.10)

## STAN PROJEKTU – przekazanie do nowej rozmowy (2026-10-26, aktualizacja 2026-10-27)

> **Dla Claude w nowej rozmowie („wykonaj md”):** przeczytaj CAŁY ten plik, potem `CLAUDE.md` (zasady),
> a przy pracy nad kodem – pliki wskazane w sekcjach. Repo `unreachable_sniper` NIE jest w tej sesji domyślnie:
> dodaj je narzędziem `add_repo` (owner `PodolskiSzymon`, repo `unreachable_sniper`, dostęp `push`), sklonuj i
> przełącz na gałąź `claude/hopeful-faraday-n33quh`. **Potem przeczytaj CAŁY `PLAN_OCENY.md` – to główny plan
> dalszej pracy** (ocena ofert: „AI rozpoznaje, dane wyceniają, program decyduje”; fazy F0–F5, dane i pytania do
> użytkownika). Sekcja 8 niżej = pozostałe niedoskonałości i kontekst (część z nich plan już obejmuje).
>
> **PIERWSZY KROK w nowej rozmowie (stan 2026-10-27 noc):** eksperyment 6a powtórzony z `comparables.db` –
> jakość lepsza w `mediany` (`PLAN_OCENY.md` §15); odpowiedzi §11 są w §15. Teraz porównanie jakość/koszt:
> `python -m sniper.bench` (`unreachable_sniper/sniper/bench.py`, złoty zbiór `bench_golden.json`). Watch przebudowany
> (resolver nie blokuje cyklu, przejścia co 5–7 h). **Czekamy od użytkownika na (sprawdź, co już przyszło):**
> 1. wynik `python -m sniper.bench` (tabela + `logs\bench_<czas>.txt`) → decyzja: `SNIPER_EVAL_MODE`, zdjęcia,
>    rozdzielczość, model; potem uzupełnianie złotego zbioru prawdziwymi przypadkami,
> 2. (zamknięte 28.10: iPad anulowany; `flips.csv` pusty – Sniper jeszcze nic nie kupił, użytkownik nie chce
>    o to dopytywania; `watch` 24–26.10 wyłączał sam; proxy: część ruchu analizatora idzie przez IPRoyal (stare .env),
>    razem Evomi + IPRoyal ~25 GB – wystarczy na ~1,5 mies. przy ~0,5 GB/dobę),
> 3. nowy `watch` (28.10, log): 1. cykl „zniknięć 761, pewnych sprzedaży 35 (4,6%), sprawdzone ≤ 24 h 99,5%, mediana
>    zwłoki 11,3 h” – szybkie sprawdzanie działa; udział sprzedaży dalej niski ⇒ większość zniknięć to naprawdę
>    usunięcia (relisty/podbicia). Uwaga: z 2 620 „zniknięć” 1 508 to `unlisted` (oferta żyje, przejście jej nie
>    zobaczyło) – przy `ANALYZER_GONE_AFTER_RUNS=1` ~58% sprawdzeń resolvera jest zbędnych (do zbadania: dziury
>    w pokryciu przejścia przy `newest_first`),
> 4. — , 5. — ,
> 6. dzienny koszt AI po zmianach (`log sniper` → „dziś ~$…”),
> 7. po 2–3 dniach nowego `watch`: `python -m analyzer sold-report --od <data restartu>` (cel: ≥ 90% zniknięć ≤ 24 h).
> Potem decyzja o trybie oceny i F1 (taksonomia). F0 zrobione na pełnej bazie (`sold-report`, `flips`).

---

### 0. Dostęp nowego czatu do danych użytkownika (2026-10-27)

Użytkownik może dać bazę na jeden z dwóch sposobów – zapytaj, który wybrał:

* **A. Claude Code na serwerze (Remote Control)** – sesja działa na serwerze użytkownika, w folderze
  `C:\Users\szymo\analyse_data`: masz prawdziwą bazę (`ANALYZER_DB`), logi Snipera i możesz sam uruchamiać
  komendy (`python -m analyzer …`, `sqlite3`, eksperyment). Zasady: baza tylko do odczytu (`analysis.open_ro`) –
  `watch` może pisać równolegle; serwer ma 4 GB RAM (SQL z agregacją, nie ładować wszystkiego do pamięci); **żadnych
  zapytań do Vinted** i nic przez proxy bez zgody; nie zatrzymuj `watch`/Snipera i nie zmieniaj `.env` bez pytania;
  nie wypisuj sekretów z `.env`; płatne wywołania AI (eksperyment, `ai-condition`) – najpierw podaj koszt.
* **B. Lekka kopia bazy przez Dysk Google** – użytkownik robi `python -m analyzer slim-db` (kopia bez tabeli `raw`
  + tabele `analysis.db` z przedrostkiem `a_`, ZIP w `<folder bazy>\export\<data>\analyzer_slim.zip`), wrzuca ZIP na
  Dysk, udostępnia „Każdy z linkiem” i podaje link. W środowisku chmurowym muszą być dozwolone domeny
  `drive.google.com` i `drive.usercontent.google.com` (ustawienia środowiska → Network access → Allowed domains;
  bez tego curl dostaje 403 od proxy – wtedy poproś użytkownika o zmianę i NIE zgaduj wyników). Pobranie (ID z linku
  `…/file/d/<ID>/view`), do katalogu roboczego/scratchpadu, nigdy do repo:
  `curl -L -o slim.zip "https://drive.usercontent.google.com/download?id=<ID>&export=download&confirm=t"` → `unzip`
  → `sqlite3`/Python `file:analyzer_slim.db?mode=ro`. To migawka – świeże dane = nowy `slim-db`. Po pracy przypomnij
  użytkownikowi, żeby wyłączył udostępnianie linku.
  Wariant pełny: użytkownik może zamiast slim wrzucić całą bazę (`analyzer_full.db` z `VACUUM INTO`, ~1,3 GB, z tabelą
  `raw` – surowe odpowiedzi API, skompresowane `rawstore`) + `analysis.db` – pobieranie tak samo (curl z `confirm=t`).
* W obu przypadkach: schemat bazy – `analyzer/db.py` (migracje v1–v11) i `PLAN_ANALIZY.md` (zastrzeżenia do danych:
  `deleted` ≠ sprzedaż, sprzedaże przed 24.10 niepełne, cena = ostatnia cena wystawienia, dryf kursów).

### 1. O co chodzi (cel biznesowy)

Użytkownik (Szymon, rozmawiamy **po polsku**) **flipuje elektronikę na Vinted**: kupuje okazje, sprzedaje w ≤ 7 dni.
Ma **ograniczony kapitał i mało czasu** – chce kupować tylko najlepsze okazje i szybko obracać gotówką.
Dwa programy na jego serwerze:

* **Analizator** (`PodolskiSzymon/analyse_data`, folder `analyzer/`) – zbiera cały rynek 7 kategorii Vinted do SQLite,
  liczy ceny, wykrywa oszustwa/relisty, ocenia stan przez AI, generuje **wytyczne cenowe** dla Snipera.
* **Sniper** (`PodolskiSzymon/unreachable_sniper`, folder `sniper/`) – co kilka sekund skanuje nowe oferty, ocenia
  je AI (Gemini) według wytycznych, wysyła **ntfy (push) + mail** o okazjach. Auto-zakup istnieje, ale jest
  **wyłączony** (Vinted wylogowuje bota – patrz `unreachable_sniper/CLAUDE.md`).
* **Pilot** (`analyzer/remote.py`, `remote.bat`) – sterowanie z telefonu przez ntfy.

### 2. Infrastruktura u użytkownika

* Serwer: **Windows, stary laptop i5-5200U, 4 GB RAM, Python 3.12**, ~400 GB wolnego dysku. Konsola `cmd`.
  ⇒ komendy lekkie (strumieniowo, SQL z agregacją), z postępem w terminalu, krótki wynik do wklejenia.
* Ścieżki: `C:\Users\szymo\analyse_data`, `C:\Users\szymo\unreachable_sniper` (venv `.venv`),
  baza `C:\Users\szymo\category_analyzer\data\analyzer.db` (~1,3 GB, `ANALYZER_DB`), raporty
  `…\category_analyzer\data\reports\<data>\`, logi pilota `…\data\remote\{watch,sniper}.log`,
  logi Snipera `unreachable_sniper\sniper\logs\` (`evaluations.jsonl/.csv`, `oceny.html`, `mails.csv`, `sniper.log`).
* **Gałęzie:** od 2026-10-27 w OBU repo `claude/magical-bell-vdwpt1` (zawiera całą `claude/hopeful-faraday-n33quh`
  + zmiany z 27.10). Na serwerze (lokalnie dalej gałąź hopeful-faraday) aktualizacja: `git pull origin
  claude/magical-bell-vdwpt1` w obu repo. Wcześniej: `claude/hopeful-faraday-n33quh` (`main` w obu jest stary).
  Na serwerze oba repo są już na tej gałęzi (2026-10-26). Aktualizacja u użytkownika: `git pull` w obu.
* **Dwa pliki `.env`** (tej samej treści – wzór `ENV_SERWER.example`, bez sekretów):
  `unreachable_sniper\sniper\.env` (czyta Sniper) i `analyse_data\sniper\.env` (analizator + pilot).
  Naprawione 2026-10-26: pilot przekazywał Sniperowi swoje zmienne i przesłaniały one plik Snipera
  (`remote.own_env_keys` / `drop_env`). **Ustawienia Snipera zmienia się w pliku Snipera + `restart sniper`;**
  zmiana w pliku pilota wymaga ponownego uruchomienia `remote.bat`.
* Windows: okno konsoli z „Wybierz …” w tytule = tryb QuickEdit wstrzymał program (Esc; wyłączyć QuickEdit).
* AI: Gemini (klucz w `.env`), domyślnie `gemini-3.8-flash`; użytkownik testował `gemini-3.1-flash-lite`
  (~3× taniej, w próbce 17 ofert dobre decyzje, drobne halucynacje). OpenRouter dodany, **nieprzetestowany na żywo**.
  Dzienny limit `SNIPER_AI_DAILY_LIMIT_USD` (użytkownik ma 20).
* Proxy Evomi (17 GB) – tylko skan Vinted. Zdjęcia/AI/ntfy bez proxy.
* Sprzęt do testów kupiony (2026-10-26, ~970 zł): MSI Z270 Tomahawk + i5-7400 + chłodzenie Intel BOX, Patriot Viper
  2×4 GB DDR4 3000, zasilacz MSI MAG A850GN PCIE5, SSD Kingston 128 GB, przejściówka SO-DIMM→DIMM DDR4.
  ⇒ `SNIPER_TEST_HAVE=gpu,ddr4,sodimm_ddr4,nvme,sata`. Brak: DDR5 (płyta), DDR5 SO-DIMM. Opis: `SPRZET_DO_TESTOW.md`.

### Komendy u użytkownika (ściąga)
```bat
cd C:\Users\szymo\analyse_data
python -m analyzer status | report | sniper-guide | szukaj <kategoria> [słowa] [--max N] | auto --force
python -m pytest analyzer/tests -q          (u Claude: python -m pytest analyzer/tests -q)
cd C:\Users\szymo\unreachable_sniper
.venv\Scripts\python -m sniper.evaluator --last 20 [--compare]   (ocena historii innym modelem, porównanie)
```
Pilot (temat `pilot-…` w aplikacji ntfy; opcjonalnie PIN na początku): `status`, `start|stop|restart watch|sniper|all`,
`log watch|sniper`, `wytyczne`, `oceny`, `pomoc` (też „włącz/wyłącz/zatrzymaj”). Okazje idą na **osobny** temat
`SNIPER_NTFY_TOPIC`. Użytkownik wyłącza Snipera na noc (`stop sniper`).

### 3. Reguły biznesowe (aktualne – decyzje użytkownika)

* **Koszt zakupu** = cena + wysyłka + **opłata Vinted kupującego 5% + 2,90 zł** (`SNIPER_BUYER_FEE_*`).
* **Koszty sprzedaży** 46 zł (Podbicie międzynarodowe 7 dni ~26 zł + wysyłka ~20 zł).
* **Reguła zysku (2026-10-28, ostatnia wersja):** zysk ≥ 300 zł zawsze; marża ≥ ~28% przy tanich (sprzedaż
  ≤ 1 000 zł) malejąco liniowo do ~25% przy drogich (≥ 2 500 zł); spełniona = okazja z oceną co najmniej 8 (program
  podnosi). Wzory: `analyzer/guide.py: min_margin / max_buy`, `sniper/evaluator.py: rule_min_margin / rule_max_buy`,
  `SNIPER_RULE_*`. Katalogi Snipera (auto) zawsze od 300 zł. Poniżej wersja z 26.10 (historia):
* **Reguła zysku (2026-10-26):** zysk = sprzedaż − koszt zakupu − 46 zł; marża = zysk / sprzedaż.
  **Zysk ≥ 300 zł zawsze; 40%+ → 300 zł, 35% → 400, 30% → 500 (+20 zł/pkt); marża < 30% → nigdy** (także drogi sprzęt).
  Wzór max zakupu: `analyzer/guide.py: max_buy` (to samo w `sniper/evaluator.py: rule_max_buy`). Historia: 25.10
  40%→300 … 20%→1100 (+40/pkt) + wyjątek 30%/150 zł; 26.10 rano 30%→500, 20%→700; 26.10 po S25 (19%) – minimum 30%.
* **Skala ocen** (prompt `SYSTEM_PROMPT` w `sniper/evaluator.py`, orientacyjna, AI ocenia BEZ kraju):
  7 = reguła na styk ~30%; 8 = ~35% + szybka sprzedaż (≤ ~5 dni) albo ~40% wolniej; 9 = ~40% szybko albo ~45%+
  i zysk ~500+; 10 = ~45–50%+ i zysk ~800+. Minus 1–2 za niepewną cenę, długą sprzedaż, stan, braki, pracę.
* **Polska +1** do oceny okazji (program, `SNIPER_AI_PL_BONUS`) – szybsza dostawa = szybszy obrót. Tylko dla is_deal.
* **Nie kupujemy uszkodzonych** (na części, blokady, zbity ekran, nie działa, artefakty) – nigdy okazja.
* Brak ładowarki (laptop/konsola przenośna/tablet) → AI odejmuje koszt zamiennika.
* Cena „sprzedaży” z bazy = ostatnia cena wystawienia (jest „Zaproponuj cenę”) ⇒ **górna granica**.
* Powiadomienia: użytkownik ustawił `SNIPER_NTFY_MIN_SCORE` / `SNIPER_AI_MIN_SCORE` na 8 lub 9.
* Zasada zakupów (doradzona po utracie S22 w 3 min): przy 8+/10 kupować od razu, pytać po zakupie (ochrona kupującego
  Vinted: 2 dni od dostarczenia na zgłoszenie niezgodności). Negocjować tylko 5–7 lub stare oferty.

### 4. Analizator (`analyse_data/analyzer/`) – co jest

Stary rdzeń zbierania (crawl/watch/resolver/details/extract) opisany w `KONTEKST_CATEGORY_ANALYZER.md` i
`PLAN_ANALIZY.md` (części A–E odhaczone). Dodane w tych rozmowach:
* `analysis.py` (wspólne: open_ro, analysis.db z flagami/relistami/ai_condition/meta), `suspicious.py`, `relist.py`,
  `stats.py`, `report.py`, `export.py`, `ai_condition.py` (stan techniczny przez AI: opis + 3 zdjęcia, async,
  limiter RPM/TPM), `extract.py` (VERSION 2, negacje), `photos.py` (archiwum wszystkich zdjęć bez proxy),
  `auto.py` (automat co 3,5 dnia w `watch`: flagi, relisty, AI stanu nowych, raport, wytyczne → kopia do Snipera;
  alarm ntfy „brak sprzedaży” = zmiana API), `remote.py` (pilot), `notify.py`.
* **`guide.py` – wytyczne dla Snipera** (`sniper-guide`): grupy per kategoria (laptopy wg karty graficznej, MacBooki,
  zintegrowane wg **linii CPU + generacji** (bez generacji pomijane); telefony/tablety model+pamięć; konsole
  platforma+wariant (liczba-wariant i duplikaty usuwane); GPU układ+VRAM; RAM typ/forma/pojemność; dyski typ/pojemność).
  Cena sprzedaży S = wyższa z (mediana zniknięć ≥ 10 szt., środek p25–mediana aktywnych). Kolumna „% ofert ≤ max”;
  **⚠ gdy > 10%** (grupa mieszana, cena niepewna). TOP_ROWS 80. Pisze `guides/<kategoria>.md`, **`catalogs.json`**
  (zakresy cen katalogów: od 60% min max-zakupu, do max × 1,15; laptop waga 3) i **`comparables.db`**.
* **`comparables.py`** (2026-10-26): `comparables.db` = SQLite FTS5 (słowa tytułu jak w Sniperze, kategoria, cena,
  zniknięta) + fts5vocab; bez flag/relistów/uszkodzonych; kopiowany do Snipera. **Nieprzetestowany na prawdziwej bazie**.
* **Zniknięcia od 2026-10-29:** `deleted` dopiero po drugim 404/104 z /services w kolejnym cyklu
  (`ANALYZER_CONFIRM_404`, licznik „fałszywe 404”); `listings.seller_id` (v12) + `szafa-test` (szafa sprzedawcy –
  `analyzer/wardrobe.py`, endpoint z przeglądarki użytkownika, opis w `KONTEKST_CATEGORY_ANALYZER.md`).
* **`watch` od 2026-10-27** (prośba użytkownika „podejrzanie mało sprzedaży”): dane pokazały, że resolver brał
  odstęp stron katalogu 2–6 s (~700 ofert/h) i w jednym wywołaniu robił też ~12 tys. ponownych sprawdzeń
  niewidocznych/ukrytych co 3 dni → resolve ~17 h, następne przejście czekało (przerwy 16–21 h, mediana zwłoki
  rozpoznania 88 h, 5% zniknięć ≤ 24 h), a szczegóły prawie nie szły (24–25.10: 71 i 238 dziennie, zaległość 56 tys.).
  Teraz: przejście → `resolve(only="fresh")` (świeże zniknięcia) → log „Cykl: zniknięć N, pewnych sprzedaży X (%),
  ≤ 24 h %, mediana zwłoki” → automat → do następnego startu RÓWNOLEGLE ponowne sprawdzenia (`only="due"`, do
  `deadline`), szczegóły, zdjęcia. `ANALYZER_RESOLVE_DELAY_S` 1–2,5 s, `ANALYZER_WATCH_HOURS` 5–7 h (przejście ≈ 3,1 h,
  ≈ 85 MB proxy). Szacunek proxy analizatora ≈ 0,5–0,6 GB/dobę (przejścia ~340 MB + resolver + szczegóły) – za dużo
  przy budżecie → `ANALYZER_WATCH_HOURS=8-10`. `sold-report` pokazuje też pracę watch na dzień (szczegóły / nowe).
* **`find.py`** – `python -m analyzer szukaj ram ddr4 dimm 16 --max 200`: najtańsze aktywne oferty z linkami; RAM:
  forma/typ z kodu naklejki w opisie (PC4-…-U = PC, -S = laptop, PC3 = DDR3).
* Testy: **243** (`python -m pytest analyzer/tests -q`), atrapa rynku `analyzer/tests/fake_market.py`.

### 5. Sniper (`unreachable_sniper/sniper/`) – przepływ oferty

1. **Skan** (`scout.py`): `SNIPER_CATALOGS=auto` → `guides/catalogs.json`; katalogi 3580 laptopy, 3661 telefony,
   3728 tablety, 3025 konsole, 3582/3583/3584 podzespoły/nośniki/akcesoria (karta/RAM/dysk z tytułu, reszta bez
   szczegółów). Po kolei, przeplatane wagami (`categories.schedule`, `SNIPER_CATALOG_WEIGHTS=laptop:6,phone:6,
   tablet:2,console:2,gpu:1,ram:1,storage:1`), `SNIPER_POLL_INTERVAL` (7–10 s), `SNIPER_CATEGORIES` włącza kategorie
   (u użytkownika teraz laptop,phone,tablet,console; gpu,ram,storage po dojściu sprzętu – już doszedł).
   Heartbeat: „Katalogi (skany / nowe / do oceny)”.
2. Szczegóły (sidebar + shipping, przez proxy) → `Offer` z `category`.
3. **Przed AI** (`evaluator.submit`): `already_seen` (ta sama oferta nie tańsza – pomijana, pamięć z evaluations.jsonl)
   → `prefilter` (słowa per kategoria `SNIPER_AI_EXCLUDE_KEYWORDS_<KAT>`) → `gate`: brak wytycznych kategorii;
   tabela (`guides.py`: dopasowanie wiersza po słowach, warianty Pro/Max/Ti blokują, bez pojemności → najwyższy
   wariant; koszt > max × 1,25) ; **podobne oferty** (koszt > szacunek × 1,2 × 0,7) → dzienny limit $.
4. **AI** (`gemini` / `anthropic` / `openrouter`): system = wytyczne kategorii (laptop: `laptop.md` + ręczne
   `guidelines.md`), user = oferta (+ koszt zakupu z opłatą), zdjęcia (`SNIPER_AI_MAX_PHOTOS`), `<karta_rynku>`
   (pasujące wiersze), `<porownywalne>` (mediana podobnych ofert). JSON wg `EVALUATION_SCHEMA`.
5. **Po AI – program** (`evaluate`): `enforce_profit_rule` (przelicza zysk/marżę/max zakup z wartości AI; wartość
   AI > szacunek z podobnych × 1,2 → przycięta; łamie regułę → nie okazja, ocena ≤ 6; < 45% wartości → flaga „bardzo
   tanio”), `cap_without_market_data` (brak wiersza i podobnych ofert → ocena ≤ 7, laptopy wyjątek),
   `apply_pl_bonus`.
6. Wyjście: `evaluations.jsonl/.csv`, `oceny.html` (≥ `SNIPER_AI_REPORT_ABOVE`), mail (`SNIPER_AI_MIN_SCORE`,
   `SNIPER_AI_NOTIFY_FAILED`), ntfy (`SNIPER_NTFY_MIN_SCORE`) z: koszt z opłatą, max zakup, zysk, marża, dni,
   „Sprzedawca z Polski +1”, **„Do testu: …”** (`categories.test_kit` + `SNIPER_TEST_HAVE` → „⚠ BRAK SPRZĘTU”).
   Kopia logów na Dysk Google: `SNIPER_MIRROR_DIR`.
* Ustawienia `.env` – pełna lista z opisami: `unreachable_sniper/sniper/.env.example`, wzór serwera
  `analyse_data/ENV_SERWER.example`. Reguła w Sniperze: `SNIPER_RULE_MIN_PROFIT/_MIN_MARGIN/_PER_POINT/_COSTS`.
* Testy: **215** + 1 pominięty (`python -m pytest sniper/tests -q`; `test_categories.py`, `test_experiment.py`).
* `evaluator.Task` (2026-10-27): zapytanie do AI = schemat + instrukcja systemowa + polecenie + normalizacja JSON;
  `DEFAULT_TASK` = zwykła ocena; backendy (`generate(..., task=)`), parsery (`normalize=`) i `_call_model(offer,
  comps, hint=, task=)` to przyjmują – nowe tryby oceny bez kopiowania backendów.
* Kontekst historyczny Snipera (API Vinted, sesja konta, auto-zakup): `unreachable_sniper/CLAUDE.md`.

### 6. Co wyszło w praktyce (26.10, `oceny.html` 366 ocen + `mails.csv`)

* Przed dzisiejszymi poprawkami 39 ocen 8–10, większość z zyskiem 150–250 zł (Wii, PS1–3, Xbox Classic, tanie tablety)
  – stara reguła (wyjątek 150 zł, marża 20%) + **AI zmyślało ceny retro** (Wii 600–760 zł, GBC 850, C64 800).
  Przy nowych regułach zostałoby ~10.
* Użytkownik **kupił 7 rzeczy (~2 650 zł)** z alertów: 2× Wii + Wii czarne bez pilota, iPhone 12 128 (bateria <80%),
  Galaxy A17, Galaxy Tab A 10.1 (2019), „iPad Air 2022” (w parametrach **iPad 10.9 (2022)**; 27.10 zrzut Ustawień
  od sprzedawczyni = **iPad Air 4. gen. (2020) 64 GB, MYFQ2FD/A** – oba źródła w ogłoszeniu błędne; użytkownik
  dostał wiadomość po słowacku z prośbą o anulowanie – wynik nieznany, zapytać). Szac. zysk łącznie
  ~600–1 100 zł, wszystko od zagranicznych sprzedawców (RO/SK/LT). Rada: Wii składać w zestawy, gry osobno.
* S22 (8/10) sprzedany w 3 min, gdy użytkownik negocjował → zasada „kupuj od razu przy 8+”.
* Burst 12 maili „NIEOCENIONA” (błąd API) → `SNIPER_AI_NOTIFY_FAILED=false`.
* Duplikaty tej samej oferty (podbicia) → `SNIPER_AI_SKIP_SEEN`.
* 209/366 ocen = 3/10 → bramka z podobnych ofert.

### 6a. Eksperyment 2026-10-27: dwa sposoby oceny (`unreachable_sniper/sniper/experiment.py`)

Użytkownik chce porównać na 50 ostatnich ocenach Snipera (z `logs/evaluations.jsonl`, bez maili, Sniper bez zmian):

* **`mediany`** (pomysł użytkownika): słowa z tytułu → `Comparables.levels()` = kilka median z `comparables.db`
  (model + liczby + wariant → 1. liczba → bez liczb → „cała rodzina” = pierwsze znaczące słowo tytułu, df ≤ 50%,
  bez słów ogólnych `GENERIC`) → `<mediany>` + karta rynku + wytyczne kategorii + zdjęcia → AI SAMO wycenia
  (`median_used`), może poprawić model, gdy parametry przeczą tytułowi (`corrected_model`, np. iPad Air 2022 →
  starsza generacja, zła karta w laptopie, zły RAM w telefonie); `in_medians=false` → nie okazja, ocena ≤ 3. Program
  potem `enforce_profit_rule` z wybraną medianą (przycięcie ×1,2) + premia PL.
* **`model`** (wersja planu): AI tylko rozpoznaje – marka, model, `params` (wartość, pewność 0–100, źródło), `variants`
  a)/b) gdy pewność < 80% (z `search_words`), stan (enum), flagi; BEZ cen. Program wycenia każdy wariant
  (`comparables.lookup`, bez niego wiersz tabeli), cena S = najtańszy wariant × (1 − 0,08), reguła zysku, ocena wzorem
  (`formula_score`: 10 = marża ≥ 45% i zysk ≥ 800; 9 = ≥ 45% i ≥ 500; 8 = ≥ 40% albo ≥ 35% i ≥ 500; 7 = reguła;
  −1 przy stanie „nie_wiadomo” albo pewności modelu < 80%), uszkodzone/blokada ≤ 2, wariant bez danych → nie okazja,
  `upside` = „jeśli to <lepszy wariant>, zarobisz ~X zł więcej”; premia PL.
* Wyjście: tabela „stara → nowa ocena, tytuł, S, zysk (marża), ⇄ poprawiony model / = wyceniony wariant, upside,
  ← INNA DECYZJA” + PODSUMOWANIE (okazje stare → nowe, oceny 8+, ta sama decyzja, brak w medianach / poprawione
  modele albo warianty a/b / bez danych, koszt) + `logs/experiment_<tryb>.jsonl` (pełne odpowiedzi, `old` = stara
  ocena, `levels` = użyte mediany).
* **Jak ocenić wyniki:** (1) okazje 8+ w każdym trybie – przejrzeć ręcznie (link w `offer.url`): czy model i cena
  sprzedaży są realne, czy to nie akcesorium / uszkodzony; (2) fałszywe okazje starego Snipera (wysoka stara ocena,
  nowa niska) – kto ma rację; (3) `mediany`: czy poziom „cała rodzina” nie zawyża (iPad Pro w medianie zwykłych
  iPadów), ile razy AI wycenia z rodziny zamiast z dokładnej mediany, czy `corrected_model` ma sens; (4) `model`: ile
  ofert bez danych (słabe pokrycie `comparables.db` = argument za taksonomią z planu), czy warianty a/b są sensowne;
  (5) koszt; (6) pierwszy test `comparables.db` na prawdziwej bazie – dziwne dopasowania zapisać. Wnioski do
  dziennika `PLAN_OCENY.md` §15 i decyzja z użytkownikiem: który tryb wdrożyć w Sniperze (np. jako
  `SNIPER_EVAL_MODE`), co z planu zostaje.
* Warunek: `comparables.db` w `SNIPER_GUIDES_DIR` (robi go `python -m analyzer sniper-guide`); bez niego program
  ostrzega i wynik nie ma sensu.
* **Wynik 27.10 (szczegóły `PLAN_OCENY.md` §15):** przebieg bez `comparables.db` → `mediany` nieważny; `model`
  odtworzony offline z prawdziwą bazą: zabija fałszywe okazje retro (Wii, GBC), zostawia iPhone 14 Pro 850 zł, ale
  dawał 10/10 oszustwom (iPhone 16 za 800 zł) → `cheap_guard`. Powtórka u użytkownika (po `git pull` w obu repo):
  `python -m analyzer sniper-guide` (z `ANALYZER_SNIPER_GUIDES_DIR` → kopiuje `comparables.db`), sprawdzić, że jest
  `unreachable_sniper\sniper\guides\comparables.db`, `restart sniper`, potem oba `sniper.experiment … --last 50`.
* **Sniper 27.10 (poza eksperymentem):** `SNIPER_PRICE_FLOOR=300` (price_from każdego katalogu ≥ 300 zł), wysyłka
  przeliczana z waluty sprzedawcy (`FX_TO_PLN`; było 799 HUF = 799 zł), kraj sprzedawcy z waluty wysyłki (premia PL
  wcześniej nigdy nie działała), tokenizacja liter spoza PL, `comparables` próg słów 35% + słowa ogólne obcych
  języków, heartbeat „/N!” = pełna strona nowych ofert (zwiększ `SNIPER_PER_PAGE`).

### 7. Zasady pracy (skrót `CLAUDE.md`)

Po polsku (także komentarze w kodzie). Claude **nie ma dostępu do vinted.pl ani bazy** – kod + testy na atrapach,
użytkownik uruchamia i wkleja wynik. Bez sekretów i danych w repo (`.env`, `*.db`, `data/`, eksporty). **Sprzedawcy**
(zmiana 2026-10-26, decyzja użytkownika): w bazie i eksportach jako stały hash (`seller_hash`, zapisywany zawsze),
nicków nie zbieramy (niepotrzebne); `export-analysis --split` = paczka na kategorię do wysłania w czacie (Claude nie
otworzy linku do Dysku bez connectora). Zapytania do Vinted tylko z realnego ruchu przeglądarki – bez zgadywania
endpointów. Commit + push po każdej zmianie na `claude/hopeful-faraday-n33quh` w danym repo; testy obu repo przed
pushem; bez PR. Odpowiedzi: konkretnie, z komendami do wklejenia na serwerze (`git pull` w obu, `sniper-guide`,
`restart sniper`).

### 8. Do zrobienia / niedoskonałości (priorytety)

00. ~~Wyniki eksperymentu 6a~~ (27.10, `PLAN_OCENY.md` §15) → **powtórka z `comparables.db`** i decyzja o trybie.

0. **GŁÓWNY PLAN: `PLAN_OCENY.md`** (2026-10-26) – taksonomia modeli, ceny S7 z danych (`prices.json`), AI tylko do
   rozpoznania i stanu (z cytatami jako dowodem), deterministyczna ocena, pętla zwrotna (flipy, wynik alertów,
   backtest). Punkty 1, 3, 4, 5, 7, 9 niżej są jego częścią. **YOLO / zbiór zdjęć – odrzucone i cofnięte 26.10.**

1. **Kalibracja na nowych danych (najpierw):** poprosić o `oceny.html`, `mails.csv` z 2–3 dni po zmianach z 26.10 i
   linię kosztu (`log sniper` → „dziś ~$…”). Sprawdzić: ile 8–10, czy reguła/limity działają, ile kosztuje dzień,
   ile ofert odcina bramka z podobnych, czy flash-lite trafnie ocenia okazje. (Parser kart: regexy po
   `<article class="card` – patrz analiza 26.10.)
2. **`comparables.db` na prawdziwej bazie** – nie testowane: czas i RAM budowy (4 GB), rozmiar pliku, trafność
   dopasowań dla tytułów RO/LT/SK/CZ (słowa ogólne odcina df ≤ 20%, ale np. „consola”, „telefon funcțional”), próg
   60% słów, min 8 ofert, `LIMIT 2000`. Dodać komendę diagnostyczną w Sniperze/analizatorze („pokaż podobne do
   tytułu X”) – użytkownik będzie mógł sprawdzić wyceny ręcznie.
3. **Śledzenie wyników flipów** (brak!): rejestr zakupów i sprzedaży (cena zakupu, sprzedaży, dni, koszty) – bez
   tego nie da się zweryfikować reguły, cen S ani ocen AI. Propozycja: prosty `flips.csv` + komenda raportu ROI.
4. **Ceny sprzedaży (D2/D3 z `PLAN_ANALIZY.md`)**: dziś S = ostatnia cena wystawienia zniknięć (sold + deleted) –
   górna granica; po 2–4 tyg. `watch` z szybkim resolverem → ceny i czas SPRZEDAŻY per model. Wtedy sell_days z danych.
5. **Grupy mieszane ⚠** (PS5 17%, DDR5 16 GB 27%, DDR4 64 GB, SATA/NVMe 4 TB, DDR4 DIMM 32): rozdzielić warianty
   (PS5 disc/digital/slim/pro, zestawy 2× vs 1× kość, laptop/PC) w `extract.py`/`guide.group_key`.
6. **Laptopy**: wyjątek od limitu „brak danych”; zintegrowane wykluczone z dopasowania tabeli (`Row.words`) –
   rozważyć dopasowanie po generacji CPU; `guidelines.md` (ręczne) ma ceny S użytkownika (starsze niż dane).
7. **Wybór modelu AI**: porównać `gemini-3.1-flash-lite` vs `3.8-flash` (`--compare`) na okazjach 8+; OpenRouter
   (Qwen/DeepSeek/GLM) – pierwszy test na żywo; ceny modeli w `config.MODEL_PRICES` (bez wpisu koszt = 0 i limit
   dzienny nie działa – OpenRouter podaje koszt sam).
8. **Sprzedawcy zagraniczni**: większość ofert RO/SK/LT/SE; rozważyć karę/limit czasu dostawy w ocenie lub filtr
   krajów; waluty przeliczane przez Vinted.
8a. **Handlarze (hash sprzedawcy, od 2026-10-26)**: `seller_hash` zapisywany zawsze – starsze zniknięte oferty go
   nie mają, aktywne uzupełnia każde przejście. Gdy użytkownik wyśle `export-analysis --split`: udział ofert od
   sprzedawców z ≥ 5 ofertami w grupie, czy psują medianę / szybkość sprzedaży, relisty u tego samego sprzedawcy
   (lepsze wykrywanie relistów), ew. wykluczenie handlarzy z „sprzedam za ~”.
9. **Backtest** (pozostałość D5): ocena historii ofert nowymi regułami vs to, co się sprzedało.
10. **Drobne**: nazwy grup typu „Xbox serie S i X seriess”; ~~`catalogs.json` od 50 zł~~ (27.10: Sniper
    `SNIPER_PRICE_FLOOR=300` podnosi dolną granicę każdego katalogu); procesory jako kategoria (użytkownik pytał;
    brak w analizatorze); DDR5 – stanowisko B (H610M DDR5 + Pentium G7400) gdy będą okazje; auto-zakup wyłączony.

### 9. Gdzie co jest (mapa plików)

| temat | plik |
|---|---|
| **plan dokładnej oceny (główny)** | `PLAN_OCENY.md` |
| eksperyment mediany / model | `unreachable_sniper/sniper/experiment.py`, `sniper/comparables.py: levels`, `evaluator.Task` |
| zasady pracy | `analyse_data/CLAUDE.md`, `unreachable_sniper/CLAUDE.md` |
| historia analizatora, API Vinted | `KONTEKST_CATEGORY_ANALYZER.md`, `PLAN_ANALIZY.md` (dziennik wyników na końcu) |
| serwer, pilot, uruchamianie | `PILOT.md`, `ENV_SERWER.example`, `remote.bat`, `watch.bat` |
| sprzęt do testów | `SPRZET_DO_TESTOW.md` |
| reguła zysku, wytyczne | `analyzer/guide.py`, `sniper/guidelines.md` (laptopy, ręczne), `sniper/evaluator.py` (prompt, enforce) |
| katalogi, wagi, sprzęt testowy | `sniper/categories.py` |
| tabela wytycznych, dopasowanie | `sniper/guides.py` |
| podobne oferty | `analyzer/comparables.py`, `sniper/comparables.py` (tokenizacja musi być zgodna!) |
| szukanie w bazie | `analyzer/find.py` |

---

# Część B – dziennik z PLAN_OCENY.md §15 (2026-10-26 … 29.10)

* 2026-10-26: plan spisany; YOLO odrzucone i cofnięte; `seller_hash` zapisywany zawsze, `export-analysis --split`
  gotowe (D2). Sniper dalej na v1 (gemini-3.8-flash, użytkownik doładował 160 zł).
* 2026-10-27: iPad kupiony 26.10 (SK): tytuł „iPad Air 2022”, formularz Vinted „iPad 10.9 (2022)”, a zrzut Ustawień od
  sprzedawcy = **iPad Air (4. generacja, 2020), 64 GB** – OBA źródła błędne. Wniosek do §5/§6: sprzeczność tytułu
  i formularza = item niepewny (bez okazji przed potwierdzeniem); przy tabletach/telefonach w powiadomieniu
  podpowiedź „poproś o zrzut Ustawienia → Ogólne → To urządzenie (nazwa i numer modelu)”. Użytkownik prosi
  o anulowanie.
* 2026-10-27: użytkownik nieprzekonany do całego planu – najpierw porównanie na danych: `python -m sniper.experiment
  mediany --last 50` (jego pomysł: kilka median z `comparables.db` od szczegółowej do całej rodziny → AI wycenia samo,
  może poprawić model, brak w medianach = ignoruj) vs `python -m sniper.experiment model --last 50` (AI tylko
  rozpoznaje z pewnością %, warianty a/b, program wycenia gorszy wariant + „zarobisz więcej, jeśli to X”). Wyniki:
  `unreachable_sniper/sniper/logs/experiment_<tryb>.jsonl` – NOWY CZAT: poproś o podsumowania obu i porównaj
  (zgodność ze starymi ocenami, okazje, poprawione modele, brak danych, koszt), zanim ruszysz F1+.
* **2026-10-27 – wyniki eksperymentu 6a** (pliki `experiment_{mediany,model}.jsonl` + pełna baza `analyzer_full.db`
  z Dysku, migawka 27.10 ~10:10). **Oba przebiegi szły BEZ `comparables.db`** (ostrzeżenie w logu; u użytkownika nie
  było pliku w `unreachable_sniper\sniper\guides` – to znaczy, że od 26.10 także zwykły Sniper działał bez bramki
  „podobne oferty” i bez przycinania wyceny AI). ⇒ `mediany`: 50/50 „brak w medianach” = wynik nieważny (AI musiało
  dać ≤ 3); `model`: wycenione tylko 10/50 (z wierszy tabeli). Koszt: mediany $0,82, model $0,73 za 50 ofert
  (~1,5 centa/ofertę, jak zwykła ocena – zdjęcia dominują).
  * Zbudowałem `comparables.db` z prawdziwej bazy (166 tys. ofert, 18 MB, ~3 s, ~50 MB RAM – §8.2 STAN: OK) i
    odtworzyłem część programową trybu `model` offline (rozpoznania AI z pliku, bez nowych wywołań): wycenione 41/50.
  * **Stary Sniper: 4 okazje, z tego 3 fałszywe** – Wii 128 zł (10/10) i 100 zł (9/10): dane = mediana aktywnych
    ~450 zł, S_kons ~370 zł → zysk ~190 zł (AI zakładało 600–760); Game Boy Color re-shell 435 zł (9/10): mediana
    ~450–500 zł → strata (AI: 850). Prawdziwa: **iPhone 14 Pro 128 GB za 850 zł** (PL, 149 opinii, bateria 80%):
    S z danych 1 584 → S_kons 1 457, zysk ~510 zł, marża 35% → `model` 7/10 (+1 PL = 8 po poprawce kraju niżej).
  * **`model` bez bramki daje 10/10 oszustwom**: iPhone 16 za 800 zł i „Telefon 16 pro” za 1 000 zł (konta bez
    opinii, „TYLKO PRZEZ DHL I INPOST”) – AI samo wpisało „oszustwo” w red_flags, a program to pominął. Stary
    Sniper dał 0 (AI wycenia + ocenia ryzyko). → dodane `cheap_guard`: < 45% wartości + konto bez opinii = nie
    okazja; < 45% z opiniami = max 7 („sprawdź ręcznie”). Wniosek do F3: flagi oszustwa z AI (enum) muszą działać.
  * `mediany` – poziomy na prawdziwej bazie (bez AI): „cała rodzina” bywa bezużyteczna albo groźna: „iPad 2” →
    tylko „ipad” (mediana 713 zł, a iPad 2 = ~300 zł), Pixel 9 → „google”, iPad Pro 11 (tytuł HU) → „eladó”
    (= „sprzedam”). Model AI z taką medianą łatwo „znajdzie” okazję – ten tryb wymaga dokładnego poziomu albo
    taksonomii (F1). Poprawne poziomy dla iPhone'ów pojawiły się dopiero po poprawce df niżej.
  * **Błędy znalezione i poprawione (Sniper, gałąź `claude/magical-bell-vdwpt1`):**
    (1) wysyłka w walucie sprzedawcy doliczana jak zł – **799 HUF = +799 zł** (Xbox One S 328 zł → koszt 1 146 zł,
    iPad Pro 11 1 458 zł → 2 253 zł; RON/EUR małe błędy) → kurs `FX_TO_PLN`;
    (2) **kraj sprzedawcy pusty w 50/50** – premia „Polska +1” nie zadziałała ani razu → kraj z waluty wysyłki
    (PLN = opis po polsku 20/20; EUR bez zgadywania);
    (3) tokenizacja tytułów cięła litery spoza PL („Vând” → „v nd”, „Säljer” → „s ljer”) – w obu repo;
    (4) `comparables`: „iphone” (25% bazy) > progu 20% → „iPhone 7” szukał każdego telefonu z „7” (mediana 834 zł,
    po poprawce 365 zł), „Telefon iphone 16” → [16 telefon] 650 zł (po poprawce 2 255 zł) – próg 35% + słowa
    ogólne w językach sprzedawców; zostaje znany problem: liczby dziesiętne („10.2” → „10”, „2”) mieszają iPad 2
    z iPadem 10.2 – rozwiąże taksonomia F1.
  * **Rekomendacja:** kierunek `model` (AI rozpoznaje, program wycenia z danych) – na danych zabił wszystkie 3
    fałszywe okazje retro i zostawił prawdziwą; ale tylko z bramką oszustw i z lepszym dopasowaniem cen (słowa
    tytułu są kruche → F1 taksonomia). `mediany` nie da się ocenić bez powtórki z `comparables.db`; z poziomów
    widać ryzyko „całej rodziny”. Decyzja po powtórce obu trybów (komendy w STAN §6a).
  * **Próg ceny 300 zł** (prośba użytkownika): catalogs.json zaczynał od 50–100 zł (tablety 50, telefony 100).
    W 50 ocenach 14 ofert < 300 zł = 29% tokenów, wśród nich 2 fałszywe 9–10/10 (Wii), 0 prawdziwych okazji.
    Przy regule zakup < 300 zł byłby okazją tylko przy sprzedaży ≥ ~650 zł. → `SNIPER_PRICE_FLOOR=300` (domyślnie),
    „/N!” w heartbeat = cała strona nowa. Tempo nowych ofert z `crawl_runs` 26.10 (≥ progów analizatora): telefony
    ~1,8/min, konsole ~0,8/min, laptopy ≥ 700 zł ~0,3/min, tablety ~0,25/min → `SNIPER_PER_PAGE=6` wystarczy.
  * **F0 – `sold-report` na bazie 27.10:** przejścia od 24.10 12:00 – 3 na katalog (laptopy 5), najdłuższa przerwa
    16–21 h (cel 10–14 h; 25.10 brak szybkich rozpoznań), przejście #137 z 24.10 niedokończone ⇒ `watch` miał przerwy.
    Zniknięcia rozpoznane od 24.10: 20 307, z tego **sprawdzone ≤ 24 h tylko 5%** (cel ≥ 90%). Udział sold+blocked
    wg zwłoki: ≤ 12 h 3,2%, 12–24 h 16,9%, 1–3 dni 8,4%, > 3 dni 3,1% (głównie recheck 24.10) ⇒ potwierdza hipotezę
    C4: sprawdzane późno sprzedane już nie istnieją (404 = „deleted”); szybkie sprawdzanie daje 3–5× więcej pewnych
    sprzedaży. Per kategoria (zwłoka ≤ 3 dni, 2,4 dnia): konsole 98 sold+blocked / 358 deleted (21,5%), telefony
    34 / 843 (3,9% – podejrzanie mało, sprawdzić relisty/podbicia telefonów), laptopy 8 / 261, GPU 5, tablety 5,
    dyski 3, RAM 2. 26.10: 153 pewne sprzedaże / dzień łącznie. ⇒ do F2 potrzebne ≥ 2–4 tyg. CIĄGŁEGO `watch`
    i szybszy resolver (C4: `ANALYZER_GONE_AFTER_RUNS=1` / krótszy `ANALYZER_WATCH_HOURS` – decyzja użytkownika).
* **2026-10-27 wieczór – `watch` częściej (prośba użytkownika „podejrzanie mało sprzedaży”).** Przyczyna z danych:
  resolver sprawdzał ~700 ofert/h (odstęp stron katalogu 2–6 s) bez przerwy 25.10 18:00 → 27.10 10:00 – oprócz
  świeżych zniknięć ~12 tys. ponownych sprawdzeń niewidocznych/ukrytych co 3 dni; przejście czekało na koniec
  resolve ⇒ przerwy 16–21 h, mediana zwłoki rozpoznania (od 26.10) 88 h, p25 24 h. Szczegóły ofert prawie stały
  (24.10: 71, 25.10: 238, 26.10: 2 513; aktywnych bez szczegółów 56 580). Zmiany: świeże zniknięcia zaraz po
  przejściu, ponowne sprawdzenia w tle do końca cyklu (równolegle ze szczegółami), odstęp resolvera 1–2,5 s,
  przejścia co 5–7 h, linia „Cykl: …” w logu. Oczekiwana zwłoka sprzedanej ~6–9 h. Do sprawdzenia po 2–3 dniach:
  `sold-report --od <restart>` (≥ 90% ≤ 24 h, udział sold+blocked), 429 w logu resolvera, zużycie Evomi.
* **2026-10-27 – odpowiedzi użytkownika (§11):** sprzedaje głównie zagranicznym kupującym (Podbicie
  międzynarodowe) ⇒ R = mediana wszystkich rynków (§4.2 bez zmian); kupować chce głównie od Polaków (szybsza
  dostawa – premia PL +1 zostaje, od 27.10 działa: kraj z waluty wysyłki). Negocjacje: wystawia z zawyżoną ceną
  i schodzi „o kilka set zł” ⇒ δ liczone od JEGO ceny wystawienia nic nie mówi o rynku; δ = 8% od mediany rynku
  zostaje do czasu danych z `flips.csv` (cena otrzymana vs mediana aktywnych w dniu sprzedaży).
* **2026-10-27 – powtórka 6a z `comparables.db`:**
  `mediany`: 1 okazja (iPhone 14 Pro 850 zł, 7/10 = prawdziwa), 0 ocen 8+, ta sama decyzja 47/50, 9 poprawionych
  modeli (sensowne: iPad 6 Cellular A1954, PS5 Fat, GBC re-shell, iPad Pro 12.9 2020), brak w medianach 7; oszustwa
  (iPhone 16 za 800 / 16 Pro za 1 000) – AI samo 0/10 mimo „zysku” 1 500 zł; Wii białe 6/10 (S 480, zysk 296 zł –
  tuż pod progiem; dane potwierdzają), Wii czarne bez pada S 180 → 2, iPad 2 S 80 (trafnie). Koszt $0,73.
  `model`: 3 okazje – iPhone 14 Pro (prawdziwa), **iPad 2 za 125 zł (FAŁSZYWA: wyceniony jako „iPad 3 16 GB” 491 zł –
  słowa „ipad 3 16” łapią iPady 10.x)**, Realme 14 Pro+ 500 zł (S 937 z 9 ofert – za mało danych; `mediany` dało
  S 880 i 5/10); oszustwa 3/10 (cheap_guard działa). Koszt $0,58 (−21%).
  Złoty zbiór (`unreachable_sniper/sniper/bench_golden.json`, 18 ofert): `mediany` 1/1 trafione, 0 fałszywych;
  `model` 1/1, 1 fałszywa. **Wniosek: jakość lepsza w `mediany`** (AI z medianami łapie oszustwa, zestawy, generacje,
  których dopasowanie słów nie widzi); `model` jest tańszy, ale jego wycena zależy od kruchych słów tytułu.
  → `SNIPER_EVAL_MODE=mediany` dodane (laptopy dalej zwykle); decyzja po `sniper.bench`.
* **2026-10-27 – koszty AI:** 50 ocen = $0,58–0,82 (~1,2–1,6 centa/ofertę; ~13,6 tys. tokenów wejścia na ofertę,
  z tego zdjęcia ~1 100 tokenów każde, wyjście ~1,4 tys. z myśleniem). Na tych 50 ofertach **do AI poszłoby tylko
  15**: próg 300 zł odcina 14, bramka „za drogo wg podobnych ofert” 21 (działa dopiero od skopiowania
  `comparables.db` 27.10), prawdziwa okazja przechodzi ⇒ ~70% mniej wywołań za darmo. Dalsze próby: `python -m
  sniper.bench` (warianty: mediany, 3 zdjęcia, średnia / niska rozdzielczość zdjęć, krótsze myślenie,
  flash-lite + mediany, kaskada „tani model bez zdjęć → pełna ocena tylko ≥ 4/10”), miary: złoty zbiór (okazje
  trafione / przegapione / fałszywe, S w zakresie), zgodność z odniesieniem, $/ofertę. Równoległość AI 3 → 10.
* **2026-10-28 – pytanie użytkownika: model decyzyjny zamiast LLM (basal-omni-1.0-ultra, Remek Kinas).** To model
  „decyzyjny” (Gemma 4 31B + LoRA): stan (tekst/zdjęcia) + pytanie z listą dozwolonych odpowiedzi → skalibrowane
  prawdopodobieństwa w jednym przebiegu (choice / tak-nie / score), bez cen i bez arytmetyki. Pasuje do etapów A/B
  z §6 (wybór item_id z kandydatów taksonomii, flagi: uszkodzony / blokada / oszustwo / akcesorium), NIE do wyceny
  (tę i tak robi program). Ultra: ~62 GB VRAM (bf16, 1× GPU 80 GB), FP8 tylko tekst; ~80 ms/pytanie na H200;
  eksperymentalny, zdjęcia z telefonu słabsze (zero-shot). Na serwerze użytkownika (4 GB RAM, bez GPU) niewykonalny;
  wynajem GPU 24/7 drożej niż Gemini po bramkach. Mniejsze: omni-mini 4B (16 GB VRAM, zdjęcia), basal-2.0 pico 0,8B
  (tekst, GGUF 812 MB, CPU). Wniosek: wrócić po F1 (taksonomia = lista kandydatów) jako tani etap A tekstowy –
  porównać w `sniper.bench` na złotym zbiorze.
* **2026-10-28 – dzień testowy (decyzja użytkownika; Sniper wyłączony, bo jeszcze nie działa dobrze).** Te same
  oferty przez 12 wariantów: `mediany` / `model` / `basal` × gemini-3.8-flash / gemini-2.5-flash-lite (myślenie
  medium; 2.5 przez thinking_budget) × 3 / 6 zdjęć – `python -m sniper.bench --warianty dzien_testowy --last 50
  --bez-bramki`. Tryb `basal`: program dobiera kandydatów z tabeli wytycznych, basal (lokalny model decyzyjny – nie
  generuje tekstu, tylko wybiera z podanych odpowiedzi) wybiera model + flagi tak/nie, z wybranego wiersza mediany
  z bazy, Gemini ocenia (`unreachable_sniper/sniper/basal.py`, API wg dokumentacji, nieprzetestowane na żywo – Claude
  nie mógł zainstalować basal w swoim środowisku). Uwaga: „basal-2.0 pico” nie istnieje – najmniejsze są
  basal-omni-pico 0,8B (GGUF, CPU przez Ollama / llama.cpp) i basal-2.0-mini 1,5B (udokumentowane CPU:
  `--mode eager --device cpu`). Wynik → wybór: najlepszy / najtańszy / optymalny wariant.
* **2026-10-28 – nowa reguła zysku (użytkownik):** okazja na 8 przy marży ≥ ~28% (tanie, sprzedaż ≤ 1 000 zł) →
  ~25% (drogie, ≥ 2 500 zł), zysk ≥ 300 zł; koniec dopłaty „+20 zł/pkt poniżej 40%”. W §7 progi 8/9/10 odpowiednio:
  8 = reguła, 9 = marża ~35%+ albo zysk ~600+, 10 = ≥ 45% i ≥ 800 zł. Katalogi Snipera od 300 zł (wcześniej
  `catalogs.json` dawał 50–400 zł). Przykład z kopii bazy: iPhone 14 Pro 128 GB max zakup 1 051 → 1 112 zł,
  PS5 1 695 → 1 819 zł; przy tanich (S < ~1 070 zł) decyduje zysk 300 zł.
* **2026-10-29 – wynik dnia testowego (68 ofert = 50 ostatnich + złoty zbiór, bez bramki, $3,90).** Gemini 2.5 Flash
  Lite: 404 „niedostępny dla nowych kont” (wszystkie 272 oceny = błąd; dlatego „błyskawicznie”); basal pominięty
  (serwer nie uruchomiony). Gemini 3.8 Flash:
  | wariant | $/ofertę | tok. we/wy | okazje | złote: trafione / fałszywe | S w zakresie |
  | mediany 3 zdj. | 0,0156 | 12,9k / 1,6k | 3 | 1 / 1 (Wii 7/10, „bardzo tanio”) | 11/12 |
  | **mediany 6 zdj.** | **0,0158** | 15,0k / 1,6k | **1** | **1 / 0** | 10/12 |
  | model 3 zdj. | 0,0129 | 11,2k / 1,2k | 5 | 1 / 2 (iPhone 16 oszustwo 8/10 – wzięty za iPhone 15; iPad 2) | 8/11 |
  | model 6 zdj. | 0,0130 | 13,0k / 1,2k | 4 | 1 / 1 (iPad 2) | 10/11 |
  Najlepsza jakość: **mediany + 3.8 Flash + 6 zdjęć** (jedyna okazja = iPhone 14 Pro 850 zł; laptop Asus za 578 zł
  odrzucony przy zysku 296 zł i nowym koncie; Wii wycenione realnie na 370 zł). `model` myli się na dopasowaniu słów
  (Galaxy A25 wyceniony na 1 222 zł, iPad 2) i na oszustwach. 3 vs 6 zdjęć: tylko ~2 tys. tokenów (~0,2 centa) różnicy –
  zdjęcia to mały koszt; ~11 tys. tokenów to tekst (prompt + pełna tabela wytycznych ~4–5 tys.), ~38% kosztu to
  wyjście z myśleniem (1,6k × $3,75/M). Dalej: `dzien_testowy2` (tańsze modele 3.5 / 3.1 Flash Lite, myślenie low,
  wytyczne tylko z pasującymi wierszami – `SNIPER_AI_GUIDE_ROWS=dopasowane`). Bramka (próg 300 zł + podobne oferty)
  i tak odcina ~70% ofert przed AI.
* **2026-10-29 – dzień testowy 2 (mediany, 6 zdjęć, 68 ofert, $3,88):**
  | wariant | $/ofertę | tok. we/wy | okazje | złote fałszywe | S w zakr. | zgodność z 3.8 (decyzja / ±1) |
  | **3.8 Flash** | 0,0135 | 15,3k / 1,6k | 1 | 0 | 12/13 | odniesienie |
  | 3.8 myślenie low | 0,0130 | 15,3k / 0,4k | 2 | 1 (Wii 7) | 12/13 | 99% / 88% |
  | 3.8 krótkie wytyczne | 0,0126 | 9,7k / 1,7k | 2 | 1 (Wii 7) | 10/11 | 99% / 96% |
  | 3.5 Flash Lite | 0,0086 | 15,3k / 1,6k | 6 | 0 (ale 5 okazji 8-9 spoza złotych) | 11/13 | 93% / 72% |
  | 3.5 Lite krótkie | 0,0067 | 9,8k / 1,7k | 8 | 1 | 10/12 | 90% / 68% |
  | 3.1 Flash Lite | 0,0029 | 15,3k / 0,6k | 4 | 0 (3 fałszywe spoza złotych) | 10/13 | 96% / 66% |
  Tanie modele „łykają” błędy sprzedawców: „Steam Deck OLED 256 GB” (nie istnieje – LCD) 9/10, iPhone XR 375 zł 9/10,
  iPad Pro 11 2018 9/10 – 3.8 Flash wszystkie odrzucił z uzasadnieniem. **Decyzja: mediany + gemini-3.8-flash +
  6 zdjęć + myślenie medium + pełne wytyczne** (jakość priorytetem); myślenie low / krótkie wytyczne oszczędzają tylko
  4–7% (różnice w niejawnym cache Gemini są większe niż te oszczędności). Koszt i tak tnie bramka przed AI (~70%).
  Złoty zbiór +5 ofert z tego testu (23).
* **2026-10-29 – zniknięcia: fałszywe 404 i szafa sprzedawcy (pomysł użytkownika).** Użytkownik trafił na
  aktywną ofertę, której strona dała 5× 404 → resolver po jednym 404/104 z /services oznaczał `deleted`, co mogło
  zawyżać usunięcia. Teraz: pierwsze 404 = `gone_404` + potwierdzenie w następnym cyklu (`ANALYZER_CONFIRM_404=2`);
  404 → 200 liczone jako „fałszywe 404” w `[RESOLVE] Wynik` (to zmierzy skalę zjawiska). Migracja v12: `seller_id`
  (z katalogu) i `gone_404`. `python -m analyzer szafa-test` – sprawdza w szafie sprzedawcy ostatnie zniknięcia
  (sprzedana / aktywna / brak / konto usunięte) i ile kosztuje strona szafy; po wyniku decyzja, czy dołożyć szafę
  do resolvera (koszt ~8 KB na pozycję – za drogo dla każdego zniknięcia, raczej dla `deleted` w ważnych grupach).
* **2026-10-30 – pięć próśb użytkownika (mediany co 2 dni, szybszy skan, szafa, kilka proxy, brak danych).**
  1) Automat (mediany = `comparables.db` + wytyczne) co 2 dni (`ANALYZER_AUTO_DAYS`, było 3,5). Termin i tak był w
  `analysis.db` (`meta.auto_at`), ale `watch` sprawdzał go dopiero PO przejściu (~3,1 h) – każdy restart w trakcie
  przejścia odsuwał mediany. Teraz sprawdzenie także na starcie cyklu (`__main__.auto_if_due`), test
  `test_watch_runs_overdue_auto_before_crawl`. 2) Sniper: pamięta 5 najnowszych ID z poprzedniego skanu katalogu
  (`SNIPER_OVERLAP_IDS`); gdy na stronie 1 nie ma żadnego = przyszło więcej, niż mieści strona → od razu strona 2
  (`SNIPER_GAP_PAGES=1`, do pierwszej znanej oferty) i pętla tego proxy co `SNIPER_POLL_FAST` (3 s) przez
  `SNIPER_FAST_MINUTES` (10). „/N!” w heartbeat liczy teraz te przepełnienia. 3) Szafa: `watch` jej NIE używa –
  `szafa-test` tylko czyta i niczego nie zapisuje, więc stany sold/deleted od szafy się nie zmieniły; efekt pokaże
  `szafa-test --limit 50` (tabela „nasz stan → w szafie”). Mediany nie trzeba przeliczać przed tą oceną – S w
  wytycznych i `comparables.db` liczy wszystkie zniknięcia razem (sold + blocked + deleted). 4) Kilka proxy:
  `SNIPER_PROXY_ROUTES=phone:x,console:y` + `SNIPER_PROXY_<X>_HOST/_AUTH` (albo `_URL`) i `_POLL`; każde proxy =
  osobna sesja (`logs/session_<x>.json`), osobna pętla (`scout.Lane`), szczegóły oferty przez to samo proxy co katalog,
  ruch w `traffic_<x>.csv`, przeglądarki (odświeżanie sesji) po kolei – 4 GB RAM. Szacunek (pomiary z 10.2026: skan ≈
  6 KB, szczegóły ≈ 15 KB): pętla co 3 s ≈ 190 MB/dobę skanów + ~60 MB szczegółów telefonów i konsol ≈ 7–8 GB/mies.
  Tanie residential poza IPRoyal / Evomi (ceny z blogów dostawców, 10.2026 – sprawdzić przed zakupem): DataImpulse
  ~1 $/GB pay-as-you-go, transfer nie wygasa, kraj gratis; Decodo ~2–4 $/GB; Webshare ~3 $/GB; Rayobyte pay-as-you-go
  3,5 $/GB, nie wygasa. Najpierw najmniejszy pakiet i dzień testu (403 / odświeżenia sesji w logu).
  5) „Brak danych w medianach” – propozycje bez kodu (prośba): (a) dane o laptopach 300–700 zł
  (`ANALYZER_PRICE_MIN_3580=300`; dziś laptopy omijają limit `cap_without_market_data` i nie mają danych < 700 zł),
  (b) klasy pewności jak PLAN_OCENY §4.6 – dokładna grupa = jak dziś; tylko rodzina / mało ofert = okazja, gdy reguła
  spełniona też przy p25 aktywnych × (1 − δ), ocena −1; brak danych = zamiast alertu „okazja” cichsze powiadomienie
  „do ręcznej oceny” tylko przy dużej marży wg AI, (c) druga próba median po modelu rozpoznanym przez AI
  (`corrected_model` / `laptop_model`) – bez dodatkowego wywołania AI, (d) mała grupa ściągana do rodzica
  (n / (n + 8)), (e) sufit z ceny nowego (x-kom, PLAN_OCENY §12a), (f) progi dobrać na `alert-outcomes` / `sniper.bench`
  (złoty zbiór nie może stracić prawdziwej okazji iPhone 14 Pro 850 zł).
* **2026-10-30 (wieczór) – poprawki po uwagach użytkownika.** Kilka proxy prościej: zamiast `SNIPER_PROXY_ROUTES`
  numerowane `SNIPER_PROXY_2_HOST` / `_AUTH` / `_KATEGORIE` (także po polsku: telefony, konsole…) / `_POLL`, 2..9.
  Przyspieszanie dotyczy tylko kategorii z przepełnioną stroną (wysyp telefonów nie przyspiesza RAM-u): dodatkowe
  skany tego katalogu co `SNIPER_POLL_MIN` (minimalny odstęp jednego proxy, domyślnie 3 s; zastępuje `SNIPER_POLL_FAST`).
  Laptopy bez danych rynku też najwyżej 7 (zwolnienie usunięte – watch zbiera laptopy od 300 zł). Wysyłka: była
  już w koszcie (`shipping_details` → zł), ale kursy stałe – teraz `sniper/fx.py` z pliku prebid, którego używa
  Vinted (adres od użytkownika; co 12 h, bez proxy, podejrzane kursy odrzucane), a brak `shipping_details` = jedna
  ponowna próba, potem ocena ≤ 7 z flagą. `szafa-test` u użytkownika nie ruszył – uruchomiony w starym folderze
  `category_analyzer` (stary kod i stary `.env` z błędami parsowania); trzeba w `analyse_data`.
* **2026-10-31 – szafa i tempo Snipera.** `szafa-test --limit 50` (nowa wersja, sesja odświeżona po 401): próbka
  wzięła same `unlisted` → 46/50 dalej aktywne w szafie (= dziury w pokryciu przejścia, nie zniknięcia), 4 brak;
  strona szafy ~97 KB (nie ~8 KB) – szafa w resolverze byłaby droga. Wcześniejsze „konta usunięte” użytkownika =
  sprawdzanie /member/<numer OFERTY> (pomyłka), nie dowód. `szafa-test --stany` (domyślnie deleted) – właściwe
  pytanie o 5% sprzedanych. Sniper (prośba): bez dociągania strony 2; przepełnienie = odstęp tej kategorii krótszy o
  `SNIPER_POLL_STEP` (3 s) od zwykłego, najwyżej do `SNIPER_POLL_MIN`; po `SNIPER_FAST_MINUTES` spokoju o krok dłuższy.
  Kredyty Gemini wyczerpane (402 w auto) – Sniper bez oceny AI do doładowania.
