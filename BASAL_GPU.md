# Basal 2.0 Mini na GeForce 920M – krok 1 (środowisko), kroki 2–3 (próbka i test)

Plan użytkownika (06.11): regex na tytule → przy wątpliwościach lokalny model decyzyjny basal na GPU → mediany.
Ten plik to krok 1. Kroki 2–3: `python -m analyzer basal-sample` i `basal-test` (`analyzer/basal_poc.py`).
**Po kroku 3 czekamy na wyniki użytkownika** – dopiero potem regexy rodzin i kaskada (kroki 4–5).

> **Wynik u użytkownika (06.11): `ggml_vulkan: Error: Vulkan 1.2 required` → karta 920M odpada** (ostatni
> sterownik 425.31 ma Vulkan 1.1 i CUDA 10.1). basal tylko na CPU: llama.cpp „Windows x64 (CPU)” w
> `C:\Users\szymo\llama-cpu`, serwer z `-ngl 0`, dalej wariant A / B. Wariant C (eager, torch, ~3 GB) odpada przy
> 4 GB RAM. Szacunek 10–30 s / ofertę → basal tylko jako bramkarz wątpliwych ofert, nie dla każdej.

## Co trzeba wiedzieć przed instalacją (sprawdzone w dokumentacji github.com/rkinas/basal, v2.5.5)

* **basal-2.0-mini**: 1,5 mld parametrów, na bazie Bielika v3 (architektura Llama), PL + EN, Apache-2.0, kontekst
  8 192 tokenów. Oficjalny GGUF (repo `Remek/basal-2.0-mini-GGUF`): **Q8_0 i Q5_K_M** (Q4/Q6 nie ma).
  Q5_K_M to ok. 1,1 GB (szacunek z rozmiarów basal-1.0-1.5B: Q4_K_M 1,0 GB, Q8_0 1,7 GB). Q8_0 (~1,7 GB) się nie
  zmieści, bo dochodzi pamięć podręczna kontekstu i bufory.
* basal **nie pisze tekstu**. Dostaje ogłoszenie i listę dozwolonych odpowiedzi, a zwraca ich skalibrowane
  prawdopodobieństwa (`POST /v1/systemone`). Sam `llama-cli` / `ollama run` dałby zwykły tekst, a nie te liczby.
  Potrzebny jest `basal-serve` przed llama.cpp albo GGUF z metadanymi decyzji (wariant A niżej).
* **GeForce 920M = Kepler (compute capability 3.5), 2 GB DDR3.** Ma to konsekwencje:
  * **Ollama** używa karty dopiero od compute capability 5.0, więc tu liczyłaby tylko na procesorze. Odpada.
  * **CUDA**: gotowe paczki llama.cpp są budowane z CUDA 12, a ta nie obsługuje Keplera. Sterownik dla Keplera
    kończy się na gałęzi R470 (Windows 474.xx), która ma CUDA najwyżej 11.4. Samodzielna kompilacja z CUDA 11.4 dla
    sm_35 jest możliwa, ale ciężka i niepewna (sam kod llama.cpp mógł już porzucić Keplera). To tylko awaryjnie.
  * **Vulkan**: sterownik 474.xx ma Vulkan 1.2, a llama.cpp ma gotowe paczki z Vulkanem. **Od tego zaczynamy.**
    Nie mam jak sprawdzić, czy backend Vulkan ruszy na Keplerze – pokaże to log z punktu 3.
  * Szybkość: 920M ma ok. 0,4 TFLOPS. W klasyfikacji liczy się głównie przetworzenie promptu (~500–900 tokenów),
    więc karta powinna być kilka razy szybsza niż 2 rdzenie i5-5200U. Odpowiedź da pomiar w kroku 3.

## Krok 1 – instalacja (Windows, cmd)

1. Sterownik i karta:
   ```
   nvidia-smi
   ```
   Na liście „GeForce 920M” z 2048 MiB. **Ostatni sterownik dla laptopowych Keplerów to 425.31 (04.2019)** - 47x.xx
   są tylko dla kart stacjonarnych (poprawka 06.11). 425.31 nie dodaje `nvidia-smi` do PATH:
   `"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"`. Ten sterownik ma Vulkan 1.1 i CUDA ≤ 10.1 -
   czy llama.cpp Vulkan ruszy, pokaże `--list-devices`; jeśli nie, test na procesorze (wariant C).

