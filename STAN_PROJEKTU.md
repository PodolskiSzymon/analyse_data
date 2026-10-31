# STAN PROJEKTU – punkt startowy nowej rozmowy (2026-10-30, wieczór)

> **„wykonaj md” = przeczytaj CAŁY ten plik i działaj wg §6–§7.** `CLAUDE.md` wczytuje się sam. Innych plików nie
> czytaj na zapas – mapa w §9 mówi, co otworzyć przy danym temacie. Archiwum decyzji z liczbami: `HISTORIA.md`
> (tylko `grep` po dacie/temacie). Plan docelowy oceny: `PLAN_OCENY.md` (czytaj przy F1+).

## Start sesji (technicznie)

1. Drugie repo: `add_repo` (owner `PodolskiSzymon`, repo `unreachable_sniper`, access `push`) → sklonuj do
   `/home/user/unreachable_sniper` → `register_repo_root`.
2. Gałąź w OBU repo: cała praca jest na `claude/gifted-volta-x1764p` (od 30.10; wcześniej `claude/magical-bell-vdwpt1`,
   `main` stary). Jeśli sesja ma inną gałąź:
   `git fetch origin claude/gifted-volta-x1764p && git checkout -B <gałąź sesji> origin/claude/gifted-volta-x1764p`
   i powiedz użytkownikowi nową nazwę – na serwerze: `git fetch origin <gałąź> && git checkout <gałąź>` w obu repo
   (potem `git pull origin <gałąź>`).
3. Testy (bez sieci): tu `python -m pytest analyzer/tests -q` (258), w `unreachable_sniper`
   `python -m pytest sniper/tests -q` (245 + 1 pominięty). Oba przed każdym pushem.

## 0. Dane użytkownika (Claude nie ma dostępu do Vinted ani bazy)

* Użytkownik wrzuca na Dysk Google pełną bazę (`analyzer_full.db` z `VACUUM INTO`, ~1,4 GB, z tabelą `raw`) +
  `analysis.db` albo lekką (`python -m analyzer slim-db` → ZIP) i daje linki „każdy z linkiem”. Pobieranie TYLKO do
  scratchpadu: `curl -L -o plik "https://drive.usercontent.google.com/download?id=<ID>&export=download&confirm=t"`,
  otwierać `file:…?mode=ro`. Wymaga dozwolonych domen `drive.google.com`, `drive.usercontent.google.com` (inaczej
  403 – poproś o zmianę ustawień środowiska, NIE zgaduj wyników). Ostatnia migawka: 27.10 ~10:10.
* Logi Snipera (`evaluations.jsonl/.csv`, `oceny.html`, `sniper.log`) i `watch.log` użytkownik wysyła w czacie.
* Remote Control na serwer nie zadziała (Windows – narzędzie obsługuje tylko Mac/Linux).
* Zastrzeżenia do danych: `deleted` ≠ sprzedaż; sprzedaże przed 24.10 niepełne; cena = ostatnia cena wystawienia
  (górna granica, jest „Zaproponuj cenę”); laptopy w bazie dopiero od 700 zł (`ANALYZER_PRICE_MIN_3580`).

## 1. Cel

Użytkownik (Szymon, po polsku) flipuje elektronikę na Vinted: kupuje tylko najlepsze okazje, sprzedaje w ≤ 7 dni,
ograniczony kapitał i czas. Kupuje głównie od Polaków (szybka dostawa), sprzedaje głównie zagranicznym (Podbicie
międzynarodowe), wystawia drożej i schodzi „o kilka set zł”. **Twoje zadanie: rozwijać oba programy** (nie dopytywać
o jego prywatne zakupy/flipy; trzymać się jego planu testów, nie wybiegać naprzód).

* **Analizator** (`analyse_data/analyzer/`) – cały rynek 7 kategorii Vinted → SQLite; ceny, sprzedaże, relisty,
  oszustwa; generuje **wytyczne** dla Snipera (`guides/<kat>.md`, `catalogs.json`, `comparables.db`).
* **Sniper** (`unreachable_sniper/sniper/`) – co kilka sekund nowe oferty → ocena AI (Gemini) → ntfy + mail.
  Auto-zakup istnieje, ale **wyłączony na stałe** (Vinted wylogowuje bota; nie obchodzić wykrywania).
* **Pilot** (`analyzer/remote.py`, `remote.bat`, `PILOT.md`) – ntfy z telefonu: `status`, `start|stop|restart
  watch|sniper|all`, `log watch|sniper`, `wytyczne`, `oceny`, `pomoc`.

