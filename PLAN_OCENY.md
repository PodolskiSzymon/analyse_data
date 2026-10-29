# PLAN_OCENY.md – maksymalnie dokładna ocena ofert przy minimalnym zgadywaniu AI (2026-10-26)

> **Dla Claude w nowej rozmowie:** to jest GŁÓWNY plan dalszej pracy (ważniejszy niż lista w `STAN_PROJEKTU.md` §8,
> który opisuje stan i kontekst – przeczytaj go najpierw). Realizuj fazy po kolei (§9), odhaczaj `[x]` w liście
> kontrolnej (§14), wyniki z danych użytkownika dopisuj do dziennika (§15) z datą. Zasady pracy: `CLAUDE.md`
> (po polsku, bez dostępu do Vinted i bazy – kod + testy na atrapie, użytkownik uruchamia i wkleja wynik, komendy
> lekkie z postępem, commit + push na gałąź sesji w obu repo – od 27.10 `claude/magical-bell-vdwpt1` –, bez PR).
>
> **Decyzje użytkownika (2026-10-26):** YOLO / zbiór zdjęć z ramkami – **odrzucone i cofnięte** (zysk nieistotny,
> patrz §13). Cel: ocena „ultra dokładna” – AI ma jak najmniej zgadywać. Dalsza praca w nowym czacie.

---

## 1. Diagnoza – skąd dziś biorą się błędy (konkretnie, z miejscami w kodzie)

| # | Problem | Gdzie | Skutek |
|---|---|---|---|
| 1 | **AI podaje cenę sprzedaży** (`market_value_pln`), a z niej program liczy zysk, marżę, regułę. Reguła sprawdza ofertę względem liczby, którą wymyśliło to samo AI – kółko. | `sniper/evaluator.py`: `EVALUATION_SCHEMA`, `enforce_profit_rule` (przycina tylko, gdy są podobne oferty) | Zawyżone okazje (Wii 600–760 zł, GBC 850, C64 800 – 26.10). |
| 2 | **Cena „sprzedam za ~” = WYŻSZA z dwóch szacunków** (mediana zniknięć vs środek p25–mediana ofert). | `analyzer/guide.py: rows()` | Systematyczny optymizm – zawsze bierzemy lepszy wariant. |
| 3 | „Zniknięte” = sprzedane **+ usunięte** (usunięcia to nie sprzedaże: relisty, wycofania, nieudane). | `guide.collect` (`gone`) | Mieszanka; usunięte wiszą zwykle dłużej i drożej. |
| 4 | Cena z bazy = **ostatnia cena wystawienia**, bez rabatu „Zaproponuj cenę”. | dane | Kolejne +5–15% optymizmu (sprzedane ~10–15% poniżej mediany ofert, dziennik 25.10). |
| 5 | **Grupy z regexów** (`config_key`) mieszają warianty (⚠: PS5 disc/digital/slim, DDR5 1×/2× kość, laptopy różnych generacji). | `analyzer/extract.py`, `guide.group_key` | Cena grupy nie pasuje do konkretnej sztuki. |
| 6 | **Dopasowanie oferty do wiersza po słowach tytułu** (`guides.match`) i podobne oferty po słowach (`comparables.db`, FTS5). | `sniper/guides.py`, `sniper/comparables.py` | Kruche: tytuły RO/LT/SK/HU, „PS4 + 2 pady”, akcesoria łapane jako konsole. |
| 7 | Formularz Vinted (marka/model/pamięć/platforma/kondycja baterii wybrane przez sprzedawcę z listy) **jest w sidebarze, który Sniper już pobiera – ale Sniper go nie czyta**. | `sniper/extractor.py` (brak atrybutów) | Tracimy najpewniejsze źródło identyfikacji za 0 transferu. |
| 8 | **Czas sprzedaży zgaduje AI** (`sell_days_estimate`). | schemat AI | Ocena 8 vs 9 zależy od zgadywania. |
| 9 | **Ocenę 0–10 wystawia AI** wg „orientacyjnej” skali; program tylko przycina. | `SYSTEM_PROMPT` | Niepowtarzalne, nieweryfikowalne oceny. |
| 10 | **Zdjęcia idą do AI dla każdej oferty** po bramce (u użytkownika `SNIPER_AI_MAX_PHOTOS=12` ≈ 13 tys. tokenów/ofertę – ~1 090 tokenów/zdjęcie, dziennik 25.10). | `GeminiBackend.generate` | Największy koszt, a większość ofert odpada na cenie. |
| 11 | **Brak sprzężenia zwrotnego**: nie wiemy, za ile użytkownik naprawdę sprzedaje, ile alertów było trafnych, jaki jest rzeczywisty rabat przy negocjacji. | brak | Nie da się skalibrować niczego powyżej. |
| 12 | Liczba **pewnych sprzedaży jest mała** (do 24.10: 307 sold + 148 blocked; błąd API ~10–24.10 zaliczał sprzedane do deleted). Poprawny resolver działa od 24.10. | dane | Ceny sprzedaży per model dopiero się zbierają. |

