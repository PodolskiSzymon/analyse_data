# human_client – makieta klienta Vinted „jak człowiek” (bez proxy)

Plik programu: `human_client/client.py`. Testy (bez sieci): `python -m pytest human_client -q` (12 testów).

**Zasada działania:** przeglądarka (Twój Chrome/Edge, **stały profil**) służy tylko do zdobywania i odświeżania sesji,
**rzadko** (co 15–60 min albo po 401/403). Właściwe zapytania idą zwykłym HTTP przez `curl_cffi`, z **odciskiem TLS
Chrome** i z **tymi samymi** nagłówkami (`User-Agent`, `sec-ch-ua`), które wysyła Twoja przeglądarka, w **ludzkim
tempie**. Proxy nie ma: ruch idzie z Twojego łącza i Twojego IP.

> ⚠ To jest **makieta**: robi kilka stron katalogu i zapisuje je do `human_client/out/`. Nie jest podłączona do
> `analyzer` (ten dalej używa `sniper/session.py` + proxy). Zbieranie danych automatem jest wbrew regulaminowi
> Vinted. Bez proxy ewentualna blokada trafia w **Twoje domowe IP i Twoje konto**. Jeśli wkleisz ciastka
> zalogowanego konta, każde zapytanie idzie jako Ty. Bezpieczniej: ciastka **gościa** (niezalogowana karta), bo do
> katalogu logowanie nie jest potrzebne.

---

## 0. Instalacja i pierwsze uruchomienie

```bat
cd C:\Users\szymo\analyse_data
git pull
pip install curl_cffi playwright patchright
copy human_client\config.example.json human_client\config.json
copy human_client\secrets.example.json human_client\secrets.json
notepad human_client\secrets.json          & rem wklej tokeny (punkt 1)
python -m human_client.client --dry-run --pages 200   & rem symulacja tempa, bez sieci
python -m human_client.client --refresh-only          & rem otwiera przeglądarkę, zapisuje state.json
python -m human_client.client --pages 3               & rem 3 strony katalogu w ludzkim tempie
```

`secrets.json`, `config.json`, `state.json`, `profile\` i `out\` są w `.gitignore` i nie trafiają do repo. Nikomu
ich nie wysyłaj (ani do czatu).

---

## 1. Tokeny (x-csrf-token, x-anon-id, ciastka) – skąd je wziąć

Vinted używa trzech rzeczy:

| Co | Gdzie | Po co |
|---|---|---|
| `x-csrf-token` | nagłówek zapytań do `/api/...` (też `<meta name="csrf-token">` w stronie) | ochrona przed CSRF; wymagany przy części zapytań |
| `x-anon-id` | nagłówek zapytań; to samo co ciastko `anon_id` | identyfikator gościa / urządzenia |
| ciastka: `access_token_web`, `refresh_token_web`, `anon_id`, `v_udt`, `datadome`, … | nagłówek `Cookie` | sesja; `access_token_web` to krótko ważny JWT, `refresh_token_web` służy stronie do wydania nowego, `datadome` to ciastko ochrony antybotowej |

**Jak je skopiować (Chrome/Edge):**
1. Otwórz `https://www.vinted.pl/catalog/3580`. Najlepiej w profilu, którego potem użyje program (punkt 3), albo
   w zwykłym oknie.
2. F12 → zakładka **Network (Sieć)** → filtr `items` → odśwież stronę (F5).
3. Kliknij zapytanie `items?page=1...` (domena `api.vinted.pl`) → **Headers → Request Headers**.
4. Skopiuj do `secrets.json`:
   * wartość `x-csrf-token` (np. `75f6c9fa-dc8e-4e52-a000-e09dd4084b3e`) → pole `"x-csrf-token"`,
   * wartość `x-anon-id` (np. `0e5c3a1b-...`) → pole `"x-anon-id"`,
   * **całą** wartość nagłówka `cookie` (długi tekst `anon_id=...; access_token_web=eyJ...; ...`) → pole `"cookie"`.

   Szybciej: prawy klik na zapytaniu → **Copy → Copy as cURL (bash)**, wklej do Notatnika, wartości są w liniach
   `-H 'x-csrf-token: …'` i `-b '…'` (to ciastka).

