# analyse_data – analiza rynku Vinted (kontynuacja `category_analyzer`)

**Gdy użytkownik napisze „wykonaj md” (albo „wykonaj plan”) → otwórz `PLAN_ANALIZY.md` i wykonuj go krok po kroku,
od pierwszego niezrobionego kroku (lista kontrolna na końcu pliku). Po każdym kroku odhacz go w `PLAN_ANALIZY.md`,
commit + push.** Nie pytaj o rzeczy, które plik już rozstrzyga.

To repo jest **zrzutem** `PodolskiSzymon/category_analyzer` (gałąź `claude/focused-johnson-6ytqgt`, commit `26110ca`,
2026-10-24): cały kod `analyzer/` + `sniper/`, dokumentacja i testy (333 testy przechodzą). Pełna historia decyzji
i ustaleń o API Vinted: **`KONTEKST_CATEGORY_ANALYZER.md`** (dawny CLAUDE.md – czytaj, gdy dotykasz kodu
zbierającego dane albo czegoś, czego tu nie ma). Szczegóły Snipera: `sniper/CONTEXT.md`.

## Najważniejsze zasady (obowiązują dalej)

* Rozmawiamy **po polsku**; komentarze w kodzie po polsku; konkretnie, z wynikami testów.
* **Claude NIE ma dostępu do vinted.pl ani do bazy użytkownika.** Baza (`analyzer.db`, ~1,3 GB) jest tylko na
  serwerze użytkownika (Windows, stary laptop i5-5200U / 4 GB RAM, Python 3.12). Wszystko, co czyta bazę albo sieć,
  uruchamia użytkownik i wkleja wynik / wysyła plik. Ty piszesz kod + testy na atrapie (syntetyczna baza SQLite).
  ⇒ Komendy muszą być **lekkie** (4 GB RAM: strumieniowo / SQL z agregacją, nie ładować wszystkiego do pandas),
  pokazywać postęp (użytkownik myśli, że się zawiesiło, gdy terminal milczy) i dawać **krótki** wynik do wklejenia.
* Zapytania do Vinted tylko na podstawie realnego ruchu przeglądarki (cURL z F12) albo testu u użytkownika –
  **bez zgadywania endpointów**. Budżet proxy jest ograniczony (Evomi) – analiza ma działać **bez sieci**.
* **Nie commitować** sekretów (`.env`, hasła, klucze, tokeny, temat ntfy) ani danych (`data/`, `*.db`, eksporty).
* **RODO**: nazw/ID sprzedawców nie zapisujemy i nie eksportujemy. W eksportach z opisami maskować e-mail/telefon/URL
  (`analyzer/sample.py: redact`).
* Cena „sprzedaży” = ostatnia cena wystawienia (Vinted ma „Zaproponuj cenę”) → w raportach **górna granica**.
* Nie tworzyć PR bez prośby. Commity na gałąź domyślną `main` tego repo (repo było puste – nie ma innej gałęzi),
  chyba że użytkownik powie inaczej. W commitach/kodzie nie wpisywać identyfikatora modelu AI.

## Uruchomienie (u użytkownika)

```bat
cd C:\Users\szymo
git clone https://github.com/PodolskiSzymon/analyse_data
cd analyse_data
pip install -r sniper\requirements.txt
copy ..\category_analyzer\sniper\.env sniper\.env
rem baza zostaje w starym folderze - wskaż ją (albo przenieś folder data\):
echo ANALYZER_DB=C:\Users\szymo\category_analyzer\data\analyzer.db>> sniper\.env
python -m analyzer status
```

Testy (u Ciebie, bez sieci): `python -m pytest analyzer/tests sniper/tests -q`.
