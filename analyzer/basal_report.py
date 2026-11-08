"""Raport z wyników basal-test (2026-11-07): `python -m analyzer basal-raport --katalog D:\\basal\\v2 --etykieta 45b`.

Per rodzina i pytanie: trafność na przypadkach testowych, zgodność z regułami (gdy reguła coś wie), odpowiedzi pewne
(≥ 70%) i niepewne ze wzorcem; zbiorczo per pytanie (model, pamiec, stan ...) przez wszystkie rodziny; lista
„pewnych błędów” (pewność ≥ 70%, a odpowiedź inna niż oczekiwana w przypadku testowym) - od nich zaczyna się
poprawianie instrukcji basala; lista „pewnych rozbieżności z regułami” na prawdziwych ofertach (08.11: w ~90% to
reguła się myliła - zaprzeczenia, języki, formułki - więc „R” to dolna granica trafności basala). Bez sieci, bez bazy.
"""

import json
import re
from collections import defaultdict
from pathlib import Path

from .basal_families import NO_RULE, UNKNOWN

CONFIDENT = 0.7


def latest_results(folder, label=""):
    """Najnowszy plik wyników dla każdej próbki (z daną etykietą)."""
    best = {}
    for path in Path(folder).glob("*_wyniki_*.json"):
        m = re.match(r"(.+?)_wyniki_(?:(.+)_)?(\d{4})\.json$", path.name)
        if not m or (label and m.group(2) != label):
            continue
        stem = m.group(1)
        if stem not in best or path.stat().st_mtime > best[stem].stat().st_mtime:
            best[stem] = path
    return best


def _family(stem):
    from . import basal_poc

    return basal_poc.family_from_path(f"{stem}.jsonl")


def summarize(results, questions):
    out = {}
    for q in questions:
        c = defaultdict(int)
        for r in results:
            ans, conf = r["answers"].get(q), r["confidence"].get(q) or 0
            want = r["expected"].get(q) if r["expected"] else r["rules_all"].get(q)
            if r["expected"] and q in r["expected"]:
                c["test"] += 1
                c["test_ok"] += ans == want
            elif not r["expected"] and want not in NO_RULE:
                c["rule"] += 1
                c["rule_ok"] += ans == want
            else:
                c["unknown_ref"] += 1
                c["basal_unknown"] += ans == UNKNOWN
                continue
            key = "sure" if conf >= CONFIDENT else "unsure"
            c[key] += 1
            c[f"{key}_ok"] += ans == want
        out[q] = dict(c)
    return out


def _ratio(ok, n):
    return f"{ok}/{n}" if n else "-"


def write(folder, label=""):
    folder = Path(folder)
    found = latest_results(folder, label)
    lines, data = [], {"rodziny": {}, "pytania": {}, "pewne_bledy": [], "rozbieznosci_z_regulami": []}
    totals = defaultdict(lambda: defaultdict(int))
    times = []
    for stem, path in sorted(found.items()):
        content = json.loads(path.read_text(encoding="utf-8"))
        results, summary = content["wyniki"], content["podsumowanie"]
        fam = _family(stem) or stem
        questions = list(results[0]["answers"]) if results else []
        per_q = summarize(results, questions)
        ms = (summary.get("czas_ms") or {}).get("mediana")
        if ms:
            times.append((ms, len(results)))
        data["rodziny"][fam] = {"plik": path.name, "ofert": len(results), "mediana_ms": ms, "pytania": per_q}
        parts = []
        for q, c in per_q.items():
            for k, v in c.items():
                totals[q][k] += v
            parts.append(
                f"{q} T{_ratio(c.get('test_ok', 0), c.get('test', 0))} "
                f"R{_ratio(c.get('rule_ok', 0), c.get('rule', 0))} "
                f"P{_ratio(c.get('sure_ok', 0), c.get('sure', 0))}"
            )
        lines.append(f"{fam:<26} {len(results):>3} ofert {ms or '?':>5} ms | " + " | ".join(parts))
        for r in results:
            if not r["expected"]:
                for q, ans in r["answers"].items():
                    rule, conf = r["rules_all"].get(q), r["confidence"].get(q) or 0
                    if rule not in NO_RULE and ans not in (None, UNKNOWN) and ans != rule and conf >= CONFIDENT:
                        data["rozbieznosci_z_regulami"].append(
                            {"rodzina": fam, "tytul": r["title"], "pytanie": q, "odpowiedz": ans,
                             "pewnosc": round(conf, 2), "regula": rule}
                        )
            for q, want in r["expected"].items():
                conf = r["confidence"].get(q) or 0
                if r["answers"].get(q) != want and conf >= CONFIDENT:
                    data["pewne_bledy"].append(
                        {
                            "rodzina": fam,
                            "tytul": r["title"],
                            "pytanie": q,
                            "odpowiedz": r["answers"].get(q),
                            "pewnosc": round(conf, 2),
                            "oczekiwane": want,
                        }
                    )
    head = [
        f"Wyniki basala ({label or 'wszystkie etykiety'}): {len(found)} rodzin, "
        f"{sum(n for _ms, n in times)} ofert"
        + (f", mediana czasu {sorted(m for m, _ in times)[len(times) // 2]} ms" if times else ""),
        "T = przypadki testowe OK/razem, R = zgodność z regułami (reguły też się mylą), P = pewne (≥ 70%) zgodne "
        "ze wzorcem / pewne",
        "",
    ]
    agg = ["", "Zbiorczo per pytanie (wszystkie rodziny):"]
    for q, c in sorted(totals.items(), key=lambda kv: -kv[1].get("sure", 0)):
        data["pytania"][q] = dict(c)
        agg.append(
            f"  {q:<12} testy {_ratio(c['test_ok'], c['test']):>9}  reguły {_ratio(c['rule_ok'], c['rule']):>9}  "
            f"pewne {_ratio(c['sure_ok'], c['sure']):>9}  niepewne {_ratio(c['unsure_ok'], c['unsure']):>9}"
        )
    errs = ["", f"Pewne błędy na przypadkach testowych: {len(data['pewne_bledy'])} (pierwsze 40)"]
    errs += [
        f"  {e['rodzina']}: {e['tytul'][:50]} | {e['pytanie']}: {e['odpowiedz']} ({e['pewnosc']:.0%}), "
        f"oczekiwane {e['oczekiwane']}"
        for e in data["pewne_bledy"][:40]
    ]
    by_q = defaultdict(list)
    for e in data["rozbieznosci_z_regulami"]:
        by_q[e["pytanie"]].append(e)
    diff = ["", f"Pewne rozbieżności z regułami (prawdziwe oferty): {len(data['rozbieznosci_z_regulami'])} - kto ma "
                "rację? (po 3 na pytanie, całość w .json)"]
    for q, items in sorted(by_q.items(), key=lambda kv: -len(kv[1])):
        diff.append(f"  {q} ({len(items)}):")
        diff += [f"    {e['rodzina']}: {e['tytul'][:55]} | basal {e['odpowiedz']} ({e['pewnosc']:.0%}), reguła "
                 f"{e['regula']}" for e in items[:3]]
    text = "\n".join(head + lines + agg + errs + diff)
    name = f"raport_{label or 'wszystko'}"
    (folder / f"{name}.txt").write_text(text, encoding="utf-8")
    (folder / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return text, folder / f"{name}.txt"
