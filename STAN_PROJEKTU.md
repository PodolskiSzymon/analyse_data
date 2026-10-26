# STAN PROJEKTU – przekazanie do nowej rozmowy (2026-10-26)

> **Dla Claude w nowej rozmowie („wykonaj md”):** przeczytaj CAŁY ten plik, potem `CLAUDE.md` (zasady),
> a przy pracy nad kodem – pliki wskazane w sekcjach. Repo `unreachable_sniper` NIE jest w tej sesji domyślnie:
> dodaj je narzędziem `add_repo` (owner `PodolskiSzymon`, repo `unreachable_sniper`, dostęp `push`), sklonuj i
> przełącz na gałąź `claude/hopeful-faraday-n33quh`. Potem zacznij od sekcji **8. Do zrobienia** – najpierw zapytaj
> użytkownika o świeże `oceny.html` + `mails.csv` + linię kosztu AI (punkt 8.1), bo od nich zależy kalibracja.

---

## 1. O co chodzi (cel biznesowy)

Użytkownik (Szymon, rozmawiamy **po polsku**) **flipuje elektronikę na Vinted**: kupuje okazje, sprzedaje w ≤ 7 dni.
Ma **ograniczony kapitał i mało czasu** – chce kupować tylko najlepsze okazje i szybko obracać gotówką.
Dwa programy na jego serwerze:

* **Analizator** (`PodolskiSzymon/analyse_data`, folder `analyzer/`) – zbiera cały rynek 7 kategorii Vinted do SQLite,
  liczy ceny, wykrywa oszustwa/relisty, ocenia stan przez AI, generuje **wytyczne cenowe** dla Snipera.
* **Sniper** (`PodolskiSzymon/unreachable_sniper`, folder `sniper/`) – co kilka sekund skanuje nowe oferty, ocenia
  je AI (Gemini) według wytycznych, wysyła **ntfy (push) + mail** o okazjach. Auto-zakup istnieje, ale jest
  **wyłączony** (Vinted wylogowuje bota – patrz `unreachable_sniper/CLAUDE.md`).
* **Pilot** (`analyzer/remote.py`, `remote.bat`) – sterowanie z telefonu przez ntfy.

## 2. Infrastruktura u użytkownika

* Serwer: **Windows, stary laptop i5-5200U, 4 GB RAM, Python 3.12**, ~400 GB wolnego dysku. Konsola `cmd`.
  ⇒ komendy lekkie (strumieniowo, SQL z agregacją), z postępem w terminalu, krótki wynik do wklejenia.
