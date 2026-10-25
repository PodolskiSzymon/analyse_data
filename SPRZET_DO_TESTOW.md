# Sprzęt do sprawdzania kupionych rzeczy (2026-10-25)

Ceny to **orientacyjne ceny używanych części na OLX / Allegro Lokalnie** – przed zakupem sprawdź aktualne.
Krótka wersja („Do testu: …”) przychodzi w powiadomieniu ntfy i w mailu o każdej okazji (Sniper, `categories.TEST_KITS`),
razem z tym, co AI zauważy w konkretnej ofercie (np. „karta wymaga 12V-2x6”).

## Laptopy, telefony, tablety – nic nie trzeba

Nie kupujemy uszkodzonych, więc test = włączyć i sprawdzić:
* **laptop**: ekran (białe / czarne tło – martwe piksele, plamy), klawiatura, touchpad, porty USB / HDMI, Wi-Fi,
  kamera, bateria (`powercfg /batteryreport` w Windows), ładowarka w zestawie; brak hasła BIOS i konta firmowego;
* **telefon / tablet**: wylogowany iCloud / konto Google (blokada aktywacji!), bateria (iPhone: Ustawienia → Bateria
  → Kondycja), aparaty, głośniki, mikrofon, Face ID / odcisk palca, ładowanie.

## Konsole – telewizor albo monitor z HDMI

Plus pad, jeśli nie ma go w zestawie (najtańszy używany ~100–150 zł). Sprawdź: uruchamia się, czyta płyty
(wersja z napędem), łączy z siecią, konto sprzedawcy wylogowane, brak bana (spróbuj wejść do sklepu / zagrać online).

## Karty graficzne – stanowisko A (~1 000–1 300 zł raz)

**Kompatybilność:** karta graficzna PCIe działa z **każdym** procesorem i płytą z gniazdem PCIe x16 – nie trzeba
kilku procesorów. Wyjątki, które ten zestaw już pokrywa:
* karty RTX 40 / 50 często mają złącze **12V-2x6 / 12VHPWR** → zasilacz ATX 3.0/3.1 z tym kablem (albo przejściówka
  od karty – używane często jej nie mają);
* **Intel Arc** wymaga Resizable BAR (włącz w BIOS – B450 z Ryzenem 3000 / 5000 to ma po aktualizacji BIOS-u);
* bardzo stare karty (sprzed ~2014) bez UEFI – włącz CSM w BIOS-ie (B450 ma).

| część | propozycja (najtaniej) | ~cena używane |
|---|---|---|
| płyta główna | AM4 **B450** (MSI B450-A Pro, ASUS Prime B450M…) | 150–250 zł |
| procesor | **Ryzen 5 3600** (albo 5500) – bez grafiki, obraz idzie z testowanej karty | 200–300 zł |
| RAM | 2× 8 GB DDR4 3200 | 150–250 zł |
| zasilacz | **850 W ATX 3.0/3.1 z 12V-2x6**, 80+ Gold – NOWY (testujesz nieznane karty; dla RTX 5090 – 1 000 W) | 400–500 zł (nowy) |
| dysk | SSD SATA 240–256 GB z Windows 11 (bez aktywacji wystarczy) | 60–80 zł |
| reszta | kabel HDMI / DP, monitor albo TV; chłodzenie Wraith z boxa; „ramka testowa” albo karton | 0–80 zł |

**Test karty (~40 min):**
1. **GPU-Z** – czy układ, VRAM i BIOS zgadzają się z opisem (wykrywa podróbki / przerobione karty).
2. **FurMark 2** albo **OCCT** (test GPU) 20–30 min – brak artefaktów, wyłączeń; temperatura GPU < ~85 °C,
   hot spot / memory junction < ~100–105 °C (HWiNFO).
3. **3DMark Time Spy** (darmowa wersja demo w Steam) – wynik zbliżony do średniej dla tego modelu.
4. Wentylatory (szum, grzechotanie), wszystkie wyjścia obrazu.

## Pamięci RAM

| rodzaj (z tytułu) | czym | koszt |
|---|---|---|
| **DDR4 DIMM** (PC) | stanowisko A | 0 zł (masz) |
| **DDR5 DIMM** (PC) | **stanowisko B**: płyta LGA1700 **DDR5** (B660 / B760) + **Pentium G7400** (ma grafikę – nie trzeba karty); zasilacz i SSD ze stanowiska A | ~500–650 zł |
| **DDR4 SO-DIMM** (laptop) | przejściówka SO-DIMM → DIMM na stanowisku A (najtaniej; czasem kapryśna) albo mini PC z DDR4 SO-DIMM (Lenovo ThinkCentre M720q / M920q, Dell OptiPlex Micro) | 30–40 zł / 300–450 zł |
| **DDR5 SO-DIMM** (laptop) | laptop z DDR5 SO-DIMM, który akurat masz na sprzedaż; inaczej mini PC z DDR5 SO-DIMM | 0 zł / 450–600 zł |

Na początek wystarczy stanowisko A + przejściówka SO-DIMM; stanowisko B dopiero, gdy będziesz kupować DDR5 do PC.

**Test RAM:** **MemTest86** (darmowy, bootowalny pendrive) – minimum 1 pełny przebieg (16–32 GB ≈ 1–2 h), 0 błędów;
**CPU-Z** zakładka SPD – producent, pojemność i częstotliwość jak w opisie. Zestaw (2×) testuj razem i każdą kość osobno.

## Dyski SSD – przejściówka USB (~30–80 zł)

* **NVMe / M.2**: obudowa M.2 NVMe → USB-C (np. z układem RTL9210B, obsługuje też M.2 SATA) ~50–80 zł;
* **SATA 2,5"**: przejściówka SATA → USB 3.0 ~30 zł.

**Test dysku:** **CrystalDiskInfo** – stan „Dobry”, godziny pracy, ilość zapisanych danych (TBW) vs gwarancja,
realokowane sektory 0; **h2testw** – zapis i odczyt całej pojemności (wykrywa podróbki „2 TB” z 64 GB w środku);
**CrystalDiskMark** – prędkości zbliżone do specyfikacji (przez USB NVMe ograniczy do ~1 000 MB/s – to normalne).

## Podsumowanie – co kupić od razu

1. Stanowisko A (karty + DDR4): ~1 000–1 300 zł.
2. Przejściówka SO-DIMM → DIMM DDR4 + obudowa NVMe → USB-C + przejściówka SATA → USB: ~120–150 zł.
3. Później, jeśli DDR5 do PC się opłaca: stanowisko B ~500–650 zł.

Programy (wszystkie darmowe): GPU-Z, FurMark 2, OCCT, HWiNFO, 3DMark demo, MemTest86, CPU-Z, CrystalDiskInfo,
CrystalDiskMark, h2testw.
