# STAN PROJEKTU – punkt startowy nowej rozmowy (2026-11-07)

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
3. Testy (bez sieci): tu `python -m pytest analyzer/tests -q` (281), w `unreachable_sniper`
   `python -m pytest sniper/tests -q` (286 + 1 pominięty). Oba przed każdym pushem.

## Jak odpowiadać użytkownikowi (preferencje – ważne, sprawdzone w rozmowach)

* **Po polsku, krótko, konkretnie.** Najpierw odpowiedź / decyzja („bierz X, bo…”), potem szczegóły. Tabele do
  porównań (oferty, karty, warianty). Bez lania wody i bez powtarzania tego, co już ustalone.
* **Komendy do skopiowania (Ctrl+C / Ctrl+V):** każda komenda w OSOBNYM bloku, **po kolei**, z **pełnymi ścieżkami**
  (`C:\Users\szymo\analyse_data`, `C:\Users\szymo\unreachable_sniper`, baza
  `C:\Users\szymo\category_analyzer\data\analyzer.db`), bez `$`, bez wymyślonych placeholderów, gdy da się podać
  prawdziwą ścieżkę; gdy placeholder konieczny (nazwa pliku z `dir`) – napisz, skąd go wziąć. Windows: cmd (PowerShell
  tylko, gdy trzeba – i powiedz to). Po każdej komendzie: **co powinno się pokazać** i co zrobić, gdy nie.
* **Instrukcje krok po kroku**, numerowane, z punktami kontrolnymi („przyślij mi wynik X”). Użytkownik uczy się
  narzędzi (DB Browser, WizTree, cmd, sterowniki) – rozpisuj kliknięcia, gdy to GUI.
* **SQL dla DB Browser for SQLite** (użytkownik go używa): pełne zapytanie do wklejenia w „Wykonaj SQL”, kolumny po
  polsku, link `https://www.vinted.pl/items/<id>`; uprzedź o fałszywych dopasowaniach (opisy zagraniczne!).
  Wyniki przysyła jako PDF – czytaj je i oceniaj oferty (pułapki: uszkodzone w obcym języku, laptopowe RAM-y).
* **Uczciwie o niepewności**: co sprawdzone (testy na atrapie), czego nie (sprzęt, Vinted na żywo); nie zgaduj
  endpointów Vinted ani parametrów sprzętu – przyznaj się do błędu od razu (np. sterownik 920M = 425.31).
* **Doradztwo zakupowe** (karty, RAM, obudowy, PC): oceniaj konkretne ogłoszenia ze zrzutów, wskazuj ryzyka (opis
  „uszkodzona” po tłumaczeniu, zasilacz, wtyczki, SAS vs SATA, laptopowe kości), dawaj ranking i jedną rekomendację.
* Zmiany w kodzie: od razu z testem, commit + push, w odpowiedzi 1–2 zdania „co zmieniłem” + komendy do wdrożenia
  na serwerze (`git pull` + restart). Nie proś o wklejanie haseł / kluczy do czatu.

## Zrzut stanu (08.11) – co zrobione ostatnio i co dalej