2. llama.cpp z Vulkanem. Ze strony https://github.com/ggml-org/llama.cpp/releases pobierz najnowszy plik
   `llama-b<numer>-bin-win-vulkan-x64.zip` i rozpakuj do `C:\Users\szymo\llama-vulkan`. Sprawdź, czy widzi kartę:
   ```
   C:\Users\szymo\llama-vulkan\llama-server.exe --list-devices
   ```
   Na liście musi być `Vulkan0: NVIDIA GeForce 920M`. Jeśli jest pusta, wklej mi wynik – zostanie CPU albo CUDA 11.4.

3. Model (Python 3.12, osobne środowisko, żeby nie ruszać analizatora ani Snipera):
   ```
   py -3.12 -m venv C:\Users\szymo\basal-env
   C:\Users\szymo\basal-env\Scripts\activate
   pip install -U huggingface_hub
   hf download Remek/basal-2.0-mini-GGUF --include "*Q5_K_M*" --local-dir C:\Users\szymo\basal-models
   dir C:\Users\szymo\basal-models
   ```
   Zapisz dokładną nazwę pliku `.gguf` z `dir` (dalej: `<plik>`).

4. Serwer – **wariant A** (najlżejszy dla 4 GB RAM: tylko llama-server, bez torch). basal dopisuje do kopii GGUF
   metadane decyzji, a llama-server sam odpowiada na `/v1/systemone`:
   ```
   pip install "basal @ https://github.com/rkinas/basal/archive/refs/tags/v2.5.5.tar.gz"
   basal-export-gguf --help
   ```
   Wklej mi wynik `--help`. Dokumentacja opisuje opcję `--systemone`, ale nie podaje pełnej składni, więc nie
   zgaduję jej. Potem uruchom serwer na karcie:
   ```
   C:\Users\szymo\llama-vulkan\llama-server.exe -m C:\Users\szymo\basal-models\<plik z --systemone> --host 127.0.0.1 --port 8000 -ngl 99 -c 2048 -np 1 -b 512 -ub 256 -t 2
   ```
   Opcje dobrane pod 2 GB VRAM: `-ngl 99` = wszystkie warstwy na kartę, `-c 2048` = kontekst wystarczający na tytuł
   + 1 200 znaków opisu (mała pamięć KV), `-np 1` = jedno zapytanie naraz, `-ub 256` = mniejszy bufor obliczeń,
   `-t 2` = 2 rdzenie i5-5200U. W logu szukaj `offloaded N/N layers to GPU` i rozmiarów buforów `Vulkan0`.
   Gdy zabraknie pamięci (błąd alokacji), daj `-ngl 20`: część warstw zostanie wtedy na procesorze.

   **Wariant B** (gdy A nie zadziała): llama-server na porcie 8080 z oryginalnym plikiem, a przed nim basal-serve.
   Ten wariant potrzebuje torch (wersja CPU wystarczy, ok. 300–500 MB RAM):
   ```
   pip install torch --index-url https://download.pytorch.org/whl/cpu
   pip install "basal @ https://github.com/rkinas/basal/archive/refs/tags/v2.5.5.tar.gz"
   C:\Users\szymo\llama-vulkan\llama-server.exe -m C:\Users\szymo\basal-models\<plik> --host 127.0.0.1 --port 8080 -ngl 99 -c 2048 -np 1 -b 512 -ub 256 -t 2
   basal-serve --model Remek/basal-2.0-mini --mode llamacpp --llamacpp-url http://127.0.0.1:8080 --port 8000
   ```
   (Drugie okno cmd dla basal-serve.) **Wariant C**, ostateczność (bez karty):
   `basal-serve --model Remek/basal-2.0-mini --mode eager --device cpu --port 8000`.

