"""Raport rynku (PLAN_ANALIZY.md, A5): `python -m analyzer report [--age-days 14] [--photo-flag]` - bez sieci.

Kolejno: flagi podejrzanych (suspicious) i relisty → analysis.db, statystyki (stats.collect), wyniki do
`<folder bazy>/reports/<RRRR-MM-DD>/`:
  * summary.md  - krótkie zestawienie (≤ ~150 linii) do wklejenia w czat,
  * configs.csv - pełna tabela grup (poziom, kategoria, klucz, rynek, stan) ze wszystkimi miarami,
  * report.html - jeden plik: te same tabele + pełna tabela konfiguracji z filtrem i sortowaniem (bez internetu).
"""
import csv
import html
import json
import re

from . import analysis

COLUMNS = ("level", "category", "key", "market", "cond", "n_active", "active_p25", "active_med", "active_p75",
           "n_sold", "sold_p25", "sold_med", "sold_p75", "n_deleted", "deleted_p25", "deleted_med", "deleted_p75",
           "n_old_active", "st_low", "st_high",
           "days_med", "days_n", "drop_share", "n_dropped", "drop_pct_med", "drop_days_med", "st_low_dropped",
           "st_low_not_dropped", "fav_active_med", "fav_sold_med", "views_active_med", "views_sold_med", "spread",
           "low_data")
CAT_PL = {"laptop": "laptopy", "phone": "telefony", "tablet": "tablety", "console": "konsole", "gpu": "karty graf.",
          "ram": "RAM", "storage": "dyski SSD"}
TOP_CONFIGS, TOP_PARENTS = 6, 3
HTML_MIN_OFFERS = 10            # report.html: tylko grupy z co najmniej tyloma ofertami (CSV - wszystkie)


# ---------------------------------------------------------------------------------------------- formatowanie


def zl(v):
    return "-" if v is None else f"{v:,.0f}".replace(",", " ")


def pct(v, digits=0):
    return "-" if v is None else f"{v * 100:.{digits}f}%"


def num(v, digits=1):
    return "-" if v is None else f"{v:.{digits}f}"


def st_range(m):
    if m["st_low"] is None:
        return "-"
    return f"{m['st_low'] * 100:.0f}–{m['st_high'] * 100:.0f}%"


def days(m):
    return "-" if m["days_med"] is None else f"{m['days_med']:.1f} (n={m['days_n']})"


def show_key(key):
    """Klucz do tabel markdown: „|” rozbija kolumny → „ / ” (w configs.csv zostaje oryginał)."""
    return str(key).replace("|", " / ")


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return out


# ---------------------------------------------------------------------------------------------- sekcje


def quality_rows(result, flags_info):
    q = result["quality"]
    rows = []
    for cat in analysis.CATEGORIES:
        states = q["states"].get(cat, {})
        total = sum(states.values())
        if not total:
            continue
        excl = sum(q["excluded"].get(cat, {}).values())
        rel = sum(q["relist_old"].get(cat, {}).values())
        used = total - excl - rel - max(states.get("blocked", 0) - q["excluded"].get(cat, {}).get("blocked", 0), 0)
        keyed = q["keyed"].get(cat, {}).get("yes", 0)
        foreign = sum(q["foreign"].get(cat, {}).values())
        rows.append([CAT_PL[cat], total, states.get("active", 0), states.get("sold", 0), states.get("deleted", 0),
                     states.get("blocked", 0), excl, rel, used, pct(keyed / used if used else None),
                     pct(foreign / used if used else None)])
    return rows


def delay_rows(result):
    """Udział sprzedanych (sold + blocked) wśród zniknięć według zwłoki sprawdzenia (services_at/state_at −
    last_seen) - eksperyment C4: spadek % sold przy dłuższej zwłoce = sprzedane znikają z Vinted (404)."""
    from .stats import DELAY_EDGES

    edges = (0,) + DELAY_EDGES
    labels = [f"{a}–{b} dni" for a, b in zip(edges, edges[1:])] + [f"≥ {edges[-1]} dni"]
    buckets = {}
    for (_cat, bucket, state), values in result["quality"]["delays"].items():
        b = buckets.setdefault(bucket, {"sold": 0, "deleted": 0, "delays": []})
        b[state] += len(values)
        b["delays"] += values
    rows = []
    for bucket in sorted(buckets):
        b = buckets[bucket]
        n = b["sold"] + b["deleted"]
        rows.append([labels[bucket], b["sold"], b["deleted"], pct(b["sold"] / n if n else None, 1),
                     num(analysis.median(b["delays"]))])
    return rows


