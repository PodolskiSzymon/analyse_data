@echo off
rem ===========================================================================================================
rem  PC z GTX 1060 (2026-11-19): porównanie trybu „tylko pudełko” (6 zdjęć po 512 / 384 / 320 px) z pełnym testem
rem  na 100 ofertach, w których pełny test widział pudełko, i 40 z tekstem „bez pudełka”. ~140 ofert x 3 rozmiary.
rem  19.11: po jednym zdjeciu wyszlo gorzej (42% / 55%) - teraz 4 zdjecia naraz po 768 i 1024 px (kontekst 16384).
rem  Wynik: F:\vision\telefony_uzywane_qwen_porownanie_pojedynczo.txt (wznawia się po przerwaniu). Ścieżki jak pc_kilka_dni.bat.
rem ===========================================================================================================
set LLAMA=C:\llama-cuda\llama-server.exe
set BASAL_ENV=C:\basal-env\Scripts
set CODE=C:\analyse_data
set PHOTOS=D:\photos
set ANALYZER_DB=F:\analyzer.db
set VISION_SAMPLE=F:\vision\telefony_uzywane.jsonl
cd /d %CODE%
rem 19.11: Pillow zmniejsza zdjecia przed wyslaniem do modelu - bez niej szly w pelnej rozdzielczosci (wolno, bledy 400)
"%BASAL_ENV%\python.exe" -m pip install -q pillow
taskkill /im llama-server.exe /f >nul 2>&1
start "llama-wizja" /min "%LLAMA%" -hf ggml-org/Qwen2.5-VL-3B-Instruct-GGUF --host 127.0.0.1 --port 8081 -ngl 99 -c 16384
timeout /t 120 /nobreak
"%BASAL_ENV%\python.exe" -m analyzer vision-porownaj --plik "%VISION_SAMPLE%" --model qwen --api openai --zdjecia 4 --zdjecia-dir "%PHOTOS%" --rozmiary 768,1024 --ile 100 --bez 40
taskkill /im llama-server.exe /f
pause
