# Basal 2.0 Mini na GeForce 920M – krok 1 (środowisko), kroki 2–3 (próbka i test)

Plan użytkownika (06.11): regex na tytule → przy wątpliwościach lokalny model decyzyjny basal na GPU → mediany.
Ten plik to krok 1. Kroki 2–3: `python -m analyzer basal-sample` i `basal-test` (`analyzer/basal_poc.py`).
**Po kroku 3 czekamy na wyniki użytkownika** – dopiero potem regexy rodzin i kaskada (kroki 4–5).

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