* **Basal (lokalny model decyzyjny jako „bramkarz”)** – plan użytkownika: regex na tytule → basal przy wątpliwościach
  → mediany; **kroki 1–3 gotowe, test v2 przeanalizowany i poprawiony 08.11, czekamy na powtórkę; kroki 4–5 (regexy
  rodzin, kaskada w Sniperze) DOPIERO po akceptacji wyników przez użytkownika.** `BASAL_GPU.md` (instrukcja; §G PC,
  §H serwer 8 GB, §I wyniki 08.11 + komendy powtórki), `analyzer/basal_poc.py`.
  * **v1 (6 rodzin: `s23`, `gtx1060`, `rtx3060`, `ddr4`, `nvme`, `i5`, §F):** 4.5B lepszy od mini w taktowaniu RAM,
    końcówkach i5, liczbie sztuk; gorszy w RTX 3060 (Ti) → dopisek „bez Ti”. Mini szybszy.
  * **v2 (07.11) – cały rynek:** `analyzer/basal_families.py` + `basal_specs.py`, tabela `BASAL_RODZINY.md`.
    173 rodziny (telefony 58, laptopy 33, konsole 22, karty 17, tablety 13, płyty 8, RAM 7, dyski 7, CPU 7,
    zestawy 1), 4152 próbki (24 / rodzinę) + 1083 przypadki testowe (pułapki wariantów, formularza, języka). Rodzina:
    regex tytułu → `model_nav` / platforma z formularza → rodziny zapasowe; warianty z tokenów (słowa marki
    opcjonalne, nakładanie: wygrywa dłuższe / później kończące się). Formularz Vinted podawany basalowi jako
    „bywa błędny”. CLI: `basal-sample --wszystkie`, `basal-test --katalog --etykieta --pomin-gotowe`,
    `basal-raport --katalog --etykieta` (`analyzer/basal_report.py`: T testy / R reguły / P pewne ≥ 70%, lista
    „pewnych błędów”), `basal-rodziny`.
  * **Pułapki formularza z bazy:** ~11% telefonów ma „256/512 MB” w pamięci; „iPad 9” vs formularz „9.7 (2018)”
    (51); „iPhone 17e” vs „17” (30); „MacBook Air 2020” Intel / M1 niejednoznaczne (720); laptopy: RAM w polu dysku
    (367), dysk w polu RAM (359). Zgodność reguł z formularzem: iPhone ~99%, Galaxy S 96–98%; tytuł zna wariant
    w laptopach / tabletach tylko w 34–81% → **tam basal może dać najwięcej**.
  * **Wydajność (PC, GTX 1060 6 GB, 4.5B Q5_K_M, ~4,1 GB VRAM):** ~3,5 s / ofertę; 1 slot (`-np 1`) szybszy niż 4.
    Całość bazy: 201 766 ofert z opisem ≈ 7 dni, 136 098 aktywnych ≈ 4,7 dnia ciągłej pracy.
  * **Wyniki v2 (08.11, `BASAL_GPU.md` §I):** 5236 zapytań w 5,5 h; testy 84% (pewne 92%), ale większość błędów to
    wadliwe przypadki testowe (etykiety grup w tytułach, nieistniejące konfiguracje) - generator przepisany. Na
    prawdziwych ofertach basal przy pewnej rozbieżności z regułą ma rację w ~9 / 10 (stan, model, sztuki). **Stan vs
    płatne `ai-condition` (309 wspólnych ofert): reguła 48% → po poprawce 61%, basal 90% (pewne 95%)**; reguła
    „uszkodzona” na całej bazie zgodna z AI w 23% → basal może zastąpić płatne AI stanu. W trudnej próbce basal
    zmienia grupę cenową ~17% ofert (stan 2%, model 2%, parametry 9% - laptopy 23%, RAM 35% -, sztuki 4%).
    Słabości basala poprawione w pytaniach: „Kupię …” → telefon, liczby z przykładów („8/256” → 8 GB przy „12/256”,
    „2x8 = 16”), procesor spoza listy → najbliższa pozycja, „GTX 1060” → nie wiadomo, nazwa rodziny w treści
    podpowiadała odpowiedź, „cena za sztukę”, Kindle = „inna rzecz” w rodzinie czytników, zbity ekran „mało
    widoczny”. Poprawki reguł: prefiks kart wg producenta (było: GeForce 7600 → RX 7600, Arc A770 → GTX 770), „+”
    osobno ≠ Plus, iPad „9,7"”, MacBook 14" / 16", akcesoria tabletu, „Sprzedam lub zamienię” = sprzedaż; nowe
    `basal-test --tylko-testowe --rodziny`, sekcja „pewne rozbieżności z regułami” w raporcie.
