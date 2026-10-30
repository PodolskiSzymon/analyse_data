# analyse_data – analizator rynku Vinted + (w drugim repo) Sniper okazji

**„wykonaj md” → przeczytaj CAŁY `STAN_PROJEKTU.md` (start sesji, cel, przepływ, reguły, ustawienia, wyniki, na co
czekamy, następne kroki, mapa plików) i postępuj wg niego.** Nic więcej na zapas: `PLAN_OCENY.md` (plan docelowy
oceny) przy F1+, `HISTORIA.md` (archiwum z liczbami) tylko przez `grep`, `KONTEKST_CATEGORY_ANALYZER.md` przy kodzie
zbierającym dane. Nie pytaj o rzeczy, które te pliki rozstrzygają.

## Zasady (obowiązują zawsze)

* Rozmawiamy **po polsku**; komentarze w kodzie po polsku; konkretnie, z wynikami testów i komendami do wklejenia.
* **Claude NIE ma dostępu do vinted.pl ani do bazy użytkownika.** Baza (`analyzer.db`, ~1,4 GB) jest na serwerze
  użytkownika (Windows, i5-5200U, **4 GB RAM**, Python 3.12). Ty piszesz kod + testy na atrapie (syntetyczna SQLite),
  użytkownik uruchamia i wkleja wynik albo daje kopię bazy przez Dysk (`STAN_PROJEKTU.md` §0). Komendy: **lekkie**
  (SQL z agregacją, strumieniowo), z **postępem** w terminalu, **krótki** wynik.
* Zapytania do Vinted tylko na podstawie realnego ruchu przeglądarki (cURL z F12) albo testu u użytkownika – **bez
  zgadywania endpointów**. Budżet proxy ograniczony – analiza działa bez sieci. Nie obchodzić wykrywania botów.
* **Nie commitować** sekretów (`.env`, hasła, klucze, tokeny, tematy ntfy) ani danych (`data/`, `*.db`, eksporty,
  linki do Dysku). W eksportach z opisami maskować e-mail/telefon/URL (`analyzer/sample.py: redact`).
* Sprzedawca w bazie jako stały hash (`seller_hash`) + liczbowe `seller_id` (od 29.10, do szafy); nicków nie zbieramy.
* Cena „sprzedaży” = ostatnia cena wystawienia → w raportach **górna granica**; `deleted` ≠ sprzedaż.
* Bez PR bez prośby. Commit + push na gałąź sesji w OBU repo (stan: `claude/magical-bell-vdwpt1`; nowa gałąź sesji →
  oprzeć na niej, `STAN_PROJEKTU.md` „Start sesji”). W commitach/kodzie nie wpisywać identyfikatora modelu AI.
* Testy (bez sieci): `python -m pytest analyzer/tests -q`; w `unreachable_sniper`: `python -m pytest sniper/tests -q`.
