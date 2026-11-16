# Popyt - dlaczego Sniper zgłasza rzeczy, których nikt nie kupuje (analiza 2026-11-16)

Prośba użytkownika (16.11): reMarkable 2 kupiony za 1200, sprzedany za 1400 (słaby interes); iPad A16 na gwarancji
sprzedany w 24 h bez negocjacji (dałoby się ~300 zł drożej); S23 sprzedany dobrze za 1000. Przejrzeć bazę,
postawić hipotezy, zaproponować rozwiązanie. Dane: kopia 07.11 (`slim.db`, 278 823 oferty, 11.10-07.11), używane
telefony / tablety / konsole, nowe oferty = pierwsze widzenie 16.10-03.11 (18 dni, każda obserwowana ≥ 4 dni).
Narzędzie do powtórki na nowszej bazie: `python narzedzia\popyt.py --baza <kopia.db>`.

## Najważniejsze wnioski

1. **Szacunek Snipera jest zawyżony tam, gdzie oferty wiszą.** Dziś: `max(mediana zniknięć, środek p25-mediana
   aktywnych)`. Aktywne to w 50-93% oferty wiszące od tygodni (za drogie - nikt ich nie kupuje), więc ich mediana
   to cena „życzeniowa”. Cena ofert, które naprawdę schodzą:

   | cena / mediana aktywnych tego modelu | n | mediana |
   |---|---|---|
   | nowe, dalej wiszące po ≥ 7 dniach | 9 301 | 0,94 |
   | nowe, zniknięte ≤ 3 dni (bez ponownych wystawień) | 7 150 | 0,88 |
   | potwierdzone sprzedane ≤ 7 dni | 263 | **0,82** |
   | dzisiejszy szacunek Snipera | - | ~0,90-0,95 |

   Per model (szacunek dziś → mediana ceny zniknionych ≤ 3 dni): **reMarkable 2 1375 → 1101-1184 (-14..-20%)**,
   MatePad 11 900 → brak szybkich (1 w 18 dni), Galaxy Tab S6 Lite 650 → 501 (-23%), iPad Air 2022 1850 → 1592
   (-14%), **iPhone 12 588 → 530 (-10%, stąd tylko +80 zł)**, A17 489 → 439, Steam Deck 1623 → 1499, **S23 1067 →
   1042 (-2%)**, **iPad A16 1700 → 1700 (0%)**. Doświadczenia użytkownika zgadzają się z tą kolumną co do złotówki
   (S23 sprzedany za 1000 ≈ cena szybkich; reMarkable za 1400 = powyżej ceny szybkich, mały zysk).

2. **„Rotacja” (zniknięte / wszystkie) nie mierzy popytu.** Pewnych sprzedaży jest ~3,5% zniknięć; 30% nowych ofert
   jest usuwanych w kilka dni niezależnie od ceny (cena 0,6-1,0 × mediana: 31-35% usuniętych, > 1,15: 23%).
   reMarkable miał rotację 24% - tyle co S23 (25%).

3. **Popyt najlepiej widać po: udziale nowych ofert znikających w tydzień (≤ 7 d) i liczbie takich zniknięć na
   tydzień (= liczba kupujących).**

   | model | nowe / mies. | ≤ 3 d | ≤ 7 d | szybkich / tydz. | wiszące | polubienia / dzień | klasa |
   |---|---|---|---|---|---|---|---|
   | iPad A16 | 78 | 57% | 68% | 12,4 | 50% | 13,0 | gorący |
   | iPad Air (2022) | 63 | 42% | 55% | 8,2 | 65% | 2,4 | gorący |
   | PS5 | 983 | 42% | 54% | 125 | 69% | 1,0 | gorący |
   | Steam Deck | 88 | 28% | 38% | 7,8 | 63% | 4,6 | normalny |
   | Galaxy S23 | 177 | 19% | 28% | 11,7 | 72% | 0,65 | normalny |
   | iPhone 12 | 1 318 | 21% | 28% | 88 | 77% | 0,73 | normalny |
   | Galaxy A17 | 72 | 23% | 30% | 5,1 | 57% | 0,74 | normalny |
   | Galaxy Tab S6 Lite | 73 | 14% | 30% | 5,1 | 76% | 0,37 | normalny / wolny |
   | reMarkable 2 | 27 | 19% | 31% | 1,9 | 50% | 2,6 | wolny |
   | iPhone 8 | 152 | 13% | 20% | 7,0 | 82% | 0,08 | wolny |
   | MatePad 11 | 22 | 8% | 8% | 0,4 | 84% | 0,29 | martwy |
   | tablety graficzne | 27 | 0% | 6% | 0,4 | 93% | 0,36 | martwy |

   Klasy (propozycja): gorący ≤ 7 d ≥ 50% i ≥ 3 / tydz.; martwy < 15% albo < 0,7 / tydz.; wolny < 25% albo < 2 /
   tydz.; reszta normalny. reMarkable jest „wolny” (mało kupujących), a o stracie zdecydowała głównie zawyżona
   wycena (pkt 1).

## Hipotezy (H) i wynik sprawdzenia