* **`extract.py` v5 (08.11, produkcja):** usterka w zdaniu warunkowym („Jeśli sprzęt będzie uszkodzony - protokół”,
  formułka handlarza), „nigdy nie był uszkodzony”, zaprzeczenia „nu / neturi / nema” i po słowie („defektu nav”),
  „nie włączany” - na całej bazie 1138 ofert mniej oznaczonych jako uszkodzone (telefony 666, konsole 158, laptopy
  124); gdzie jest ocena AI: 1104 z nich sprawne wg AI, 18 uszkodzone (z 2488 łapanych przez regułę). Watch przelicza cechy sam w pierwszym cyklu po aktualizacji.
* **Płatne AI stanu w analizatorze (pytanie użytkownika 08.11 - „analizator nic nie daje płatnemu AI”):** daje -
  `ai-condition` (Gemini 3.8 Flash, klucz `SNIPER_AI_API_KEY`): 25.10 ręcznie 8696 ofert ze zdjęciami (~$25), potem
  automat w `watch` (`auto.py` krok 2: nowe oferty ze wzmianką o usterce, do 3000 na automat, od 31.10 sam opis,
  ~$0,2-0,7 na raz) - razem 13 786 ocen, ~$33 (szacunek z tokenów). Wynik: `analysis.db: ai_condition`, `report`
  bierze stąd stan zamiast z reguł. Od 08.11 `ANALYZER_AUTO_AI_LIMIT=0` wyłącza (wcześniej 0 = bez limitu!).
  Basal (stan zgodny z tym AI w 90-95%) może to zastąpić za darmo.
* **Sniper – tryb polowania na kartę pod basala** (`unreachable_sniper` 80ec482): `SNIPER_HUNT_FOR_GPU=true`,
  `SNIPER_HUNT_FILE` (domyślnie `sniper/hunt_for_basal.md`, 13 celów: RTX 2060 12 GB … 3060 12 GB / 3060 Ti /
  3070 / 3080 / 4060 (Ti) / 4070+ ≤ 400–500 zł); każda nowa oferta przed filtrami i AI, trafienie = ntfy priorytet 5
  + `logs/hunt.jsonl`; pomija uszkodzone / części / laptopy / „kupię”. 290 testów Snipera.
* **Sprzęt – decyzja odłożona (rada 08.11: nic nie kupować przed wynikami v2).** RX 580 8 GB ≈ GTX 1060 (Vulkan,
  na Windows ryzyko sterownika); lepsza wartość z bazy: GTX 1080 Ti 11 GB ~500 zł (szac. 2–2,5× szybciej), GTX 1070
  ~400 zł. Do czyszczenia median wystarczy wsadowy basal na obecnym PC (noc / weekend); karta na serwer ma sens
  dopiero dla basala w czasie rzeczywistym w Sniperze (wymaga też RAM + obudowy). Serwer docelowo: stacja robocza
  (MSI Z270, i5-7400, 8 GB DDR4, zasilacz 1000 W) z Ubuntu Server 24.04; laptop-serwer (920M Kepler) odpada dla GPU.
  Zdjęcia: `data\photos` ~292 GB → plan HDD 8 TB (`ANALYZER_PHOTOS_DIR`); `photos-clean` usuwa tylko `deleted`.
* **Wcześniej (01–07.11):** Sniper – padnięte proxy nie blokuje innych, mediany szczegółowe (stan, 5G/LTE, kod
  modelu, RAM) po fałszywej okazji Samsung A17; analizator – `comparables.db` ze stanem, ekstrakcja v4,
  `photos-clean`, ntfy o padniętym proxy w watch, test basala.