def _ratio(result, cat, market, cond, state):
    r = (result.get("ratios") or {}).get((cat, market, cond), {}).get(state)
    return f"{r[0]:.2f} (n={r[1]})" if r and r[0] is not None else "-"


def category_rows(result, market="PL", cond="ok"):
    groups = result["groups"]
    rows = []
    for cat in analysis.CATEGORIES:
        m = groups.get(("category", cat, "*", market, cond))
        if not m:
            continue
        rows.append([CAT_PL[cat], m["n_active"], zl(m["active_med"]), m["n_sold"], m["n_deleted"], st_range(m),
                     days(m), _ratio(result, cat, market, cond, "sold"), _ratio(result, cat, market, cond, "deleted"),
                     pct(m["drop_share"]), num(m["drop_pct_med"]) + "%",
                     f"{num(m['fav_active_med'], 0)} / {num(m['fav_sold_med'], 0)}"])
    return rows


def damaged_rows(groups):
    rows = []
    for cat in analysis.CATEGORIES:
        ok, bad = groups.get(("category", cat, "*", "PL", "ok")), groups.get(("category", cat, "*", "PL", "uszk"))
        if not bad:
            continue
        ratio = bad["active_med"] / ok["active_med"] if ok and ok["active_med"] and bad["active_med"] else None
        rows.append([CAT_PL[cat], bad["n_active"] + bad["n_sold"] + bad["n_deleted"], zl(ok and ok["active_med"]),
                     zl(bad["active_med"]), pct(ratio), zl(ok and ok["sold_med"]), zl(bad["sold_med"])])
    return rows


def top_rows(groups, level, per_category, market="PL", cond="ok"):
    """Konfiguracje z największą liczbą ZNIKNIĘĆ (sold + deleted) - pewnych sprzedaży jest za mało, by po nich
    sortować; usunięte to górna granica sprzedaży (zastrzeżenie 1). Tylko grupy z ≥ 5 aktywnymi (jest z czym
    porównać cenę)."""
    rows = []
    for cat in analysis.CATEGORIES:
        mine = [(k[2], m) for k, m in groups.items() if k[0] == level and k[1] == cat and k[3] == market
                and k[4] == cond and m["n_active"] >= 5 and m["n_sold"] + m["n_deleted"] > 0]
        mine.sort(key=lambda km: (-(km[1]["n_sold"] + km[1]["n_deleted"]), -km[1]["n_sold"], km[0]))
        for key, m in mine[:per_category]:
            spread = m["deleted_med"] / m["active_med"] if m["deleted_med"] and m["active_med"] else None
            rows.append([CAT_PL[cat], f"`{show_key(key)}`", m["n_active"],
                         f"{zl(m['active_p25'])}–{zl(m['active_med'])}–{zl(m['active_p75'])}",
                         m["n_sold"], zl(m["sold_med"]), m["n_deleted"], zl(m["deleted_med"]), num(spread, 2),
                         st_range(m), days(m)])
    return rows