Przykład `secrets.json` (wartości zmyślone):
```json
{
  "x-csrf-token": "75f6c9fa-dc8e-4e52-a000-e09dd4084b3e",
  "x-anon-id": "0e5c3a1b-7d2f-4c55-9a1e-2b6f0c8d9e11",
  "cookie": "anon_id=0e5c3a1b-7d2f-4c55-9a1e-2b6f0c8d9e11; access_token_web=eyJhbGciOi...; refresh_token_web=eyJhbGciOi...; v_udt=...; datadome=..."
}
```

**Wklejać, czy pobierać z przeglądarki?** Program robi obie rzeczy i tak jest najlepiej:
* wklejone ciastka służą tylko jako **zasiew przy pierwszym starcie** (gdy nie ma jeszcze `state.json`). Program
  wkłada je do profilu przeglądarki i wchodzi na vinted.pl;
* od tej chwili **profil przeglądarki trzyma własne, aktualne ciastka**. Przy każdym odświeżeniu strona sama
  wymienia `access_token_web` (dzięki „staremu” `refresh_token_web`) i `datadome`, a program je odczytuje
  (`context.cookies()`), razem z tokenem CSRF z zapytań strony.
* `x-csrf-token` / `x-anon-id` z `secrets.json` są tylko **zapasem**, gdy strona sama ich nie wyśle.

Kiedy wkleić od nowa: gdy usuniesz `profile\` i `state.json` albo gdy `--refresh-only` loguje
`tokeny: brak` i dostajesz 401/403 mimo odświeżenia.

Czas ważności: log pokazuje `access_token_web ważny do HH:MM` (odczyt pola `exp` z JWT, funkcja `jwt_expiry`).
Odświeżanie ustaw **krócej** niż ten czas.

---

## 2. Przeglądarka, w której ma być użyty token

W `config.json` → `"browser"`:

| Chcesz | Ustaw |
|---|---|
| Google Chrome zainstalowany w systemie (zalecane) | `"channel": "chrome", "executable_path": ""` |
| Microsoft Edge | `"channel": "msedge", "executable_path": ""` |
| konkretny plik przeglądarki | `"channel": "", "executable_path": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"` |
| Edge z pliku | `"executable_path": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe"` |
| Brave / inny Chromium | `"executable_path": "C:\\Program Files\\BraveSoftware\\Brave-Browser\\Application\\brave.exe"` |

Ścieżkę sprawdzisz, wpisując w tej przeglądarce `chrome://version` (lub `edge://version`), pole **„Ścieżka pliku
wykonywalnego”**. Firefox nie działa (inny silnik; Patchright obsługuje tylko Chromium).

Dlaczego prawdziwy Chrome, a nie Chromium Playwrighta: odcisk (wersja, kodeki, `sec-ch-ua` z „Google Chrome”)
wygląda jak u zwykłego użytkownika. `"headless": false` = widoczne okno. Tryb headless zdradza się m.in. napisem
`HeadlessChrome` w User-Agent (sprawdzone w teście tej makiety). Program używa **Patchrighta**, jeśli jest
zainstalowany (łata wycieki protokołu CDP), a inaczej zwykłego Playwrighta.

---

## 3. Stały profil przeglądarki

Profil = folder z ciastkami, localStorage, cache i historią. Stały profil sprawia, że Vinted widzi **powracającą**
przeglądarkę, a nie co chwilę nową, czystą. W `config.json`:

```json
"profile_dir": "human_client/profile"
```