5. Sprawdzenie: `curl http://127.0.0.1:8000/health` (wariant B / C) albo strona `http://127.0.0.1:8000` (A),
   oraz `nvidia-smi` – ile MiB zajmuje llama-server (cel: ≤ 1,2–1,4 GB).

Uwaga na RAM (4 GB): przy teście najlepiej zatrzymaj watch (Sniper może działać). Po teście zamknij okna serwera.

## Kroki 2–3 (w zwykłym środowisku analizatora, drugie okno cmd)

```
cd C:\Users\szymo\analyse_data
python -m analyzer basal-sample --rodzina s23 --limit 40
python -m analyzer basal-test --plik "<ścieżka z poprzedniej komendy>"
```

`basal-sample` losuje oferty Samsunga S23 z opisem warstwowo: FE, Plus, Ultra, prawdopodobne akcesoria,
uszkodzenia, podróbki, zaprzeczenia w opisie i zwykłe. Drukuje je i zapisuje do `data\basal\s23_<czas>.jsonl`.
Opisy mają zamaskowane e-maile, telefony i linki.

`basal-test` wysyła każdą ofertę do basala i drukuje `tytuł -> etykieta -> pewność`, p(uszkodzony), p(akcesorium)
i czas. Potem dopisuje 8 krótkich przypadków z zaprzeczeniami i pułapkami (`[test]`, np. „S23 (nie FE!)”, „nie
uszkodzony, bez rys”, „etui do S23 Ultra”, „FE zamiast S23”, „Ultra Mod” = klon) z oczekiwaną etykietą, oznaczając
OK albo BŁĄD. Przy ofertach z bazy pokazuje, gdzie basal różni się od prostych reguł (`≠ reguły`). Na końcu:
czasy (średni, mediana, max, pierwsze zapytanie z rozgrzewką), VRAM (przed / szczyt, z `nvidia-smi`) i wynik
przypadków testowych. Wyniki trafiają do `data\basal\s23_<czas>_wyniki_<godz>.json` – ten plik albo wydruk
wyślij mi do oceny.

---

# Test na PC z GTX 1060 6 GB (Windows) – plan na 08.11

Ten PC służy tylko do testu, nie jako serwer. GTX 1060 (Pascal) ma CUDA, więc bierzemy gotowy llama.cpp z
**CUDA 12** (nie CUDA 13 – ta nie obsługuje już Pascala; nie Vulkan). 6 GB mieści i mini (1,5B, ~1,4 GB), i większy
basal-2.0 4,5B w Q5_K_M (~3,5 GB) – testujemy oba.

## A. Na laptopie-serwerze: próbka (tam jest baza)

```
cd C:\Users\szymo\analyse_data
git pull origin claude/gifted-volta-x1764p
python -m analyzer basal-sample --rodzina s23 --limit 40
```
Plik `C:\Users\szymo\category_analyzer\data\basal\s23_<czas>.jsonl` skopiuj na PC (pendrive / sieć), np. do
`C:\basal\s23.jsonl`.

## B. Na PC: sterownik i llama.cpp CUDA 12

1. `nvidia-smi` – „GeForce GTX 1060 6GB”, sterownik 5xx (jeśli starszy: najnowszy z nvidia.com).
2. Z https://github.com/ggml-org/llama.cpp/releases pobierz DWA pliki: **„Windows x64 (CUDA 12)”** i obok
   **„CUDA 12.4 DLLs”**. Rozpakuj OBA do tego samego folderu `C:\llama-cuda` (`tar -xf <zip> -C C:\llama-cuda`).
   Brak `VCRUNTIME140.dll` → https://aka.ms/vs/17/release/vc_redist.x64.exe.
3. `C:\llama-cuda\llama-server.exe --list-devices` → ma być `CUDA0: NVIDIA GeForce GTX 1060 6GB`.

## C. Na PC: Python, modele, basal