## 2. Zasada docelowa: „AI rozpoznaje i czyta, dane wyceniają, program decyduje”

Każda liczba w powiadomieniu ma **źródło** i **klasę pewności**. AI nie podaje żadnej ceny, czasu ani oceny 0–10.

| Wielkość | Kto | Skąd |
|---|---|---|
| Co to jest (kanoniczny model + wariant) | 1) formularz Vinted, 2) reguły taksonomii, 3) AI **wybiera z listy kandydatów** (nie wymyśla) | §5, §6 |
| Stan, kompletność, ryzyka (uszkodzenia, blokady, oszustwo, zdjęcia stockowe) | AI (tekst, potem zdjęcia) **z dosłownymi cytatami / numerem zdjęcia jako dowodem** | §6 |
| Cena sprzedaży w ≤ 7 dni (S7) + przedział | dane analizatora (`prices.json`) | §4 |
| Korekty (bateria, stan z formularza, braki akcesoriów) | dane (mnożniki z rynku), tylko w dół dla braków | §4.5 |
| Dni do sprzedaży | dane (mediana dla modelu / krzywa kategorii) + dni dostawy (PL vs zagranica) | §4.4 |
| Koszt zakupu, zysk, marża, reguła | program (jak dziś: cena + wysyłka + 5% + 2,90 zł; koszty 46 zł) | `rule_max_buy` |
| Ocena 0–10 | program, deterministyczna funkcja | §7 |
| Opinia AI (tekst „dlaczego”) | AI – tylko informacyjnie, nie zmienia liczb | – |

## 3. Docelowy przepływ oferty w Sniperze (v2)

```
skan → szczegóły (sidebar, już pobierany)
 → [1] identyfikacja bez AI: atrybuty formularza + taksonomia (reguły)        → item_id / kandydaci / nieznany
 → [2] wycena z prices.json (S7, przedział, klasa A–D, dni)                   → zysk/marża przy S_kons
 → [3] bramka: na pewno nie okazja (nawet przy najlepszym kandydacie i górze przedziału) → STOP (0 tokenów)
 → [4] AI etap A – SAM TEKST, tani model: wybór item_id z kandydatów + wariant + flagi tekstowe z cytatami
       → program weryfikuje cytaty (muszą być dosłownie w tytule/opisie), przelicza [2]–[3]
 → [5] AI etap B – ZDJĘCIA, tylko potencjalne okazje: stan, kompletność, zgodność z modelem, stock, uszkodzenia
       (dowód = numer zdjęcia + opis); przy ocenie ≥ 9 albo niezgodności opcjonalnie drugi model
 → [6] program: korekty → zysk/marża → reguła → ocena 0–10 (§7) → PL +1
 → [7] powiadomienie z pochodzeniem liczb: „S7 1 450 zł (14 sprzedanych / 60 dni, klasa A), ~4 dni”
```
Oszczędność tokenów (to, czego użytkownik chciał od YOLO) wynika z [3] i z tego, że zdjęcia [5] dostają tylko
potencjalne okazje (kilka % ofert), a etap A to ~1–2 tys. tokenów tekstu zamiast ~13 tys. ze zdjęciami.

## 4. Model ceny (analizator) – `prices.json`

