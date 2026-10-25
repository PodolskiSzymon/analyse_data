# Serwer: Sniper + watch + pilot z telefonu

Wszystko poniżej robisz **na serwerze** (Windows, `cmd`). Analizator (`analyse_data`) już tam jest.

## 1. Sniper z GitHuba na serwer

```bat
cd C:\Users\szymo
git clone https://github.com/PodolskiSzymon/unreachable_sniper
cd unreachable_sniper
python -m venv .venv
.venv\Scripts\python -m pip install -r sniper\requirements.txt
.venv\Scripts\python -m playwright install chromium
.venv\Scripts\patchright install chrome
```

Repo jest prywatne – przy `git clone` Windows otworzy okno logowania do GitHuba (zaloguj się raz).

Pliki, których **nie ma na GitHubie** (sekrety, sesja) – przenieś z komputera **pendrive'em** (nie przez GitHub ani
mail; Dysk Google tylko na chwilę i potem usuń, bo `.env` ma hasła i klucze):

| z komputera | na serwer | po co |
|---|---|---|
| `unreachable_sniper\sniper\.env` | `C:\Users\szymo\unreachable_sniper\sniper\.env` | proxy, AI, ntfy, mail – **bez tego nie ruszy** |
| `unreachable_sniper\sniper\guidelines.md` | to samo miejsce | Twoje wytyczne (jeśli zmieniane) |
| `unreachable_sniper\sniper\logs\` | to samo miejsce | historia ocen i zakupów (zalecane) |
| `unreachable_sniper\profiles\scraper\` | to samo miejsce | zalogowana sesja bota (albo krok niżej) |

Sesja konta Vinted (tylko przy auto-zakupie), jeśli nie przeniosłeś `profiles\scraper\`:

```bat
.venv\Scripts\python -m sniper.account_session --login
```

Próba: `start.bat` w folderze `unreachable_sniper` → Sniper ma ruszyć; zamknij go (Ctrl+C).

⚠ **Nie uruchamiaj Snipera jednocześnie na komputerze i na serwerze** – dwa razy więcej ruchu przez proxy i ryzyko
podwójnego zakupu. Gdy na serwerze działa, wyłącz go na komputerze.

## 1a. Sniper na wszystkie kategorie (D5, 2026-10-25)

Nowa wersja Snipera jest na gałęzi `claude/hopeful-faraday-n33quh` (na `main` jest stara, bez `push.py` i `start.bat`).
Na serwerze, w `cmd`:

```bat
cd C:\Users\szymo\unreachable_sniper
git fetch origin
git checkout claude/hopeful-faraday-n33quh
git pull
.venv\Scripts\python -m pip install -r sniper\requirements.txt
```

Jeśli `git checkout` odmówi („Your local changes … guidelines.md”): `git checkout -- sniper\guidelines.md` i ponów
(Twoja wersja wytycznych jest już na tej gałęzi).

Potem:
1. `.env` – wzór `ENV_SERWER.example` w tym repo: jeden plik, wklejony w **oba** miejsca
   (`unreachable_sniper\sniper\.env` i `analyse_data\sniper\.env`), z Twoimi danymi w miejscach `<...>`.
2. Wytyczne i zakresy cen do Snipera (od razu, nie czekając na automat):
   ```bat
   cd C:\Users\szymo\analyse_data
   python -m analyzer sniper-guide
   ```
   Kopiuje `laptop.md`, `phone.md`, … i `catalogs.json` do `unreachable_sniper\sniper\guides` (z
   `ANALYZER_SNIPER_GUIDES_DIR`). Potem automat robi to sam 2× w tygodniu; Sniper łapie zmiany bez restartu.
3. Telefon: `restart sniper`. W `log sniper` na starcie: `ZWIADOWCA START | 3580 (laptopy) … ×3; 3661 (telefony) …`
   i `[AI] Wytyczne per kategoria (...): laptop, phone, …`.

Co robi teraz Sniper: skanuje 7 katalogów po kolei (laptopy co ~30 s, reszta co ~90 s przy skanie co 10 s – transfer
proxy jak dotąd), w podzespołach / nośnikach / akcesoriach bierze tylko karty, RAM i dyski (reszta bez pobierania
szczegółów), odrzuca bez AI oferty wyraźnie droższe niż „max zakup” z tabeli (bramka ×1,25), a pozostałe ocenia AI
według wytycznych **tej kategorii** (reguła zysku: 40% → 300 zł … 20% → 1 100 zł). Powiadomienie: kategoria, cena,
max zakup, zysk, marża, dni do sprzedaży.

## 2. Ustawienia pilota

1. Wylosuj nazwę tematu sterowania (działa jak hasło):
   ```bat
   python -c "import secrets; print('pilot-' + secrets.token_urlsafe(16))"
   ```
2. Dopisz do `C:\Users\szymo\analyse_data\sniper\.env` (ten od analizatora):
   ```
   ANALYZER_CONTROL_TOPIC=pilot-<to, co wypisała komenda>
   ANALYZER_CONTROL_PIN=1234
   SNIPER_DIR=C:\Users\szymo\unreachable_sniper
   ANALYZER_CONTROL_AUTOSTART=watch,sniper
   ```
   * `ANALYZER_CONTROL_PIN` – opcjonalny; wtedy każde polecenie zaczynasz od PIN-u: `1234 status`.
   * `ANALYZER_CONTROL_AUTOSTART` – co ma się włączyć samo po starcie pilota (np. po restarcie Windows); puste = nic.
   * `SNIPER_NTFY_TOPIC` **zostaw stary** – na niego idą okazje ze Snipera.
   * Pilot odpowiada zawsze w swoim temacie `pilot-...` (tam, gdzie piszesz polecenia – jak czat).
   * Opcjonalnie `ANALYZER_NTFY_TOPIC=pilot-<to samo co wyżej>` – wtedy także alarm „brak sprzedaży” i automat
     analizatora przyjdą do tematu pilota (bez tej linii idą na stary temat razem z okazjami).
3. Uruchom pilota: dwuklik `C:\Users\szymo\analyse_data\remote.bat`. Na telefon przyjdzie „Pilot: uruchomiony”.
4. Autostart: Win+R → `shell:startup` → wklej tam **skrót** do `remote.bat`.
   ⚠ Jeśli masz w autostarcie skrót do `watch.bat` – **usuń go**: `watch` uruchamia teraz pilot (inaczej działałyby
   dwa `watch` na jednej bazie).

## 3. Telefon (aplikacja ntfy)

1. W aplikacji ntfy: **+** → subskrybuj temat `pilot-...` (ten z punktu 2.1).
2. Wejdź w ten temat i wpisz wiadomość na dole ekranu, np.:

| polecenie | co robi |
|---|---|
| `status` | co działa i od kiedy |
| `start watch` / `stop watch` / `restart watch` | analizator |
| `start sniper` / `stop sniper` / `restart sniper` | Sniper |
| `start all` / `stop all` | oba naraz |
| `log watch` / `log sniper` | ostatnie linie logu |
| `wytyczne` | aktualne wytyczne Snipera (wszystkie kategorie z `sniper\guides` + `guidelines.md`) w jednym pliku jako załącznik na telefon + kopia na Dysk Google, jeśli ustawione `ANALYZER_GDRIVE_DIR=G:\Mój dysk\program` (folder z aplikacji Dysk Google na serwerze) |
| `pomoc` | lista poleceń |

(Z PIN-em: `1234 stop sniper`. Działa też po polsku: „włącz sniper”, „zatrzymaj watch”.)

Pilot pilnuje programów: jeśli włączony program się wyłączy (błąd, brak internetu), po 60 s uruchomi go ponownie
i przyśle powiadomienie z końcówką logu. Logi: `C:\Users\szymo\category_analyzer\data\remote\watch.log`,
`...\remote\sniper.log`.

Zatrzymanie z telefonu kończy proces od razu (razem z przeglądarką Snipera) – dane są bezpieczne: baza zapisuje się
w transakcjach, a przerwane przejście `watch` wznawia się przy następnym starcie.