Serwer: Windows, i5-5200U, **4 GB RAM**, Python 3.12, `cmd`. Ścieżki: `C:\Users\szymo\analyse_data`,
`C:\Users\szymo\unreachable_sniper` (venv `.venv`), baza `C:\Users\szymo\category_analyzer\data\analyzer.db`
(`ANALYZER_DB`), logi pilota `…\data\remote\{watch,sniper}.log`, logi Snipera `unreachable_sniper\sniper\logs\`.
**Dwa `.env`**: `unreachable_sniper\sniper\.env` (Sniper; zmiana + `restart sniper`) i `analyse_data\sniper\.env`
(analizator + pilot; zmiana = ponowne `remote.bat`). Wzór obu: `ENV_SERWER.example`. Proxy: Evomi + IPRoyal razem
~25 GB (analizator ~0,5 GB/dobę); AI/zdjęcia/ntfy bez proxy.

## 2. Jak to działa (przepływ)

**`watch` (analizator):** przejście katalogów (~3,1 h, ~85 MB proxy) → `resolve(only="fresh")` świeżych zniknięć
(`/api/v2/items/{id}/services`: sprzedana / zarezerwowana / żyje; 404/104 = `gone_404`, `deleted` dopiero po drugim
404 w kolejnym cyklu) → log „Cykl: zniknięć N, pewnych sprzedaży X (%), ≤ 24 h %, mediana zwłoki” → `auto` (co 2
dni, też zaraz po restarcie: flagi, relisty, AI stanu, raport, `sniper-guide` → kopia do Snipera) → do następnego
startu (5–7 h) równolegle: ponowne sprawdzenia (`only="due"`), szczegóły ofert, zdjęcia. Od 29.10 zapisuje
`listings.seller_id` (migracja v12).

**Sniper – jedna oferta:** skan katalogów (`SNIPER_CATALOGS=auto` → `catalogs.json`, każdy od `SNIPER_PRICE_FLOOR`
300 zł, przeplot wagami; od 30.10 osobna pętla i sesja na każde proxy (`SNIPER_PROXY_<N>_KATEGORIE`); na stronie 1
brak każdej z 5 ofert poprzedniego skanu = przepełnienie → ta kategoria o `SNIPER_POLL_STEP` s częściej, do `SNIPER_POLL_MIN`) → nowe ID → sidebar + shipping (proxy) → `Offer` (kategoria z katalogu/tytułu; wysyłka
przeliczona z waluty sprzedawcy `FX_TO_PLN`; kraj z waluty wysyłki, EUR = nieznany) → `submit`: już widziana →
słowa wykluczone → **bramka** (koszt > max zakup z tabeli × 1,25 albo „za drogo” wg podobnych ofert – odcina ~70%)
→ dzienny limit $ → **AI w trybie `mediany`**: kilka median z `comparables.db` (od dokładnej do rodziny) + karta
rynku + pełne wytyczne kategorii + 6 zdjęć → AI wycenia sama, może poprawić model; laptopy oceniane zwykłym trybem →
**program**: `enforce_profit_rule` (przelicza zysk/marżę, przycina wartość > szacunek × 1,2, spełniona reguła →
ocena ≥ 8), `cheap_guard` (koszt < 45% wartości: konto bez opinii → nie okazja, inaczej ≤ 7), PL +1 → 
`evaluations.jsonl/.csv`, `oceny.html` (+ kopia na Dysk `SNIPER_MIRROR_DIR`), ntfy (`SNIPER_NTFY_MIN_SCORE`), mail.

## 3. Reguły biznesowe (aktualne, 28.10)

* Koszt zakupu K = cena + wysyłka (zł) + 5% + 2,90 zł. Koszty sprzedaży 46 zł (Podbicie ~26 + wysyłka ~20).
* Zysk P = S − K − 46, marża M = P / S. **Okazja: P ≥ 300 zł i M ≥ ~28% (S ≤ 1 000 zł) liniowo do ~25% (S ≥ 2 500)**
  → ocena ≥ 8; 9 = M ~35%+ albo P ~600+; 10 = M ≥ 45% i P ≥ 800. Polska +1. Uszkodzone / blokady – nigdy okazja.
  Brak ładowarki → minus koszt zamiennika. Przy 8+ kupować od razu (ochrona kupującego 2 dni od dostawy).
* Kod (zmieniać razem): `analyzer/guide.py: min_margin / max_buy / meets_rule`, `sniper/evaluator.py:
  rule_min_margin / rule_max_buy / enforce_profit_rule / SYSTEM_PROMPT`, `sniper/experiment.py: formula_score`,
  `.env` `SNIPER_RULE_*`.

## 4. Ustawienia produkcyjne (decyzje 29.10)

* Ocena: `SNIPER_EVAL_MODE=mediany`, `SNIPER_AI_MODEL=gemini-3.8-flash`, `SNIPER_AI_MAX_PHOTOS=6`,
  `SNIPER_AI_EFFORT=medium`, pełne wytyczne (`SNIPER_AI_GUIDE_ROWS=wszystkie`), `SNIPER_AI_MAX_CONCURRENT=10`.
  Koszt ~$0,014–0,016 za ocenioną ofertę (po bramce). Tańsze modele (3.5 / 3.1 Flash Lite) halucynują okazje
  („Steam Deck OLED 256 GB” 9/10) – odrzucone; `gemini-2.5-flash-lite` = 404 dla nowych kont.
* Skan (propozycja dla użytkownika, nie wiadomo, czy wpisał): `SNIPER_CATALOG_WEIGHTS=phone:4,console:4,laptop:1,
  tablet:1`, `SNIPER_POLL_INTERVAL=7`, `SNIPER_PER_PAGE=6` („/N!” w heartbeat = N przepełnień strony).
* Kilka proxy / przyspieszanie (30.10, użytkownik kupuje 2 proxy residential): `SNIPER_PROXY_2_HOST/_AUTH/
  _KATEGORIE/_POLL` (numery 2..9); `SNIPER_OVERLAP_IDS=5`, `SNIPER_POLL_STEP=3`, `SNIPER_POLL_MIN=3`,
  `SNIPER_FAST_MINUTES=10`; kursy walut na żywo (`sniper/fx.py`, `SNIPER_FX_REFRESH_H=12`); brak `shipping_details`
  = ocena ≤ 7; laptopy bez danych też ≤ 7 (bez zwolnienia). Automat (mediany) co 2 dni (`ANALYZER_AUTO_DAYS=2`).
* `watch`: `ANALYZER_WATCH_HOURS=5-7`, `ANALYZER_GONE_AFTER_RUNS=1`, `ANALYZER_RESOLVE_DELAY_S=1-2.5`,
  `ANALYZER_CONFIRM_404=2`. Do decyzji: `ANALYZER_PRICE_MIN_3580=300` (dziś brak danych o laptopach < 700 zł, a
  Sniper je ocenia).
* Sniper był wyłączany „bo nie działa dobrze”; 29.10 znów chodził (z alertów kupione 4 rzeczy, §5).

## 5. Najważniejsze wyniki z danych (szczegóły: `HISTORIA.md` część B)

* **Dni testowe 28–29.10** (`sniper.bench`, 68 ofert = 50 ostatnich + złoty zbiór, bez bramki): `mediany` +
  3.8 Flash + 6 zdjęć = jedyna okazja to prawdziwa (iPhone 14 Pro 850 zł), 0 fałszywych; `model` (AI rozpoznaje,
  program wycenia po słowach tytułu) tańszy o ~20%, ale fałszywe okazje (iPad 2 jako „iPad 3 16 GB”, Galaxy A25
  1 222 zł, oszustwo iPhone 16 za 800 zł). Zdjęcia 3 vs 6 = ~0,2 centa różnicy; koszt to głównie tekst (pełna tabela
  wytycznych ~4–5 tys. tokenów) i wyjście z myśleniem. Złoty zbiór: `unreachable_sniper/sniper/bench_golden.json`
  (23 oferty, 1 prawdziwa okazja).
* **Stary Sniper (przed 27.10)**: AI zmyślało ceny retro (Wii 600–760 zł, GBC 850) → fałszywe 9–10/10; brak
  `comparables.db` u użytkownika do 27.10 = bramka nie działała; wysyłka 799 HUF liczona jako 799 zł; premia PL nie
  działała nigdy (kraj pusty). Wszystko naprawione 27.10.
* **`watch`**: przed 27.10 zniknięcia sprawdzane ≤ 24 h tylko w 5% (resolver blokował cykl, przerwy 16–21 h). Po
  przebudowie 1. cykl (28.10): zniknięć 761, pewnych sprzedaży 35 (4,6%), ≤ 24 h 99,5%, mediana zwłoki 11,3 h.
  Udział sprzedaży dalej niski ⇒ większość zniknięć to usunięcia/relisty (albo fałszywe 404 – mierzymy). 1 508 z
  2 620 „zniknięć” to oferty żywe (`unlisted`, przejście ich nie zobaczyło) ⇒ dziury w pokryciu przejścia.
* `comparables.db` z prawdziwej bazy: 166 tys. ofert, 18 MB, ~3 s, ~50 MB RAM. Znany błąd dopasowania słów: liczby
  dziesiętne („10.2” → „10”, „2”) mieszają iPad 2 z iPadem 10.2 – rozwiąże taksonomia (F1).
* Zakupy z alertów: 26.10 7 szt. ~2 650 zł (2× Wii, Wii, iPhone 12, Galaxy A17, Tab A 10.1, iPad Air 4 – anulowany);
  29.10 4 szt.: HP ProBook 440 G9 i3-12/16/256 PL (koszt ~645 → sprzedaż ~1 000–1 100, najlepszy), iPad mini 6 64 RO
  (~982 → 1 300–1 400, na styk), **Xiaomi 12T 256 HR (~391 → 550–600, zysk ~110–160 – reguła NIE spełniona)**,
  **Asus Laptop 15 i3-10 gen 10/500 RO (~457 → 750–850, brak danych < 700 zł)**. `flips.csv` pusty.

## 6. Czekamy od użytkownika (sprawdź, co przyszło; nie ponaglaj)

1. `evaluations.csv`/`.jsonl` z serwera – **czemu Xiaomi 12T i Asus dostały alert** (wysłany `oceny.html` był
   identyczny jak z 28.10 → kopia na Dysk (`mirror.py`) albo `report.py` przestała się odświeżać – też do zbadania).
2. Wynik `python -m analyzer szafa-test` (po ~1 dniu zbierania `seller_id`) – czy sprzedane oferty są w szafie
   sprzedawcy (`www.vinted.pl/api/v2/wardrobe/{seller_id}/items`, ~8 KB/stronę; niepotwierdzone).
3. Linie `[RESOLVE] Wynik` z `watch.log` – ile „fałszywych 404” (404 → potem 200).
4. Po 2–3 dniach nowego `watch`: `python -m analyzer sold-report --od 2026-10-28` (cel ≥ 90% zniknięć ≤ 24 h).
5. Decyzja `ANALYZER_PRICE_MIN_3580=300`; czy wpisał ustawienia §4; dzienny koszt AI (`log sniper` → „dziś ~$…”).
6. Po zakupie proxy: wpisy `SNIPER_PROXY_2_*` itd. (§4) + log startu Snipera (`[SCOUT] proxy …: skan co …`)
   i heartbeat `Proxy (tempo skanu)` / `traffic_<nazwa>.csv` – błędy, 403/429, transfer na proxy.
7. Decyzja w sprawie propozycji „brak danych w medianach” (HISTORIA B, 30.10: klasy pewności, druga próba po
   modelu z AI, laptopy 300–700 zł) – kodu jeszcze nie ma, na prośbę użytkownika.
8. (Opcjonalnie) serwer basal do testu trybu `basal`: `basal-serve --model Remek/basal-2.0-mini --mode eager
   --device cpu --port 8000`, potem `python -m sniper.bench --warianty bas_38_z6 --last 50 --bez-bramki`
   (`sniper/basal.py` napisany wg dokumentacji, nigdy nie uruchomiony na żywo).

## 7. Następne kroki rozwoju (priorytet)

1. Po (1): znaleźć, którędy alert przeszedł mimo niespełnionej reguły / braku danych (ścieżka `evaluate` → `_finish`
   → `push.notify_deal`, tryb laptopów zwykły, `cap_without_market_data` – laptopy wyjątek) i naprawić z testem.
2. Po (2)/(3): szafa w resolverze tylko tam, gdzie się opłaca (np. `deleted` w ważnych grupach); dziury w pokryciu
   przejścia (`unlisted` 58%) – sprawdzić `newest_first`, głębokość stron, zakresy cen.
3. **F4 `alert-outcomes`** (PLAN_OCENY §8.2): co stało się z ofertami z alertów (sprzedana? po ilu godzinach? za
   ile wg bazy) – automatyczna miara trafności bez pracy użytkownika; potem `backtest`.
4. Dane o tanich laptopach (próg 300 zł) – Sniper ocenia laptopy 300–700 zł bez danych.
5. **F1 taksonomia** (konsole → telefony → tablety; PLAN_OCENY §5) – usuwa kruche dopasowanie słów; potem F2
   `prices.json` z prawdziwych sprzedaży (≥ 2–4 tyg. ciągłego `watch`, ~21.11).
6. Pomysły: link w ntfy prowadzący prosto do zakupu (szybkość ręcznego kupna); grupy mieszane ⚠ w wytycznych
   (PS5 disc/digital/slim, DDR5 1×/2× kość); handlarze z `seller_hash`/`seller_id` (relisty, mediany).

## 8. Pułapki

* `analyse_data/sniper/` to STARA kopia Snipera, z której analizator bierze sesję/config. Zmiany Snipera →
  `unreachable_sniper/sniper/`.
* Tokenizacja tytułów musi być identyczna: `analyzer/comparables.py` ↔ `sniper/comparables.py` + `sniper/guides.py:
  tokens` (litery Unicode `[^\W\d_]+|\d+`).
* Gemini 3 → `thinking_level`, Gemini 2.x → `thinking_budget` (`evaluator.thinking_config`). Ceny modeli w
  `sniper/config.py: MODEL_PRICES` (brak wpisu = koszt 0 i limit dzienny nie działa).
* Strony/`services` ofert Vinted potrafią chwilowo dawać 404 (użytkownik: 5× 404, za 6. razem OK).
* Zapytania do Vinted tylko z prawdziwego ruchu przeglądarki (cURL z F12) – bez zgadywania endpointów; budżet proxy.
* Komendy dla serwera: lekkie (SQL z agregacją, strumieniowo), z postępem, krótki wynik do wklejenia.
* Okno `cmd` z „Wybierz” w tytule = QuickEdit wstrzymał program (Esc).

## 9. Mapa (otwieraj przy temacie)

| temat | plik |
|---|---|
| plan docelowy oceny (taksonomia, ceny S7, AI tylko rozpoznaje) | `PLAN_OCENY.md` |
| historia decyzji i wyniki z liczbami | `HISTORIA.md` (A: stan 26–29.10, B: dziennik) |
| zbieranie danych, API Vinted, schemat bazy | `KONTEKST_CATEGORY_ANALYZER.md`, `analyzer/db.py` (v1–v12), `PLAN_ANALIZY.md` |
| Sniper: moduły, API, sesja konta, auto-zakup | `unreachable_sniper/CLAUDE.md` → `sniper/HISTORIA_SNIPERA.md` |
| serwer, pilot, `.env` | `PILOT.md`, `ENV_SERWER.example`, `unreachable_sniper/sniper/.env.example` |
| reguła zysku, wytyczne | `analyzer/guide.py`, `sniper/evaluator.py`, `sniper/guides.py`, `sniper/guidelines.md` (laptopy, ręczne) |
| mediany / podobne oferty | `analyzer/comparables.py`, `sniper/comparables.py` (`levels`), `sniper/experiment.py` (`MEDIANS_TASK`, `finish_medians`, `cheap_guard`) |
| porównanie wariantów oceny | `sniper/bench.py`, `sniper/bench_golden.json`, `sniper/basal.py` |
| zniknięcia, sprzedaże | `analyzer/resolver.py`, `analyzer/sold_report.py`, `analyzer/wardrobe.py` |
| katalogi, wagi, próg ceny | `sniper/categories.py`, `sniper/scout.py`, `sniper/config.py` |
| rejestr flipów | `analyzer/flips.py` (`flips.csv` obok bazy) |
| sprzęt do testów | `SPRZET_DO_TESTOW.md` (`SNIPER_TEST_HAVE`) |

**Ściąga komend (serwer):**
```bat
cd C:\Users\szymo\analyse_data
python -m analyzer status | sold-report [--od DATA] | szafa-test [--limit 20] | flips | sniper-guide | auto --force
python -m analyzer szukaj <kategoria> [słowa] [--max N] | slim-db | report
cd C:\Users\szymo\unreachable_sniper
.venv\Scripts\python -m sniper.bench [--warianty A,B] [--last 50] [--bez-bramki] [--lista]
.venv\Scripts\python -m sniper.report --stats          (podsumowanie evaluations.jsonl)
.venv\Scripts\python -m sniper.evaluator --last 20 [--compare]
```
