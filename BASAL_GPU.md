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
Okno 3 (w folderze `analyse_data`, środowisko z kroku C) - wszystkie próbki naraz (rodzina z nazwy pliku,
`--etykieta` trafia do nazwy wyników):
```
for %f in (D:\basal\*.jsonl) do python -m analyzer basal-test --plik "%f" --etykieta mini
```

## E. Na PC: test 4.5B

Zamknij okna 1 i 2 (Ctrl+C) i uruchom z większym modelem:
```
C:\llama-cuda\llama-server.exe -m C:\basal-models\4.5b\basal-2.0-4.5B-Q5_K_M.gguf --host 127.0.0.1 --port 8080 -ngl 99 -c 4096 -np 1
basal-serve --model Remek/basal-2.0-4.5B --mode llamacpp --llamacpp-url http://127.0.0.1:8080 --http-parallel 1 --template-prefix off --host 127.0.0.1 --port 8000
for %f in (D:\basal\*.jsonl) do python -m analyzer basal-test --plik "%f" --etykieta 45b
```
Kilka ofert naraz (więcej pracy dla karty, wyższa przepustowość - przydatne przy masowym przeglądzie bazy; dla
bramkarza w Sniperze liczy się czas jednej oferty): llama-server `-np 4 -c 16384` (4 sloty po 4096), basal-serve
`--http-parallel 4`, basal-test `--rownolegle 4`; podsumowanie ma „ofert na minutę” i „naraz”.
(`--template-prefix off` – dokumentacja basal wymaga go tylko dla 4.5B.)

## F. Rodziny wariantów (07.11 – sedno testu)

Każda rodzina to JEDEN model z wariantami, które tytuł często pomija albo podaje źle (jak S23 Ultra / FE / Plus):

| `--rodzina` | kategoria | pytania do basala (wybór z listy + pewność) |
|---|---|---|
| `s23` | telefony | etykieta: S23 / Plus / Ultra / FE / uszkodzony / akcesorium / podróbka |
| `gtx1060` | karty | model (1060 czy „jak 1060”), **VRAM 3 / 5 / 6 GB**, stan, liczba sztuk |
| `rtx3060` | karty | **3060 czy 3060 Ti**, **VRAM 8 / 12 GB**, stan, liczba sztuk |
| `ddr4` | RAM (od 07.11 wszystkie typy) | **typ DDR2 i starsze / DDR3 / 4 / 5**, **taktowanie znamionowe** (do 1333, 1600…3600, 3733–4600, 4800 / 5200 / 5600, 6000+; PC3-12800 = 1600, PC4-21300 = 2666, „pracowały na 2133”), forma PC / laptop / serwer, stan, liczba sztuk |
| `nvme` | dyski | **970 EVO / EVO Plus / PRO / 980 / 980 PRO / 990 EVO / 990 EVO Plus / 990 PRO**, pojemność, stan, liczba sztuk |
| `i5` | procesory | model i5-8400…14600, **końcówka brak / F / K / KF / T** („i5 9400 f”, „to nie F”), stan, liczba sztuk |

Wszędzie też tak/nie: „czy cena jest za jedną sztukę z kilku”. Odpowiedź `nie_wiadomo` jest poprawna, gdy ogłoszenie
naprawdę nie mówi wariantu (basal ma NIE zgadywać).

Próbka (`basal-sample`) bierze najpierw oferty, gdzie **tytuł nie podaje wariantu** („tytuł bez: vram (jest w
opisie)”), **opis zmienia wariant** („opis zmienia: mhz”), potem pułapki językowe (zaprzeczenia, cena za sztukę,
zestawy, „jak GTX 1060”, „pomyłka w tytule”, XMP / „pracowały na”, obcy język). Przykłady z bazy: „Gainward GTX 1060
3072MB” (3 GB w MB), „Geforce 1060 3GT OC”, „Corsair Vengeance RGB Light Enhancement Kit (DDR4)” (atrapy bez
pamięci!), „Kingston 4GB DDR3L … 4 sticks + 1 opened”.

Wydruk `basal-test`: przy każdej ofercie odpowiedzi z pewnością; `≠ reguły: X` (regex z tytułu + opisu mówi co innego),
`basal wie (X), reguły nie` (wariant tylko z kontekstu); przy przypadkach testowych `OK` / `BŁĄD (oczekiwane X)`.
Podsumowanie: trafność per pytanie na przypadkach testowych, zgodność z regułami, czasy, VRAM.

Przypadki testowe dostają cenę typową dla rodziny (części / uszkodzone - niższą) i stan „Bardzo dobry” (07.11: bez
ceny i stanu basal uciekał w `nie_wiadomo` / `inna_rzecz`). Podsumowanie ma też „pewność ≥ 70%”: ile odpowiedzi
pewnych i niepewnych zgadza się ze wzorcem (oczekiwane albo reguły) - podstawa progu bramkarza.