* Pierwsze uruchomienie tworzy folder (`launch_persistent_context`), każde kolejne go używa.
* Możesz „oswoić” profil ręcznie. Zatrzymaj program, a potem uruchom tę przeglądarkę z tym profilem:
  ```bat
  "C:\Program Files\Google\Chrome\Application\chrome.exe" --user-data-dir="C:\Users\szymo\analyse_data\human_client\profile"
  ```
  Pochodź po Vinted, zaakceptuj ciasteczka (baner RODO), zamknij okno. Program zastanie profil z historią.
* **Nie** wskazuj swojego codziennego profilu Chrome (`%LOCALAPPDATA%\Google\Chrome\User Data`). Jest zablokowany,
  gdy Chrome jest otwarty, a program mógłby go zepsuć. Zrób osobny.
* Jeden profil = jeden program naraz (dwa procesy na jednym profilu kończą się błędem).
* Reset: usuń `human_client\profile\` i `human_client\state.json`, wklej świeże tokeny.

---

## 4. Rzadkie odświeżanie sesji

```json
"refresh_minutes": [15, 60]
```

* Po każdym odświeżeniu program losuje, za ile minut zrobi następne (tu 15–60 min; np. `[20, 20]` = zawsze 20 min,
  `[45, 90]` = rzadziej).
* Odświeżenie poza harmonogramem następuje tylko po **401/403** (sesja wygasła albo Datadome chce nowego ciastka),
  raz na zapytanie. Drugi 401/403 z rzędu nie otwiera przeglądarki w kółko.
* `state.json` przetrwa restart programu. Jeśli sesja jest świeża, program **nie otwiera przeglądarki wcale**
  (test `test_existing_state_is_reused`).
* `"keep_open": false` zamyka przeglądarkę po odświeżeniu (na 4 GB RAM to ważne). `true` trzyma ją otwartą
  (szybsze odświeżenia, ~300–500 MB RAM stale).
* Przy odświeżeniu przeglądarka zachowuje się jak człowiek: strona główna, kilka ruchów myszą i przewinięć, potem
  `warmup_url` (katalog), łącznie ~10–20 s.

Przykłady: tylko po błędach `[600, 600]` (co 10 h, w praktyce gdy 401/403); bardzo ostrożnie `[15, 25]`.

---

## 5. Ludzkie tempo i zachowanie

```json
"pacing": {
  "gap_s": [2.0, 6.0],
  "read_chance": 0.15,
  "read_s": [8.0, 25.0],
  "break_every_min": [25, 35],
  "break_s": [60, 240],
  "active_hours": [8, 23],
  "max_requests_per_session": 300
}
```

| Pole | Co robi | Przykład |
|---|---|---|
| `gap_s` | zwykły odstęp; rozkład trójkątny (najczęściej ~3 s, czasem 6 s), a nie równy rytm | `[1.5, 4]` szybciej, `[4, 12]` wolniej |
| `read_chance`, `read_s` | z tym prawdopodobieństwem dłuższa pauza, jak przy czytaniu oferty | `0.15` → co ~7. zapytanie 8–25 s |
| `break_every_min`, `break_s` | co ~pół godziny przerwa 1–4 min | `[40, 60]`, `[300, 900]` = przerwa na kawę |
| `active_hours` | poza tymi godzinami program śpi (start losowo do 30 min po godzinie) | `[7, 24]`; `[0, 24]` = bez snu |
| `max_requests_per_session` | po tylu zapytaniach koniec przebiegu | `300` |

* **429** (za dużo zapytań) → czeka 5, potem 15, potem 30 min, a przy czwartym razie kończy na dziś.
* Nagłówki jak z przeglądarki (`referer`, `origin`, `sec-fetch-*`, `x-next-app`) z cURL-a w `sniper/config.py`.
* Bez proxy **tempo jest najważniejszą ochroną**: wszystkie zapytania idą z jednego domowego IP. Zacznij od
  `--pages 3`, potem zwiększaj.
* Podgląd tempa bez sieci: `python -m human_client.client --dry-run --pages 200` (wirtualny zegar, log z każdym
  odstępem, łączny czas i liczba odświeżeń).

---

## 6. Zgodny odcisk TLS w zapytaniach HTTP

Każde połączenie HTTPS zaczyna się od `ClientHello`: lista szyfrów, rozszerzeń, kolejność, HTTP/2 SETTINGS. Z tego
liczy się odcisk (JA3/JA4). `httpx`/`requests` (Python, OpenSSL) mają odcisk inny niż Chrome. Ochrona widzi wtedy
„User-Agent mówi Chrome, a TLS mówi Python”, a to klasyczny sygnał bota (także dla ciastka `datadome`, które jest
wiązane z odciskiem).

`curl_cffi` to curl z łatkami (curl-impersonate), który wysyła `ClientHello` i HTTP/2 jak prawdziwa przeglądarka:

```python
from curl_cffi import requests
s = requests.Session(impersonate="chrome", trust_env=False)   # trust_env=False: bez proxy z systemu
r = s.get("https://api.vinted.pl/svc-catalogue/items", params={...}, headers={...})
```

W `config.json`: `"http": {"impersonate": "chrome"}`.
* `"chrome"` = najnowszy profil Chrome znany zainstalowanej wersji `curl_cffi`. Można podać konkretny, np.
  `"chrome136"`, a dla Edge `"edge101"`. Lista: `python -c "from curl_cffi.requests import BrowserType; print([b.value for b in BrowserType])"`.
* **Spójność:** odcisk TLS „Chrome”, `User-Agent` i `sec-ch-ua` **Twojej** przeglądarki (program odczytuje je
  z `navigator.userAgent` / `navigator.userAgentData` przy odświeżeniu). Dlatego zalecany jest Chrome
  (`"channel": "chrome"`) + `"impersonate": "chrome"`. Wersja TLS w `curl_cffi` może być o kilka wersji starsza
  niż Twój Chrome. Odcisk TLS zmienia się między wersjami rzadko, więc zwykle to nie przeszkadza; regularnie
  aktualizuj `pip install -U curl_cffi`.
* Sprawdzenie odcisku (z Twojego komputera, raz): `python -c "from curl_cffi import requests; print(requests.get('https://tls.browserleaks.com/json', impersonate='chrome').json().get('ja4'))"`
  i porównaj z `https://tls.browserleaks.com/json` otwartym w Chrome. Powinny być takie same albo bardzo podobne.