| # | Hipoteza | Wynik na danych | Werdykt |
|---|---|---|---|
| H1 | Mediana aktywnych zawyżona przez wiszące oferty; wyceniać ceną ofert, które schodzą | tabela pkt 1; backtest 16-25.10 → 27.10-02.11: oferty wystawione na 90-100% wyceny „szybkiej” znikają w 7 d w 45%, wg obecnej 42%; dla rzadkich modeli różnica 14-58% | ✔ główna przyczyna |
| H2 | Rotacja (zniknięte / wszystkie) to popyt | usunięcia ~30% nowych ofert bez względu na cenę; sprzedaży potwierdzonych ~1% | ✘ zastąpić |
| H3 | Udział nowych ofert znikających ≤ 7 d | iPad A16 68%, PS5 54%, S23 28%, reMarkable 31%, MatePad 8%, graficzne 6% | ✔ dobra miara |
| H4 | Liczba szybkich zniknięć na tydzień (ilu kupujących) | iPad A16 12, S23 12, reMarkable 1,9, MatePad 0,4 | ✔ odróżnia małe rynki |
| H5 | Udział wiszących (od pierwszego przejścia) | MatePad 84%, graficzne 93%, iPhone 8 82% vs iPad A16 50%; korelacja z ≤ 7 d -0,47 (telefony) | ~ pomocnicza |
| H6 | Polubienia na dzień (za darmo z katalogu) | korelacja z ≤ 7 d: telefony 0,56, tablety 0,36, konsole 0,18; reMarkable 2,6 / dzień - lubią, nie kupują | ~ tylko w obrębie kategorii |
| H7 | Dni zapasu (aktywne / szybkie zniknięcia na dzień) | iPad A16 29, PS5 70, Steam Deck 112, S23 266, reMarkable 234, MatePad 1152 | ~ karze duże rynki z wiszącymi |
| H8 | Kolejka: (tańsi świeży konkurenci + 1) / kupujący na tydzień | iPad A16 4-6 dni, Steam Deck 9, reMarkable 18-27, MatePad 90-126; ale S23 33-39 dni, a sprzedał się szybko | ✘ za prosta dla dużych rynków |
| H9 | Niższa cena = szybciej | zniknięcia ≤ 3 d: 0,6-1,0 × mediana 26-28%, 1,0-1,25 19-21%, > 1,25 12-18% - kara głównie za cenę POWYŻEJ mediany | ✔ wystawiać ≤ mediany |
| H10 | Wariant sprzętu zmienia płynność | iPhone 11-15: bateria < 80% ≤ 7 d 27% (cena 0,95), ≥ 85% 34-36% (1,05-1,09); 64 GB 22% vs 128 GB 34% przy tej samej cenie; pęknięty 31% przy 0,87 | ✔ do wyceny / oceny |
| H11 | Gwarancja / faktura | telefony z „gwarancja” ≤ 7 d 38% vs 29% i cena 0,96 vs 0,89; faktura / paragon 38% vs 29% | ✔ premia |
| H12 | Pudełko | telefony z pudełkiem 33% vs bez 27% (cena 0,80) | ✔ jest (×0,88) |
| H13 | Mała różnica cen używany / nowy (Vinted) = słaby popyt | ≤ 7 d 28% / 31% / 33% w grupach różnicy | ✘ bez znaczenia |
| H14 | Częste obniżki ceny = słaby popyt | konsole (ROG Ally, Switch 2) obniżają najczęściej, a schodzą | ✘ zachowanie sprzedawców |
| H15 | Gorące modele wyceniane za nisko | iPad A16: używane szybkie do 2 200-2 800, nowe na Vinted mediana 1 800, ≤ 3 d 57% → wycena do mediany aktywnych / ceny nowego i podpowiedź „wystaw drożej” | ✔ (uwaga użytkownika +300 zł) |
| H16 | Huawei bez usług Google (MatePad, P40 i nowsze) - mały popyt w UE | MatePad 11 8%, P50 Pro 0 szybkich, P40 Pro szybkie za 305 przy medianie 775; P30 Pro (z Google) 34% | ~ wiedza + mało danych |
| H17 | Dodatki (folio, rysiki) podnoszą cenę wystawienia, nie sprzedaży | reMarkable z kompletem wisi za 1 700-2 100, szybkie 1 017-1 307 | ✔ reguła E jest |
| H18 | Wyniki alertów i własnych sprzedaży jako kalibracja | (F4 `alert-outcomes`, dziennik zakupów użytkownika) | do zrobienia |

## Propozycja zmian (do akceptacji)

1. **Analizator → `comparables.db`**: przy każdej ofercie `life_days`, `fresh` (nowa w oknie), `fast` (zniknęła ≤ 3 d,
   nie jest ponownym wystawieniem). Wymaga `auto --force` po wdrożeniu.
2. **Sniper - wycena**: szacunek = mediana ceny szybkich zniknięć (≥ 5 ofert); przy mniejszej liczbie
   `min(obecny szacunek, p25 aktywnych)`. Klasa „gorący”: jak dziś (do środka p25-mediana), w alercie „wystaw ~X”.
3. **Sniper - klasa popytu zamiast rotacji** (tylko telefony, tablety, konsole; czytniki zostają przy 0,3):
   martwy → okazja tylko ≤ 50% wyceny (bramka przed AI), wolny → wymagany zysk × 1,5 i ocena -1, gorący → ocena +0,5.
4. **Wariant w wycenie**: bateria < 80% ×0,95, 64 GB osobno (już w medianach), „gwarancja” / „faktura” +5% (blok
   `<rynek>`).
5. **Kalibracja**: F4 - co się stało z ofertami z alertów; dziennik zakupów / sprzedaży użytkownika - progi klas co
   miesiąc. Dane z 07.11 to 18 dni nowych ofert - małe rynki (reMarkable 27 / mies.) mają mało szybkich zniknięć;
   po 4+ tygodniach ciągłego `watch` przeliczyć (`narzedzia/popyt.py`) i ewentualnie poprawić progi.