**Wyniki mini na GTX 1060 (07.11):** ~0,7–0,9 s na ofertę, karta ~1,7 GB VRAM. Model / wariant podany w tekście -
bardzo dobrze (RTX 3060 / Ti 30/30, Samsung NVMe 26/26, pojemność 24/24); odpowiedzi z pewnością ≥ 70% prawie zawsze
zgodne (typ RAM 12/12, VRAM 15/15, model dysku 18/18), błędy skupiają się w niepewnych. Słabo: taktowanie RAM
(brakowało DDR3 / DDR5 w odpowiedziach), liczba sztuk („Dual”, „2X”), przypadki testowe bez ceny. Poprawione 07.11;
s23 wywalał się na znaku U+2028 w opisie (odczyt próbki).
GTX 1060: model 29/30, VRAM 17/17 + 5 trafnych tam, gdzie reguły widzą sprzeczność („lepsza niż wersja 3GB”), „3GT”
= 3 GB; wszystkie pewne (≥ 70%) odpowiedzi o model / VRAM zgodne (26/26, 19/19). i5: dawna lista modeli (8400+)
nie obejmowała 17 z 30 ofert (6500, 7400, 3570, 11500, 14500...) - rozszerzona do 2.-14. generacji; końcówka (F / K)
słabo (pewność zwykle < 50%, często „K” bez powodu) - opis pytania z przykładami; błędy pewne: „sam wiatrak” jako
sprawny procesor, procesor + płyta jako sprawna (nie zestaw) - opisy stanu poprawione.

**Mini po poprawkach testu (07.11, 14:38):** karta pracuje (Menedżer zadań „Cuda” 94–96%, VRAM 1,7 GB), 46–122 ofert
na minutę. Pewne (≥ 70%) odpowiedzi: model karty / dysku / procesora, VRAM, pojemność, typ RAM, wersja S23 -
praktycznie zawsze trafne (np. NVMe model 25/25, pojemność 25/25, typ RAM 19/19, VRAM 20/20 i 16/16, i5 model
24/26 - dwie „niezgodności” to listy procesorów, gdzie myliła się reguła; S23 20/22). Słabe: taktowanie RAM (DDR2
800 / 1066 i kody PC3 → „nie wiadomo” z wysoką pewnością), końcówka i5 (nigdy ≥ 70%), liczba sztuk („Ventus”,
„x2 cena za sztukę” → 2). Reguły porównawcze poprawione (S23: „etui gratis” w opisie ≠ akcesorium, „S23 + zegarek” ≠
Plus; RAM: „non-ECC” ≠ serwer, „desktop … not for laptops (SO-DIMM)” = PC).

**4.5B (07.11, 14:52):** VRAM ~4,0–4,1 GB, 15–44 ofert na minutę (~3× wolniej niż mini). Lepszy niż mini: taktowanie
RAM (wzorzec 21/26 vs 14/26), typ RAM 26/26, końcówka i5 27/28 (mini 20/28), liczba sztuk z wysoką pewnością
i trafnie (NVMe 30/32, RTX 30/31, GTX 28/32), VRAM RTX 27/28. Gorzej: model RTX 3060 - przy zwykłej 3060 odpowiadał
„nie wiadomo” (18 z 34, także z pewnością ~80%) - pytanie poprawione („bez Ti w nazwie = zwykła 3060”). Pewne błędy:
naklejka PC4-2133 przy tytule 3200 → 3200, „cena za sztukę, mam 4 kości” → 4. Taktowania DDR2/DDR3 jako odpowiedzi
800 / 1066 / 1333 (zamiast „do 1333”). Q8_0 4.5B nie zmieści się pewnie w 6 GB i nie da zauważalnej różnicy.

**Wykorzystanie GPU:** Menedżer zadań domyślnie pokazuje wykres „3D”, a llama.cpp liczy na „Cuda” - wtedy widać
~0–2%. Sprawdzenie w czasie testu: `"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe" --query-gpu=utilization.gpu,memory.used --format=csv -l 1`
(albo w Menedżerze kliknąć nazwę małego wykresu i wybrać „Cuda” / „Compute_0”). Karta pracuje zrywami (ułamek
sekundy na ofertę), resztę czasu zajmują basal-serve (Python) i kolejne zapytania.

Do oceny wyślij oba pliki `..._wyniki_<godz>.json` (albo wydruki): etykiety, przypadki testowe OK / BŁĄD,
czasy, VRAM. Gdy `basal-serve --mode llamacpp` nie ruszy – wklej błąd; awaryjnie wariant A (`basal-export-gguf
--systemone`, wtedy llama-server sam na porcie 8000 i bez okna 2).
