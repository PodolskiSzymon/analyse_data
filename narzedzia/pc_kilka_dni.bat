@echo off
rem ===========================================================================================================
rem  PC z GTX 1060 - praca na kilka dni bez obsługi (2026-11-15):
rem    1. basal: powtórka testu v2 z poprawkami (45b_t2 przypadki testowe ~1 h, 45b_v3 całość ~5 h) + raporty
rem    2. model wizyjny Qwen2.5-VL-3B (llama.cpp): pudełko / napisy / 5G / pamięć na zdjęciach z próbki
rem  Basal i model wizyjny nie mieszczą się naraz w 6 GB - idą po kolei. Każdy krok wznawia się sam
rem  (--pomin-gotowe, plik wyników wizji dopisywany po każdej ofercie): po restarcie wystarczy uruchomić .bat jeszcze raz.
rem  ŚCIEŻKI PONIŻEJ SPRAWDŹ / POPRAW PRZED STARTEM.
rem ===========================================================================================================
set LLAMA=C:\llama-cuda\llama-server.exe
set BASAL_MODEL=C:\basal-models\4.5b\basal-2.0-4.5B-Q5_K_M.gguf
set BASAL_ENV=C:\basal-env\Scripts
set CODE=C:\analyse_data
set BASAL_DIR=D:\basal\v2
set PHOTOS=D:\photos
set ANALYZER_DB=F:\analyzer.db
rem próbka robiona tu, z kopii bazy i zdjęć na dysku (także sprzedane / usunięte) -> F:\vision\
set VISION_SAMPLE=F:\vision\telefony_uzywane.jsonl
if not exist "%CODE%\data" mkdir "%CODE%\data"
cd /d %CODE%
echo [%date% %time%] start > "%CODE%\data\pc_kilka_dni.log"

rem ---------------------------------------------------------------- 0. próbka do wizji (raz; potem pomijana)
if not exist "%VISION_SAMPLE%" "%BASAL_ENV%\python.exe" -m analyzer vision-sample --szukaj "" --kategoria phone,tablet --uzywane --limit 30000 --zdjecia 3 --zdjecia-dir "%PHOTOS%" --nazwa telefony_uzywane
echo [%date% %time%] próbka gotowa >> "%CODE%\data\pc_kilka_dni.log"

rem ---------------------------------------------------------------- 1. basal
echo === BASAL: uruchamiam llama-server i basal-serve ===
start "llama-basal" /min "%LLAMA%" -m "%BASAL_MODEL%" --host 127.0.0.1 --port 8080 -ngl 99 -c 4096
timeout /t 90 /nobreak
start "basal-serve" /min "%BASAL_ENV%\basal-serve.exe" --model Remek/basal-2.0-4.5B --mode llamacpp --llamacpp-url http://127.0.0.1:8080 --http-parallel 1 --template-prefix off --host 127.0.0.1 --port 8000
timeout /t 180 /nobreak
"%BASAL_ENV%\python.exe" -m analyzer basal-test --katalog "%BASAL_DIR%" --etykieta 45b_t2 --tylko-testowe --pomin-gotowe
"%BASAL_ENV%\python.exe" -m analyzer basal-raport --katalog "%BASAL_DIR%" --etykieta 45b_t2
"%BASAL_ENV%\python.exe" -m analyzer basal-test --katalog "%BASAL_DIR%" --etykieta 45b_v3 --pomin-gotowe
"%BASAL_ENV%\python.exe" -m analyzer basal-raport --katalog "%BASAL_DIR%" --etykieta 45b_v3
echo [%date% %time%] basal gotowy >> "%CODE%\data\pc_kilka_dni.log"
taskkill /fi "WINDOWTITLE eq basal-serve*" /t /f
taskkill /im llama-server.exe /f
timeout /t 20 /nobreak

rem ---------------------------------------------------------------- 2. model wizyjny
echo === WIZJA: uruchamiam llama-server z Qwen2.5-VL-3B ===
start "llama-wizja" /min "%LLAMA%" -hf ggml-org/Qwen2.5-VL-3B-Instruct-GGUF --host 127.0.0.1 --port 8081 -ngl 99 -c 8192
timeout /t 180 /nobreak
"%BASAL_ENV%\python.exe" -m analyzer vision-test --plik "%VISION_SAMPLE%" --model qwen --api openai --zdjecia 3 --zdjecia-dir "%PHOTOS%"
echo [%date% %time%] wizja gotowa >> "%CODE%\data\pc_kilka_dni.log"
taskkill /im llama-server.exe /f
echo === KONIEC - wyniki: %BASAL_DIR%\raport_45b_*.txt i obok %VISION_SAMPLE% plik *_qwen.txt ===
