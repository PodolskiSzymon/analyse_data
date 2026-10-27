"""Rejestr flipów (PLAN_OCENY.md §8.1) – `python -m analyzer flips [--szablon] [--plik ŚCIEŻKA]`.

Plik `flips.csv` leży obok bazy (`<folder bazy>/flips.csv`, NIE w repo), średnik jako separator i przecinek
dziesiętny – otwiera się wprost w polskim Excelu. Jeden wiersz = jedna kupiona rzecz; puste pola = jeszcze nie wiadomo
(np. niesprzedane). `--szablon` zapisuje plik z nagłówkiem i 7 zakupami z 26.10 do uzupełnienia (nie nadpisuje).

Raport: realny zysk / marża / dni obrotu sprzedanych, kapitał zamrożony w niesprzedanych, δ = rabat od ceny
wystawienia („Zaproponuj cenę”; start w planie 0,08), zgodność stanu z ogłoszeniem, wynik wg oceny alertu.
"""
import csv
import statistics
from datetime import date
from pathlib import Path

COLUMNS = ["data_zakupu", "id_oferty", "kategoria", "model", "koszt_zakupu_lacznie", "kraj_sprzedawcy",
           "data_dostawy", "stan_zgodny", "problemy", "cena_wystawienia", "data_wystawienia", "data_sprzedazy",
           "cena_otrzymana", "koszty_sprzedazy", "ocena_alertu", "notatki"]
# Zakupy z alertów 26.10 (STAN_PROJEKTU.md §6) – kwoty i daty uzupełnia użytkownik.
FIRST_PURCHASES = [("console", "Nintendo Wii"), ("console", "Nintendo Wii"), ("console", "Nintendo Wii czarne bez pilota"),
                   ("phone", "iPhone 12 128 GB (bateria < 80%)"), ("phone", "Samsung Galaxy A17"),
                   ("tablet", "Samsung Galaxy Tab A 10.1 (2019)"), ("tablet", "iPad Air 4 64 GB (anulowanie?)")]
DEFAULT_SALE_COSTS = 46.0            # Podbicie ~26 zł + wysyłka ~20 zł (reguła zysku), gdy pole puste


def path_for(db_path):
    return Path(db_path).parent / "flips.csv"


def write_template(path):
    """Szablon z nagłówkiem i zakupami z 26.10 → True; istniejącego pliku nie rusza (False)."""
    path = Path(path)
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        out = csv.writer(f, delimiter=";")
        out.writerow(COLUMNS)
        for category, model in FIRST_PURCHASES:
            out.writerow(["2026-10-26", "", category, model] + [""] * (len(COLUMNS) - 4))
    return True


def _num(text):
    text = (text or "").replace("zł", "").replace("\xa0", "").replace(" ", "").replace(",", ".").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _day(text):
    try:
        return date.fromisoformat((text or "").strip()[:10])
    except ValueError:
        return None


def load(path):
    """→ lista słowników z liczbami/datami (wiersze bez kosztu zakupu pomijane)."""
    rows = []
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader((line for line in f if not line.startswith("#")), delimiter=";"):
            cost = _num(raw.get("koszt_zakupu_lacznie"))
            if cost is None:
                continue
            sale_costs = _num(raw.get("koszty_sprzedazy"))
            rows.append({
                "model": (raw.get("model") or "").strip(), "category": (raw.get("kategoria") or "").strip(),
                "cost": cost, "bought": _day(raw.get("data_zakupu")), "delivered": _day(raw.get("data_dostawy")),
                "listed": _day(raw.get("data_wystawienia")), "sold": _day(raw.get("data_sprzedazy")),
                "ask": _num(raw.get("cena_wystawienia")), "got": _num(raw.get("cena_otrzymana")),
                "sale_costs": DEFAULT_SALE_COSTS if sale_costs is None else sale_costs,
                "match": (raw.get("stan_zgodny") or "").strip().upper()[:1],
                "score": _num(raw.get("ocena_alertu")), "country": (raw.get("kraj_sprzedawcy") or "").strip().upper(),
            })
    return rows


def _med(values):
    values = [v for v in values if v is not None]
    return statistics.median(values) if values else None


def report(rows, today=None):
    today = today or date.today()
    sold = [r for r in rows if r["got"] is not None]
    open_ = [r for r in rows if r["got"] is None]
    lines = [f"Flipy: kupione {len(rows)}, sprzedane {len(sold)}, w toku {len(open_)} "
             f"(zamrożone {sum(r['cost'] for r in open_):.0f} zł)"]
    if sold:
        for r in sold:
            r["profit"] = r["got"] - r["cost"] - r["sale_costs"]
            r["margin"] = r["profit"] / r["got"] if r["got"] else None
            r["days"] = (r["sold"] - r["bought"]).days if r["sold"] and r["bought"] else None
            r["days_listed"] = (r["sold"] - r["listed"]).days if r["sold"] and r["listed"] else None
        profit = sum(r["profit"] for r in sold)
        invested = sum(r["cost"] for r in sold)
        lines.append(f"  sprzedane: zysk {profit:.0f} zł na {invested:.0f} zł ({profit / invested * 100:.0f}% "
                     f"kapitału), mediana marży {_med([r['margin'] for r in sold]) * 100:.0f}%, mediana dni "
                     f"zakup→sprzedaż {_fmt(_med([r['days'] for r in sold]))}, wystawienie→sprzedaż "
                     f"{_fmt(_med([r['days_listed'] for r in sold]))}")
        meets = sum(1 for r in sold if r["profit"] >= 300 and r["margin"] is not None and r["margin"] >= 0.30)
        lines.append(f"  reguła (zysk ≥ 300 zł, marża ≥ 30%) spełniona w {meets}/{len(sold)}")
        deltas = [1 - r["got"] / r["ask"] for r in sold if r["ask"]]
        if deltas:
            lines.append(f"  δ (rabat od ceny wystawienia): mediana {_med(deltas) * 100:.1f}% z {len(deltas)} "
                         f"(plan zakłada 8%)")
        by_score = {}
        for r in sold:
            if r["score"] is not None:
                by_score.setdefault(int(r["score"]), []).append(r["profit"])
        if by_score:
            lines.append("  zysk wg oceny alertu: " + ", ".join(
                f"{k}/10: {len(v)} szt., mediana {statistics.median(v):.0f} zł" for k, v in sorted(by_score.items())))
        lines.append("  sprzedane: " + "; ".join(f"{r['model'][:28]} {r['profit']:+.0f} zł"
                                                 f" ({_fmt(r['days'])} dni)" for r in sold))
    checked = [r for r in rows if r["match"] in ("T", "N")]
    if checked:
        bad = [r["model"][:28] for r in checked if r["match"] == "N"]
        lines.append(f"  stan zgodny z ogłoszeniem: {len(checked) - len(bad)}/{len(checked)}"
                     + (f" (niezgodne: {', '.join(bad)})" if bad else ""))
    if open_:
        lines.append("  w toku: " + "; ".join(
            f"{r['model'][:28]} {r['cost']:.0f} zł, {(today - r['bought']).days if r['bought'] else '?'} dni"
            for r in open_))
    return lines


def _fmt(value):
    return "-" if value is None else f"{value:g}"