* **Co dalej (kolejność):**
  1. ~~Wyniki v2 → analiza → poprawki~~ (zrobione 08.11). **Powtórka na PC z poprawkami** (`BASAL_GPU.md` §I:
     `--etykieta 45b_t2 --tylko-testowe` ~1 h, potem `45b_v3` całość ~5 h) → sprawdzić, czy poprawki działają
     (testy, pewne rozbieżności z regułami), następna runda poprawek.
  2. Lista zaufania bramkarza: per rodzina i pytanie, gdzie pewne odpowiedzi ≥ 95% trafne (testy + rozbieżności
     przejrzane ręcznie) - tam basal nadpisuje regułę, gdzie indziej tylko uzupełnia.
  3. **Wpływ na mediany:** `basal-batch` (do napisania) - basal wsadowo na PC po wybranych ofertach z kopii bazy
     (najpierw reguła „uszkodzona” ~9,8 tys. ≈ 9-10 h, potem laptopy / tablety z wariantem tylko w opisie), wynik do
     `analysis.db` jak `ai-condition` → mediany przed / po per rodzina. Zastępuje płatne `ai-condition`.
  4. Kroki 4–5 planu (regexy rodzin + kaskada regex → basal → mediany w Sniperze) – po akceptacji użytkownika.
  5. Sprzęt: karta dopiero, gdy basal ma działać w czasie rzeczywistym w Sniperze (wsadowo wystarcza GTX 1060).
  6. Przeprowadzka serwera na Linuksa (unity systemd dla llama-server / basal-serve / Snipera / watch), 4.5B Q8_0
     na karcie 8 GB (§H). Ew. zmniejszanie zdjęć (1024 px, JPEG q80) – nierozstrzygnięte.

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

* **Analizator** (`analyse_data/analyzer/`) – cały rynek 10 katalogów Vinted (laptopy, telefony, tablety, konsole +
  od 31.10 podzespoły z własnych katalogów: RAM 3603, dyski 3607, karty 3602, procesory 3599, płyty 3600, zestawy
  3601; ogólne 3582/3583/3584 wycofane) → SQLite; ceny, sprzedaże, relisty,
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
300 zł, przeplot wagami; osobna pętla i sesja na każde proxy (`SNIPER_PROXY_<N>_KATEGORIE`); na stronie 1 brak każdej
z 5 ofert poprzedniego skanu = przepełnienie → ta kategoria o `SNIPER_POLL_STEP` s częściej, do `SNIPER_POLL_MIN`) →
nowe ID → sidebar + shipping (proxy) → `Offer` (kategoria z katalogu; wysyłka z waluty sprzedawcy `FX_TO_PLN`) →
`submit`: **`route`** (31.10: wiersze tabeli dla TEJ oferty – model + warianty, z opisu, rodzina / marka; oferta
z innej kategorii w tytule, np. iPad w telefonach, dostaje kategorię z tytułu) → już widziana → słowa wykluczone →
**bramka** (koszt > max zakup z tabeli × 1,25; koszt > max zakup wg reguły zysku przy wycenie = szacunek podobnych
× 1,2; tryb mediany bez żadnej mediany – AI i tak dałoby ≤ 3) → dzienny limit $ → **AI dwuetapowo**: szybka ocena
(myślenie low, zdjęcia medium), pełna (myślenie medium, zdjęcia domyślne) tylko dla okazji / ≥ 6; w zapytaniu:
stała legenda tabeli (instrukcja systemowa) + wiersze rodziny + mediany z `comparables.db` (tryb `mediany`; laptopy
zwykłym trybem z podobnymi ofertami) + 6 zdjęć → **program**: `enforce_profit_rule` (przelicza zysk/marżę, przycina
wartość > szacunek × 1,2, spełniona reguła → ocena ≥ 8), `cheap_guard` (koszt < 45% wartości: konto bez opinii →
nie okazja, inaczej ≤ 7), PL +1 → `evaluations.jsonl/.csv` (`stage` 1/2 / 2/2), `oceny.html` (+ kopia na Dysk
`SNIPER_MIRROR_DIR`), ntfy (`SNIPER_NTFY_MIN_SCORE`), mail.

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
  `SNIPER_AI_EFFORT=medium` (pełna ocena), od 31.10 wiersze rodziny zamiast pełnych wytycznych (niżej),
  `SNIPER_AI_MAX_CONCURRENT=10`.
  Koszt ~$0,014–0,016 za ocenioną ofertę (po bramce). Tańsze modele (3.5 / 3.1 Flash Lite) halucynują okazje
  („Steam Deck OLED 256 GB” 9/10) – odrzucone; `gemini-2.5-flash-lite` = 404 dla nowych kont.