### 4.1 Jednostka: kanoniczny `item_id` (z taksonomii §5)
Np. `console/sony/ps4-pro`, wariant `1tb`; `phone/apple/iphone-13-pro`, wariant `128gb`. Hierarchia rodzic → dziecko
(`ps4` → `ps4-slim`, `ps4-pro`) pozwala spaść poziom wyżej, gdy dziecko ma mało danych (klasa niższa).

### 4.2 Cena odniesienia R
`R(item)` = mediana ceny **aktywnych, sprawnych** ofert tego item_id (wszystkie rynki – użytkownik sprzedaje z
Podbiciem międzynarodowym, kupujący z całej UE; PL/zagranica raportować osobno), okno 30 dni, bez flag
(`suspicious`), relistów i uszkodzonych (`ai_condition` > reguły). Aktywnych ofert jest dużo → R stabilne nawet dla
rzadkich modeli.

### 4.3 S7 z krzywej „szansa sprzedaży w 7 dni vs cena / R” (rdzeń planu)
Dla każdej oferty z **wiarygodnym początkiem** (`first_seen` po pierwszym przejściu kategorii albo `created_at`;
patrz `stats.start_of`) i obserwowanej ≥ 7 dni: `r = cena / R(item)`, `y = 1`, jeśli `sold`/`blocked` w ≤ 7 dni od
początku (resolver od 24.10). Krzywa `P_kat(r)` per **kategoria** (dużo danych – izotoniczna/malejąca, kubełki r co
0,05), poziom per item przez R. Wtedy:
* **S7(item) = R × r\***, gdzie r\* = największe r z `P_kat(r) ≥ τ` (start τ = 0,5; do kalibracji §8).
* Gdy item ma własne ≥ 10 sprzedaży w 60 dni – własna korekta poziomu (mediana r sprzedanych vs krzywa).
* **S_kons = S7 × (1 − δ)** – δ = rabat negocjacji; start **0,08**, potem z rejestru flipów (§8.1).
* Przedział: p25–p75 cen sprzedanych / bootstrap; do reguły zysku idzie **S_kons** (dolna strona).
* Zakaz: żadnego `max()` dwóch szacunków (§1 #2). Usunięte (deleted) NIE są sprzedażami.
* Do czasu, gdy krzywa ma dane (≥ ~4 tyg. po 24.10 i ≥ ~200 sprzedanych w kategorii): **S_tymcz = środek
  p25–mediana aktywnych × (1 − δ)** – bez mediany zniknięć, klasa najwyżej B.

### 4.4 Dni do sprzedaży
Mediana `days_to_sell` sprzedanych tego item_id (≥ 5) albo z krzywej kategorii przy r\*; plus dni dostawy do
użytkownika: PL ~2, zagranica z danych (później) – start 7. Do oceny (§7) liczy się „dni sprzedaży” (bez dostawy);
dostawa wpływa przez premię PL.

### 4.5 Korekty z danych (tylko tam, gdzie dane je pokazują)
* Stan z formularza (`status_label` / `condition_grade`: nowy / bardzo dobry / dobry / zadowalający) – mnożnik =
  mediana r w danej grupie stanu (per kategoria).
* Bateria (telefony, `battery_bucket`/`battery_pct`: < 80, 80–84, 85–89, 90+) – mnożnik z danych.
* **Braki** (brak ładowarki / pada / zasilacza) – minus cena zamiennika (z ofert akcesoriów w bazie albo stała z
  wytycznych). **Dodatki (gry, 2. pad, pudełko) NIE podnoszą S** (asymetria = ostrożność; ewentualnie osobna
  informacja „można sprzedać osobno ~X zł”).
* Uszkodzone – poza modelem (nie kupujemy).

### 4.6 Klasy pewności
* **A** – item ma ≥ 10 sprzedanych / 60 dni + krzywa kategorii.
* **B** – ≥ 15 aktywnych (R) + krzywa kategorii (albo S_tymcz).
* **C** – tylko rodzic (np. „PS4” bez wariantu) albo < 15 aktywnych → okazja tylko, gdy reguła spełniona także przy
  p25 aktywnych × (1 − δ); ocena −1.
* **D** – brak danych → **nigdy okazja** (max 6; opcjonalnie powiadomienie „do ręcznej oceny” przy dużej różnicy
  ceny wg AI – wyłączone domyślnie).

### 4.7 Trend i świeżość
R z ostatnich 14 dni vs 30 dni; spadek > 5% → używaj 14 dni + flaga „ceny spadają” (premiery, np. nowy iPhone).
`prices.json` ma datę; Sniper ostrzega, gdy plik starszy niż 7 dni (automat 2×/tydz. już jest – `analyzer/auto.py`).

### 4.8 Format `prices.json` (publikowany obok `guides/*.md`, kopiowany przez `auto.publish`)
```json
{"generated_at": "...", "matcher_version": 1, "delta": 0.08, "tau": 0.5,
 "curves": {"console": [[0.70, 0.81], [0.75, 0.74], ...]},
 "items": {"console/sony/ps4-pro|1tb": {"name": "PlayStation 4 Pro 1 TB", "R": 820, "R_pl": 850, "n_active": 143,
            "n_sold_60d": 12, "sold_p25": 690, "sold_med": 740, "s7": 760, "s_kons": 699, "days_med": 4,
            "trend_14_30": -0.03, "grade": "A", "adjust": {"status": {"dobry": 0.93}, "missing": {"pad": 80}}}}}
```
Tabele `guides/<kategoria>.md` generować z tego samego (dla człowieka), a nie liczyć osobno.

## 5. Taksonomia (identyfikacja) – `taxonomy/<kategoria>.json` + jeden matcher w obu repo

* **Budowa:** Claude układa strukturę z wiedzy (rodziny, modele, warianty, kody modeli typu CUH-7216B / A2633,
  słowa w językach RO/LT/SK/CZ/HU/DE), **a listę modeli i aliasów bierze z danych** (najczęstsze tytuły / n-gramy
  i wartości formularza z eksportu, §10 D2). Ceny w taksonomii – **nigdy**.
* **Wpis:**
  ```json
  {"id": "console/sony/ps4-pro", "name": "PlayStation 4 Pro", "parent": "console/sony/ps4",
   "all": [["ps4", "playstation 4", "play station 4"], ["pro"]], "none": ["slim", "pad", "kontroler", "gra", "etui", "obudowa"],
   "codes": ["cuh-7\\d{3}"], "variants": {"storage": ["500gb", "1tb", "2tb"]},
   "form": {"video_game_platform": ["PlayStation 4"]}, "essentials": ["pad", "zasilacz/kabel"]}
  ```
* **Kolejność źródeł:** kod modelu (najpewniejszy) > formularz Vinted (`model_nav`, `internal_memory_capacity`,
  `video_game_platform`, `battery_health`… – kody w `analyzer/extract.py`) > reguły tytułu > reguły opisu > AI (§6).
  Sprzeczność źródeł (np. formularz „iPhone 13”, tytuł „13 Pro”) → `item_id` niepewny → nie okazja bez AI etapu A.
* **Akcesoria i śmieci** (sam pad, gra, etui, pudełko, „na części”) – osobne `id` typu `console/accessory/*` →
  odcinane przed AI (dziś łapane jako konsole – np. kierownica Thrustmaster).
* **Jeden matcher:** `analyzer/taxonomy.py` (czysty Python, bez zależności) + **ta sama kopia** `sniper/taxonomy.py`;
  wspólny plik testów `taxonomy_golden.json` (≥ 100 tytułów na kategorię z oczekiwanym id, także zagraniczne)
  skopiowany do obu repo; `MATCHER_VERSION` w kodzie i w `prices.json` – niezgodność → Sniper loguje ostrzeżenie i
  przechodzi na v1. (Dziś tokenizacja jest zduplikowana w `analyzer/comparables.py` i `sniper/guides.py` – to ma
  zniknąć.)
* **Przypisanie w bazie:** tabela `analysis.db: item_ids(listing_id, item_id, variant, src, version)`; nieprzypisane
  częste tytuły → raport `taxonomy-report` (pokrycie per kategoria, top 50 nieprzypisanych) → rozbudowa taksonomii;
  opcjonalnie AI etap A wsadowo dla reszty (tekst, tani model, cache – jak `ai_condition`).
* **Laptopy osobno** (§9 F5): kombinacji za dużo na listę modeli → item = klasa (GPU / linia + generacja CPU) +
  korekty (RAM, ekran Hz, rozmiar); start z obecnych grup `guide.group_key`.

## 6. AI – tylko rozpoznanie i czytanie, z dowodami

### Etap A (tekst, tani model – np. `gemini-3.1-flash-lite`; wszystkie oferty po bramce [3])
Wejście: tytuł, opis, atrybuty formularza, cena, kraj, **lista kandydatów** (top 5 z matchera: id + nazwa + krótki
opis różnic) + „inny” + „nie_wiem”. Schemat (wszystko z enumów / krótkie):
```json
{"item_id": "console/sony/ps4-pro" | "inny" | "nie_wiem", "variant": {"storage": "1tb"},
 "evidence": ["CUH-7216B", "PS4 Pro 1TB"],                       // DOSŁOWNE fragmenty tytułu/opisu
 "condition_text": "sprawny" | "drobna_usterka" | "uszkodzony" | "na_czesci" | "nie_wiadomo",
 "flags": [{"kind": "blokada|kontakt_poza_vinted|tylko_odbior|niezgodnosc|brak_akcesorium|inne", "quote": "..."}],
 "missing": ["pad"], "extras": ["2 gry"]}
```
Program: **każdy cytat musi występować w tekście** (po normalizacji wielkości liter/spacji) – inaczej twierdzenie
odrzucone i oferta „niepewna”. `inny`/`nie_wiem` → klasa D (nie okazja). Wybór spoza kandydatów niemożliwy (enum).

### Etap B (zdjęcia, lepszy model – obecny `gemini-3.8-flash`; tylko potencjalne okazje po przeliczeniu)
Schemat: `photos_seen`, per zdjęcie `{"photo": n, "finding": "pęknięty ekran|rysa|naklejka z modelem|zdjęcie
stockowe|ekran blokady|komplet|..."}`, `condition_photos` (enum jak wyżej), `model_consistent` (czy zdjęcia pasują
do item_id), `confidence` (niska/średnia/wysoka). Brak liczb cenowych. Zdjęcia: max 6 (pierwsze + ewentualnie te z
naklejką/ekranem – kolejność od Vinted).

### Spójność (tylko dla ocen ≥ 9 albo niezgodności A↔B)
Drugie wywołanie etapu B innym modelem (OpenRouter albo Anthropic) – różnica w stanie/zgodności → ocena max 7 +
„sprawdź ręcznie”. Koszt pomijalny (kilka ofert dziennie).

### Prompt
Krótki, bez tabel cen (ceny są programu) – AI nie ma czego „dopasowywać” i nie ma pokusy liczyć. Instrukcja:
„Nie oceniasz ceny. Odpowiadasz tylko tym, co wynika z tekstu/zdjęć; gdy nie wiesz – `nie_wiem`.”

## 7. Ocena 0–10 – deterministyczna (program), zgodna z regułami użytkownika

```
K = cena + wysyłka + 5% + 2,90 zł      S = S_kons (po korektach §4.5)      P = S − K − 46      M = P / S
nie okazja (ocena ≤ 6): M < 30% | P < próg(M) (300 przy 40%+, 400 przy 35%, 500 przy 30%; +20 zł/pkt) |
                        klasa D | item niepewny | flaga uszkodzenia/blokady/oszustwa | cytaty nie przeszły
okazja – bazowo:
  10: M ≥ 45% i P ≥ 800 i dni_sprzedaży ≤ 5
   9: (M ≥ 45% i P ≥ 500) albo (M ≥ 40% i dni ≤ 5)
   8: (M ≥ 35% i dni ≤ 5) albo M ≥ 40%
   7: reguła spełniona
kary: klasa C −1; stan „nie_wiadomo”/confidence niska −1; trend „ceny spadają” −1
premia: sprzedawca z Polski +1 (max 10)
```
Do rozważenia z użytkownikiem: ranking po **zysku na dzień zamrożonej gotówki** (P / K / (dni dostawy + dni
sprzedaży)) – lepiej oddaje „szybko obracać kapitałem” niż sama marża. Ocena AI (stara) zostaje tylko w logu do
porównań w trybie cienia.

## 8. Pętla zwrotna – bez niej „dokładność” jest nieweryfikowalna

### 8.1 Rejestr flipów (`data/flips.csv`, NIE w repo) + `python -m analyzer flips`
Kolumny: `data_zakupu;id_oferty;kategoria;model;koszt_zakupu_lacznie;kraj_sprzedawcy;data_dostawy;stan_zgodny(T/N);
problemy;cena_wystawienia;data_wystawienia;data_sprzedazy;cena_otrzymana;koszty_sprzedazy;ocena_alertu;notatki`.
Raport: realny zysk/marża/dni vs przewidywane, **δ** = 1 − cena_otrzymana / cena_wystawienia (mediana), trafność
klas, ROI kapitału. Pierwsze wpisy: 7 zakupów z 26.10 (STAN_PROJEKTU §6).

### 8.2 Wynik alertów (automatycznie, bez pracy użytkownika)
Analizator i tak śledzi każdą ofertę. Raport `alert-outcomes`: dla ofert z `evaluations.jsonl` (ocena ≥ 7): czy
zniknęła i kiedy, stan sold/deleted, cena. **Prawdziwa okazja znika szybko** – % alertów 8+ sprzedanych w ≤ 24/48 h
vs zwykłe oferty tego item_id = miara trafności bez kupowania. Wejście: `evaluations.jsonl` (kopiuje się na Dysk –
`SNIPER_MIRROR_DIR`) – ścieżka w `.env` analizatora.

### 8.3 Backtest (`python -m analyzer backtest --od 2026-11-01`)
Dla ofert z okna: wycena wyłącznie danymi sprzed pojawienia się oferty (bez AI – identyfikacja regułami) →
porównanie z wynikiem. Metryki: MdAPE S7 vs cena sprzedanych (cel ≤ 10% dla klas A/B), kalibracja P(sprzedana ≤ 7 d)
(±10 pp), % ofert, które byłyby okazją, i ile z nich sprzedało się w 48 h. Wynik decyduje o τ i δ.

## 9. Fazy (kolejność, pliki, kryteria odbioru)

**F0 – zdrowie danych (najpierw, krótko).** Czy `watch` chodzi bez przerw od 24.10? Ile sprzedanych / tydzień /
kategoria od 24.10; zwłoka resolvera (`services_at − last_seen`); % sold vs deleted wśród sprawdzonych ≤ 24 h.
Kod: komenda `sold-report` (lekka, SQL z agregacją) – może być rozszerzeniem `diag`. Odbiór: ≥ 90% zniknięć
sprawdzonych ≤ 24 h, znane tempo napływu sprzedaży. Też: szablon `flips.csv` + `flips` (§8.1).

**F1 – taksonomia: konsole → telefony → tablety → GPU/RAM/dyski.** Pliki: `analyzer/taxonomy.py`,
`taxonomy/*.json`, `taxonomy_golden.json`, `analysis.db: item_ids`, `taxonomy-report`, testy na atrapie
(`analyzer/tests/fake_market.py`). Odbiór: pokrycie ≥ 85% ofert kategorii (bez akcesoriów), precyzja ≥ 97% na
200 losowych tytułach (Claude sprawdza na eksporcie, użytkownik wyrywkowo), akcesoria odcięte.

**F2 – model ceny.** `analyzer/prices.py` → `prices.json` (§4.8); `guide.py` generuje tabele z `prices.json`
(koniec `max()` i mieszania deleted); `auto.publish` kopiuje `prices.json` + `taxonomy/*.json`; `backtest`. Do czasu
krzywej – S_tymcz. Odbiór: backtest §8.3 (gdy dane pozwolą), klasy A/B dla ≥ 70% ofert w konsolach/telefonach.

**F3 – Sniper v2** (`unreachable_sniper`): `extractor.py` czyta atrybuty formularza z sidebaru (to samo co
`analyzer/details.attributes` – zero transferu); `sniper/taxonomy.py` (kopia matchera); `sniper/prices.py`
(ładowanie `prices.json`, ponowne wczytanie po zmianie jak `guides._File`); `evaluator.py`: etapy A/B (§6), nowe
schematy, weryfikacja cytatów, deterministyczna ocena (§7), `SNIPER_EVAL_MODE=v1|v2|shadow`; `push.py`/`notifier.py`/
`report.py`: pochodzenie liczb i klasa. **Najpierw `shadow`** (v2 liczy i loguje obok v1, powiadamia v1) 2–3 dni →
porównanie → przełączenie. Kategorie bez taksonomii (laptopy) zostają na v1. Odbiór: koszt AI/dzień ↓ ≥ 50%, ≥ 90%
powiadomień z klasą A/B, przegląd 20 alertów z użytkownikiem.

**F4 – kalibracja (stała, co tydzień w `auto`).** `alert-outcomes` + `flips` + `backtest` → δ, τ, kary; krótki
raport na ntfy/plik. Odbiór: δ z ≥ 10 sprzedaży użytkownika; trafność alertów raportowana co tydzień.

**F5 – laptopy.** Klasa = GPU (dyskretne) / linia + generacja CPU (zintegrowane) / MacBook chip; korekty RAM,
odświeżanie ekranu, rozmiar, linia (Legion/ROG/TUF…) z danych (regresja log-ceny albo najbliżsi sąsiedzi po
cechach z `features`, nie po słowach). Ten sam S7 i ocena. Do tego czasu v1 + `guidelines.md`.

## 10. Dane od użytkownika (dokładnie co i kiedy)

* **D1 (od razu):** `python -m analyzer status` i `python -m analyzer diag` (wkleić); pilot `status` (czy `watch`
  chodzi i od kiedy). Bez tego F0 nie ruszy.
* **D2 (do F1):** `python -m analyzer export-analysis --split` (bez opisów; z opisami tylko na prośbę) → wysłać
  foldery `console\`, `phone\`, `tablet\` (+ `crawl_runs.csv`). Potem `gpu\ ram\ storage\`, na końcu `laptop\`.
  Plik za duży do wysłania → powiedzieć Claude rozmiar, dostanie węższy eksport.
* **D3:** `unreachable_sniper\sniper\logs\evaluations.jsonl` (ostatnie dni) – zbiór testowy i porównanie AI vs dane.
* **D4:** wypełniony `flips.csv` (7 zakupów z 26.10 + każdy kolejny) – szablon da Claude w F0.
* **D5 (po ~4 tyg. od 24.10, ok. 21.11):** świeży eksport → krzywe S7 i backtest.

## 11. Pytania do użytkownika (zadać na początku F0 – wpływają na model)

1. Gdzie są Twoi kupujący – głównie PL czy cała UE (Podbicie międzynarodowe zawsze)? (rynek R: PL czy wszystkie)
2. O ile zwykle schodzisz z ceny przy „Zaproponuj cenę”? (start δ)
3. Jaki % Twoich wystawień sprzedaje się w 7 dni i co robisz z resztą (obniżka o ile)? (τ)
4. Priorytet kategorii i maksymalna kwota na jedną sztukę / łączny kapitał zamrożony?
5. Czy kupujesz od zagranicznych sprzedawców bez ograniczeń (dłuższa dostawa, trudniejszy zwrot)?
6. Ile czasu na sztukę (test, czyszczenie, zdjęcia) – czy tanie rzeczy z zyskiem 300 zł są warte zachodu?

## 12. Czy analiza rynku w innym czacie Claude? – odpowiedź

**Tak, ale nie jako opisowy raport, tylko jako pliki do repo w formacie z tego planu.** Ceny „z czatu” zestarzeją się
po tygodniu – produkcyjne ceny ma liczyć kod analizatora 2× w tygodniu. Czat analityczny przydaje się do jednorazowej
pracy na eksporcie: zbudowanie taksonomii z tytułów, znalezienie mieszanych grup, pierwsze krzywe S7, ustalenie δ/τ.
**Najlepiej robić to w tym samym czacie, który pisze kod** („wykonaj md” + wysłane pliki z D2): wynik od razu trafia
do repo i testów. Osobny czat tylko do zrównoleglenia – wtedy wkleić mu poniższy prompt, a jego pliki dać czatowi
z kodem.

> **Prompt dla czatu analitycznego:** „Jesteś analitykiem rynku używanej elektroniki (Vinted, PL + UE). W załączniku
> eksport analizatora dla kategorii <X>: `listings.csv.gz` (oferty: tytuł, stan `state` active/sold/blocked/deleted,
> `price_now`, `sold_price`, `first_seen`, `created_at`, `seller_currency`, `status_label`, `seller_hash`),
> `features.csv.gz` (parametry z ekstrakcji, `config_key`), `observations_real.csv.gz` (zmiany cen). Zasady: cena
> sprzedaży = ostatnia cena wystawienia (górna granica), `deleted` to NIE sprzedaż, sprzedaże przed 24.10.2026 są
> niepełne, oferty zagraniczne mają ułamkowe ceny w zł. Zadania: (1) taksonomia kategorii w formacie JSON z sekcji 5
> pliku PLAN_OCENY.md (wklejam ją niżej) – rodziny, modele, warianty, aliasy w językach PL/RO/LT/SK/CZ/HU/DE, kody
> modeli, słowa wykluczające akcesoria; bez cen; (2) `taxonomy_golden.json`: 150 prawdziwych tytułów z eksportu
> z oczekiwanym id (także trudne i zagraniczne); (3) pokrycie: jaki % ofert łapie Twoja taksonomia, top 50
> nieprzypisanych tytułów; (4) dla 20 najliczniejszych modeli: R (mediana aktywnych), liczba sprzedanych od 24.10,
> mediana r = cena sprzedanych / R, mediana dni do sprzedaży; (5) grupy mieszane (szeroki rozkład ceny – czemu).
> Wynik: pliki JSON + krótki `wnioski_<X>.md` z liczbami. Nie podawaj cen z własnej wiedzy – tylko z danych.”

## 13. Odrzucone / czego nie robić

* **YOLO / ramki na zdjęciach** (cofnięte 26.10, commity revert w obu repo): wykrycie „konsola + 2 pady” nie zastąpi
  rozpoznania wariantu, stanu ani opisu; oszczędność tokenów osiągamy taniej przez bramkę ceny i etap A tekstowy (§3).
  Wrócić najwyżej, gdy etap B będzie dominującym kosztem – i wtedy jako wybór zdjęć, nie identyfikacja.
* **AI podające ceny / dni / ocenę** – nie (§2). Także „wartość wg AI” w powiadomieniu – usunąć w v2.
* **`max()` dwóch szacunków, mieszanie deleted ze sprzedanymi, dodawanie wartości za dodatki** – nie (§4).
* **Ceny wpisywane ręcznie z wiedzy Claude** – nie (wiedza = ceny ofertowe sprzed daty odcięcia).
* Nie przebudowywać wszystkiego naraz: v1 działa i zarabia – v2 obok w trybie cienia, kategoriami.
* Ryzyka: zmiany API Vinted (alarm „brak sprzedaży” w `auto` jest), mała liczba sprzedaży dla rzadkich modeli
  (klasy C/D – i dobrze, że nie dają okazji), dryf kursów (zagraniczne ceny), handlarze (`seller_hash` – sprawdzić
  w F2, czy psują R; ew. jedna oferta na sprzedawcę w medianie).

## 14. Lista kontrolna

- [~] F0: ~~D1~~ (zamiast `status`/`diag` – pełna baza z 27.10, §15) · [x] `sold-report` · [x] szablon + komenda
  `flips` · [ ] odpowiedzi na pytania §11 (kupujący PL/UE, δ – czekam) · [ ] `flips.csv` wypełniony (D4)
- [ ] Eksperyment 6a powtórzony z `comparables.db` (tryb `mediany` był nieważny) → decyzja `SNIPER_EVAL_MODE`
- [ ] F1 konsole: taksonomia + golden + `item_ids` + `taxonomy-report`; pokrycie/precyzja OK
- [ ] F1 telefony, tablety; [ ] GPU, RAM, dyski
- [ ] F2: `prices.py` + `prices.json` (S_tymcz), tabele md z `prices.json`, publikacja do Snipera
- [ ] F3: Sniper – atrybuty formularza, matcher, prices, etap A, bramka, etap B, ocena §7, `shadow` → `v2`
- [ ] F4: `alert-outcomes`, `backtest`, cotygodniowa kalibracja δ/τ
- [ ] F2b (po ~21.11): krzywe S7 z prawdziwych sprzedaży, klasy A
- [ ] F5: laptopy

## 15. Dziennik (dopisuj z datą)

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
