@echo off
rem Pilot z telefonu (ntfy): start / stop / status watch i Snipera. Opis: PILOT.md.
rem Skrot do tego pliku w autostarcie (Win+R -> shell:startup) = pilot dziala po restarcie Windows.
cd /d %~dp0
:loop
python -m analyzer remote
echo [%date% %time%] pilot zakonczyl dzialanie - ponowny start za 30 s (Ctrl+C, aby przerwac)
timeout /t 30 /nobreak >nul
goto loop