---

## 7. Co jest w logu (przykład)

```
09:00:01 [BROWSER] patchright, profil C:\...\human_client\profile, chrome
09:00:01 [BROWSER] Zasiane ciastka z secrets.json: 9
09:00:17 [SESJA] Ciastek 14, tokeny: x-anon-id, x-csrf-token, UA: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWeb, access_token_web ważny do 11:00, następne odświeżenie za 37 min
09:00:18 [KATALOG] strona 1: HTTP 200, ofert 96, 38.2 KB
09:00:18 [TEMPO] odstęp 3.4 s
09:00:22 [KATALOG] strona 2: HTTP 200, ofert 96, 37.9 KB
09:00:22 [TEMPO] czytanie 14.2 s
...
09:01:10 [KONIEC] ofert 288 -> C:\...\human_client\out\catalog_20261106_090110.json
```

Plik wynikowy nie zawiera danych sprzedawców (pole `user` jest usuwane, RODO).

## 8. Co dalej (gdy makieta zadziała)

* Jeśli `curl_cffi` + profil działa stabilnie bez proxy, tę samą sesję (`state.json`) można podłączyć do
  `analyzer` zamiast `sniper/session.py` (osobny krok, po decyzji; teraz analyzer działa przez Evomi).
* Zmiany endpointów i parametrów tylko na podstawie cURL z F12, jak w reszcie projektu.