* Skan (propozycja dla użytkownika, nie wiadomo, czy wpisał): `SNIPER_CATALOG_WEIGHTS=phone:4,console:4,laptop:1,
  tablet:1`, `SNIPER_POLL_INTERVAL=7`, `SNIPER_PER_PAGE=6` („/N!” w heartbeat = N przepełnień strony).
* Kilka proxy / przyspieszanie (30.10, użytkownik kupuje 2 proxy residential): `SNIPER_PROXY_2_HOST/_AUTH/
  _KATEGORIE/_POLL` (numery 2..9); `SNIPER_OVERLAP_IDS=5`, `SNIPER_POLL_STEP=3`, `SNIPER_POLL_MIN=3`,
  `SNIPER_FAST_MINUTES=10`; kursy walut na żywo (`sniper/fx.py`, `SNIPER_FX_REFRESH_H=12`); brak `shipping_details`
  = ocena ≤ 7; laptopy bez danych też ≤ 7 (bez zwolnienia). Automat (mediany) co 2 dni (`ANALYZER_AUTO_DAYS=2`).
* Koszty AI (31.10, domyślne): `SNIPER_AI_GUIDE_ROWS=rodzina`, `SNIPER_AI_TWO_STAGE=true`
  (`SNIPER_AI_QUICK_EFFORT=low`, `SNIPER_AI_QUICK_MEDIA_RESOLUTION=medium`, `SNIPER_AI_CONFIRM_FROM=6`),
  `SNIPER_AI_SKIP_NO_DATA=true`; analizator `ANALYZER_AUTO_AI_PHOTOS=0` (AI stanu bez zdjęć). `SNIPER_CATEGORIES`
  musi zawierać `cpu,motherboard,bundle` (albo być puste), żeby Sniper skanował nowe katalogi podzespołów.
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

* **Laptopy po specyfikacji (01.11, pomysł użytkownika):** mediany laptopów po karcie / procesorze + generacji / RAM /
  dysku / MacBooku (tabela `laptop_specs` w `comparables.db`, `sniper/specs.py` = te same reguły co
  `analyzer/extract.py`, test `SPEC_PARITY` w obu repo), nie po słowach tytułu. Specyfikacja z tekstu w 52% ofert
  z opisem (próbka bazy); resztę AI odczytuje w szybkim etapie (opis / zdjęcia / numer modelu) → mediany dla niej →
  pełna ocena (czerwona flaga „specyfikację rozpoznało AI”). Laptop bez żadnej specyfikacji → bez danych (≤ 3), jak
  inne kategorie. Ekstrakcja v3: i5-1135G7 (końcówki G1/G7), „MacBook Air M3 16GB”, RAM po RO/HU/DE, „16GB 512GB”.
* **Tańsze modele (01.11, research):** Claude Haiku 5.5 $0,10 / $0,50 za 1 mln tokenów (≤ 100 tys. w zapytaniu) vs
  Gemini 3.8 Flash $0,75 / $3,75 (od 2027 r. $1,50 / $7,50); Sniper i analizator obsługują Anthropic. Do sprawdzenia
  benchem (`--warianty haiku55,haiku55_low --ref zapisane`) przed przełączeniem; opcja hybrydy: szybki etap na Haiku
  (`SNIPER_AI_QUICK_PROVIDER/_MODEL`), pełna ocena okazji na Gemini.