* Ścieżki: `C:\Users\szymo\analyse_data`, `C:\Users\szymo\unreachable_sniper` (venv `.venv`),
  baza `C:\Users\szymo\category_analyzer\data\analyzer.db` (~1,3 GB, `ANALYZER_DB`), raporty
  `…\category_analyzer\data\reports\<data>\`, logi pilota `…\data\remote\{watch,sniper}.log`,
  logi Snipera `unreachable_sniper\sniper\logs\` (`evaluations.jsonl/.csv`, `oceny.html`, `mails.csv`, `sniper.log`).
* **Gałęzie: w OBU repo pracujemy na `claude/hopeful-faraday-n33quh`** (nie `main` – `main` w obu jest stary).
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

## 3. Reguły biznesowe (aktualne – decyzje użytkownika)

* **Koszt zakupu** = cena + wysyłka + **opłata Vinted kupującego 5% + 2,90 zł** (`SNIPER_BUYER_FEE_*`).
* **Koszty sprzedaży** 46 zł (Podbicie międzynarodowe 7 dni ~26 zł + wysyłka ~20 zł).
* **Reguła zysku (2026-10-26, ostatnia wersja):** zysk = sprzedaż − koszt zakupu − 46 zł; marża = zysk / sprzedaż.
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

## 4. Analizator (`analyse_data/analyzer/`) – co jest

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
* **`find.py`** – `python -m analyzer szukaj ram ddr4 dimm 16 --max 200`: najtańsze aktywne oferty z linkami; RAM:
  forma/typ z kodu naklejki w opisie (PC4-…-U = PC, -S = laptop, PC3 = DDR3).
* Testy: **242** (`python -m pytest analyzer/tests -q`), atrapa rynku `analyzer/tests/fake_market.py`.

## 5. Sniper (`unreachable_sniper/sniper/`) – przepływ oferty

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
* Testy: **208** (`python -m pytest sniper/tests -q`; nowe w `sniper/tests/test_categories.py`).
* Kontekst historyczny Snipera (API Vinted, sesja konta, auto-zakup): `unreachable_sniper/CLAUDE.md`.

## 6. Co wyszło w praktyce (26.10, `oceny.html` 366 ocen + `mails.csv`)

* Przed dzisiejszymi poprawkami 39 ocen 8–10, większość z zyskiem 150–250 zł (Wii, PS1–3, Xbox Classic, tanie tablety)
  – stara reguła (wyjątek 150 zł, marża 20%) + **AI zmyślało ceny retro** (Wii 600–760 zł, GBC 850, C64 800).
  Przy nowych regułach zostałoby ~10.
* Użytkownik **kupił 7 rzeczy (~2 650 zł)** z alertów: 2× Wii + Wii czarne bez pilota, iPhone 12 128 (bateria <80%),
  Galaxy A17, Galaxy Tab A 10.1 (2019), „iPad Air 2022” (w parametrach **iPad 10.9 (2022)** = zwykły iPad 10 –
  wysłano sprzedawcy pytanie o model po słowacku; jeśli iPad 10 – prośba o anulowanie). Szac. zysk łącznie
  ~600–1 100 zł, wszystko od zagranicznych sprzedawców (RO/SK/LT). Rada: Wii składać w zestawy, gry osobno.
* S22 (8/10) sprzedany w 3 min, gdy użytkownik negocjował → zasada „kupuj od razu przy 8+”.
* Burst 12 maili „NIEOCENIONA” (błąd API) → `SNIPER_AI_NOTIFY_FAILED=false`.
* Duplikaty tej samej oferty (podbicia) → `SNIPER_AI_SKIP_SEEN`.
* 209/366 ocen = 3/10 → bramka z podobnych ofert.

## 7. Zasady pracy (skrót `CLAUDE.md`)

Po polsku (także komentarze w kodzie). Claude **nie ma dostępu do vinted.pl ani bazy** – kod + testy na atrapach,
użytkownik uruchamia i wkleja wynik. Bez sekretów i danych w repo (`.env`, `*.db`, `data/`, eksporty). **RODO**: bez
nazw/ID sprzedawców w eksportach/analizach (uwaga: `oceny.html` Snipera ma nazwę sprzedawcy – lokalnie u użytkownika,
nie przenosić do repo ani odpowiedzi). Zapytania do Vinted tylko z realnego ruchu przeglądarki – bez zgadywania
endpointów. Commit + push po każdej zmianie na `claude/hopeful-faraday-n33quh` w danym repo; testy obu repo przed
pushem; bez PR. Odpowiedzi: konkretnie, z komendami do wklejenia na serwerze (`git pull` w obu, `sniper-guide`,
`restart sniper`).

## 8. Do zrobienia / niedoskonałości (priorytety)

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
9. **Backtest** (pozostałość D5): ocena historii ofert nowymi regułami vs to, co się sprzedało.
10. **Drobne**: nazwy grup typu „Xbox serie S i X seriess”; `catalogs.json` od 50 zł (dużo tanich ofert – bramka
    i reguła 300 zł je odcinają, ale kosztuje to szczegóły przez proxy); procesory jako kategoria (użytkownik pytał;
    brak w analizatorze); DDR5 – stanowisko B (H610M DDR5 + Pentium G7400) gdy będą okazje; auto-zakup wyłączony.

## 9. Gdzie co jest (mapa plików)

| temat | plik |
|---|---|
| zasady pracy | `analyse_data/CLAUDE.md`, `unreachable_sniper/CLAUDE.md` |
| historia analizatora, API Vinted | `KONTEKST_CATEGORY_ANALYZER.md`, `PLAN_ANALIZY.md` (dziennik wyników na końcu) |
| serwer, pilot, uruchamianie | `PILOT.md`, `ENV_SERWER.example`, `remote.bat`, `watch.bat` |
| sprzęt do testów | `SPRZET_DO_TESTOW.md` |
| reguła zysku, wytyczne | `analyzer/guide.py`, `sniper/guidelines.md` (laptopy, ręczne), `sniper/evaluator.py` (prompt, enforce) |
| katalogi, wagi, sprzęt testowy | `sniper/categories.py` |
| tabela wytycznych, dopasowanie | `sniper/guides.py` |
| podobne oferty | `analyzer/comparables.py`, `sniper/comparables.py` (tokenizacja musi być zgodna!) |
| szukanie w bazie | `analyzer/find.py` |