```
py -3.12 -m venv C:\basal-env
C:\basal-env\Scripts\activate
pip install -U huggingface_hub
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install "basal @ https://github.com/rkinas/basal/archive/refs/tags/v2.5.5.tar.gz"
hf download Remek/basal-2.0-mini-GGUF --include "*Q5_K_M*" --local-dir C:\basal-models\mini
hf download Remek/basal-2.0-4.5B-GGUF --include "*Q5_K_M*" --local-dir C:\basal-models\4.5b
dir C:\basal-models\mini C:\basal-models\4.5b
```
(4.5B ~3,5 GB do pobrania.) Do testu skryptem z analizatora: skopiuj folder `analyse_data` z laptopa na PC
(bez `data`) i w tym samym środowisku `pip install httpx python-dotenv` - `basal-test` nie potrzebuje bazy,
proxy ani reszty bibliotek Snipera (sprawdzone 07.11).

## D. Na PC: test mini (2 okna cmd + 1 do testu)

Okno 1 (model na karcie):
```
C:\llama-cuda\llama-server.exe -m C:\basal-models\mini\<plik>.gguf --host 127.0.0.1 --port 8080 -ngl 99 -c 4096 -np 1
```
Szukaj w logu `CUDA0: NVIDIA GeForce GTX 1060` i `offloaded N/N layers to GPU`.

Okno 2 (`C:\basal-env\Scripts\activate`):
```
basal-serve --model Remek/basal-2.0-mini --mode llamacpp --llamacpp-url http://127.0.0.1:8080 --port 8000
```
Okno 3 (w folderze `analyse_data`, środowisko z kroku C):
```
python -m analyzer basal-test --plik C:\basal\s23.jsonl
```

## E. Na PC: test 4.5B

Zamknij okna 1 i 2 (Ctrl+C) i uruchom z większym modelem:
```
C:\llama-cuda\llama-server.exe -m C:\basal-models\4.5b\<plik>.gguf --host 127.0.0.1 --port 8080 -ngl 99 -c 4096 -np 1
basal-serve --model Remek/basal-2.0-4.5B --mode llamacpp --llamacpp-url http://127.0.0.1:8080 --template-prefix off --port 8000
python -m analyzer basal-test --plik C:\basal\s23.jsonl
```
(`--template-prefix off` – dokumentacja basal wymaga go tylko dla 4.5B.)

## F. Podzespoły: liczba sztuk (07.11)

Te same okna serwera (mini albo 4.5B). Na laptopie: próbki, potem pliki na PC i test (każda rodzina osobno):
```
python -m analyzer basal-sample --rodzina ram --limit 30
python -m analyzer basal-sample --rodzina dyski --limit 30
python -m analyzer basal-sample --rodzina karty --limit 30
python -m analyzer basal-sample --rodzina procesory --limit 30
python -m analyzer basal-test --rodzina ram --plik C:\basal\ram.jsonl
```
(`--rodzina` przy `basal-test` musi być ta sama co przy próbce.) Od 07.11 `basal-sample` bierze **trudne przypadki językowe**: zaprzeczenia („bez artefaktów”), cena za sztukę, zestawy, część / pudełko / adapter zamiast rzeczy, zamiana / kupię, kopanie krypto, „lub / chyba”, inny model w opisie niż w tytule, opis po obcemu - w nawiasie przy ofercie lista pułapek. Dawne losowanie: `--zwykle`. Dodatkowe pytania: **ile sztuk za podaną cenę**
(1 / 2 / 3 / 4 / 5+ / nie wiadomo; „2x8 GB” = 2, „cena za sztukę, mam 4” = 1) i **czy cena jest za jedną sztukę
z kilku**. Wydruk: `-> etykieta -> pewność | sztuk: N (pewność)`, przy ofertach z bazy `sztuk ≠ reguły: N`
(porównanie z prostymi regułami), przy przypadkach testowych `sztuk OK / BŁĄD`. Karty mają w testach dwie prawdziwe
oferty z 06.11 (RTX 2060 Super „brak obrazu”, GTX 1070 „czerwony ekran”).

Do oceny wyślij oba pliki `..._wyniki_<godz>.json` (albo wydruki): etykiety, przypadki testowe OK / BŁĄD,
czasy, VRAM. Gdy `basal-serve --mode llamacpp` nie ruszy – wklej błąd; awaryjnie wariant A (`basal-export-gguf
--systemone`, wtedy llama-server sam na porcie 8000 i bez okna 2).