* **Proxy w watch (07.11):** `analyzer/proxy_health.py` - licznik błędów połączenia z rzędu na całej sesji
  (katalog, szczegóły, resolver, odświeżanie sesji); ntfy „Analyzer: proxy nie działa” po
  `ANALYZER_PROXY_ALERT_AFTER` (20, przy 407 po 3), przypomnienie co 6 h, „proxy znów działa” po pierwszej odpowiedzi.
  Watch nie wysyła ruchu bez proxy (`require_proxy_url`, brak obejścia przy awarii).
* **Miejsce na dysku (07.11, WizTree u użytkownika):** archiwum zdjęć `data\photos` = 278,8 GB z 345 GB zajętych
  (476 GB dysk). Nowa komenda `python -m analyzer photos-clean [--stan deleted] [--starsze-niz 14] [--tak]` -
  usuwa zdjęcia ofert usuniętych od ≥ N dni (+ wpis w `photos/index.db`), najpierw pokazuje GB i pyta; sprzedane
  zostają; `unlisted` (żywe dla watch) dostają wpis „cleaned” - bez ponownego pobierania. Archiwum od 27.10:
  active 227 GB, unlisted 38, deleted 17,5, gone_pending 3,8, hidden 3,1, below_min 1,7, sold 0,7 GB. Plan: serwer na stację roboczą (i5-7400, 8 GB DDR4, MSI Z270, zasilacz 1000 W) z Ubuntu Server, dysk
  512 GB z laptopa; basal najpierw na Intel HD 630 (Vulkan), potem ew. RX 570 8 GB (Linux/RADV - na Windows
  sterownik AMD dla Polarisa ryzykowny, `VK_ERROR_DEVICE_LOST`).
* **Mediany szczegółowe (03.11, fałszywa okazja Samsung A17 za 377 zł, rynek używanych ~450–550 zł):** stare
  mediany mieszały nowe z metką (80% ofert A17, ~700 zł), wersję 5G z 4G, „A17” z każdym Samsungiem z „17” (litera
  „a” odpadała) i dawały AI poziom „cała rodzina samsung” (~830 zł). Teraz: `comparables.db` ma stan (`cond` new /
  used) - używane porównywane z używanymi; kod modelu jako fraza („a 17”, „rtx 3050”, „ddr 4”, przy podzespołach
  tylko przedrostki układów); 5G (telefon) i LTE / cellular (tablet) jako wariant - oferta bez 5G w tytule nie
  dostaje cen 5G, z 5G przy braku danych dostaje wszystkie wersje (ostrożniej); RAM („8/256”, „8 GB RAM”); poziom
  „każda pojemność” tylko z pojemnościami ≤ oferty; poziomów bez numeru modelu i „cała rodzina” już nie ma (zamiast:
  „ten sam model, pozostałe słowa dowolne”). Tabela wytycznych: wiersze nowych osobno („… (nowe)”, używana oferta
  ich nie widzi ani w bramce), telefony / tablety z 5G / LTE w nazwie grupy (ekstrakcja v4; „4 GB” w polu pamięci =
  RAM, pomijane). AI: wariant niepodany = najtańszy możliwy (reguła D). Symulacja na kopii bazy (31.10): A17 →
  „za drogo wg podobnych ofert” (wycena ~500 zł, max zakup 253 zł); najwyższa wycena z median spada: telefony ×0,73,
  tablety ×0,84, konsole ×0,94, karty ×0,62 (mediana), oferty bez żadnej mediany ≈ te, które dawniej miały tylko
  poziom ogólny. **Mniej alertów, ale bez okazji wyliczonych z cen nowych / innego modelu.**