def summary(result, flags_info, relist_info, day):
    groups = result["groups"]
    excl = ", ".join(flags_info["excluding"])
    lines = [f"# Raport rynku Vinted – {day}", "",
             f"Dane do {result['now'][:16].replace('T', ' ')} UTC · „stare aktywne” = starsze niż "
             f"{result['age_days']} dni · ceny w zł · grupy: {len(groups)} (pełna tabela: `configs.csv`, "
             f"`report.html`)", "",
             "## Zastrzeżenia (czytaj przed wnioskami)",
             "1. **sold = dolna granica sprzedaży.** Do ~2026-10-20 sprzedane trafiały do `deleted` (przebudowa API "
             "Vinted); `recheck` odzyskał część, reszta ofert już nie istnieje. Stąd **widełki**: "
             "ST = sell-through, dolna = sold / (sold + deleted + aktywne starsze niż "
             f"{result['age_days']} dni), górna = (sold + deleted) / (to samo).",
             "2. **Cena sprzedaży = ostatnia cena wystawienia** („Zaproponuj cenę” niewidoczne) → górna granica "
             "ceny transakcji (*).",
             "3. **Dni do sprzedaży** tylko dla ofert z datą wystawienia (`created_at`) albo widzianych pierwszy raz "
             "PO pierwszym przejściu kategorii; n = z ilu ofert. Relisty: czas od pierwszej oferty łańcucha.",
             "4. Rynek PL i zagraniczny osobno (waluta sprzedawcy; bez niej ułamkowa cena w zł = zagr.). Obniżki "
             "tylko prawdziwe (bez dryfu kursu: PLN każda zmiana, waluty ≥ 1%).",
             f"5. Wykluczone ze statystyk: flagi {excl} oraz oferty, które wystawiono od nowa (relist A→B: "
             f"A nie jest ani sprzedażą, ani zniknięciem). Sklepy (`shop_like`) i wzmianki OLX/Allegro zostają.",
             f"6. `uszk` = na części / blokada / pęknięcie (z ekstrakcji; stan z AI dla "
             f"{result.get('ai_condition', 0)} ofert) – osobno od sprawnych.",
             "7. `blocked` (sprzedana, strona oferty 404) liczona jako **sprzedana** – ceny blocked rozkładają się jak "
             "ceny sold (tabela niżej); oszustwa wycinają flagi cenowe.", "",
             "## 1. Jakość danych",
             "„w analizie” = po wykluczeniach; „z kluczem” = ma `config_key` (konfigurację).", ""]
    lines += table(["kategoria", "ofert", "aktywne", "sprzed.", "usunięte", "blocked", "wykl. flagami",
                    "relisty (A)", "w analizie", "z kluczem", "zagr."], quality_rows(result, flags_info))
    counts = flags_info["counts"]
    lines += ["", "Flagi (ofert): " + ", ".join(f"{f} {counts.get(f, 0)}" for f in flags_info["all"])
              + f" · relistów: {relist_info['pairs']} (opis {relist_info['by_description']}, tytuł "
                f"{relist_info['by_title']})", "",
              ]
    if flags_info.get("price_check"):
        lines += ["```"] + flags_info["price_check"] + ["```", ""]
    lines += ["## 2. Zwłoka sprawdzenia zniknięcia a udział sprzedanych (eksperyment C4)",
              "Zwłoka = chwila sprawdzenia (/services) − ostatnie widzenie w katalogu. Jeśli % sold maleje ze "
              "zwłoką, sprzedane oferty znikają z Vinted (404) po kilku dniach → część `deleted` to sprzedane.", ""]
    lines += table(["zwłoka", "sold (+blocked)", "deleted", "% sold", "mediana zwłoki"], delay_rows(result))
    cat_head = ["kategoria", "aktywne", "med. oferty", "sprzed.", "usunięte", "ST", "dni do sprzedaży",
                "sprzedana / aktywne*", "usunięta / aktywne", "z obniżką", "med. obniżki", "♥ akt / sprz"]
    lines += ["", "## 3. Kategorie – rynek PL, sprawne",
              "„sprzedana / aktywne” = mediana ilorazu ceny sprzedanej do mediany aktywnych TEJ SAMEJ konfiguracji "
              "(≥ 5 aktywnych); tak samo usunięte – jeśli usunięte są tańsze od aktywnych jak sprzedane, to "
              "wiele z nich to sprzedaże.", ""]
    lines += table(cat_head, category_rows(result))
    foreign = category_rows(result, market="zagr")
    if foreign:
        lines += ["", "## 4. Kategorie – rynek zagraniczny, sprawne", ""]
        lines += table(cat_head, foreign)
    damaged = damaged_rows(groups)
    if damaged:
        lines += ["", "## 5. Uszkodzone vs sprawne (PL)", ""]
        lines += table(["kategoria", "uszk. ofert", "med. oferty sprawne", "med. oferty uszk.", "uszk./sprawne",
                        "med. sprzedaży sprawne*", "med. sprzedaży uszk.*"], damaged)
    top_head = ["kat.", "konfiguracja", "akt.", "oferta", "sprz.", "sprzedaż*", "usun.", "usunięta", "usun./akt.",
                "ST", "dni (n)"]
    lines += ["", f"## 6. Konfiguracje z największą liczbą zniknięć (PL, sprawne, ≥ 5 aktywnych; top {TOP_CONFIGS})",
              "Oferta aktywnych: p25–mediana–p75; sprzedaż* / usunięta = mediana ostatniej ceny; usun./akt. = "
              "mediana usuniętych / mediana aktywnych.", ""]
    lines += table(top_head, top_rows(groups, "config", TOP_CONFIGS))
    lines += ["", f"## 7. Poziom wyżej (laptop: CPU+RAM, telefon/tablet: model, konsola: platforma+wariant…; "
                  f"top {TOP_PARENTS})", ""]
    lines += table(["kat.", "grupa"] + top_head[2:], top_rows(groups, "parent", TOP_PARENTS))
    lines += ["", "(*) górna granica ceny transakcji (ostatnia cena wystawienia)."]
    return lines


