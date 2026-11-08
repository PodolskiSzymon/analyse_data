# Rodziny basala v2 – prawie cały rynek z bazy (07.11, poprawki po teście 08.11)

Basal ma być „bramkarzem” przed medianami: z ogłoszenia (tytuł, opis, formularz Vinted) ustala DOKŁADNY wariant
i stan, żeby oferta trafiła do właściwej grupy cenowej. Rodzina = jeden model bazowy (albo linia) ze wszystkimi
wariantami, które sprzedawcy mylą albo pomijają. Kod: `analyzer/basal_families.py` (pytania, reguły, próbki,
przypadki testowe), `analyzer/basal_specs.py` (warianty, pojemności, RAM, procesory, karty – z bazy 07.11),
`analyzer/basal_report.py` (raport). Uruchamianie: `BASAL_GPU.md` §G (PC z GTX 1060) i §H (serwer z kartą 8 GB,
4.5B Q8_0).

## Skąd rodziny i warianty

Przejrzana cała baza (279 tys. ofert, 202 tys. z opisem): model z formularza Vinted (`model_nav`), tytuły, pojemności
z formularza, „8/256” z opisów, procesory / karty / RAM / dyski laptopów (`extract.py`), chipsety płyt, numery
procesorów. Warianty z ≥ 3–5 ofertami + znane, które sprzedawcy mylą (S23 FE, Switch V1 / V2, PS5 Slim Digital
z dokupionym napędem, RX 580 2048SP, „MacBook Air 2020” = Intel albo M1, iPad „9” = 9. generacja ≠ 9,7").
Przypisanie oferty: wzorzec rodziny w tytule → model / platforma z formularza → rodzina zbiorcza („inne”).
Pokrycie: laptopy 100% (z „laptopy_inne”), telefony 93%, tablety 86%, konsole i części – prawie wszystko.

Reguły (regex) to tylko porównanie dla basala – na całej bazie zgadzają się z modelem z formularza w 95–99%
(iPhone, Galaxy S), w laptopach i tabletach mniej, bo formularz Vinted nie ma wariantów (np. „IdeaPad 3” dla
Slim 3, „Pavilion 15” dla Pavilion Gaming).

## Co basal dostaje i o co jest pytany

Stan dla basala: kategoria (ogólna – „telefony komórkowe”, „pamięć RAM”; od 08.11 nie nazwa rodziny, bo podpowiadała
odpowiedź: „Kingston … do PC” w rodzinie „RAM do laptopa” wychodził laptop), tytuł, cena, stan z formularza, **pola formularza Vinted z ostrzeżeniem
„bywa błędny”** (model, pamięć, bateria, blokada SIM, platforma konsoli, RAM / dysk / procesor / ładowarka laptopa),
opis (do 1200 znaków, e-mail / telefon / linki zamaskowane). Pytania – wybór jednej odpowiedzi z listy + pewność:

| kategoria | pytania (zależnie od rodziny) |
|---|---|
| telefony | model (wariant), pamięć, RAM, 4G / 5G, bateria (Apple), blokada (konto / simlock), stan (idealny / ślady / pęknięty / usterka / na części), co sprzedawane (telefon / kilka / akcesorium / część / pudełko / podróbka / kupię); tak/nie: nieoryginalne części (Apple) |
| tablety | model (generacja / rozmiar / chip), pamięć, RAM, Wi-Fi / LTE, rysik / klawiatura, blokada, stan, co sprzedawane |
| konsole | model, pamięć, napęd (PS5 / Xbox), dock (Switch), pady, gry, przeróbka (CFW / RGH / HEN), stan, co sprzedawane; oryginał / zamiennik (pady) |
| laptopy | model, generacja (HP G, Lenovo Gen), procesor = linia (i3 … i9, Ultra, Ryzen 3 … 9) + generacja procesora (pełne listy, 08.11; MacBooki – lista chipów Apple), karta, RAM, dysk, rok (MacBook), stan, blokada (BIOS / iCloud / MDM), zasilacz, co sprzedawane |
| karty | model (chip + Ti / Super / XT / 2048SP), VRAM, typ pamięci (GDDR5 / 6 / 6X, DDR4), stan, sztuki (z odpowiedzią „cena za sztukę”) |
| RAM | typ (DDR2 - DDR5), taktowanie znamionowe, forma (PC / laptop / serwer), pojemność razem, stan, sztuki |
| dyski | model, pojemność, typ (NVMe / SATA / HDD 3,5" / 2,5" / zewnętrzny), stan (zdrowie, bad sectory), sztuki |
| procesory | model (numer), końcówka (F / K / KF / T / X / X3D / G ...), stan (wygięte piny, z płytą), sztuki |
| płyty | chipset, DDR3 / 4 / 5, Wi-Fi, format (ATX / mATX / ITX), stan (płyta laptopa / TV = inna płyta) |
| zestawy | procesor, RAM, co w zestawie (płyta + CPU / + RAM / cały komputer), stan |

Odpowiedź `nie_wiadomo` jest poprawna, gdy ogłoszenie naprawdę nie mówi wariantu – basal ma NIE zgadywać. Od 08.11
pytania nie mają liczb w przykładach, które są też odpowiedziami („8/256” → basal odpowiadał 8 GB RAM przy „12/256”,
„2x8 GB = 16 GB” → 16 GB przy „Kit 8GB (2x4GB)”), a „Kupię” / „tylko zamiana” jest sprawdzane na początku pytania „co”.

## Próbka

`basal-sample --wszystkie --limit 24`: jedno przejście bazy, w każdej rodzinie po kolei z każdej grupy:
pułapki wariantu (tytuł bez wariantu, opis zmienia wariant), pułapki formularza („256 MB” zamiast 256 GB, model
w formularzu ≠ tytuł, dysk w polu RAM, inna platforma), każdy wariant (`wariant: X` – żeby każdy był w próbce),
pułapki językowe (zaprzeczenia, uszkodzenia, cena za sztukę, zestawy, porównania, obcy język). Do tego przypadki
testowe z oczekiwanymi odpowiedziami (1116, po 3–7 na rodzinę; od 08.11 jak prawdziwe ogłoszenia: nazwy wariantów zamiast
etykiet grup – `example_name`, `basal_specs.EXAMPLES` –, pamięć / VRAM / procesor zgodne z wariantem, bez trzech sprzecznych
modeli naraz; „nie Pro Max”, wariant tylko w opisie, etui / pudełko
zamiast telefonu, iCloud, simlock, replika, „Digital + dokupiony napęd”, hasło BIOS, matryca do laptopa, cena za
sztukę, radiator bez karty, wygięte piny, płyta z laptopa ...). 173 rodziny × 24 = 4152 oferty + 1116 testów.

## Wyniki i poprawki

`basal-raport` per rodzina i pytanie: T = przypadki testowe OK, R = zgodność z regułami, P = pewne (≥ 70%) zgodne;
zbiorczo per pytanie; lista pewnych błędów. Kolejność poprawek: pewne błędy (basal pewny i zły – najgroźniejsze
dla bramkarza) → pytania z niską trafnością pewnych odpowiedzi → etykiety, których basal nie używa → przypadki
z „nie_wiadomo” mimo wariantu w tekście. Wynik docelowy: dla każdej rodziny lista pytań, którym bramkarz ufa
(pewne ≥ 95% trafne), reszta zostaje regułom / medianom. Wyniki pierwszego testu (07/08.11) i poprawki: `BASAL_GPU.md` §I.

## Lista rodzin

Generowana: `python -m analyzer basal-rodziny` (po zmianie `basal_specs.py` wkleić na nowo).

### Telefony (58 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `iphone_x` | Apple iPhone X / XS / XS Max / XR | 4: iPhone X, iPhone XS, iPhone XS Max, iPhone XR | model, pamiec, bateria, blokada, stan, co |
| `iphone_11` | Apple iPhone 11 / 11 Pro / 11 Pro Max | 3: iPhone 11, iPhone 11 Pro, iPhone 11 Pro Max | model, pamiec, bateria, blokada, stan, co |
| `iphone_12` | Apple iPhone 12 mini / 12 / 12 Pro / 12 Pro Max | 4: iPhone 12 mini, iPhone 12, iPhone 12 Pro, iPhone 12 Pro Max | model, pamiec, bateria, blokada, stan, co |
| `iphone_13` | Apple iPhone 13 mini / 13 / 13 Pro / 13 Pro Max | 4: iPhone 13 mini, iPhone 13, iPhone 13 Pro, iPhone 13 Pro Max | model, pamiec, bateria, blokada, stan, co |
| `iphone_14` | Apple iPhone 14 / 14 Plus / 14 Pro / 14 Pro Max | 4: iPhone 14, iPhone 14 Plus, iPhone 14 Pro, iPhone 14 Pro Max | model, pamiec, bateria, blokada, stan, co |
| `iphone_15` | Apple iPhone 15 / 15 Plus / 15 Pro / 15 Pro Max | 4: iPhone 15, iPhone 15 Plus, iPhone 15 Pro, iPhone 15 Pro Max | model, pamiec, bateria, blokada, stan, co |
| `iphone_16` | Apple iPhone 16e / 16 / 16 Plus / 16 Pro / 16 Pro Max | 5: iPhone 16e, iPhone 16, iPhone 16 Plus, iPhone 16 Pro, iPhone 16 Pro Max | model, pamiec, bateria, blokada, stan, co |
| `iphone_17` | Apple iPhone 17e / 17 / Air / 17 Pro / 17 Pro Max / 18 Pro / 18 Pro Max | 7: iPhone 17e, iPhone 17, iPhone Air (17 Air), iPhone 17 Pro, iPhone 17 Pro Max, iPhone 18 Pro … (+1) | model, pamiec, bateria, blokada, stan, co |
| `iphone_se` | Apple iPhone SE (1. gen 2016 / 2. gen 2020 / 3. gen 2022) | 3: iPhone SE 1. generacji (2016), iPhone SE 2. generacji (2020), iPhone SE 3. generacji (2022) | model, pamiec, bateria, blokada, stan, co |
| `iphone_stare` | Apple iPhone 8 i starsze (8 / 8 Plus / 7 / 6s / 6 / 5s / SE nie / 4 / 3G / 2G) | 16: iPhone 8, iPhone 8 Plus, iPhone 7, iPhone 7 Plus, iPhone 6s, iPhone 6s Plus … (+10) | model, pamiec, bateria, blokada, stan, co |
| `galaxy_s20` | Samsung Galaxy S20 / S20+ / S20 Ultra / S20 FE | 4: Galaxy S20, Galaxy S20+, Galaxy S20 Ultra, Galaxy S20 FE | model, pamiec, ram, siec, blokada, stan, co |
| `galaxy_s21` | Samsung Galaxy S21 / S21+ / S21 Ultra / S21 FE | 4: Galaxy S21, Galaxy S21+, Galaxy S21 Ultra, Galaxy S21 FE | model, pamiec, ram, blokada, stan, co |
| `galaxy_s22` | Samsung Galaxy S22 / S22+ / S22 Ultra | 3: Galaxy S22, Galaxy S22+, Galaxy S22 Ultra | model, pamiec, ram, blokada, stan, co |
| `galaxy_s23` | Samsung Galaxy S23 / S23+ / S23 Ultra / S23 FE | 4: Galaxy S23, Galaxy S23+, Galaxy S23 Ultra, Galaxy S23 FE | model, pamiec, ram, blokada, stan, co |
| `galaxy_s24` | Samsung Galaxy S24 / S24+ / S24 Ultra / S24 FE | 4: Galaxy S24, Galaxy S24+, Galaxy S24 Ultra, Galaxy S24 FE | model, pamiec, ram, blokada, stan, co |
| `galaxy_s25` | Samsung Galaxy S25 / S25+ / S25 Ultra / S25 FE / S25 Edge | 5: Galaxy S25, Galaxy S25+, Galaxy S25 Ultra, Galaxy S25 FE, Galaxy S25 Edge | model, pamiec, ram, blokada, stan, co |
| `galaxy_s26` | Samsung Galaxy S26 / S26+ / S26 Ultra | 4: Galaxy S26, Galaxy S26+, Galaxy S26 Ultra, Galaxy S26 Edge | model, pamiec, ram, blokada, stan, co |
| `galaxy_s_stare` | Samsung Galaxy S6 - S10 (S7 edge, S8+, S9+, S10e, S10+, S10 Lite, S10 5G) | 13: Galaxy S6, Galaxy S6 edge, Galaxy S7, Galaxy S7 edge, Galaxy S8, Galaxy S8+ … (+7) | model, pamiec, ram, blokada, stan, co |
| `galaxy_note` | Samsung Galaxy Note 8 - 20 (9, 10, 10+, 10 Lite, 20, 20 Ultra) | 7: Galaxy Note 8, Galaxy Note 9, Galaxy Note 10, Galaxy Note 10+, Galaxy Note 10 Lite, Galaxy Note 20 … (+1) | model, pamiec, ram, blokada, stan, co |
| `galaxy_z_flip` | Samsung Galaxy Z Flip (1. gen / 5G, Flip3 - Flip8, Flip7 FE) | 8: Galaxy Z Flip (1. generacja, 2020; też „Z Flip 5G”), Galaxy Z Flip3, Galaxy Z Flip4, Galaxy Z Flip5, Galaxy Z Flip6, Galaxy Z Flip7 … (+2) | model, pamiec, ram, blokada, stan, co |
| `galaxy_z_fold` | Samsung Galaxy Fold / Z Fold2 - Fold8 | 8: Galaxy Fold (1. generacja, 2019), Galaxy Z Fold2, Galaxy Z Fold3, Galaxy Z Fold4, Galaxy Z Fold5, Galaxy Z Fold6 … (+2) | model, pamiec, blokada, stan, co |
| `galaxy_a0_a1` | Samsung Galaxy A0x / A1x (A05s, A12 ... A17, 4G / 5G) | 18: Galaxy A01, Galaxy A02s, Galaxy A03, Galaxy A03s, Galaxy A04, Galaxy A04s … (+12) | model, pamiec, ram, siec, blokada, stan, co |
| `galaxy_a2_a3` | Samsung Galaxy A2x / A3x (A21s ... A37, 4G / 5G) | 17: Galaxy A20e, Galaxy A20s, Galaxy A21s, Galaxy A22, Galaxy A23, Galaxy A24 … (+11) | model, pamiec, ram, siec, blokada, stan, co |
| `galaxy_a5_a7` | Samsung Galaxy A5x / A7x (A50 ... A57, A52s, A70 ... A72, A80) | 13: Galaxy A50, Galaxy A51, Galaxy A52, Galaxy A52s, Galaxy A53, Galaxy A54 … (+7) | model, pamiec, ram, siec, blokada, stan, co |
| `galaxy_m` | Samsung Galaxy M (M12 ... M55) | 14: Galaxy M12, Galaxy M13, Galaxy M15, Galaxy M21, Galaxy M22, Galaxy M23 … (+8) | model, pamiec, ram, siec, blokada, stan, co |
| `redmi_note_9_10` | Xiaomi Redmi Note 9 / 10 (Pro, S, T, 5G) i Mi Note 10 | 10: Redmi Note 9, Redmi Note 9 Pro, Redmi Note 9S, Redmi Note 9T, Redmi Note 10, Redmi Note 10 Pro … (+4) | model, pamiec, ram, siec, blokada, stan, co |
| `redmi_note_11` | Xiaomi Redmi Note 11 (S, Pro, Pro+, 5G) | 4: Redmi Note 11, Redmi Note 11S, Redmi Note 11 Pro, Redmi Note 11 Pro+ | model, pamiec, ram, siec, blokada, stan, co |
| `redmi_note_12` | Xiaomi Redmi Note 12 (S, Pro, Pro+, 4G / 5G) | 4: Redmi Note 12, Redmi Note 12S, Redmi Note 12 Pro, Redmi Note 12 Pro+ | model, pamiec, ram, siec, blokada, stan, co |
| `redmi_note_13` | Xiaomi Redmi Note 13 (Pro, Pro+, 4G / 5G) | 3: Redmi Note 13, Redmi Note 13 Pro, Redmi Note 13 Pro+ | model, pamiec, ram, siec, blokada, stan, co |
| `redmi_note_14` | Xiaomi Redmi Note 14 (S, Pro, Pro+, 4G / 5G) | 4: Redmi Note 14, Redmi Note 14S, Redmi Note 14 Pro, Redmi Note 14 Pro+ | model, pamiec, ram, siec, blokada, stan, co |
| `redmi_note_15_17` | Xiaomi Redmi Note 15 / 17 (Pro, Pro+, Pro Max) | 6: Redmi Note 15, Redmi Note 15 Pro, Redmi Note 15 Pro+, Redmi Note 17, Redmi Note 17 Pro, Redmi Note 17 Pro Max | model, pamiec, ram, siec, blokada, stan, co |
| `redmi_liczbowe` | Xiaomi Redmi 9 - 15 i A (A, C, T) | 18: Redmi 5A, Redmi 7A, Redmi 9, Redmi 9A, Redmi 9AT, Redmi 9C … (+12) | model, pamiec, ram, siec, blokada, stan, co |
| `xiaomi_10_11` | Xiaomi Mi 10 / 11 (Pro, Lite, T, T Pro, Lite 5G NE, Ultra, i) | 13: Xiaomi 10, Xiaomi 10 Pro, Xiaomi 10 Lite, Xiaomi 10T, Xiaomi 10T Pro, Xiaomi 10T Lite … (+7) | model, pamiec, ram, siec, blokada, stan, co |
| `xiaomi_12_13` | Xiaomi 12 / 13 (X, Lite, Pro, T, T Pro, Ultra) | 12: Xiaomi 12, Xiaomi 12X, Xiaomi 12 Lite, Xiaomi 12 Pro, Xiaomi 12T, Xiaomi 12T Pro … (+6) | model, pamiec, ram, blokada, stan, co |
| `xiaomi_14_15` | Xiaomi 14 / 15 (Pro, T, T Pro, Ultra) | 10: Xiaomi 14, Xiaomi 14 Pro, Xiaomi 14 Ultra, Xiaomi 14T, Xiaomi 14T Pro, Xiaomi 15 … (+4) | model, pamiec, ram, blokada, stan, co |
| `xiaomi_17` | Xiaomi 17 (Pro, Pro Max, T, T Pro, Ultra) | 6: Xiaomi 17, Xiaomi 17 Pro, Xiaomi 17 Pro Max, Xiaomi 17 Ultra, Xiaomi 17T, Xiaomi 17T Pro | model, pamiec, ram, blokada, stan, co |
| `poco` | Xiaomi Poco (X3 ... X7, F2 ... F7, M, C) | 24: Poco X3 NFC, Poco X3 Pro, Poco X4 Pro, Poco X5, Poco X5 Pro, Poco X6 … (+18) | model, pamiec, ram, blokada, stan, co |
| `pixel_6_7` | Google Pixel 6 / 7 (a, Pro) | 6: Pixel 6, Pixel 6a, Pixel 6 Pro, Pixel 7, Pixel 7a, Pixel 7 Pro | model, pamiec, ram, blokada, stan, co |
| `pixel_8_9` | Google Pixel 8 / 9 (a, Pro, Pro XL, Pro Fold) | 8: Pixel 8, Pixel 8a, Pixel 8 Pro, Pixel 9, Pixel 9a, Pixel 9 Pro … (+2) | model, pamiec, ram, blokada, stan, co |
| `pixel_10_11` | Google Pixel 10 / 11 (a, Pro, Pro XL, Pro Fold) | 8: Pixel 10, Pixel 10a, Pixel 10 Pro, Pixel 10 Pro XL, Pixel 10 Pro Fold, Pixel 11 … (+2) | model, pamiec, ram, blokada, stan, co |
| `huawei_p` | Huawei P10 - P60 / Pura 70 - 80 (Lite, Lite E, Pro, Pro+, Pocket, Ultra) | 20: Huawei P10, Huawei P10 Lite, Huawei P20, Huawei P20 Lite, Huawei P20 Pro, Huawei P30 … (+14) | model, pamiec, ram, siec, blokada, stan, co |
| `huawei_mate_nova` | Huawei Mate (10 - 50, Lite, Pro, X) / Nova (5T - 13, SE, i) | 17: Mate 10 Lite, Mate 10 Pro, Mate 20, Mate 20 Lite, Mate 20 Pro, Mate 20 X … (+11) | model, pamiec, ram, blokada, stan, co |
| `honor_liczbowe` | Honor 50 - 600 (Lite, Smart, Pro) | 16: Honor 50, Honor 50 Lite, Honor 70, Honor 70 Lite, Honor 90, Honor 90 Lite … (+10) | model, pamiec, ram, blokada, stan, co |
| `honor_magic` | Honor Magic 4 - 8 (Lite, Pro) i Magic V (składane) | 14: Honor Magic 4 Lite, Honor Magic 4 Pro, Honor Magic 5 Lite, Honor Magic 5 Pro, Honor Magic 6 Lite, Honor Magic 6 Pro … (+8) | model, pamiec, ram, blokada, stan, co |
| `honor_x` | Honor X5 - X8 (a, b, c, d, Plus) | 15: Honor X5 Plus, Honor X5c, Honor X5c Plus, Honor X6, Honor X6a, Honor X6b … (+9) | model, pamiec, ram, siec, blokada, stan, co |
| `moto_edge` | Motorola Edge 20 - 70 (Lite, Neo, Fusion, Pro, Ultra) i Edge 2024 / 2025 | 24: Edge 20, Edge 20 Lite, Edge 20 Pro, Edge 30, Edge 30 Neo, Edge 30 Fusion … (+18) | model, pamiec, ram, blokada, stan, co |
| `moto_g` | Motorola Moto G (G04 ... G86, Power, 5G) | 28: Moto G04, Moto G05, Moto G06, Moto G06 Power, Moto G13, Moto G14 … (+22) | model, pamiec, ram, siec, blokada, stan, co |
| `moto_razr` | Motorola Razr (40, 50, 60, Ultra) i klasyczne V3 / V8 | 9: Razr 40, Razr 40 Ultra, Razr 50, Razr 50 Ultra, Razr 60, Razr 60 Ultra … (+3) | model, pamiec, ram, blokada, stan, co |
| `oneplus` | OnePlus 6 - 15 (Pro, T, R) | 19: OnePlus 6, OnePlus 6T, OnePlus 7, OnePlus 7 Pro, OnePlus 7T, OnePlus 8 … (+13) | model, pamiec, ram, blokada, stan, co |
| `oneplus_nord` | OnePlus Nord (1 - 5, 2T, CE, CE Lite, N10) | 13: OnePlus Nord (1. generacja, 2020), Nord 2, Nord 2T, Nord 3, Nord 4, Nord 5 … (+7) | model, pamiec, ram, blokada, stan, co |
| `nothing_phone` | Nothing Phone (1), (2), (2a), (2a) Plus, (3), (3a), (3a) Pro | 7: Phone (1), Phone (2), Phone (2a), Phone (2a) Plus, Phone (3), Phone (3a) … (+1) | model, pamiec, ram, blokada, stan, co |
| `realme` | Realme (8 - 16, Pro, Pro+, GT, C) | 32: Realme 8, Realme 8 Pro, Realme 9, Realme 9 Pro, Realme 9 Pro+, Realme 10 … (+26) | model, pamiec, ram, siec, blokada, stan, co |
| `oppo` | Oppo (A, Reno, Find) | 24: Oppo A17, Oppo A38, Oppo A54, Oppo A57s, Oppo A60, Oppo A74 … (+18) | model, pamiec, ram, siec, blokada, stan, co |
| `sony_xperia` | Sony Xperia (1 / 5 / 10 Mark II - V, XZ) | 16: Xperia 1 II, Xperia 1 III, Xperia 1 IV, Xperia 1 V, Xperia 5 II, Xperia 5 III … (+10) | model, pamiec, blokada, stan, co |
| `vivo` | Vivo (V, X, Y) | 10: Vivo V21, Vivo V23, Vivo V40 SE, Vivo V50 Lite, Vivo X80 Lite, Vivo X200 … (+4) | model, pamiec, ram, blokada, stan, co |
| `nokia_klasyczne` | Nokia klasyczne i ich nowe wersje (3310, 8800, 6310, 8110, 3210, N-Gage ...) | 16: Nokia 3310 oryginalna (2000), Nokia 3310 (2017, 3G / 4G - nowa wersja), Nokia 8800 (klasyczna 2005), Nokia 8800 Sirocco, Nokia 8800 Arte (zwykła), Nokia 8800 Carbon Arte … (+10) | model, blokada, stan, co |
| `vertu` | Vertu (oryginał albo replika) | 5: Vertu Signature, Vertu Aster, Vertu Constellation, Vertu Ascent, Vertu Signature Touch | model, blokada, stan, co |
| `telefony_wzmocnione` | Telefony wzmocnione (CAT, Ulefone, Blackview, Oukitel, Doogee, Cubot, Hammer) | 8: CAT (S42, S62, S75 ...), Ulefone Armor / Power Armor, Blackview (BV ...), Oukitel (WP ...), Doogee (S ...), Cubot KingKong … (+2) | model, pamiec, ram, siec, blokada, stan, co |

### Tablety (13 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `ipad` | Apple iPad (podstawowy: 5. - 11. generacja, 9,7" / 10,2" / 10,9" / A16) | 8: iPad 2 / 3 / 4 (2011 - 2012), iPad 5. generacji (9,7", 2017), iPad 6. generacji (9,7", 2018), iPad 7. generacji (10,2", 2019), iPad 8. generacji (10,2", 2020), iPad 9. generacji (10,2", 2021) … (+2) | model, pamiec, lacznosc, akcesoria, blokada, stan, co |
| `ipad_air` | Apple iPad Air (1 - 5, Air 11" / 13" M2, M3 i nowsze) | 10: iPad Air 1 (2013), iPad Air 2 (2014), iPad Air 3 (10,5", 2019), iPad Air 4 (10,9", 2020, A14), iPad Air 5 (2022, M1), iPad Air 11" (2024, M2) … (+4) | model, pamiec, lacznosc, akcesoria, blokada, stan, co |
| `ipad_pro` | Apple iPad Pro (9,7" / 10,5" / 11" / 12,9" / 13", 2015 - 2025, M1 / M2 / M4 / M5) | 15: iPad Pro 9,7" (2016), iPad Pro 10,5" (2017), iPad Pro 12,9" 1. / 2. gen. (2015 / 2017), iPad Pro 11" 1. gen. (2018), iPad Pro 12,9" 3. gen. (2018), iPad Pro 11" 2. gen. (2020) … (+9) | model, pamiec, lacznosc, akcesoria, blokada, stan, co |
| `ipad_mini` | Apple iPad mini (1 - 7) | 7: iPad mini 1 (2012), iPad mini 2 (2013, Retina), iPad mini 3 (2014), iPad mini 4 (2015), iPad mini 5 (2019), iPad mini 6 (2021, A15, USB-C) … (+1) | model, pamiec, lacznosc, akcesoria, blokada, stan, co |
| `galaxy_tab_a` | Samsung Galaxy Tab A (A 7.0 / 8.0 / 10.1, A7, A7 Lite, A8, A9, A9+, A11) | 11: Galaxy Tab A 7.0 (2016), Galaxy Tab A 8.0 (2017 / 2019), Galaxy Tab A 10.1 (2016 / 2019), Galaxy Tab A 10.5 (2018), Galaxy Tab A7, Galaxy Tab A7 Lite … (+5) | model, pamiec, ram, lacznosc, akcesoria, blokada, stan, co |
| `galaxy_tab_s` | Samsung Galaxy Tab S (S6 Lite, S7 FE, S7 - S11, Plus, Ultra, FE, FE+) | 21: Galaxy Tab S5e, Galaxy Tab S6, Galaxy Tab S6 Lite, Galaxy Tab S7, Galaxy Tab S7+, Galaxy Tab S7 FE … (+15) | model, pamiec, ram, lacznosc, akcesoria, blokada, stan, co |
| `lenovo_tab` | Lenovo Tab (M7 - M11, P11, P12, Yoga Tab, Idea Tab) | 12: Lenovo Tab M8 (Gen 2 / 3 / 4), Lenovo Tab M9, Lenovo Tab M10 HD, Lenovo Tab M10 FHD Plus / Plus (Gen 2 / Gen 3), Lenovo Tab M10 (zwykły, Gen 1 - 3), Lenovo Tab M11 … (+6) | model, pamiec, ram, lacznosc, akcesoria, blokada, stan, co |
| `tablety_huawei_honor_xiaomi` | Huawei MatePad / MediaPad, Honor Pad, Xiaomi Pad / Redmi Pad | 21: MatePad 11, MatePad 11.5, MatePad 10.4, MatePad T10, MatePad T10s, MatePad T8 … (+15) | model, pamiec, ram, lacznosc, akcesoria, blokada, stan, co |
| `surface` | Microsoft Surface (Pro 3 - 11, Go 1 - 4) | 15: Surface Pro 3, Surface Pro 4, Surface Pro 5 (2017), Surface Pro 6, Surface Pro 7, Surface Pro 7+ … (+9) | model, pamiec, ram, akcesoria, blokada, stan, co |
| `tablety_graficzne` | Tablety graficzne (Wacom, Huion, XP-Pen) - z ekranem i bez | 10: Wacom One, Wacom Intuos, Wacom Intuos Pro, Wacom Cintiq, Wacom Cintiq Pro, Huion Kamvas … (+4) | model, akcesoria, stan, co |
| `czytniki` | Czytniki e-booków i notatniki e-ink (Kindle, Kobo, PocketBook, Boox, reMarkable) | 11: Kindle (podstawowy), Kindle Paperwhite (1. - 6. gen.), Kindle Oasis, Kindle Scribe, Kindle Colorsoft, Kobo (Clara, Libra, Sage, Elipsa) … (+5) | model, pamiec, akcesoria, blokada, stan, co |
| `amazon_fire` | Amazon Fire (7, HD 8, HD 10, Max 11, Kids) | 5: Fire 7, Fire HD 8, Fire HD 10, Fire Max 11, Fire Kids Edition | model, pamiec, lacznosc, akcesoria, blokada, stan, co |
| `tablety_inne` | Inne tablety (Teclast, Blackview, Doogee, TCL, Nokia T, Realme Pad, OnePlus Pad ...) | 9: Teclast, Blackview Tab, Doogee, TCL (Tab, NxtPaper), Nokia T10 / T20 / T21, Realme Pad … (+3) | model, pamiec, ram, lacznosc, akcesoria, blokada, stan, co |

### Konsole (22 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `pady` | Kontrolery / pady sprzedawane osobno (DualShock 4, DualSense, Xbox, Switch Pro, Joy-Con) | 9: DualShock 4 (PS4), DualSense (PS5), DualSense Edge (PS5, profesjonalny), kontroler Xbox Series / One, Xbox Elite Series 2 / Core, kontroler Xbox 360 … (+3) | model, oryginal, stan, co |
| `vr_kierownice` | Gogle VR (Meta Quest 2 / 3 / 3S, PS VR / VR2) i kierownice (Logitech, Thrustmaster) | 8: Meta / Oculus Quest 2, Meta Quest 3, Meta Quest 3S, PlayStation VR (PS4), PlayStation VR2 (PS5), Logitech G29 / G920 / G923 … (+2) | model, pamiec, stan, co |
| `ps_portal` | PlayStation Portal (odtwarzacz zdalny PS5 - NIE PSP) | 2: PlayStation Portal (zwykły), PlayStation Portal 30th Anniversary | model, stan, co |
| `ps5` | Sony PlayStation 5 (standard „fat” / Slim / Pro, z napędem albo Digital) | 3: PS5 standard „fat” (CFI-10xx / 11xx, 2020 - 2023), PS5 Slim (CFI-20xx, 2023+), PS5 Pro (CFI-70xx, 2024+) | model, pamiec, naped, pady, gry, przerobka, stan, co |
| `ps4` | Sony PlayStation 4 (fat / Slim / Pro, 500 GB - 2 TB) | 3: PS4 fat (CUH-10xx / 11xx / 12xx, 2013 - 2016), PS4 Slim (CUH-2xxx), PS4 Pro (CUH-7xxx, 4K) | model, pamiec, pady, gry, przerobka, stan, co |
| `ps3` | Sony PlayStation 3 (fat / Slim / Super Slim) | 3: PS3 fat (CECHA - CECHL, 2006 - 2009), PS3 Slim (CECH-2xxx / 3xxx), PS3 Super Slim (CECH-4xxx, napęd od góry) | model, pamiec, pady, gry, przerobka, stan, co |
| `ps2_ps1` | Sony PlayStation 2 (fat / Slim) i PlayStation 1 (PSX / PSone / Classic mini) | 5: PS2 fat (SCPH-3xxxx / 5xxxx), PS2 Slim (SCPH-7xxxx / 9xxxx), PlayStation 1 / PSX (SCPH-1xxx - 9xxx), PSone (mała, 2000), PlayStation Classic (mini, 2018) | model, pady, gry, przerobka, stan, co |
| `psp_vita` | Sony PSP (1000 / 2000 / 3000 / Go / Street) i PS Vita (1000 / 2000, 3G / Wi-Fi) | 7: PSP 1000 (fat), PSP 2000 (slim), PSP 3000, PSP Go (N1000), PSP Street (E1000 / E1004), PS Vita 1000 (OLED, Wi-Fi albo 3G) … (+1) | model, gry, przerobka, stan, co |
| `xbox_series` | Microsoft Xbox Series S (512 GB / 1 TB) i Series X (z napędem / Digital) | 2: Xbox Series S (biały 512 GB albo czarny 1 TB), Xbox Series X (1 TB / 2 TB) | model, pamiec, naped, pady, gry, przerobka, stan, co |
| `xbox_one` | Microsoft Xbox One (2013 / One S / One S All-Digital / One X) | 4: Xbox One (2013, duży, zewnętrzny zasilacz), Xbox One S (biały, z napędem), Xbox One S All-Digital (bez napędu), Xbox One X (4K) | model, pamiec, pady, gry, przerobka, stan, co |
| `xbox_360` | Microsoft Xbox 360 (fat / Slim S / E, RGH / JTAG) | 3: Xbox 360 fat (Arcade / Pro / Elite / Jasper, 2005 - 2009), Xbox 360 S (Slim, 2010), Xbox 360 E (2013) | model, pamiec, pady, gry, przerobka, stan, co |
| `xbox_classic` | Microsoft Xbox (pierwszy, 2001) i Crystal | 2: Xbox (2001, czarny), Xbox Crystal (przezroczysty) | model, pady, gry, przerobka, stan, co |
| `switch_2` | Nintendo Switch 2 (2025) | 2: Nintendo Switch 2 (zwykły), Switch 2 w zestawie z grą (Mario Kart World / Pokémon) | model, pamiec, dock, pady, gry, przerobka, stan, co |
| `switch` | Nintendo Switch (V1 2017 / V2 2019 / OLED / Lite) | 4: Switch V1 (2017, HAC-001, krótsza bateria), Switch V2 (2019, HAC-001(-01), dłuższa bateria, czerwone pudełko), Switch OLED (HEG-001, 7" OLED, 64 GB), Switch Lite (HDH-001, przenośny, bez docka i odłączanych Joy-Conów) | model, pamiec, dock, pady, gry, przerobka, stan, co |
| `steam_deck` | Valve Steam Deck (LCD 64 / 256 / 512 GB, OLED 512 GB / 1 TB) | 2: Steam Deck LCD (2022, 64 / 256 / 512 GB), Steam Deck OLED (2023, 512 GB / 1 TB) | model, pamiec, pady, przerobka, stan, co |
| `pc_przenosne` | Przenośne PC (ROG Ally / Ally X / Xbox Ally, Legion Go, MSI Claw, Ayaneo) | 9: ROG Ally (Z1, zwykły), ROG Ally Z1 Extreme, ROG Ally X (2024, 24 GB / 1 TB), ROG Xbox Ally (2025), ROG Xbox Ally X (2025), Lenovo Legion Go (Z1 Extreme) … (+3) | model, pamiec, ram, przerobka, stan, co |
| `nintendo_ds_3ds` | Nintendo DS / DS Lite / DSi / 3DS / New 3DS / 2DS (XL) | 10: Nintendo DS (pierwszy „fat”, 2004), Nintendo DS Lite, Nintendo DSi, Nintendo DSi XL, Nintendo 3DS, Nintendo 3DS XL … (+4) | model, gry, przerobka, stan, co |
| `gameboy` | Nintendo Game Boy (Classic, Pocket, Color, Advance, Advance SP, Micro) | 7: Game Boy Classic (DMG-01, 1989), Game Boy Pocket, Game Boy Color, Game Boy Advance (AGB-001), Game Boy Advance SP AGS-001 (podświetlenie przednie), Game Boy Advance SP AGS-101 (jaśniejszy, podświetlany od tyłu) … (+1) | model, gry, stan, co |
| `wii` | Nintendo Wii (RVL-001 / Family / Mini) i Wii U (Basic 8 GB / Premium 32 GB) | 6: Wii (RVL-001, obsługuje gry GameCube), Wii Family Edition (RVL-101, poziomy), Wii Mini (RVL-201, bez internetu), Wii U Basic (8 GB, biały), Wii U Premium (32 GB, czarny), Wii U (wersja nieznana) | model, pady, gry, przerobka, stan, co |
| `nintendo_retro` | Nintendo retro (NES, Famicom, SNES, N64, GameCube, mini Classic, klony Pegasus) | 8: NES (oryginalny, 1986), Famicom (japoński), NES Classic Mini (2016), SNES / Super Famicom, SNES Classic Mini (2017), Nintendo 64 … (+2) | model, pady, gry, przerobka, stan, co |
| `retro_inne` | Retro: Sega (Master System, Mega Drive, Saturn, Dreamcast), Atari, Commodore, Amiga | 10: Sega Master System (I / II), Sega Mega Drive / Genesis (I / II), Sega Mega Drive Mini (2019), Sega Saturn, Sega Dreamcast, Sega Game Gear … (+4) | model, pady, gry, przerobka, stan, co |
| `retro_przenosne` | Przenośne konsole retro (Anbernic, Miyoo, Retroid, AYN Odin, TrimUI, Powkiddy) | 6: Anbernic (RG35XX, RG40XX, RG556 ...), Miyoo Mini / Mini Plus / Flip, Retroid Pocket (2S, 4, 4 Pro, 5, Mini), AYN Odin / Thor, TrimUI, Powkiddy | model, pamiec, gry, stan, co |

### Laptopy (33 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `macbook_air` | Apple MacBook Air (Intel 2010 - 2020, M1 - M5, 13" / 15") | 8: MacBook Air Intel (2010 - 2017, stara obudowa, srebrna ramka), MacBook Air Intel Retina (2018 - 2020), MacBook Air M1 (2020), MacBook Air 13" M2 (2022), MacBook Air 15" M2 (2023), MacBook Air M3 (2024, 13" / 15") … (+2) | model, procesor, karta, ram, dysk, stan, blokada, rok, zasilacz, co |
| `macbook_pro` | Apple MacBook Pro (13" / 15" Intel, 13" M1 / M2, 14" / 16" M1 Pro - M5) | 6: MacBook Pro 13" Intel (2012 - 2020), MacBook Pro 15" Intel (2012 - 2019), MacBook Pro 16" Intel (2019), MacBook Pro 13" M1 / M2 (2020 - 2022, Touch Bar), MacBook Pro 14" (2021+, M1 Pro / Max ... M5), MacBook Pro 16" (2021+, M1 Pro / Max ... M5) | model, procesor, karta, ram, dysk, stan, blokada, rok, zasilacz, co |
| `macbook_inne` | Apple MacBook 12" Retina (2015 - 2017), MacBook Neo, stare MacBooki (2006 - 2010) | 3: MacBook 12" Retina (2015 - 2017), MacBook Neo, stary MacBook (2006 - 2010, biały / aluminiowy) | model, procesor, karta, ram, dysk, stan, blokada, rok, zasilacz, co |
| `thinkpad_t` | Lenovo ThinkPad T (T14 / T14s / T15 / T16 Gen, T4x0 / T5x0) | 18: ThinkPad T14, ThinkPad T14s, ThinkPad T15, ThinkPad T16, ThinkPad T480, ThinkPad T480s … (+12) | model, generacja, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `thinkpad_x` | Lenovo ThinkPad X (X1 Carbon / Yoga / Extreme / Nano Gen, X13, X2x0, X3x0) | 12: ThinkPad X1 Carbon, ThinkPad X1 Yoga, ThinkPad X1 Extreme, ThinkPad X1 Nano, ThinkPad X13, ThinkPad X13 Yoga … (+6) | model, generacja, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `thinkpad_le` | Lenovo ThinkPad L / E (L13 - L16, E14 - E16, L4x0 / L5x0, E4x0 / E5x0) | 18: ThinkPad L13, ThinkPad L13 Yoga, ThinkPad L14, ThinkPad L15, ThinkPad L16, ThinkPad E14 … (+12) | model, generacja, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `thinkpad_p` | Lenovo ThinkPad P (P1, P14s, P15, P15s, P16, P16s, P50 - P53) - mobilne stacje robocze | 10: ThinkPad P1, ThinkPad P14s, ThinkPad P15, ThinkPad P15s, ThinkPad P16, ThinkPad P16s … (+4) | model, generacja, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `ideapad` | Lenovo IdeaPad (1, 3, 5, Slim 3 / 5, Flex 3 / 5, Duet, L340, S340 / S540, 3x0 / 5x0) | 14: IdeaPad 1, IdeaPad 3, IdeaPad 5, IdeaPad Slim 3, IdeaPad Slim 5, IdeaPad Flex 3 … (+8) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `lenovo_gaming` | Lenovo Legion (5 / 5 Pro / 5i / 7 / Pro, Y520 - Y740, Y7000), IdeaPad Gaming, LOQ | 19: Legion 5, Legion 5 Pro, Legion 5i, Legion Pro 5, Legion 7, Legion 7i … (+13) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `lenovo_yoga` | Lenovo Yoga (Slim 6 / 7 / 7i / 7x, Yoga 6 / 7 / 9, Pro 7 / 9, C930 / C940, Book) | 16: Yoga Slim 6, Yoga Slim 7, Yoga Slim 7i, Yoga Slim 7x, Yoga 6, Yoga 7 … (+10) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `asus_vivobook` | Asus Vivobook (14 / 15 / 16 / 17, S, Pro, Go, Flip, E402 / E410) | 13: Vivobook 14, Vivobook 15, Vivobook 16, Vivobook 17, Vivobook S14, Vivobook S15 … (+7) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `asus_zenbook` | Asus Zenbook (13 / 14 / 14X / S / Duo / Pro / Flip, UX) | 10: Zenbook 13, Zenbook 14, Zenbook 14X, Zenbook S13, Zenbook S14, Zenbook Duo … (+4) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `asus_tuf` | Asus TUF Gaming (A14 / A15 / A16 / A17, F15 / F16 / F17, FX50x) | 8: TUF Gaming A14, TUF Gaming A15, TUF Gaming A16, TUF Gaming A17, TUF Gaming F15, TUF Gaming F16 … (+2) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `asus_rog` | Asus ROG (Strix G15 / G16 / G17 / G18 / Scar, Zephyrus G14 / G15 / G16 / M16, Flow) | 14: ROG Strix G15, ROG Strix G16, ROG Strix G17, ROG Strix G18, ROG Strix Scar 15, ROG Strix Scar 16 … (+8) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `hp_elite_zbook` | HP EliteBook (820 - 860, 640 - 665, 735 - 755, x360, 1030 / 1040, Dragonfly) i ZBook | 25: HP EliteBook 820, HP EliteBook 830, HP EliteBook 835, HP EliteBook 840, HP EliteBook 845, HP EliteBook 850 … (+19) | model, generacja, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `hp_probook` | HP ProBook (430 - 470, 640 / 650, G1 - G11) | 10: HP ProBook 430, HP ProBook 440, HP ProBook 445, HP ProBook 450, HP ProBook 455, HP ProBook 460 … (+4) | model, generacja, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `hp_konsumenckie` | HP 250 / 255 / 15s / 14s, Pavilion (14 - 17, x360, Gaming, Aero), Envy, Spectre, OmniBook | 10: HP 250 / 240 (G5 - G10), HP 255 / 245 (G5 - G10), HP 15s / 14s / 15 / 17 (bez serii), HP Pavilion 13 / 14 / 15 / 16 / 17, HP Pavilion x360, HP Pavilion Gaming 15 / 16 / 17 … (+4) | model, generacja, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `hp_omen_victus` | HP Omen (15 / 16 / 17 / Transcend) i Victus (15 / 16) | 6: HP Omen 15, HP Omen 16, HP Omen 17, HP Omen Transcend, HP Victus 15, HP Victus 16 | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `dell_latitude_3_5` | Dell Latitude 3xxx / 5xxx (3410 - 3540, 5280 - 5590) | 29: Dell Latitude 3400, Dell Latitude 3410, Dell Latitude 3420, Dell Latitude 3510, Dell Latitude 3520, Dell Latitude 3540 … (+23) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `dell_latitude_7_9` | Dell Latitude 7xxx / 9xxx (7280 - 7490, 7300 - 7440, 9420) | 15: Dell Latitude 7280, Dell Latitude 7290, Dell Latitude 7300, Dell Latitude 7310, Dell Latitude 7320, Dell Latitude 7330 … (+9) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `dell_inspiron` | Dell Inspiron (13 / 14 / 15 / 16 / 17: 3xxx, 5xxx, 7xxx) | 26: Dell Inspiron 3501, Dell Inspiron 3505, Dell Inspiron 3510, Dell Inspiron 3511, Dell Inspiron 3520, Dell Inspiron 3525 … (+20) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `dell_vostro` | Dell Vostro (3400 - 3520, 5402 - 5515) | 10: Dell Vostro 3400, Dell Vostro 3500, Dell Vostro 3510, Dell Vostro 3520, Dell Vostro 3530, Dell Vostro 5402 … (+4) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `dell_xps` | Dell XPS (13: 93xx, 15: 95xx, 17: 97xx) | 20: Dell XPS 9300, Dell XPS 9305, Dell XPS 9310, Dell XPS 9315, Dell XPS 9320, Dell XPS 9340 … (+14) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `dell_gaming` | Dell G3 / G5 / G7 / G15 / G16 i Alienware (m15, m17, x15, x17, 13 / 15 / 17) | 8: Dell G3 (3579 / 3590), Dell G5 (5587 / 5590 / 5500), Dell G7 (7588 / 7590 / 7790), Dell G15 (5510 / 5511 / 5515 / 5520 / 5530 / 5535), Dell G16 (7620 / 7630), Alienware m15 / m16 / m17 / m18 … (+2) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `dell_precision` | Dell Precision (3xxx, 5xxx, 7xxx - mobilne stacje robocze) | 22: Dell Precision 3530, Dell Precision 3541, Dell Precision 3551, Dell Precision 3561, Dell Precision 3571, Dell Precision 5520 … (+16) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `acer_aspire_swift` | Acer Aspire (1 / 3 / 5 / 7 / Vero / V3), Swift (1 / 3 / 5 / Go / X), Extensa, TravelMate, Spin | 15: Aspire 1, Aspire 3, Aspire 5, Aspire 7, Aspire Vero, Aspire V3 … (+9) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `acer_nitro_predator` | Acer Nitro (5 / 7 / 16 / 17 / V15 / V16, Aspire V Nitro) i Predator (Helios, Triton) | 11: Nitro 5, Nitro 7, Nitro 16, Nitro 17, Nitro V15, Nitro V16 … (+5) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `msi` | MSI (GF63 / GF65 Thin, Katana, Cyborg, Sword, Pulse, Vector, Raider, Stealth, Titan, Creator, Prestige, Modern) | 14: MSI GF63 Thin, MSI GF65 Thin, MSI GL63 / GL65 / GL73 / GL75, MSI Katana (GF66 / GF76 / 15 / 17), MSI Cyborg 15, MSI Sword 15 / 17 … (+8) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `huawei_matebook` | Huawei MateBook (D14, D15, D16, 13, 14, 14s, X, X Pro, 16) | 9: MateBook D14, MateBook D15, MateBook D16, MateBook 13, MateBook 14, MateBook 14s … (+3) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `surface_laptop` | Microsoft Surface (Laptop 1 - 7, Go, Studio, Book 1 - 3, Pro 3 - 11, Go 1 - 4) | 14: Surface Laptop 1 / 2, Surface Laptop 3, Surface Laptop 4, Surface Laptop 5, Surface Laptop 6, Surface Laptop 7 … (+8) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `samsung_razer_gigabyte` | Samsung Galaxy Book, Razer Blade, Gigabyte (G5 / G6 / G7, Aorus, Aero) | 7: Samsung Galaxy Book (2 / 3 / 4 / 5, Pro, 360, Edge, Go), Razer Blade 14, Razer Blade 15, Razer Blade 16 / 17 / 18 / Pro 17, Razer Blade Stealth 13, Gigabyte G5 / G6 / G7 … (+1) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `chromebooki` | Chromebooki (Acer 314 / 315 / 514, HP 11 / 14 / x360, Lenovo, Asus, Samsung) | 6: Acer Chromebook (11, 314, 315, 514, Spin), HP Chromebook (11, 14, x360), Lenovo Chromebook / Duet / IdeaPad Flex, Asus Chromebook (CX1, CM14, C523, Flip), Samsung (Galaxy) Chromebook, Dell Chromebook | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |
| `laptopy_inne` | Inne laptopy (Fujitsu, Toshiba / Dynabook, Medion, Sony Vaio, LG Gram, Panasonic Toughbook, Asus ExpertBook, bez modelu ...) | 13: Fujitsu (Lifebook, Celsius), Toshiba / Dynabook (Satellite, Tecra, Portege), Medion (Akoya, Erazer), Sony Vaio, LG Gram, Panasonic Toughbook / Getac (CF-19, CF-31, CF-54 ...) … (+7) | model, procesor, cpu_gen, karta, ram, dysk, stan, blokada, zasilacz, co |

### Karty graficzne (17 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `gpu_pro_arc` | Karty profesjonalne (Quadro, RTX A, Radeon Pro / FirePro, Tesla) i Intel Arc | 8: Quadro K / M (Kepler / Maxwell), Quadro P / T (Pascal / Turing), Quadro RTX / RTX A (A2000 - A6000), Radeon Pro / FirePro, Tesla (obliczeniowa), Intel Arc A310 / A380 … (+2) | model, vram, stan, sztuk |
| `gpu_rtx50` | GeForce RTX 50 (5050, 5060, 5060 Ti 8 / 16 GB, 5070, 5070 Ti, 5080, 5090) | 7: RTX 5050, RTX 5060, RTX 5060 Ti (8 / 16 GB), RTX 5070, RTX 5070 Ti, RTX 5080 … (+1) | model, vram, stan, sztuk |
| `gpu_rtx40` | GeForce RTX 40 (4060, 4060 Ti 8 / 16 GB, 4070, Super, Ti, Ti Super, 4080, 4090) | 9: RTX 4060, RTX 4060 Ti (8 / 16 GB), RTX 4070, RTX 4070 Super, RTX 4070 Ti, RTX 4070 Ti Super … (+3) | model, vram, stan, sztuk |
| `gpu_rtx30_wysokie` | GeForce RTX 3070 / 3070 Ti / 3080 (10 / 12 GB) / 3080 Ti / 3090 / 3090 Ti | 6: RTX 3070, RTX 3070 Ti (GDDR6X), RTX 3080 (10 GB albo 12 GB), RTX 3080 Ti, RTX 3090, RTX 3090 Ti | model, vram, pamiec_typ, stan, sztuk |
| `gpu_rtx30_niskie` | GeForce RTX 3050 (6 / 8 GB) / 3060 (8 / 12 GB) / 3060 Ti (GDDR6 / GDDR6X) | 3: RTX 3050 (6 GB albo 8 GB), RTX 3060 (8 GB albo 12 GB), RTX 3060 Ti (8 GB, GDDR6 albo GDDR6X) | model, vram, pamiec_typ, stan, sztuk |
| `gpu_rtx20` | GeForce RTX 2060 (6 / 12 GB) / 2060 Super / 2070 / 2070 Super / 2080 / 2080 Super / 2080 Ti | 7: RTX 2060 (6 GB albo 12 GB), RTX 2060 Super, RTX 2070, RTX 2070 Super, RTX 2080, RTX 2080 Super … (+1) | model, vram, stan, sztuk |
| `gpu_gtx16` | GeForce GTX 1630 / 1650 (GDDR5 / GDDR6) / 1650 Super / 1660 / 1660 Super / 1660 Ti | 6: GTX 1630, GTX 1650 (GDDR5 albo GDDR6), GTX 1650 Super, GTX 1660, GTX 1660 Super, GTX 1660 Ti | model, vram, pamiec_typ, stan, sztuk |
| `gpu_gtx1070_1080` | GeForce GTX 1070 / 1070 Ti / 1080 / 1080 Ti (i kopalniana P104) | 5: GTX 1070, GTX 1070 Ti, GTX 1080, GTX 1080 Ti (11 GB), P104-100 (kopalniana, bez wyjść wideo - „jak GTX 1070”) | model, vram, stan, sztuk |
| `gpu_gtx1060` | GeForce GTX 1060 (3 / 5 / 6 GB) i kopalniana P106 | 2: GTX 1060, P106-100 / P106-090 (kopalniana, bez wyjść wideo - „jak GTX 1060”) | model, vram, stan, sztuk |
| `gpu_gtx10_niskie` | GeForce GT 1030 (GDDR5 / DDR4), GTX 1050 (2 / 3 GB), GTX 1050 Ti | 3: GT 1030 (GDDR5 albo DDR4), GTX 1050 (bez Ti, 2 / 3 GB), GTX 1050 Ti (4 GB) | model, vram, pamiec_typ, stan, sztuk |
| `gpu_gtx_stare` | GeForce GTX 600 / 700 / 900 (650 - 680, 750 Ti - 780 Ti, 950 - 980 Ti), GT 710 / 730 | 14: GT 710 / GT 730, GTX 650 / 650 Ti, GTX 660 / 660 Ti, GTX 670 / 680, GTX 750, GTX 750 Ti … (+8) | model, vram, stan, sztuk |
| `gpu_rx9000_7000` | Radeon RX 9060 XT / 9070 / 9070 XT i RX 7600 - 7900 XTX (GRE, XT, XTX) | 10: RX 7600, RX 7600 XT, RX 7700 XT, RX 7800 XT, RX 7900 GRE, RX 7900 XT … (+4) | model, vram, stan, sztuk |
| `gpu_rx6000` | Radeon RX 6400 / 6500 XT / 6600 (XT) / 6650 XT / 6700 (XT) / 6750 XT / 6800 (XT) / 6900 XT / 6950 XT | 12: RX 6400, RX 6500 XT, RX 6600, RX 6600 XT, RX 6650 XT, RX 6700 (10 GB) … (+6) | model, vram, stan, sztuk |
| `gpu_rx5000` | Radeon RX 5500 XT (4 / 8 GB) / 5600 XT / 5700 / 5700 XT | 4: RX 5500 XT (4 / 8 GB), RX 5600 XT, RX 5700, RX 5700 XT | model, vram, stan, sztuk |
| `gpu_rx400_500` | Radeon RX 460 / 470 / 480 / 550 / 560 / 570 / 580 (i 2048SP) / 590 (2 / 4 / 8 GB) | 9: RX 460, RX 470, RX 480, RX 550, RX 560, RX 570 … (+3) | model, vram, stan, sztuk |
| `gpu_amd_stare` | Radeon starsze (HD 5000 - 7000, R7 / R9 2xx / 3xx, Fury, Vega 56 / 64, Radeon VII) | 5: Radeon HD 5000 / 6000, Radeon HD 7000 (7750 - 7970), Radeon R7 / R9 200 (240 - 290X), Radeon R7 / R9 300 (360 - 390X), Fury, Radeon RX Vega 56 / 64, Radeon VII | model, vram, stan, sztuk |
| `gpu_retro_inne` | Karty retro i inne (AGP / PCI / ISA, Voodoo, GeForce 2 - 9, Radeon 9xxx / X) oraz bez modelu | 5: 3dfx Voodoo, GeForce 2 - 7 / FX (AGP), GeForce 8 / 9 / GT 2xx, Radeon 9xxx / X / HD 2000 - 4000, karta bez podanego modelu | model, vram, stan, sztuk |

### Pamięć RAM (7 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `ram_serwer` | Pamięć RAM serwerowa (ECC, Registered, RDIMM, LRDIMM) | 0:  | typ, mhz, forma, pojemnosc, stan, sztuk |
| `ram_ddr5` | Pamięć RAM DDR5 (PC i laptop) | 0:  | typ, mhz, forma, pojemnosc, stan, sztuk |
| `ram_ddr4_laptop` | Pamięć RAM DDR4 do laptopa (SO-DIMM) | 0:  | typ, mhz, forma, pojemnosc, stan, sztuk |
| `ram_ddr4` | Pamięć RAM DDR4 do komputera (DIMM) | 0:  | typ, mhz, forma, pojemnosc, stan, sztuk |
| `ram_ddr3` | Pamięć RAM DDR3 / DDR3L (PC i laptop) | 0:  | typ, mhz, forma, pojemnosc, stan, sztuk |
| `ram_ddr2_starsze` | Pamięć RAM DDR2 i starsza (DDR, SDRAM, SIMM, EDO) | 0:  | typ, mhz, forma, pojemnosc, stan, sztuk |
| `ram_bez_typu` | Pamięć RAM bez podanego typu | 0:  | typ, mhz, forma, pojemnosc, stan, sztuk |

### Dyski (7 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `dysk_zewnetrzny` | Dyski zewnętrzne (Samsung T5 / T7 / T9, WD My Passport / Elements, Seagate, SanDisk, Toshiba, LaCie) | 7: Samsung T5 / T7 / T7 Shield / T9 (SSD), WD My Passport / Elements / My Book, Seagate Expansion / One Touch / Basic, SanDisk Extreme Portable (SSD), Toshiba Canvio, LaCie Rugged … (+1) | model, pojemnosc, typ, stan, sztuk |
| `dysk_samsung` | Samsung SSD (970 / 980 / 990 EVO / Plus / PRO, PM9xx OEM, 850 / 860 / 870 EVO / QVO) | 12: 970 EVO (bez Plus), 970 EVO Plus, 970 PRO, 980 (bez PRO), 980 PRO, 990 EVO (bez Plus) … (+6) | model, pojemnosc, typ, stan, sztuk |
| `dysk_wd` | WD SSD (Black SN750 / SN770 / SN850X / SN7100, Blue SN550 - SN5000 / SA510, Green, Red, PC SN OEM) | 8: WD Black SN750, WD Black SN770, WD Black SN850 / SN850X, WD Black SN7100 / SN8100, WD Blue SN550 / SN570 / SN580 / SN5000, WD PC SN520 / SN530 / SN730 / SN740 / SN810 (OEM) … (+2) | model, pojemnosc, typ, stan, sztuk |
| `dysk_crucial_kingston` | Crucial (MX500, BX500, P1 - P5 Plus, T500 / T700) i Kingston (A400, NV1 - NV3, KC3000, A2000 ...) | 9: Crucial MX500 (SATA), Crucial BX500 (SATA), Crucial P1 / P2 / P3 (NVMe, bez Plus), Crucial P3 Plus / P5 / P5 Plus, Crucial T500 / T700 / T705, Kingston A400 (SATA) … (+3) | model, pojemnosc, typ, stan, sztuk |
| `dysk_ssd_inne` | Inne SSD (Adata / XPG, Lexar, Goodram, Patriot, SK Hynix, Micron, Kioxia, Intel, SanDisk, Silicon Power) | 9: Adata / XPG (SU650, Legend, SX8200, Gammix), Lexar (NM620, NM710, NM790, NS100), Goodram (CX400, IRDM, PX500), Patriot (P300, P310, P400, Burst), SK Hynix (P31, P41, Platinum, BC / PC OEM), Micron / Kioxia / Toshiba OEM (2200, 2300, BG4, XG6 ...) … (+3) | model, pojemnosc, typ, stan, sztuk |
| `dysk_hdd` | Dyski HDD 3,5" i 2,5" (Seagate Barracuda / IronWolf / Exos, WD Blue / Red / Purple, Toshiba, Hitachi) | 8: Seagate Barracuda / FireCuda, Seagate IronWolf / Exos / SkyHawk (NAS / serwer / monitoring), WD Blue (HDD), WD Red / Red Plus / Red Pro / Purple (NAS / monitoring), WD Black / Gold / Ultrastar (HDD), Toshiba (P300, N300, X300, MG) … (+2) | model, pojemnosc, typ, stan, sztuk |
| `dyski_inne` | Inne nośniki i dyski bez modelu (mSATA, pendrive, karty pamięci, kieszenie) | 4: mSATA, pendrive / karta pamięci, kieszeń / obudowa / adapter (bez dysku), dysk bez podanego modelu | model, pojemnosc, typ, stan, sztuk |

### Procesory (7 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `cpu_intel_i3` | Intel Core i3 (2. - 14. generacji) | 19: Intel Core i3-2100, Intel Core i3-2120, Intel Core i3-3220, Intel Core i3-4130, Intel Core i3-4160, Intel Core i3-4170 … (+13) | model, sufiks, stan, sztuk |
| `cpu_intel_i5` | Intel Core i5 (2. - 14. generacji) | 36: Intel Core i5-2400, Intel Core i5-2500, Intel Core i5-3470, Intel Core i5-3570, Intel Core i5-4460, Intel Core i5-4570 … (+30) | model, sufiks, stan, sztuk |
| `cpu_intel_i7` | Intel Core i7 (2. - 14. generacji, także HEDT X) | 19: Intel Core i7-2600, Intel Core i7-3770, Intel Core i7-3930, Intel Core i7-4770, Intel Core i7-4790, Intel Core i7-5820 … (+13) | model, sufiks, stan, sztuk |
| `cpu_intel_i9_ultra` | Intel Core i9 (9. - 14. gen.) i Core Ultra 5 / 7 / 9 (200S) | 10: Intel Core i9-9900, Intel Core i9-10850, Intel Core i9-10900, Intel Core i9-11900, Intel Core i9-12900, Intel Core i9-13900 … (+4) | model, sufiks, stan, sztuk |
| `cpu_ryzen_3_5` | AMD Ryzen 3 i Ryzen 5 (1000 - 9000, X / G / F / AF / X3D) | 27: AMD Ryzen 3 1200, AMD Ryzen 3 1300, AMD Ryzen 3 2200, AMD Ryzen 3 3100, AMD Ryzen 3 3200, AMD Ryzen 3 3300 … (+21) | model, sufiks, stan, sztuk |
| `cpu_ryzen_7_9` | AMD Ryzen 7 i Ryzen 9 (1700 - 9950X3D) | 20: AMD Ryzen 7 1700, AMD Ryzen 7 1800, AMD Ryzen 7 2700, AMD Ryzen 7 3700, AMD Ryzen 7 3800, AMD Ryzen 7 5700 … (+14) | model, sufiks, stan, sztuk |
| `cpu_inne` | Inne procesory (Xeon, Pentium, Celeron, Core 2, AMD FX, Phenom, Athlon, Threadripper) | 8: Intel Xeon E3 (v2 - v6), Intel Xeon E5 (v2 - v4), inny Xeon (E7, W, Scalable, X5xxx), Pentium / Celeron (G, Gold), Core 2 Duo / Quad, AMD FX (4300 / 6300 / 8320 / 8350) … (+2) | model, sufiks, stan, sztuk |

### Płyty główne (8 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `mobo_raspberry_sbc` | Raspberry Pi i inne mini komputery (Pi 3 / 4 / 5 / Zero / Pico, Orange Pi, Arduino) | 7: Raspberry Pi 3 (B / B+), Raspberry Pi 4 (1 / 2 / 4 / 8 GB), Raspberry Pi 5 (2 / 4 / 8 / 16 GB), Raspberry Pi Zero / Zero 2 W / Pico, Raspberry Pi 1 / 2 (stary), Orange Pi / Banana Pi … (+1) | chipset, ddr, wifi, format, stan |
| `mobo_am5` | Płyty AM5 (A620, B650 / B650E, X670 / X670E, B850, X870 / X870E) | 5: A620, B650, X670, B850, X870 | chipset, ddr, wifi, format, stan |
| `mobo_am4` | Płyty AM4 (A320, B350, X370, B450, X470, A520, B550, X570) | 8: A320, B350, X370, B450, X470, A520 … (+2) | chipset, ddr, wifi, format, stan |
| `mobo_lga1700_1851` | Płyty LGA1700 / LGA1851 (H610, B660, H670, Z690, B760, Z790, B860, Z890) | 8: H610, B660, H670, Z690, B760, Z790 … (+2) | chipset, ddr, wifi, format, stan |
| `mobo_lga1200` | Płyty LGA1200 (H410, B460, H470, Z490, H510, B560, Z590) | 7: H410, B460, H470, Z490, H510, B560 … (+1) | chipset, ddr, wifi, format, stan |
| `mobo_lga1151` | Płyty LGA1151 (H110, B150, H170, Z170, B250, H270, Z270, H310, B360, B365, H370, Z370, Z390) | 13: H110, B150, H170, Z170, B250, H270 … (+7) | chipset, ddr, wifi, format, stan |
| `mobo_starsze` | Płyty starsze (LGA1150 / 1155 / 2011 / 775, AM3 / AM3+ / FM2) | 15: H81, B85, H87, Z87, H97, Z97 … (+9) | chipset, ddr, wifi, format, stan |
| `mobo_inne` | Płyty bez chipsetu w tytule, płyty laptopów / TV / konsol, inna elektronika | 5: płyta główna PC (model nieznany), płyta z laptopa, płyta TV / monitora / zasilacz / T-Con, płyta konsoli (PS / Xbox / Switch), inna elektronika (karta dźwiękowa, rozszerzeń, moduł) | chipset, ddr, wifi, format, stan |

### Zestawy (1 rodzin)

| rodzina | co obejmuje | warianty | pytania |
|---|---|---|---|
| `zestaw_plyta_cpu` | Zestawy płyta główna + procesor (+ RAM) i komputery | 1: zestaw | procesor, cpu_gen, ram, co, stan |