* **Przestoje skanu (01.11, log `sniper.log`):** Dell Latitude 5320 złapany 5 min po wystawieniu, bo przez
  ~11 min (20:56–21:07) nie było żadnego skanu: proxy 2 (Evomi, telefony) nie odświeżało sesji (6 prób × timeout,
  407 od proxy), a wspólna przeglądarka była zajęta przez całą serię – inne proxy z 403 czekały. Poprawka: blokada
  przeglądarki tylko na jedną próbę, 407 przerywa wizytę od razu, rosnąca przerwa TYLKO padniętego proxy
  (`SNIPER_REFRESH_BACKOFF_MAX`, `SNIPER_PROXY_AUTH_COOLDOWN`), ntfy „proxy N nie działa / znów działa”,
  `SNIPER_REFRESH_TIMEOUT` 90 → 60. Sam program od wykrycia do pusha: ~25 s. W logu też: `3 ofert/skan` (ciągłe
  przepełnienia → zalecane `SNIPER_PER_PAGE=10`), dwa wpisy tabletów (stary zakres 300-3900 po zmianie catalogs.json dalej co 3 s – naprawione), proxy 5 bez katalogów.
* **Koszty AI 31.10** (HISTORIA B 31.10): Sniper ~1 040 wywołań/dobę × $0,0158 ≈ $16,5/dobę (ponad limit $10) →
  po zmianach (rodziny, dwa etapy, bramka wg reguły, bez AI bez danych) symulacja na bazie: 765/dobę × $0,0081 ≈
  $6,2/dobę (−63%, bez cache). Watch: AI stanu bez zdjęć ~$5 → ~$1 na automat; `classify-ai` znika (czyste katalogi).

## 6. Czekamy od użytkownika (sprawdź, co przyszło; nie ponaglaj)

000. (13.11) **Dziury w pokryciu katalogu**: `status` 13.11 - telefony 71/~200 partycji z brakami, tablety 16/27,
   dyski; w partycji ~100–230 w bazie przy 550–960 wg Vinted (07.11 na kopii: 0 braków). Podejrzenie: od kilku dni
   crawler bierze tylko ~1 stronę partycji (krótkie strony / powtórki / błędy strony 2). Czekamy na: `git pull`,
   `python -m analyzer api-test` (wynik + folder `api_test\<czas>`), SQL `crawl_runs` (ostatnie 40) i
   `findstr "Błąd strony"` / `"[CRAWL] Partycja"` z `analyzer.log`. Od 13.11 watch sam sprawdza API co cykl
   (`analyzer/health.py`, ntfy przy odchyleniu, `ANALYZER_HEALTH_NOTIFY`, `ANALYZER_HEALTH_REPEAT_H`=12) i crawler
   przy krótkiej stronie (total_entries większe) pobiera kolejne, przy powtórce kończy partycję.
   Też 13.11: użytkownik usunął `photos\index.db` - odbudowany `narzedzia/odbuduj_index.py --z-bazy` (267 459 ofert
   widzianych przed 13.11 07:32 = „mają zdjęcia”; część starych bez zdjęć). Zdjęcia zgrane na HDD na drugim PC.

00. (08.11) **Basal v2 - powtórka z poprawkami** (`BASAL_GPU.md` §I): nowy folder `analyse_data` na PC (pendrive
   albo ZIP gałęzi), te same próbki `D:\basal\v2`; najpierw `--etykieta 45b_t2 --tylko-testowe` (~1 h), potem
   `--etykieta 45b_v3` (~5 h), raporty `raport_45b_t2.txt` / `raport_45b_v3.txt` - cały folder na Dysk. Pierwszy
   test (07.11, `45b`) przeanalizowany 08.11 (Zrzut stanu). Na serwerze: `git pull` + restart watch (extract v5).
   Kroki 4–5 dopiero po akceptacji.