# ---------------------------------------------------------------------------------------------- pliki


def write_csv(path, groups):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for k in sorted(groups, key=lambda k: (k[0], k[1], -groups[k]["n_sold"], k[2], k[3], k[4])):
            m = groups[k]
            row = list(k) + [m[c] for c in COLUMNS[5:]]
            w.writerow(["" if v is None else round(v, 2) if isinstance(v, float) else int(v)
                        if isinstance(v, bool) else v for v in row])


_CSS = """
:root{--bg:#fbfaf8;--fg:#1d1d1b;--muted:#6b6a66;--line:#e4e1da;--head:#f1efe9;--accent:#3b6ea5;--warn:#9a5b00}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#171716;--fg:#ecebe7;--muted:#a3a19b;
--line:#34332f;--head:#232220;--accent:#7fb0e6;--warn:#f0b35a}}
:root[data-theme="dark"]{--bg:#171716;--fg:#ecebe7;--muted:#a3a19b;--line:#34332f;--head:#232220;--accent:#7fb0e6;
--warn:#f0b35a}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif;margin:0;
padding:16px;max-width:1400px}
h1{font-size:22px}h2{font-size:17px;margin-top:28px}p,li{color:var(--fg)}small,.muted{color:var(--muted)}
.wrap{overflow-x:auto}table{border-collapse:collapse;font-variant-numeric:tabular-nums;margin:8px 0}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:right;white-space:nowrap}
th{background:var(--head);position:sticky;top:0;cursor:pointer;user-select:none}
td:first-child,th:first-child,td.t,#configs th:nth-child(-n+5){text-align:left}code{font-size:12px}.warn{color:var(--warn)}
input{font:inherit;padding:4px 8px;border:1px solid var(--line);background:var(--bg);color:var(--fg);width:min(420px,100%)}
"""

_JS = """
document.querySelectorAll('table.sort').forEach(t=>{t.querySelectorAll('th').forEach((th,i)=>{th.onclick=()=>{
const b=t.tBodies[0],rows=[...b.rows],dir=th.dataset.d=th.dataset.d==='1'?'-1':'1';
const v=r=>{const s=r.cells[i].dataset.v??r.cells[i].textContent;const n=parseFloat(s);return isNaN(n)?s:n};
rows.sort((x,y)=>{const a=v(x),c=v(y);return (a>c?1:a<c?-1:0)*dir});rows.forEach(r=>b.appendChild(r))}})});
const f=document.getElementById('filter');if(f)f.oninput=()=>{const q=f.value.toLowerCase().split(/\\s+/);
document.querySelectorAll('#configs tbody tr').forEach(r=>{const s=r.textContent.toLowerCase();
r.style.display=q.every(w=>s.includes(w))?'':'none'})};
"""


def _md_table_to_html(lines):
    """Tabela markdown (z summary) → HTML (sortowalna)."""
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in lines]
    head, body = rows[0], rows[2:]
    esc = lambda s: html.escape(s).replace("`", "")  # noqa: E731
    out = ['<div class="wrap"><table class="sort"><thead><tr>' + "".join(f"<th>{esc(h)}</th>" for h in head)
           + "</tr></thead><tbody>"]
    for row in body:
        out.append("<tr>" + "".join(f'<td class="t">{esc(c)}</td>' if i < 2 else f"<td>{esc(c)}</td>"
                                    for i, c in enumerate(row)) + "</tr>")
    return out + ["</tbody></table></div>"]


def write_html(path, summary_lines, groups):
    out = ["<!doctype html><html lang=pl><head><meta charset=utf-8>",
           '<meta name=viewport content="width=device-width,initial-scale=1"><title>Raport rynku Vinted</title>',
           f"<style>{_CSS}</style></head><body>"]
    i = 0
    while i < len(summary_lines):
        line = summary_lines[i]
        if line.startswith("```"):
            i += 1
            block = []
            while i < len(summary_lines) and not summary_lines[i].startswith("```"):
                block.append(html.escape(summary_lines[i]))
                i += 1
            out.append("<div class=wrap><pre>" + "\n".join(block) + "</pre></div>")
            i += 1
            continue
        if line.startswith("|"):
            block = []
            while i < len(summary_lines) and summary_lines[i].startswith("|"):
                block.append(summary_lines[i])
                i += 1
            out += _md_table_to_html(block)
            continue
        text = re.sub(r"`([^`]*)`", r"<code>\1</code>", html.escape(line).replace("**", ""))
        if line.startswith("# "):
            out.append(f"<h1>{text[2:]}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{text[3:]}</h2>")
        elif line.strip():
            out.append(f"<p>{text}</p>")
        i += 1
    shown = [k for k in groups if k[0] == "category" or
             groups[k]["n_active"] + groups[k]["n_sold"] + groups[k]["n_deleted"] >= HTML_MIN_OFFERS]
    out += ["<h2>Grupy</h2>", f"<p class=muted>{len(shown)} z {len(groups)} grup (tu tylko grupy z ≥ "
            f"{HTML_MIN_OFFERS} ofertami; wszystkie są w configs.csv). Poziom config = konfiguracja, parent = poziom "
            "wyżej, category = cała kategoria. Kliknij nagłówek, by sortować; filtr: słowa oddzielone spacją "
            "(np. <code>phone PL ok iphone</code>).</p>", '<input id=filter placeholder="filtr…">',
            '<div class=wrap><table class=sort id=configs><thead><tr>'
            + "".join(f"<th>{c}</th>" for c in COLUMNS) + "</tr></thead><tbody>"]
    for k in sorted(shown, key=lambda k: (k[0] != "config", k[1], -groups[k]["n_sold"] - groups[k]["n_deleted"],
                                          k[2])):
        m = groups[k]
        cells = [f'<td class="t">{html.escape(str(v))}</td>' for v in k]
        for c in COLUMNS[5:]:
            v = m[c]
            if v is None:
                cells.append('<td data-v="-1">-</td>')
            elif isinstance(v, bool):
                cells.append(f'<td class="{"warn" if v else ""}">{"tak" if v else ""}</td>')
            elif isinstance(v, float):
                cells.append(f'<td data-v="{v}">{v:.2f}</td>' if abs(v) < 10 else f'<td data-v="{v}">{v:.0f}</td>')
            else:
                cells.append(f"<td>{v}</td>")
        out.append("<tr>" + "".join(cells) + "</tr>")
    out += ["</tbody></table></div>", f"<script>{_JS}</script></body></html>"]
    path.write_text("\n".join(out), encoding="utf-8")


def build(conn, aconn, out, age_days=14, photo_flag=False, recompute=True, progress=None, bar=True):
    """Cały raport: flagi + relisty (od nowa, jeśli recompute) → statystyki → pliki w `out`. → (ścieżki, linie)."""
    from . import relist, stats, suspicious

    say = progress or (lambda _t: None)
    if recompute:
        say("1/3 Flagi podejrzanych ofert...")
        suspicious.run(conn, aconn, photo_flag, progress=say)
        say("2/3 Relisty...")
        relist.run(conn, aconn, progress=say)
    say("3/3 Statystyki...")
    excluding = suspicious.EXCLUDING if photo_flag else tuple(f for f in suspicious.EXCLUDING
                                                               if f != "is_suspicious")
    excluded = suspicious.load(aconn, excluding)
    relists = relist.load(aconn)
    from .ai_condition import load_damaged
    ai_damaged = load_damaged(aconn)
    if ai_damaged:
        say(f"  stan techniczny z AI dla {len(ai_damaged)} ofert (zamiast reguł)")
    result = stats.collect(conn, excluded, relists, age_days, progress=bar, ai_damaged=ai_damaged)
    result["ai_condition"] = len(ai_damaged)
    counts = dict(aconn.execute("SELECT flag, COUNT(*) FROM flags GROUP BY flag").fetchall())
    flags_info = {"excluding": excluding, "counts": counts, "all": suspicious.ALL_FLAGS,
                  "price_check": suspicious.price_check(conn)}
    basis = dict(aconn.execute("SELECT basis, COUNT(*) FROM relists GROUP BY basis").fetchall())
    relist_info = {"pairs": len(relists), "by_description": basis.get("description", 0),
                   "by_title": basis.get("title", 0)}
    day = out.name
    lines = summary(result, flags_info, relist_info, day)
    paths = {"summary": out / "summary.md", "configs": out / "configs.csv", "html": out / "report.html"}
    paths["summary"].write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_csv(paths["configs"], result["groups"])
    write_html(paths["html"], lines, result["groups"])
    (out / "stats.json").write_text(json.dumps(
        {"now": result["now"], "age_days": age_days, "groups": [list(k) + [m] for k, m in result["groups"].items()]},
        ensure_ascii=False), encoding="utf-8")
    return paths, lines, result