0a. (01.11) Wybór modelu AI: wynik `python -m sniper.bench --warianty haiku55,haiku55_low --ref zapisane --bez-bramki
   --last 50` (klucz ANTHROPIC_API_KEY, ~$0,3) - czy Haiku 5.5 trafia jedyną prawdziwą okazję ze złotego zbioru bez
   fałszywych i zgadza się z zapisanymi ocenami Gemini; potem decyzja: całość / szybki etap / zostaje Gemini.
0. (31.10) Po aktualizacji: log startu Snipera (`[AI] … ocena dwuetapowa …`), dzienny koszt z heartbeat
   („dziś ~$…”), kilka linii `[AI] … etap 1/2 | 2/2` i opcjonalnie `python -m sniper.bench --warianty koszty --last 50`
   (jakość przed / po na złotym zbiorze). Pierwsze przejście `watch` nowych katalogów podzespołów → czy
   `catalogs.json` po automacie ma procesory / płyty / zestawy (tylko gdy są opłacalne grupy).

1. `evaluations.csv`/`.jsonl` z serwera – **czemu Xiaomi 12T i Asus dostały alert** (wysłany `oceny.html` był
   identyczny jak z 28.10 → kopia na Dysk (`mirror.py`) albo `report.py` przestała się odświeżać – też do zbadania).
2. (Zamknięte 31.10) Szafa sprzedawcy: 50/50 `deleted` → brak w szafie, strona szafy ~92 KB – nic nie daje
   resolverowi, test usunięty (HISTORIA B 31.10). `seller_id` zostaje (relisty, handlarze).
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
2. Dziury w pokryciu przejścia (`unlisted` 58%; 31.10: 46/50 `unlisted` dalej aktywne w szafie sprzedawcy)
   – sprawdzić `newest_first`, głębokość stron, zakresy cen.
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
| reguła zysku, wytyczne | `analyzer/guide.py`, `sniper/evaluator.py`, `sniper/guides.py` (`route` – rodziny wierszy, `rules_text`), `sniper/guidelines.md` (laptopy, ręczne) |
| koszty AI (rodziny, dwa etapy, bramka, bez danych) | `sniper/guides.py`, `sniper/evaluator.py` (`gate`, `no_data_reason`, `_staged`), `sniper/tests/test_cost.py` |
| laptopy po specyfikacji | `sniper/specs.py`, `sniper/comparables.py: spec_levels`, `sniper/evaluator.py: spec_mode / _refresh_spec_levels`, `sniper/experiment.py: LAPTOP_TASK`, `analyzer/comparables.py: laptop_spec`, `analyzer/extract.py` (v3) |
| mediany / podobne oferty | `analyzer/comparables.py`, `sniper/comparables.py` (`levels`), `sniper/experiment.py` (`MEDIANS_TASK`, `finish_medians`, `cheap_guard`) |
| porównanie wariantów oceny | `sniper/bench.py`, `sniper/bench_golden.json`, `sniper/basal.py` |
| zniknięcia, sprzedaże | `analyzer/resolver.py`, `analyzer/sold_report.py` |
| katalogi, wagi, próg ceny | `sniper/categories.py`, `sniper/scout.py`, `sniper/config.py` |
| rejestr flipów | `analyzer/flips.py` (`flips.csv` obok bazy) |
| sprzęt do testów | `SPRZET_DO_TESTOW.md` (`SNIPER_TEST_HAVE`) |

**Ściąga komend (serwer):**
```bat
cd C:\Users\szymo\analyse_data
python -m analyzer status | sold-report [--od DATA] | flips | sniper-guide | auto --force
python -m analyzer szukaj <kategoria> [słowa] [--max N] | slim-db | report
cd C:\Users\szymo\unreachable_sniper
.venv\Scripts\python -m sniper.bench [--warianty A,B] [--last 50] [--bez-bramki] [--lista]
.venv\Scripts\python -m sniper.report --stats          (podsumowanie evaluations.jsonl)
.venv\Scripts\python -m sniper.evaluator --last 20 [--compare]
```
