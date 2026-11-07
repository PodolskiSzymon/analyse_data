"""Rodziny basala v2 (2026-11-07): prawie cały rynek z bazy - telefony, tablety, konsole, laptopy, zestawy, karty,
RAM, dyski, procesory, płyty główne. Użytkownik: „jak widzisz podstawowy model, sprawdź każdy jego wariant, modele
pochodne, różne ilości dysku, RAM-u, karty graficznej, taktowania, akcesoria, dodatkowe gry...”.

Rodzina = jeden model bazowy (albo linia) z wariantami, które tytuł pomija albo myli: iPhone 13 mini / 13 / Pro /
Pro Max, Galaxy S23 / S23+ / Ultra / FE, PS5 z napędem / Digital / Slim / Pro, Switch V1 / V2 / OLED / Lite,
Latitude 5420 / 5520 / 7420, GTX 1650 GDDR5 / GDDR6 / Super... Każda rodzina ma pytania z zamkniętą listą odpowiedzi
(basal wybiera jedną, z pewnością), reguły regex do porównania (z samego tytułu i z tytułu + opisu + formularza)
i przypadki testowe z oczekiwanymi odpowiedziami. Listy wariantów i pojemności - z danych (model z formularza Vinted,
tytuły), sprawdzone ręcznie; specyfikacje rodzin w `basal_specs.py`.

Formularz Vinted (model, pamięć, bateria, blokada SIM, RAM / dysk laptopa, platforma konsoli) trafia do basala jako
osobna linia „bywa błędny” - częste pułapki: „256 MB” zamiast 256 GB, RAM w polu dysku, zły model z listy.
"""

import random
import re

from . import extract as X

UNKNOWN = "nie_wiadomo"
CONFLICT = "sprzeczne"
NO_RULE = (None, UNKNOWN, CONFLICT)


def q(instructions, criteria):
    return {"instructions": instructions, "criteria": criteria}


def nrm(text):
    """Tekst do dopasowań: małe litery bez ogonków (extract.norm), „+” → „ plus ”, „one plus” → „oneplus”,
    „Mi 13” → „xiaomi 13”."""
    t = X.norm(text).replace("+", " plus ")
    t = re.sub(r"\bone\s?plus\b", "oneplus", t)
    t = re.sub(r"(?<![a-z])mi\s?(?=\d)", "xiaomi ", t)
    return re.sub(r"\s+", " ", t).strip()


SEP = r"[\s\-_/().,]*"
JOIN = SEP + r"(?:[45]\s?g" + SEP + r")?"  # „Mi 11 Lite 5G NE”, „Galaxy S21 5G FE” - 5G / 4G w środku nazwy


def tokens(name):
    return re.findall(r"[a-z]+|\d+", nrm(name))


def token_regex(toks, optional=()):
    """Tokeny nazwy po kolei; słowa z `optional` (marka, „gaming”) mogą być pominięte w tekście."""
    parts = [rf"(?:{re.escape(t)}{JOIN})?" if t in optional else re.escape(t) + JOIN for t in toks]
    return (
        r"(?<![a-z0-9])" + "".join(parts)[: -len(JOIN)] + r"(?![a-z0-9])"
        if not toks[-1] in optional
        else r"(?<![a-z0-9])" + "".join(parts) + r"(?![a-z0-9])"
    )


def gb_label(value):
    return f"{value // 1000}tb" if value >= 1000 and value % 1000 == 0 else f"{value}gb"


def gb_text(value):
    return f"{value // 1000} TB" if value >= 1000 and value % 1000 == 0 else f"{value} GB"


# ---------------------------------------------------------------------------------------------- warianty


class Variant:
    """Wariant rodziny: klucz odpowiedzi, opis dla basala, regex (z nazwy albo podany)."""

    def __init__(self, key, label, regex, note=""):
        self.key, self.label, self.note = key, label, note
        self.rx = re.compile(regex)
        self.toks = key.split("_")

    def describe(self):
        return f"{self.label}{' - ' + self.note if self.note else ''}"


def make_variants(items, drop=()):
    """items: nazwa | (nazwa, regex) | (nazwa, regex, uwaga) | (klucz, nazwa, regex, uwaga).
    Regex z nazwy: tokeny bez słów marki (drop), o ile nie zostaje sama liczba („iPhone 13” zostaje w całości)."""
    out, seen = [], set()
    for item in items:
        if isinstance(item, str):
            item = (item,)
        if len(item) == 4:
            key, label, regex, note = item
        else:
            label = item[0]
            regex = item[1] if len(item) > 1 else None
            note = item[2] if len(item) > 2 else ""
            toks = tokens(label)
            short = [t for t in toks if t not in drop]
            while short and short[0].isdigit() and len(short) < len(toks):
                short.insert(0, toks[len(toks) - len(short) - 1])
            key = "_".join(short or toks)
            if not regex:
                # słowa marki opcjonalne, ale gdy po nich zostaje sama liczba („Honor 90”) - wymagane
                required = set(short) if short else set(toks)
                regex = token_regex(toks, optional={t for t in toks if t in drop and t not in required})
        if key in seen:
            continue
        seen.add(key)
        out.append(Variant(key, label, regex, note))
    return out


def find_variants(variants, text):
    """Klucze wariantów w tekście; dopasowanie zawarte w dłuższym (13 w „13 pro max”) się nie liczy."""
    spans = []
    for v in variants:
        for m in v.rx.finditer(text):
            spans.append((m.start(), m.end(), v.key))
    keep = set()
    for s, e, k in spans:
        # nakładające się dopasowania: wygrywa to, które sięga dalej w prawo („tab a 8.0” > „tab a 8”, „13 pro max”
        # > „13”), przy tym samym końcu - dłuższe
        if not any(k2 != k and s2 < e and s < e2 and (e2 > e or (e2 == e and e2 - s2 > e - s)) for s2, e2, k2 in spans):
            keep.add(k)
    return keep


def extends(variants, base, other):
    """Czy wariant `other` rozszerza `base` (S23 → S23 FE, 13 → 13 Pro)."""
    b = next((v.toks for v in variants if v.key == base), [])
    o = next((v.toks for v in variants if v.key == other), [])
    return len(o) > len(b) and o[: len(b)] == b


def rule_variant(variants, title, desc="", form_model=None):
    """Wariant z tytułu, gdy tytuł go mówi; gdy tytuł podaje ogólny model, a opis jego rozszerzenie - sprzeczne;
    bez wariantu w tytule - z opisu, potem z formularza."""
    t_keys = find_variants(variants, nrm(title))
    d_keys = find_variants(variants, nrm(desc)) if desc else set()
    if len(t_keys) > 1:
        return CONFLICT
    if t_keys:
        key = next(iter(t_keys))
        if any(extends(variants, key, k) for k in d_keys):
            return CONFLICT
        return key
    if len(d_keys) == 1:
        return next(iter(d_keys))
    if len(d_keys) > 1:
        return CONFLICT
    if form_model:
        f_keys = find_variants(variants, nrm(form_model))
        if len(f_keys) == 1:
            return next(iter(f_keys))
    return UNKNOWN


# ---------------------------------------------------------------------------------------------- reguły wspólne


def _first(*values):
    return next((v for v in values if v not in NO_RULE), UNKNOWN)


def _one(values):
    values = set(values)
    return values.pop() if len(values) == 1 else (UNKNOWN if not values else CONFLICT)


SIZES = re.compile(r"(?<![\d.,])(\d{1,4})\s?(gb|tb|g)(?![a-z])")
PAIR = re.compile(r"(?<![\d.,])(\d{1,2})\s?(?:gb)?\s?(?:ram)?\s?[/+]\s?(\d{2,4})\s?(?:gb|tb)?(?![\d.,])")


def storage_rule(options, title, desc="", form_raw=None, form_min=16):
    """Pamięć z tytułu, potem z opisu (wartości z listy rodziny; „8/256” → 256), potem z formularza
    („256 MB” → 256 GB). Kilka różnych wartości z listy w jednym tekście → sprzeczne."""
    opts = set(options)

    def from_text(text):
        t = nrm(text)
        vals = [int(b) for a, b in PAIR.findall(t)]
        vals += [int(n) * (1000 if u == "tb" else 1) for n, u in SIZES.findall(t)]
        hits = {v for v in vals if v in opts}
        if len(hits) > 1:  # „8 GB RAM, 128 GB” przy starych iPhonach 8 GB też jest na liście
            big = {v for v in hits if v >= 32}
            hits = big if len(big) == 1 else hits
        return _one(hits)

    by_title = from_text(title)
    if by_title != UNKNOWN:
        return gb_label(by_title) if isinstance(by_title, int) else by_title
    by_desc = from_text(desc) if desc else UNKNOWN
    if by_desc != UNKNOWN:
        return gb_label(by_desc) if isinstance(by_desc, int) else by_desc
    if form_raw:
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(tb|gb|mb)", X.norm(form_raw))
        if m:
            value = float(m.group(1).replace(",", "."))
            value = int(value * 1000) if m.group(2) == "tb" else int(value)
            if (m.group(2) == "mb" or value >= form_min) and value in opts:
                return gb_label(value)
    return UNKNOWN


def ram_rule(options, title, desc=""):
    for text in (title, desc):
        t = nrm(text)
        vals = [int(a) for a, b in PAIR.findall(t) if int(a) in options and int(b) >= 32]
        m = X.RAM.search(t)
        if m:
            vals.append(int(m.group(1) or m.group(2)))
        hits = {v for v in vals if v in options}
        if hits:
            return f"{hits.pop()}gb" if len(hits) == 1 else CONFLICT
    return UNKNOWN


def fault_rule(text):
    t = X.norm(text)
    if X.has_fault(X.FOR_PARTS, t):
        return "na_czesci"
    if X.has_fault(X.CRACKED, t):
        return "pekniety"
    return UNKNOWN


ICLOUD = re.compile(
    r"\b(?:icloud|activation lock|frp|konto google|konto samsung|google account|mdm|"
    r"zarzadzan\w* przez firm\w*|zablokowan\w* na konc\w*|blokad\w* konta)"
)
SIMLOCK = re.compile(
    r"\b(?:simlock(?! ?free)|sim-?lock(?! ?free)|zablokowan\w* (?:na|do) (?:siec|operator)\w*|"
    r"locked to|tylko (?:na|do) (?:siec|karty) (?:play|orange|plus|t-?mobile|heyah)|"
    r"blokad\w* (?:na )?(?:siec|operatora|sim))"
)


def lock_rule(text, form_sim=None):
    t = X.norm(text)
    if X.NOT_LOCKED.search(t):
        return "brak"
    if ICLOUD.search(t) and X.has_fault(ICLOUD, t):
        return "konto"
    if SIMLOCK.search(t) and X.has_fault(SIMLOCK, t):
        return "simlock"
    sim = X.norm(form_sim or "")
    if sim.startswith("blokada aktywna"):
        return "simlock"
    if sim.startswith("brak"):
        return "brak"
    return UNKNOWN


def battery_rule(text, form_bucket=None):
    for part in text.split("\n"):
        m = X.BATTERY.search(X.norm(part))
        if m:
            pct = int(m.group(1) or m.group(2))
            if 40 <= pct <= 100:
                return (
                    "95_100"
                    if pct >= 95
                    else "90_94" if pct >= 90 else "85_89" if pct >= 85 else "80_84" if pct >= 80 else "ponizej_80"
                )
    b = X.norm(form_bucket or "")
    return {"95-100%": "95_100", "90-94%": "90_94", "85-89%": "85_89", "80-84%": "80_84", "<80%": "ponizej_80"}.get(
        b.replace("–", "-"), UNKNOWN
    )


def what_rule(title, patterns, default, matched):
    t = nrm(title)
    for label, rx in patterns:
        if re.search(rx, t):
            return label
    return default if matched else UNKNOWN


WANTED = r"^(?:kupie|kupi[eę]|szukam|zamienie|zamiana|wtb|looking for|cumpar|vasarolok|keresek)\b|\bzamienie\b"
FAKE = r"\b(?:replika|replica|klon|clone|kopia|copy 1:1|1:1|fake|atrapa|dummy|podrobk\w*|imitacj\w*|niby)\b"
BOX = r"^(?:pudelko|pudelka|box|karton|opakowanie|krabice|doboz|cutie)\b|\b(?:samo|tylko|puste) (?:pudelko|opakowanie|box)"


# ---------------------------------------------------------------------------------------------- pytania wspólne

STATE_PHONE = q(
    "Jaki jest stan techniczny i wizualny SPRZEDAWANEGO urządzenia? Czytaj cały opis - zaprzeczenia "
    "(„bez rys”, „nie zbity”, „no cracks”) zmieniają znaczenie.",
    {
        "idealny": "jak nowy / bez śladów użytkowania, wszystko działa",
        "slady_uzytkowania": "drobne rysy, otarcia, ślady użytkowania - wszystko działa",
        "pekniety": "pęknięty / zbity ekran, tył (plecki) albo szkiełko aparatu - poza tym działa",
        "usterka": "coś nie działa albo jest do naprawy (Face ID, aparat, głośnik, ładowanie, linie na "
        "ekranie, bateria do wymiany / „serwis”), ale się włącza",
        "na_czesci": "nie włącza się, zalany, „na części”",
        UNKNOWN: "nie da się ustalić",
    },
)
LOCK_PHONE = q(
    "Czy urządzenie ma blokadę? Konto (iCloud / Google / Samsung, „FRP”, MDM firmowy) - nie da się "
    "używać; simlock - działa tylko z kartą jednej sieci. „Bez blokad”, „odblokowany”, „wylogowany z "
    "iCloud” = brak.",
    {
        "brak": "brak blokady (wylogowany, bez simlocka)",
        "konto": "blokada konta: iCloud / Google / Samsung (FRP) / MDM firmowy",
        "simlock": "simlock - zablokowany na jedną sieć (operatora)",
        UNKNOWN: "nie da się ustalić",
    },
)
BATTERY_Q = q(
    "Jaka jest kondycja baterii (maksymalna pojemność w %)? Opis często podaje liczbę („bateria 87%”, "
    "„kondycja 91%”), formularz - przedział. Gdy nic nie wiadomo - nie zgaduj.",
    {
        "95_100": "95-100%",
        "90_94": "90-94%",
        "85_89": "85-89%",
        "80_84": "80-84%",
        "ponizej_80": "poniżej 80% (albo „bateria do wymiany”, „serwis”)",
        UNKNOWN: "nie da się ustalić",
    },
)
WHAT_PHONE = q(
    "Co DOKŁADNIE dostaje kupujący za podaną cenę? Etui, ładowarka czy pudełko dodane do telefonu to " "nadal telefon.",
    {
        "telefon": "telefon (sam albo z dodatkami: etui, ładowarka, pudełko, szkło)",
        "kilka_telefonow": "dwa lub więcej telefonów w jednej ofercie (cena za komplet)",
        "akcesorium": "tylko akcesorium (etui, szkło, ładowarka, słuchawki, pasek) - bez telefonu",
        "czesc": "tylko część (ekran, bateria, obudowa, płyta, aparat) - bez całego telefonu",
        "pudelko": "samo pudełko (karton) po telefonie, bez telefonu",
        "podrobka": "podróbka / klon / replika / atrapa - nie oryginalny producent",
        "kupie_zamienie": "ogłoszenie kupna („kupię”, „szukam”) albo tylko zamiana",
        "inna_rzecz": "zupełnie inna rzecz",
    },
)
PHONE_WHAT_RULES = (
    ("kupie_zamienie", WANTED),
    ("pudelko", BOX),
    ("podrobka", FAKE),
    (
        "akcesorium",
        r"^(?:etui|case|cover|pokrowiec|szklo|szkielko|folia|ladowarka|kabel|"
        r"sluchawki|uchwyt|pasek|husa|tok)\b|\b(?:etui|case|szklo|folia) (?:do|na|for)\b",
    ),
    ("czesc", r"^(?:wyswietlacz|ekran|lcd|display|bateria|obudowa|plyta|klapka|tasma|aparat)\b"),
    ("kilka_telefonow", r"^(?:\d\s?x|[2-9] ?(?:szt|sztuk))|\b(?:dwa|2) telefony\b"),
)
PHONE_FLAGS_APPLE = {
    "czesci_nieoryginalne": "Czy w telefonie wymieniono ekran, baterię albo inną część na NIEORYGINALNĄ (zamiennik, "
    "komunikat „nieznana część”, „ekran nieoryginalny”)? Oryginalne części z serwisu = nie.",
}


def model_q(kind, variants, extra=None):
    crit = {v.key: v.describe() for v in variants}
    crit.update(extra or {f"inny_model": f"inny {kind} spoza tej listy (inny model albo inna marka)"})
    crit[UNKNOWN] = "nie da się ustalić, który wariant"
    return q(
        f"Który DOKŁADNIE {kind} jest sprzedawany? Liczy się sprzedawana rzecz, nie modele wymienione dla "
        f"porównania ani te, do których pasuje akcesorium. Formularz Vinted bywa błędny - tytuł i opis są "
        f"ważniejsze. Gdy ogłoszenie nie mówi wersji - nie zgaduj.",
        crit,
    )


def storage_q(kind, options, note=""):
    crit = {gb_label(v): gb_text(v) for v in options}
    crit[UNKNOWN] = "nie da się ustalić"
    return q(
        f"Ile pamięci wbudowanej (na dane - NIE RAM) ma {kind}? „8/256” = 8 GB RAM i 256 GB pamięci. "
        f"W formularzu Vinted „256 MB” to zwykle pomyłka (= 256 GB), a mała wartość („8 GB”) bywa RAM-em. "
        f"{note}Gdy nie wiadomo - nie zgaduj.",
        crit,
    )


def ram_q(kind, options):
    crit = {f"{v}gb": f"{v} GB RAM" for v in options}
    crit[UNKNOWN] = "nie da się ustalić"
    return q(
        f"Ile pamięci RAM ma {kind}? „8/256” albo „8+256” = 8 GB RAM. Nie myl z pamięcią wbudowaną ani z "
        f"„RAM Plus” / wirtualnym RAM („8+8 GB” = 8 GB RAM). Gdy nie wiadomo - nie zgaduj.",
        crit,
    )


NET_Q = q(
    "Czy to wersja 5G, czy 4G (LTE)? Liczy się wersja urządzenia (np. „A52 5G”, „Note 13 Pro 5G”), nie zasięg "
    "w okolicy. Gdy ogłoszenie tego nie mówi - nie zgaduj.",
    {"5g": "wersja 5G", "4g": "wersja 4G / LTE (bez 5G)", UNKNOWN: "nie da się ustalić"},
)


# ---------------------------------------------------------------------------------------------- kategorie
# Każda kategoria: questions(spec) → pytania, rules(spec, title, desc, form) → odpowiedzi reguł, tricky(spec, i).


def phone_questions(spec):
    v = spec["variants"]
    qs = {"model": model_q("telefon", v)}
    if spec.get("storage"):
        qs["pamiec"] = storage_q("ten telefon", spec["storage"])
    if spec.get("ram"):
        qs["ram"] = ram_q("telefon", spec["ram"])
    if spec.get("net"):
        qs["siec"] = NET_Q
    if spec.get("apple"):
        qs["bateria"] = BATTERY_Q
    qs.update({"blokada": LOCK_PHONE, "stan": STATE_PHONE, "co": WHAT_PHONE})
    return qs


NET5 = re.compile(r"(?<![\d.,])5\s?g(?![a-z])")
NET4 = re.compile(r"(?<![\d.,])4\s?g(?![a-z])|\blte\b")


def net_rule(title, desc=""):
    t = nrm(title)
    if NET5.search(t):
        return "5g"
    if NET4.search(t):
        return "4g"
    d = nrm(desc)
    m = re.search(r"\b(?:wersj\w*|version|model)\s*:?\s*([45])\s?g\b", d)
    return f"{m.group(1)}g" if m else UNKNOWN


def phone_rules(spec, title, desc="", form=None):
    form = form or {}
    v = spec["variants"]
    text = f"{title}\n{desc}"
    model = rule_variant(v, title, desc, form.get("model_nav") if desc else None)
    out = {"model": model}
    if spec.get("storage"):
        out["pamiec"] = storage_rule(spec["storage"], title, desc, form.get("internal_memory_capacity"))
    if spec.get("ram"):
        out["ram"] = ram_rule(spec["ram"], title, desc)
    if spec.get("net"):
        out["siec"] = net_rule(title, desc)
    if spec.get("apple"):
        out["bateria"] = battery_rule(text, form.get("battery_health"))
    out["blokada"] = lock_rule(text, form.get("sim_lock"))
    out["stan"] = fault_rule(text)
    out["co"] = what_rule(
        title, PHONE_WHAT_RULES, "telefon", bool(find_variants(v, nrm(title))) and not re.search(FAKE, nrm(text))
    )
    return out


def _pick(spec, i, n=2):
    """Dwa warianty do przypadków testowych: bazowy i jego rozszerzenie (jeśli jest), zależnie od numeru rodziny."""
    v = spec["variants"]
    pairs = [(a, b) for a in v for b in v if extends(v, a.key, b.key)]
    if pairs:
        return pairs[i % len(pairs)]
    return v[i % len(v)], v[(i + 1) % len(v)]


def phone_tricky(spec, i):
    base, ext = _pick(spec, i)
    sto = spec.get("storage") or [64]
    s1, s2 = sto[min(1, len(sto) - 1)], sto[-1]
    price = spec.get("price", 800)
    apple = spec.get("apple")
    form = {
        "status": "Bardzo dobry",
        "model_nav": base.label,
        "internal_memory_capacity": f"{gb_text(s1)}",
        "sim_lock": "Brak blokady",
    }
    cases = [
        (
            dict(
                title=f"{base.label} {gb_text(s1)} (nie {ext.label})",
                description=f"Zwykły {base.label}, nie wersja {ext.label}. Bez rys, w pełni sprawny.",
                expected={"model": base.key, "stan": "idealny"},
            )
            if base.key != ext.key
            else None
        ),
        dict(
            title=base.label,
            description=f"Dokładnie model {ext.label}, pamięć {gb_text(s2)}. Sprawny.",
            expected={"model": ext.key, "pamiec": gb_label(s2)},
            form={**form, "internal_memory_capacity": ""},
        ),
        dict(
            title=f"Etui do {ext.label}",
            description="Etui silikonowe, nowe. Sprzedaję samo etui, telefonu brak.",
            expected={"co": "akcesorium"},
            price=30,
            form={"status": "Nowy z metką"},
        ),
        dict(
            title=f"Pudełko {base.label} {gb_text(s1)}",
            description="Samo pudełko po telefonie z instrukcją, " "telefonu nie ma.",
            expected={"co": "pudelko"},
            price=40,
            form={"status": "Dobry"},
        ),
        dict(
            title=f"{ext.label} {gb_text(s1)}",
            description="Pęknięty tył (plecki), ekran cały, wszystko działa.",
            expected={"model": ext.key, "stan": "pekniety"},
            price=int(price * 0.7),
        ),
        dict(
            title=f"{base.label}",
            description="Blokada konta (iCloud / Google) - nie znam hasła, sprzedaję " "w całości.",
            expected={"blokada": "konto"},
            price=int(price * 0.3),
        ),
        dict(
            title=f"{base.label}",
            description=f"Pamięć {gb_text(s2)}, bez blokad, sprawny, ślady użytkowania.",
            expected={"pamiec": gb_label(s2), "blokada": "brak", "stan": "slady_uzytkowania"},
            form={**form, "internal_memory_capacity": f"{s2 if s2 < 1000 else 1} {'MB' if s2 < 1000 else 'GB'}"},
        ),
        dict(
            title=f"Kupię {base.label}",
            description=f"Kupię {base.label} w dobrym stanie, oferty na priv.",
            expected={"co": "kupie_zamienie"},
            price=10,
            form={"status": "Dobry"},
        ),
        dict(
            title=f"{ext.label} {gb_text(s1)}",
            description="Bardzo dobra replika 1:1, wygląda jak oryginał.",
            expected={"co": "podrobka"},
            price=int(price * 0.2),
        ),
        dict(
            title=f"2x {base.label}",
            description="Dwa telefony w komplecie, cena za oba, oba sprawne.",
            expected={"co": "kilka_telefonow"},
            price=int(price * 1.8),
        ),
        dict(
            title=f"{base.label} {gb_text(s1)}",
            description="Nie ma pęknięć ani rys, wszystko działa, telefon "
            "zablokowany na sieć Plus (simlock)." + (" Bateria 100%." if apple else ""),
            expected={"stan": "idealny", "blokada": "simlock", **({"bateria": "95_100"} if apple else {})},
        ),
        dict(
            title=f"{ext.label} {gb_text(s2)}",
            description="Display cracked but works fine. Unlocked, no iCloud.",
            expected={"stan": "pekniety", "blokada": "brak", "model": ext.key},
        ),
    ]
    if spec.get("ram") and len(spec["ram"]) > 1:
        r = spec["ram"][-1]
        cases.append(
            dict(
                title=f"{base.label} {r}/{s1 if s1 < 1000 else 1}",
                description="Sprawny, bez blokad.",
                expected={"ram": f"{r}gb", "pamiec": gb_label(s1)},
            )
        )
    if spec.get("net"):
        cases.append(
            dict(
                title=base.label,
                description=f"Wersja 4G (bez 5G), {gb_text(s1)}.",
                expected={"siec": "4g", "pamiec": gb_label(s1)},
            )
        )
    if apple:
        cases.append(
            dict(
                title=f"{base.label} {gb_text(s1)}",
                description="Kondycja baterii 83%, telefon sprawny.",
                expected={"bateria": "80_84"},
                form={**form, "battery_health": "85–89%"},
            )
        )
    return _rotate([c for c in cases if c], i, 7, keep=2)


def _rotate(cases, i, n, keep=0):
    """Pierwsze `keep` zawsze, resztę rotacyjnie wg numeru rodziny - razem wszystkie szablony się pojawią."""
    head, rest = cases[:keep], cases[keep:]
    if not rest:
        return head
    start = (i * 3) % len(rest)
    return head + (rest[start:] + rest[:start])[: max(0, n - keep)]


# ---------------------------------------------------------------------------------------------- tablety

CONNECT_Q = q(
    "Czy tablet ma modem (karta SIM)? Wersja LTE / 5G / Cellular / „z kartą SIM” albo tylko Wi-Fi. Gdy "
    "ogłoszenie tego nie mówi - nie zgaduj.",
    {"wifi": "tylko Wi-Fi", "lte": "LTE / 5G / Cellular (karta SIM)", UNKNOWN: "nie da się ustalić"},
)
ACCESSORY_TABLET = q(
    "Jakie DUŻE akcesoria są w zestawie z tabletem? Rysik (Apple Pencil, S Pen, Pen) i klawiatura "
    "(Magic Keyboard, Smart Keyboard, Type Cover, etui z klawiaturą) wyraźnie podnoszą cenę. Samo "
    "etui albo ładowarka się nie liczą. S Pen w pudełku tabletu Samsung też jest rysikiem.",
    {
        "brak": "bez rysika i bez klawiatury",
        "rysik": "z rysikiem",
        "klawiatura": "z klawiaturą",
        "rysik_i_klawiatura": "z rysikiem i klawiaturą",
        UNKNOWN: "nie da się ustalić",
    },
)
WHAT_TABLET = q(
    "Co DOKŁADNIE dostaje kupujący za podaną cenę? Etui czy ładowarka dodane do tabletu to nadal tablet.",
    {
        "tablet": "tablet (sam albo z dodatkami)",
        "kilka": "dwa lub więcej tabletów w jednej ofercie",
        "akcesorium": "tylko akcesorium (etui, klawiatura, rysik, ładowarka, szkło) - bez tabletu",
        "czesc": "tylko część (ekran, bateria, obudowa, płyta)",
        "pudelko": "samo pudełko bez tabletu",
        "kupie_zamienie": "ogłoszenie kupna albo tylko zamiana",
        "inna_rzecz": "inna rzecz (np. tablet graficzny do komputera, czytnik e-booków, telefon, laptop)",
    },
)
TABLET_WHAT_RULES = (
    ("kupie_zamienie", WANTED),
    ("pudelko", BOX),
    (
        "akcesorium",
        r"^(?:etui|case|cover|pokrowiec|klawiatura|keyboard|rysik|pencil|stylus|s ?pen|"
        r"szklo|folia|ladowarka|uchwyt)\b|\b(?:etui|case|klawiatura|keyboard) (?:do|na|for)\b",
    ),
    ("czesc", r"^(?:wyswietlacz|ekran|lcd|digitizer|bateria|obudowa|plyta|tasma)\b"),
)
CELL = re.compile(r"(?<![\d.,])[45]\s?g(?![a-z])|\b(?:lte|cellular|celular|sim)\b")


def connect_rule(title, desc=""):
    t = nrm(title)
    if CELL.search(t):
        return "lte"
    if re.search(r"\bwi-?fi\b", t):
        return "wifi"
    d = nrm(desc)
    if re.search(r"\b(?:wersj\w*|version)\s*:?\s*(?:lte|cellular|4g|5g|z kart\w* sim)", d):
        return "lte"
    if re.search(r"\b(?:tylko|only)\s*wi-?fi\b|\bwi-?fi\s*only\b|\bbez (?:lte|karty sim|modemu)", d):
        return "wifi"
    return UNKNOWN


PEN = re.compile(r"\b(?:apple pencil|pencil|rysik\w*|s ?pen|stylus|pen)\b")
KEYB = re.compile(r"\b(?:magic keyboard|smart keyboard|keyboard|klawiatur\w*|type cover|folio|book cover)\b")


def tablet_accessory_rule(title, desc=""):
    t = nrm(f"{title}\n{desc}")
    pen = X.has_fault(PEN, t)
    key = X.has_fault(KEYB, t)
    return "rysik_i_klawiatura" if pen and key else "rysik" if pen else "klawiatura" if key else UNKNOWN


def tablet_questions(spec):
    v = spec["variants"]
    qs = {"model": model_q("tablet", v, spec.get("other"))}
    if spec.get("storage"):
        qs["pamiec"] = storage_q("ten tablet", spec["storage"])
    if spec.get("ram"):
        qs["ram"] = ram_q("tablet", spec["ram"])
    if spec.get("connect", True):
        qs["lacznosc"] = CONNECT_Q
    if spec.get("accessories", True):
        qs["akcesoria"] = ACCESSORY_TABLET
    if spec.get("lock", True):
        qs["blokada"] = LOCK_PHONE
    qs.update({"stan": STATE_PHONE, "co": WHAT_TABLET})
    return qs


def tablet_rules(spec, title, desc="", form=None):
    form = form or {}
    v = spec["variants"]
    text = f"{title}\n{desc}"
    out = {"model": rule_variant(v, title, desc, form.get("model_nav") if desc else None)}
    if spec.get("storage"):
        out["pamiec"] = storage_rule(spec["storage"], title, desc, form.get("internal_memory_capacity"), form_min=8)
    if spec.get("ram"):
        out["ram"] = ram_rule(spec["ram"], title, desc)
    if spec.get("connect", True):
        out["lacznosc"] = connect_rule(title, desc)
    if spec.get("accessories", True):
        out["akcesoria"] = tablet_accessory_rule(title, desc)
    if spec.get("lock", True):
        out["blokada"] = lock_rule(text, None)
    out["stan"] = fault_rule(text)
    out["co"] = what_rule(title, TABLET_WHAT_RULES, "tablet", bool(find_variants(v, nrm(title))))
    return out


def tablet_tricky(spec, i):
    base, ext = _pick(spec, i)
    sto = spec.get("storage") or [16]
    s1, s2 = sto[0], sto[-1]
    price = spec.get("price", 700)
    form = {"status": "Bardzo dobry", "model_nav": base.label, "internal_memory_capacity": gb_text(s1)}
    cases = [
        dict(
            title=f"{base.label} {gb_text(s1)} (nie {ext.label})" if base.key != ext.key else base.label,
            description=f"To {base.label}, nie {ext.label}. Bez rys, sprawny, tylko Wi-Fi.",
            expected={"model": base.key, "lacznosc": "wifi"} if base.key != ext.key else {"lacznosc": "wifi"},
        ),
        dict(
            title=f"Tablet {base.label.split(' ')[0]}",
            description=f"Model {ext.label}, {gb_text(s2)}, wersja LTE " "z kartą SIM.",
            expected={"model": ext.key, "pamiec": gb_label(s2), "lacznosc": "lte"},
        ),
        dict(
            title=f"{base.label} {gb_text(s1)} + rysik",
            description="W zestawie rysik i klawiatura, etui gratis.",
            expected={"akcesoria": "rysik_i_klawiatura"},
            price=int(price * 1.3),
        ),
        dict(
            title=f"Klawiatura do {ext.label}",
            description="Sama klawiatura, tabletu nie sprzedaję.",
            expected={"co": "akcesorium"},
            price=120,
            form={"status": "Dobry"},
        ),
        dict(
            title=f"{base.label}",
            description="Zablokowany na koncie iCloud / Google, nie znam hasła.",
            expected={"blokada": "konto"},
            price=int(price * 0.3),
        ),
        dict(
            title=f"{ext.label} {gb_text(s1)}",
            description="Pęknięta szybka w rogu, dotyk działa, wszystko sprawne.",
            expected={"stan": "pekniety"},
            price=int(price * 0.6),
        ),
        dict(
            title=f"{base.label}",
            description=f"Pamięć {gb_text(s2)}, sam tablet bez rysika i klawiatury.",
            expected={"pamiec": gb_label(s2), "akcesoria": "brak"},
            form={**form, "internal_memory_capacity": f"{s2 if s2 < 1000 else 1} {'MB' if s2 < 1000 else 'GB'}"},
        ),
        dict(
            title=f"Pudełko {base.label}", description="Samo pudełko po tablecie.", expected={"co": "pudelko"}, price=30
        ),
    ]
    return _rotate(cases, i, 6, keep=2)


# ---------------------------------------------------------------------------------------------- konsole

PADS_Q = q(
    "Ile kontrolerów (padów) jest w zestawie? Switch: para Joy-Conów (lewy + prawy) = 1, Switch Lite ma "
    "wbudowane = 0 dodatkowych. Kierownica, VR, Move, pilot się nie liczą.",
    {
        "0": "bez pada (albo tylko wbudowane sterowanie)",
        "1": "jeden",
        "2": "dwa",
        "3_plus": "trzy lub więcej",
        UNKNOWN: "nie da się ustalić",
    },
)
GAMES_Q = q(
    "Ile gier (płyty, kartridże) jest w zestawie? Gry cyfrowe na koncie i gry wbudowane w konsolę (np. "
    "w wersji mini) się nie liczą. „Bez gier” = 0.",
    {"0": "bez gier", "1_2": "1-2 gry", "3_5": "3-5 gier", "6_plus": "6 i więcej gier", UNKNOWN: "nie da się ustalić"},
)
MOD_Q = q(
    "Czy konsola jest przerobiona / odblokowana (CFW, jailbreak, HEN, RGH / JTAG, chip, „modat”, „modded”, "
    "softmod)? Zaprzeczenie („nie przerabiana”, „oryginalny soft”) = nie.",
    {"brak": "nieprzerabiana", "przerobiona": "przerobiona / odblokowana", UNKNOWN: "nie da się ustalić"},
)
STATE_CONSOLE = q(
    "Jaki jest stan techniczny SPRZEDAWANEJ konsoli? Zaprzeczenia („nie ma driftu”, „nie przegrzewa "
    "się”) zmieniają znaczenie.",
    {
        "sprawna": "sprawna (ślady użytkowania nie przeszkadzają)",
        "drobne_wady": "drobne wady - drift pada, porysowany ekran, głośny wentylator, brak klapki - " "ale działa",
        "usterka": "poważna usterka - nie czyta płyt, przegrzewa się, brak obrazu, niebieskie światło, "
        "czerwony pierścień, uszkodzony port HDMI",
        "na_czesci": "nie włącza się / na części",
        UNKNOWN: "nie da się ustalić",
    },
)
WHAT_CONSOLE = q(
    "Co DOKŁADNIE dostaje kupujący za podaną cenę? Pady, gry i kable dodane do konsoli to nadal konsola.",
    {
        "konsola": "konsola (sama albo z padami, grami, kablami)",
        "tylko_pady": "tylko kontroler(y) / Joy-Cony - bez konsoli",
        "tylko_gry": "tylko gry - bez konsoli",
        "akcesorium": "tylko akcesorium (stacja dokująca, etui, ładowarka, kable, kierownica, VR, zasilacz, karta pamięci)",
        "czesc": "tylko część (napęd, obudowa, płyta, dysk, wentylator, ekran)",
        "pudelko": "samo pudełko",
        "kupie_zamienie": "ogłoszenie kupna albo tylko zamiana",
        "inna_rzecz": "inna rzecz (np. inna konsola, telefon, gra planszowa)",
    },
)
CONSOLE_WHAT_RULES = (
    ("kupie_zamienie", WANTED),
    ("pudelko", BOX),
    (
        "tylko_pady",
        r"^(?:pad|pady|kontroler\w*|controller\w*|dualsense|dualshock|joy-?con\w*|manet\w*|" r"ovladac\w*|gamepad)\b",
    ),
    ("tylko_gry", r"^(?:gra|gry|game|games|hra|hry|jocuri|spel)\b"),
    (
        "akcesorium",
        r"^(?:stacja|dock|etui|case|ladowark\w*|kabel|zasilacz|kierownic\w*|ps ?vr|"
        r"headset|sluchawki|karta pamieci|torba|podstawk\w*|grip)\b",
    ),
    ("czesc", r"^(?:naped|obudowa|plyta|wentylator|ekran|wyswietlacz|dysk)\b"),
)
MOD = re.compile(
    r"\b(?:cfw|jailbreak\w*|jailbreakowan\w*|hen\b|henkaku|rgh\d?|jtag|chip\w*|picofly|modat\w*|modded|"
    r"moded|przerobion\w*|przerabian\w*|softmod\w*|atmosphere|luma\w*|homebrew|ps2 ?fmcb|fmcb|"
    r"odblokowan\w*|hackowan\w*|hacked|unlocked)\b"
)


def pads_rule(title, desc=""):
    t = nrm(f"{title}\n{desc}")
    words = {"jeden": 1, "jednym": 1, "dwa": 2, "dwoma": 2, "trzy": 3, "trzema": 3, "cztery": 4}
    m = re.search(
        r"\b(\d|jeden|jednym|dwa|dwoma|trzy|trzema|cztery)\s*(?:x\s*)?(?:pad\w*|kontroler\w*|controller\w*|"
        r"dualsense|dualshock|joy-?con\w*|manet\w*|ovlada\w*)",
        t,
    )
    if m:
        n = words.get(m.group(1)) or int(m.group(1))
        return "3_plus" if n >= 3 else str(n)
    if re.search(r"\bbez (?:pad\w*|kontroler\w*|joy-?con\w*)", t):
        return "0"
    if re.search(r"\b(?:z |plus ?)(?:padem|pad\b|kontrolerem|controllerem)", t):
        return "1"
    return UNKNOWN


def games_rule(title, desc=""):
    t = nrm(f"{title}\n{desc}")
    m = re.search(r"\b(\d{1,3})\s*(?:gry|gier|gra|games?|hry|her|jocuri|spel|spil|jatek\w*)\b", t)
    if m:
        n = int(m.group(1))
        return "0" if n == 0 else "1_2" if n <= 2 else "3_5" if n <= 5 else "6_plus"
    if re.search(r"\bbez gier\b|\bno games\b", t):
        return "0"
    if re.search(r"\b(?:z gra|z grami|plus gra|plus gry)\b", t):
        return UNKNOWN
    return UNKNOWN


def mod_rule(title, desc=""):
    t = X.norm(f"{title}\n{desc}")
    if re.search(
        r"\b(?:nie (?:jest )?(?:przerabian\w*|przerobion\w*|modowan\w*)|nieprzerabian\w*|"
        r"oryginalny (?:soft|firmware)|no mods?|not modded|bez przerob\w*)\b",
        t,
    ):
        return "brak"
    if X.has_fault(MOD, t):
        return "przerobiona"
    return UNKNOWN


def console_questions(spec):
    v = spec["variants"]
    qs = {
        "model": model_q(
            "model konsoli", v, spec.get("other") or {"inna_konsola": "inna konsola albo inna rzecz spoza tej listy"}
        )
    }
    if spec.get("storage"):
        qs["pamiec"] = storage_q(
            "konsola (dysk / pamięć wbudowana)",
            spec["storage"],
            "Karta pamięci włożona do konsoli to nie pamięć wbudowana. ",
        )
    for name, question in spec.get("extra_q", {}).items():
        qs[name] = question
    if spec.get("pads", True):
        qs["pady"] = PADS_Q
    if spec.get("games", True):
        qs["gry"] = GAMES_Q
    if spec.get("mod", True):
        qs["przerobka"] = MOD_Q
    qs.update({"stan": STATE_CONSOLE, "co": WHAT_CONSOLE})
    return qs


def console_rules(spec, title, desc="", form=None):
    v = spec["variants"]
    out = {"model": rule_variant(v, title, desc)}
    if spec.get("storage"):
        out["pamiec"] = storage_rule(spec["storage"], title, desc, form_min=1)
    for name, fn in spec.get("extra_rules", {}).items():
        out[name] = fn(title, desc)
    if spec.get("pads", True):
        out["pady"] = pads_rule(title, desc)
    if spec.get("games", True):
        out["gry"] = games_rule(title, desc)
    if spec.get("mod", True):
        out["przerobka"] = mod_rule(title, desc)
    out["stan"] = "na_czesci" if X.has_fault(X.FOR_PARTS, X.norm(f"{title}\n{desc}")) else UNKNOWN
    out["co"] = what_rule(title, CONSOLE_WHAT_RULES, "konsola", bool(find_variants(v, nrm(title))))
    return out


def console_tricky(spec, i):
    base, ext = _pick(spec, i)
    price = spec.get("price", 600)
    sto = spec.get("storage") or []
    cases = [
        dict(
            title=f"{base.label} (nie {ext.label})" if base.key != ext.key else base.label,
            description=f"To {base.label}, nie wersja {ext.label}. Sprawna, 2 pady, 3 gry w zestawie.",
            expected=(
                {"model": base.key, "pady": "2", "gry": "3_5"} if base.key != ext.key else {"pady": "2", "gry": "3_5"}
            ),
        ),
        dict(
            title=f"Konsola {spec['short']}",
            description=f"Dokładnie {ext.label}"
            + (f", dysk {gb_text(sto[-1])}" if sto else "")
            + ". Bez pada, bez gier.",
            expected={"model": ext.key, "pady": "0", "gry": "0", **({"pamiec": gb_label(sto[-1])} if sto else {})},
        ),
        dict(
            title=f"Pad do {base.label}",
            description="Sam kontroler, oryginalny, bez driftu. Konsoli nie sprzedaję.",
            expected={"co": "tylko_pady"},
            price=120,
        ),
        dict(
            title=f"{base.label} + 10 gier",
            description="Konsola przerobiona (CFW / jailbreak), gry na karcie i 10 " "płyt / kartridży.",
            expected={"przerobka": "przerobiona", "gry": "6_plus"},
            price=int(price * 1.2),
        ),
        dict(
            title=f"{ext.label}",
            description="Nie przerabiana, oryginalny soft. Nie czyta płyt / gier, poza tym " "działa.",
            expected={"przerobka": "brak", "stan": "usterka"},
            price=int(price * 0.5),
        ),
        dict(
            title=f"{base.label}",
            description="Nie włącza się, sprzedaję na części.",
            expected={"stan": "na_czesci"},
            price=int(price * 0.3),
        ),
        dict(
            title=f"Pudełko po {base.label}",
            description="Samo pudełko z wkładką, bez konsoli.",
            expected={"co": "pudelko"},
            price=40,
        ),
        dict(
            title=f"Kupię {base.label}",
            description="Kupię konsolę, może być z grami.",
            expected={"co": "kupie_zamienie"},
            price=10,
        ),
        dict(
            title=f"{ext.label} zestaw",
            description="Wszystko działa, drift w lewym analogu, poza tym idealna. " "Dwa pady i jedna gra.",
            expected={"stan": "drobne_wady", "pady": "2", "gry": "1_2"},
        ),
    ]
    cases += spec.get("tricky_extra", [])
    return _rotate(cases, i, 7, keep=2)


# ---------------------------------------------------------------------------------------------- laptopy


def cpu_bucket(name):
    """Nazwa z extract._cpu → odpowiedź pytania o procesor (rodzina + generacja)."""
    if not name:
        return None
    n = name.lower()
    m = re.match(r"(i[3579])-(\d{4,5})", n)
    if m:
        num = m.group(2)
        gen = int(num[:2]) if len(num) == 5 else int(num[0])
        if len(num) == 4 and num[0] == "1":  # i5-1135G7 = 11. gen, i7-1260P = 12. gen
            gen = int(num[:2])
        return f"intel_{m.group(1)}_{gen}gen"
    m = re.match(r"ultra ([579]) (\d)", n)
    if m:
        return f"intel_ultra{m.group(1)}_s{m.group(2)}"
    m = re.match(r"ryzen ([3579]) (\d)", n)
    if m:
        return f"ryzen{m.group(1)}_{m.group(2)}000"
    m = re.match(r"apple (m\d)(?: (pro|max|ultra))?", n)
    if m:
        return f"apple_{m.group(1)}" + (f"_{m.group(2)}" if m.group(2) else "")
    if re.match(r"(celeron|pentium|athlon)", n):
        return "celeron_pentium_athlon"
    if n.startswith("snapdragon"):
        return "snapdragon"
    return None


def cpu_label(key):
    m = re.match(r"intel_(i\d)_(\d+)gen", key)
    if m:
        return f"Intel Core {m.group(1)} {m.group(2)}. generacji"
    m = re.match(r"intel_ultra(\d)_s(\d)", key)
    if m:
        return f"Intel Core Ultra {m.group(1)} (seria {m.group(2)})"
    m = re.match(r"ryzen(\d)_(\d)000", key)
    if m:
        return f"AMD Ryzen {m.group(1)} seria {m.group(2)}000"
    m = re.match(r"apple_(m\d)(?:_(\w+))?", key)
    if m:
        return f"Apple {m.group(1).upper()}" + (f" {m.group(2).capitalize()}" if m.group(2) else "")
    return {"celeron_pentium_athlon": "Intel Celeron / Pentium / AMD Athlon", "snapdragon": "Snapdragon (ARM)"}[key]


def gpu_bucket(name):
    if not name:
        return None
    if name == "integrated":
        return "zintegrowana"
    return name.replace(" ", "")


GPU_LABELS = {"zintegrowana": "zintegrowana (Intel UHD / Iris Xe / Radeon Graphics / Apple)"}


def laptop_questions(spec):
    v = spec["variants"]
    qs = {"model": model_q("model laptopa", v, spec.get("other"))}
    if spec.get("gen"):
        crit = {
            g: (f"G{g[1:]}" if re.fullmatch(r"g\d+", g) else f"Gen {g[3:]}" if g.startswith("gen") else g)
            for g in spec["gen"]
        }
        crit[UNKNOWN] = "nie da się ustalić"
        qs["generacja"] = q(
            "Która generacja tego modelu (HP: G1, G2...; Lenovo: Gen 1, Gen 2...)? Często jest tylko "
            "w opisie albo w nazwie procesora. Gdy nie wiadomo - nie zgaduj.",
            crit,
        )
    cpu = {c: cpu_label(c) for c in spec["cpu"]}
    cpu.update({"inny": "inny procesor (spoza listy)", UNKNOWN: "nie da się ustalić"})
    qs["procesor"] = q(
        "Jaki procesor ma TEN laptop (rodzina i generacja)? i5-8250U = Intel Core i5 8. generacji, "
        "i7-1165G7 = 11. generacji, Ryzen 5 5600H = seria 5000, Apple M1 Pro. Formularz podaje tylko "
        "linię (np. „Intel Core i5”) - generacja jest w tytule / opisie. Gdy nie wiadomo - nie zgaduj.",
        cpu,
    )
    gpu = {
        g: GPU_LABELS.get(g)
        or g.upper()
        .replace("RTX", "RTX ")
        .replace("GTX", "GTX ")
        .replace("MX", "MX ")
        .replace("RX", "RX ")
        .replace("TI", " Ti")
        .replace("SUPER", " Super")
        for g in spec["gpu"]
    }
    gpu.update({"inna": "inna karta (spoza listy)", UNKNOWN: "nie da się ustalić"})
    qs["karta"] = q(
        "Jaka karta graficzna? Dedykowana (RTX / GTX / RX / MX / Quadro) albo zintegrowana. „RTX 3050 4GB” = "
        "RTX 3050. Gdy nie wiadomo - nie zgaduj.",
        gpu,
    )
    qs["ram"] = q(
        "Ile pamięci RAM ma TEN laptop? Nie myl z dyskiem (SSD) ani pamięcią karty graficznej. Formularz "
        "bywa błędny (np. „512 GB” w polu RAM). Gdy nie wiadomo - nie zgaduj.",
        {**{f"{r}gb": f"{r} GB" for r in spec["ram"]}, UNKNOWN: "nie da się ustalić"},
    )
    qs["dysk"] = q(
        "Jaki dysk ma TEN laptop (pojemność)? Brak dysku = sprzedawany bez dysku. Formularz bywa błędny (np. "
        "„8 GB” w polu dysku to RAM). Gdy nie wiadomo - nie zgaduj.",
        {
            **{gb_label(d): gb_text(d) + (" lub więcej" if d == spec["disk"][-1] else "") for d in spec["disk"]},
            "brak_dysku": "bez dysku",
            UNKNOWN: "nie da się ustalić",
        },
    )
    qs["stan"] = q(
        "Jaki jest stan TEGO laptopa? Zaprzeczenia („bez pęknięć”, „klawiatura działa”) zmieniają znaczenie.",
        {
            "sprawny": "sprawny (ślady użytkowania nie przeszkadzają)",
            "drobne_wady": "drobne wady - słaba bateria, otarcia, brak gumki, martwy piksel - ale działa",
            "uszkodzony": "uszkodzony, ale się włącza - pęknięta / zbita matryca, zawiasy, obudowa, klawiatura albo "
            "touchpad nie działa",
            "na_czesci": "nie włącza się, zalany, bez płyty / na części",
            UNKNOWN: "nie da się ustalić",
        },
    )
    qs["blokada"] = q(
        "Czy laptop jest zablokowany? Hasło BIOS / supervisor, Computrace, blokada iCloud lub MDM (Mac), "
        "konto firmowe - utrudniają albo uniemożliwiają użycie. „Bez blokad”, „wylogowany” = brak.",
        {
            "brak": "brak blokady",
            "bios_haslo": "hasło BIOS / supervisor / Computrace",
            "konto": "blokada iCloud / MDM / konto firmowe",
            UNKNOWN: "nie da się ustalić",
        },
    )
    qs.update(spec.get("extra_q", {}))
    qs["zasilacz"] = q(
        "Czy w zestawie jest zasilacz (ładowarka)? Formularz Vinted ma pole „ładowarka” - bywa błędne.",
        {"tak": "zasilacz w zestawie", "nie": "bez zasilacza", UNKNOWN: "nie da się ustalić"},
    )
    qs["co"] = q(
        "Co DOKŁADNIE dostaje kupujący za podaną cenę? Torba czy mysz dodane do laptopa to nadal laptop.",
        {
            "laptop": "laptop (sam albo z dodatkami)",
            "kilka": "dwa lub więcej laptopów w jednej ofercie",
            "czesc": "tylko część (matryca, płyta główna, klawiatura, obudowa, bateria, dysk, wentylator)",
            "zasilacz_akcesorium": "tylko zasilacz / ładowarka / stacja dokująca / torba",
            "kupie_zamienie": "ogłoszenie kupna albo tylko zamiana",
            "inna_rzecz": "inna rzecz (komputer stacjonarny, tablet, monitor)",
        },
    )
    return qs


LAPTOP_WHAT_RULES = (
    ("kupie_zamienie", WANTED),
    (
        "czesc",
        r"^(?:matryca|ekran|wyswietlacz|lcd|plyta|klawiatura|obudowa|bateria|wentylator|"
        r"zawias\w*|palmrest|tasma|dysk)\b|\b(?:matryca|klawiatura|bateria|obudowa) (?:do|z)\b",
    ),
    ("zasilacz_akcesorium", r"^(?:zasilacz|ladowarka|charger|stacja dokujaca|docking|torba|plecak)\b"),
)
BIOS = re.compile(
    r"\b(?:bios (?:password|haslo)|haslo (?:do )?bios\w*|haslo (?:administrator|supervisor)\w*|"
    r"supervisor password|zablokowan\w* bios|computrace|absolute)\b"
)
APPLE_LOCK = re.compile(
    r"\b(?:icloud|mdm|activation lock|zarzadzan\w* przez firm\w*|remote management|"
    r"konto firmow\w*|device enrollment)\b"
)


def laptop_rules(spec, title, desc="", form=None):
    form = form or {}
    v = spec["variants"]
    t, d = X.norm(title), X.norm(desc)
    text = f"{t}\n{d}"
    out = {"model": rule_variant(v, title, desc, form.get("model_nav") if desc else None)}
    if spec.get("gen"):
        gens = set()
        for part in (t, d):
            gens |= {f"g{g}" for g in re.findall(r"\bg\s?(\d{1,2})\b", part) if f"g{g}" in spec["gen"]}
            gens |= {
                f"gen{g}" for g in re.findall(r"\bgen(?:eration)?\.?\s?(\d{1,2})\b", part) if f"gen{g}" in spec["gen"]
            }
            if gens:
                break
        out["generacja"] = _one(gens)
    cpu = cpu_bucket(X._cpu(t)) or cpu_bucket(X._cpu(d))
    out["procesor"] = cpu if cpu in spec["cpu"] else (UNKNOWN if cpu is None else "inny")
    gpu = gpu_bucket(X._gpu(t)) or gpu_bucket(X._gpu(d))
    out["karta"] = gpu if gpu in spec["gpu"] else (UNKNOWN if gpu is None else "inna")
    ram = X._ram(t, loose=True) or X._ram(d)
    if ram is None and form.get("computer_ram") and desc:
        ram = X._gb(form["computer_ram"])
    out["ram"] = f"{ram}gb" if ram in spec["ram"] else UNKNOWN
    disk = X._storage(t, loose=True) or X._storage(d)
    if disk is None and form.get("computer_storage_capacity") and desc:
        disk = X._gb(form["computer_storage_capacity"])
        disk = disk if disk and disk >= 64 else None
    if disk:
        disk = min(spec["disk"], key=lambda x: abs(x - disk)) if disk < spec["disk"][-1] else spec["disk"][-1]
        disk = disk if abs(disk - (X._storage(t, loose=True) or X._storage(d) or disk)) <= disk * 0.15 else disk
    out["dysk"] = (
        gb_label(disk)
        if disk
        else ("brak_dysku" if re.search(r"\bbez dysku\b|\bno (?:ssd|hdd|disk)\b", text) else UNKNOWN)
    )
    if X.has_fault(X.FOR_PARTS, text):
        out["stan"] = "na_czesci"
    elif X.has_fault(X.CRACKED, text):
        out["stan"] = "uszkodzony"
    else:
        out["stan"] = UNKNOWN
    if X.NOT_LOCKED.search(text):
        out["blokada"] = "brak"
    elif X.has_fault(BIOS, text):
        out["blokada"] = "bios_haslo"
    elif X.has_fault(APPLE_LOCK, text):
        out["blokada"] = "konto"
    else:
        out["blokada"] = UNKNOWN
    if re.search(r"\bbez (?:zasilacza|ladowarki)\b|\bno charger\b|\bwithout charger\b", text):
        out["zasilacz"] = "nie"
    elif re.search(
        r"\b(?:z zasilaczem|z ladowarka|zasilacz w zestawie|ladowarka w zestawie|oryginaln\w* zasilacz\w*|"
        r"charger included)\b",
        text,
    ):
        out["zasilacz"] = "tak"
    else:
        charger = X.norm(form.get("laptop_charger_included") or "")
        out["zasilacz"] = ("nie" if charger.startswith("brak") else "tak" if charger else UNKNOWN) if desc else UNKNOWN
    out["co"] = what_rule(title, LAPTOP_WHAT_RULES, "laptop", bool(find_variants(v, nrm(title))))
    for name, fn in spec.get("extra_rules", {}).items():
        out[name] = fn(title, desc)
    return out


def laptop_tricky(spec, i):
    base, ext = _pick(spec, i)
    price = spec.get("price", 1500)
    cpu = spec["cpu"][i % len(spec["cpu"])]
    gpu = next((g for g in spec["gpu"] if g != "zintegrowana"), None)
    ram, disk = spec["ram"][min(2, len(spec["ram"]) - 1)], spec["disk"][min(2, len(spec["disk"]) - 1)]
    form = {
        "status": "Bardzo dobry",
        "model_nav": base.label,
        "computer_ram": f"{ram} GB",
        "computer_storage_capacity": gb_text(disk),
        "laptop_charger_included": "W zestawie",
    }
    cases = [
        dict(
            title=f"{base.label} (nie {ext.label})" if base.key != ext.key else base.label,
            description=f"Model {base.label}, nie {ext.label}. {cpu_label(cpu)}, {ram} GB RAM, SSD {gb_text(disk)}.",
            expected=(
                {"model": base.key, "procesor": cpu, "ram": f"{ram}gb", "dysk": gb_label(disk)}
                if base.key != ext.key
                else {"procesor": cpu, "ram": f"{ram}gb"}
            ),
        ),
        dict(
            title=f"Laptop {spec['short']}",
            description=f"Dokładnie {ext.label}. Pamięć {ram} GB, dysk {gb_text(disk)}"
            + (f", karta {gpu.upper()}" if gpu else "")
            + ".",
            expected={"model": ext.key, "ram": f"{ram}gb", **({"karta": gpu} if gpu else {})},
            form={**form, "computer_ram": f"{disk} GB", "computer_storage_capacity": f"{ram} GB"},
        ),
        dict(
            title=f"{base.label}",
            description="Hasło BIOS (supervisor), nie znam hasła. Poza tym działa.",
            expected={"blokada": "bios_haslo"},
            price=int(price * 0.4),
        ),
        dict(
            title=f"{base.label} pęknięta matryca",
            description="Matryca pęknięta w rogu, laptop się włącza i działa " "na zewnętrznym monitorze.",
            expected={"stan": "uszkodzony"},
            price=int(price * 0.5),
        ),
        dict(
            title=f"Matryca do {ext.label}",
            description="Sama matryca, sprawna, wyjęta z laptopa.",
            expected={"co": "czesc"},
            price=150,
        ),
        dict(
            title=f"{ext.label}",
            description="Bez zasilacza (ładowarki), bateria trzyma 2 godziny, poza tym bez wad.",
            expected={"zasilacz": "nie", "stan": "drobne_wady"},
            form={**form, "laptop_charger_included": "W zestawie"},
        ),
        dict(
            title=f"{base.label}",
            description="Nie włącza się, prawdopodobnie płyta. Na części.",
            expected={"stan": "na_czesci"},
            price=int(price * 0.25),
        ),
        dict(
            title=f"{base.label} bez dysku",
            description=f"Sprzedawany bez dysku i bez systemu, {ram} GB RAM.",
            expected={"dysk": "brak_dysku", "ram": f"{ram}gb"},
            price=int(price * 0.7),
        ),
    ]
    cases += spec.get("tricky_extra", [])
    return _rotate(cases, i, 6, keep=2)


# ---------------------------------------------------------------------------------------------- podzespoły


def _parts():
    from . import basal_poc as P  # pytania o stan / sztuki / cenę za sztukę wspólne z rodzinami v1

    return P


GPU_PREFIX = r"(?:gtx|rtx|geforce|nvidia|gt|rx|radeon|amd|arc|intel|quadro|tesla|hd|r[579])"


def gpu_rx(model, suffix=None, prefix=GPU_PREFIX, neg_suffix=None):
    """Regex modelu karty: prefiks marki / serii do kilkunastu znaków przed numerem („GeForce GTX 1650”, „rx580”),
    opcjonalna końcówka (Ti / Super / XT); bez końcówki - nie może po numerze stać inna końcówka."""
    rx = rf"(?<![a-z0-9]){prefix}\b[\w\s]{{0,14}}?(?<![0-9]){model}"
    if suffix:
        rx += rf"{SEP}{suffix}(?![a-z0-9])"
    else:
        rx += rf"(?![0-9])(?!{SEP}(?:{neg_suffix or 'ti|super|xtx|xt|gre'})(?![a-z]))"
    return rx


def vram_rule(options, title, desc=""):
    for text in (title, desc):
        t = nrm(text)
        vals = [int(n) for n, u in SIZES.findall(t) if u in ("gb", "g")]
        vals += [round(int(m) / 1024) for m in re.findall(r"(?<![\d.,])(\d{4,5})\s?mb\b", t)]
        hits = {v for v in vals if v in options}
        if hits:
            return f"{hits.pop()}gb" if len(hits) == 1 else CONFLICT
    return UNKNOWN


PART_WHAT = (
    r"^(?:radiator|heatsink|chlodzen\w*|cooler|wentylator\w*|backplate|riser|adapter|kabel|przejsciowk\w*|"
    r"pudelko|box|uchwyt|kieszen|obudowa|tasma|pasta)\b|\b(?:bez karty|bez dysku|bez procesora|sam radiator|"
    r"samo pudelko|tylko pudelko)\b"
)


def part_state_rule(title, desc=""):
    t = nrm(title)
    text = X.norm(f"{title}\n{desc}")
    if re.search(PART_WHAT, t):
        return "czesc"
    if re.search(WANTED, t):
        return "inna_rzecz"
    if X.has_fault(X.FOR_PARTS, text):
        return "uszkodzona"
    return UNKNOWN


def gpu_questions(spec):
    P = _parts()
    v = spec["variants"]
    vram = {f"{g}gb": f"{g} GB" for g in spec["vram"]}
    vram[UNKNOWN] = "nie da się ustalić"
    return {
        "model": model_q(
            "model karty graficznej",
            v,
            {"inna": "inna karta albo inna rzecz (model z listy tylko " "dla porównania: „wydajność jak ...”)"},
        ),
        "vram": q(
            "Ile pamięci (VRAM) ma TA karta? Szukaj w opisie, naklejkach i kodach modeli (np. „4G”, "
            "„GV-N1650…4GD”, „8GD6”, „3072MB” = 3 GB). Wersje tego samego chipa różnią się pamięcią i ceną. "
            "Gdy nie wiadomo - nie zgaduj.",
            vram,
        ),
        **spec.get("extra_q", {}),
        "stan": P.CONDITION_PART,
        "sztuk": P.QUANTITY,
    }


def gpu_rules(spec, title, desc="", form=None):
    P = _parts()
    out = {"model": rule_variant(spec["variants"], title, desc), "vram": vram_rule(spec["vram"], title, desc)}
    for name, fn in spec.get("extra_rules", {}).items():
        out[name] = fn(title, desc)
    out.update({"stan": part_state_rule(title, desc), "sztuk": P.rule_quantity({"title": title, "description": desc})})
    return out


def gpu_tricky(spec, i):
    base, ext = _pick(spec, i)
    vr = spec["vram"]
    price = spec.get("price", 400)
    cases = [
        dict(
            title=f"Karta graficzna {base.label}",
            description=f"Model {base.label} (nie {ext.label}), " f"{vr[0]} GB, w pełni sprawna, bez artefaktów.",
            expected=(
                {"model": base.key, "vram": f"{vr[0]}gb", "stan": "sprawna"}
                if base.key != ext.key
                else {"vram": f"{vr[0]}gb", "stan": "sprawna"}
            ),
        ),
        dict(
            title=f"{ext.label}",
            description=f"Pamięć {vr[-1]} GB GDDR, sprawna, wymieniona pasta.",
            expected={"model": ext.key, "vram": f"{vr[-1]}gb"},
        ),
        dict(title=f"{base.label} {vr[0]}GB x2", description="Dwie karty, cena za sztukę.", expected={"sztuk": "1"}),
        dict(
            title=f"Radiator {ext.label}",
            description="Samo chłodzenie z wentylatorami, karty brak.",
            expected={"stan": "czesc"},
            price=60,
        ),
        dict(
            title=f"{base.label}",
            description="Brak obrazu, wentylatory się kręcą. Na części.",
            expected={"stan": "uszkodzona"},
            price=int(price * 0.3),
        ),
        dict(
            title=f"Komputer z {base.label}",
            description="Cały zestaw PC: procesor, płyta, RAM, zasilacz i karta.",
            expected={"stan": "zestaw"},
            price=int(price * 3),
        ),
        dict(
            title=f"{ext.label} Dual / Windforce 2X",
            description="Dwa wentylatory, złącze PCIe x16, sprawna.",
            expected={"sztuk": "1", "stan": "sprawna"},
        ),
    ]
    return _rotate(cases, i, 6, keep=2)


RAM_TOTAL = (1, 2, 4, 8, 16, 24, 32, 48, 64, 96, 128)


def ram_total_rule(title, desc=""):
    for text in (title, desc):
        t = nrm(text)
        m = re.search(r"(?<![\d.,])(\d)\s?x\s?(\d{1,2})\s?gb\b", t) or re.search(r"\b(\d{1,3})\s?gb\s?\(\s?(\d)\s?x", t)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            total = a * b if re.match(r"\d\s?x", m.group(0)) else a
            if total in RAM_TOTAL:
                return f"{total}gb"
        sizes = {int(n) for n in re.findall(r"(?<![\d.,])(\d{1,3})\s?gb\b", t)} & set(RAM_TOTAL)
        if sizes:
            return f"{sizes.pop()}gb" if len(sizes) == 1 else CONFLICT
    return UNKNOWN


def ram_questions(spec):
    P = _parts()
    fam = P.FAMILIES["ddr4"]["questions"]
    total = {f"{g}gb": f"{g} GB razem" for g in RAM_TOTAL}
    total[UNKNOWN] = "nie da się ustalić"
    return {
        "typ": fam["typ"],
        "mhz": fam["mhz"],
        "forma": fam["forma"],
        "pojemnosc": q(
            "Ile GB pamięci RAZEM dostaje kupujący za podaną cenę (wszystkie kości)? „2x8 GB” = 16 GB, "
            "„16 GB (2x8)” = 16 GB, „cena za sztukę 8 GB” = 8 GB. Gdy nie wiadomo - nie zgaduj.",
            total,
        ),
        "stan": P.CONDITION_PART,
        "sztuk": P.QUANTITY,
    }


def ram_rules(spec, title, desc="", form=None):
    P = _parts()
    out = P.rules_ddr4(f"{title}\n{desc}")
    out["sztuk"] = P.rule_quantity({"title": title, "description": desc})
    out["pojemnosc"] = ram_total_rule(title, desc)
    out["stan"] = part_state_rule(title, desc)
    return out


def ram_tricky(spec, i):
    P = _parts()
    cases = [
        dict(title=t, description=d, expected=e, **({"price": p[0]} if p else {}))
        for t, d, e, *p in P.FAMILIES["ddr4"]["tricky"]
    ]
    cases += [
        dict(
            title="RAM 2x8GB DDR4",
            description="Zestaw dwóch kości po 8 GB, 3200 MHz, do PC.",
            expected={"pojemnosc": "16gb", "sztuk": "2", "forma": "pc"},
        ),
        dict(
            title="Pamięć 32GB (4x8GB) DDR3",
            description="Cztery kości 1600 MHz z komputera.",
            expected={"pojemnosc": "32gb", "sztuk": "4", "typ": "ddr3", "mhz": "1600"},
        ),
    ]
    return _rotate(cases, i, 6, keep=0)


DISK_TYPE_Q = q(
    "Jaki to rodzaj dysku? NVMe (M.2 PCIe), SSD SATA (2,5\" albo M.2 SATA), HDD 3,5\" (do PC), HDD 2,5\" "
    "(laptop), dysk zewnętrzny (USB, w obudowie, „portable”), inny (mSATA, pendrive, karta pamięci).",
    {
        "nvme": "SSD NVMe (M.2 PCIe)",
        "ssd_sata": "SSD SATA (2,5\" albo M.2 SATA)",
        "hdd_35": "HDD 3,5\"",
        "hdd_25": "HDD 2,5\"",
        "zewnetrzny": "dysk zewnętrzny (USB)",
        "inny": "mSATA / pendrive / karta pamięci / inny",
        UNKNOWN: "nie da się ustalić",
    },
)
DISK_STATE_Q = q(
    "Jaki jest stan TEGO dysku? Zdrowie (SMART, „health”, „kondycja”) w % i błędy mówią najwięcej; "
    "zaprzeczenia („bez bad sectorów”, „0 błędów”) zmieniają znaczenie.",
    {
        "sprawny": "sprawny, zdrowie dobre albo nieznane, bez błędów",
        "zuzyty": "zużyty - zdrowie poniżej ~80%, realokowane sektory, ostrzeżenia SMART - ale działa",
        "uszkodzony": "uszkodzony / nie wykrywany / bad sectory / na części",
        "czesc": "tylko część albo akcesorium (kieszeń, radiator, adapter, pudełko) - bez dysku",
        "zestaw": "w zestawie z inną dużą rzeczą (komputer, laptop, konsola)",
        UNKNOWN: "nie da się ustalić",
    },
)


def disk_type_rule(title, desc=""):
    t = X.norm(f"{title}\n{desc}")
    if re.search(
        r"\b(?:portable|external|zewnetrzn\w*|przenosn\w*|usb[ -]?c?\s?3|my passport|elements|expansion|"
        r"t7|t5|t9|canvio|one touch|extreme portable)\b",
        X.norm(title),
    ):
        return "zewnetrzny"
    if re.search(
        r"\bnvme|pcie|m\.?2 ?(?:2280|2242|2230)? ?nvme|\bsn\d{3,4}\b|9[789]0 (?:pro|evo)|\bnv[123]\b|kc3000|"
        r"\bp[35] plus|\bp[1235]\b",
        t,
    ):
        return "nvme"
    if re.search(r"\bmsata|pendrive|karta pamieci|micro ?sd|\bsd card|flash drive", t):
        return "inny"
    if re.search(r"\bssd\b", t):
        return "ssd_sata"
    if re.search(
        r"\b(?:hdd|dysk twardy|hard disk|hard drive|7200|5400|barracuda|ironwolf|wd (?:blue|red|purple|"
        r"black|gold|green))\b",
        t,
    ):
        return (
            "hdd_25"
            if re.search(r"\b2[.,]5\b|laptop|notebook", t)
            else "hdd_35" if re.search(r"\b3[.,]5\b", t) else UNKNOWN
        )
    return UNKNOWN


def disk_state_rule(title, desc=""):
    t = X.norm(f"{title}\n{desc}")
    m = re.search(r"\b(?:health|zdrowi\w*|kondycj\w*|stan zdrowia|zivotnost|zdravi)\D{0,12}(\d{1,3})\s?%", t)
    if m:
        return "zuzyty" if int(m.group(1)) < 80 else "sprawny"
    if re.search(PART_WHAT, nrm(title)):
        return "czesc"
    if X.has_fault(X.FOR_PARTS, t) or X.has_fault(re.compile(r"\b(?:bad ?sector\w*|nie wykrywa\w*|niewykrywan\w*)"), t):
        return "uszkodzony"
    return UNKNOWN


def storage_part_questions(spec):
    P = _parts()
    cap = {gb_label(c): gb_text(c) for c in spec["capacity"]}
    cap[UNKNOWN] = "nie da się ustalić"
    return {
        "model": model_q("model dysku", spec["variants"], {"inny": "inny dysk albo inna rzecz"}),
        "pojemnosc": q(
            "Jaka jest pojemność TEGO dysku? Producenci dysków liczą 1 TB = 1000 GB (480 / 500 / "
            "512 GB to różne dyski). Gdy nie wiadomo - nie zgaduj.",
            cap,
        ),
        "typ": DISK_TYPE_Q,
        "stan": DISK_STATE_Q,
        "sztuk": P.QUANTITY,
    }


def storage_part_rules(spec, title, desc="", form=None):
    P = _parts()
    return {
        "model": rule_variant(spec["variants"], title, desc),
        "pojemnosc": storage_rule(spec["capacity"], title, desc),
        "typ": disk_type_rule(title, desc),
        "stan": disk_state_rule(title, desc),
        "sztuk": P.rule_quantity({"title": title, "description": desc}),
    }


def storage_part_tricky(spec, i):
    base, ext = _pick(spec, i)
    c = spec["capacity"]
    cases = [
        dict(
            title=f"{base.label} {gb_text(c[1 % len(c)])}",
            description=f"To {base.label}, nie {ext.label}. " "Zdrowie 100%, 0 błędów.",
            expected=(
                {"model": base.key, "stan": "sprawny", "pojemnosc": gb_label(c[1 % len(c)])}
                if base.key != ext.key
                else {"stan": "sprawny"}
            ),
        ),
        dict(
            title="Dysk SSD",
            description=f"Model {ext.label}, pojemność {gb_text(c[-1])}, sprawny.",
            expected={"model": ext.key, "pojemnosc": gb_label(c[-1])},
        ),
        dict(
            title=f"{base.label} {gb_text(c[0])}",
            description="Zdrowie 61%, realokowane sektory, ale działa.",
            expected={"stan": "zuzyty"},
        ),
        dict(
            title=f"{ext.label}",
            description="Nie jest wykrywany przez BIOS. Na części.",
            expected={"stan": "uszkodzony"},
        ),
        dict(
            title=f"Kieszeń do {base.label}",
            description="Sama obudowa USB, dysku brak.",
            expected={"stan": "czesc"},
            price=40,
        ),
        dict(
            title=f"2x {base.label} {gb_text(c[0])}", description="Dwa dyski, cena za komplet.", expected={"sztuk": "2"}
        ),
    ]
    return _rotate(cases, i, 5, keep=2)


def cpu_part_questions(spec):
    P = _parts()
    suf = {s: d for s, d in spec["suffixes"].items()}
    suf[UNKNOWN] = "nie da się ustalić"
    return {
        "model": model_q("model procesora (numer)", spec["variants"], {"inny": "inny procesor albo inna rzecz"}),
        "sufiks": q(
            "Jaka litera / końcówka stoi BEZPOŚREDNIO po numerze SPRZEDAWANEGO procesora? Liczy się tylko "
            "ten numer - nie procesory wymienione dla porównania i nie litery w innych słowach. Zaprzeczenia "
            "(„nie F”, „ma grafikę”) zmieniają znaczenie. Numer bez litery i nic o końcówce = bez litery.",
            suf,
        ),
        "stan": q(
            "Co i w jakim stanie jest sprzedawane? Wygięte / brakujące piny (nóżki) = uszkodzony. Zaprzeczenia "
            "(„piny proste”, „nie podkręcany”) zmieniają znaczenie.",
            {
                "sprawna": "sprawny procesor",
                "uszkodzona": "uszkodzony (wygięte piny, nie startuje, na części)",
                "czesc": "tylko chłodzenie / pudełko / pasta - bez procesora",
                "zestaw": "procesor razem z płytą główną (i ew. RAM)",
                "inna_rzecz": "inna rzecz, kupię albo zamienię",
                UNKNOWN: "nie da się ustalić",
            },
        ),
        "sztuk": P.QUANTITY,
    }


def cpu_part_rules(spec, title, desc="", form=None):
    P = _parts()
    model = rule_variant(spec["variants"], title, desc)
    suffix = UNKNOWN
    if model not in NO_RULE:
        num = re.escape(model.split("_")[-1])
        for text in (nrm(title), nrm(desc)):
            found = {
                s.replace(" ", "") for s in re.findall(rf"(?<![0-9]){num}\s?((?:x3d|xt|kf|ks|ge|af|[a-z])?)\b", text)
            }
            found = {s or "brak" for s in found}
            found = {s for s in found if s in spec["suffixes"]}
            if found:
                suffix = _one(found)
                break
    t = nrm(title)
    stan = part_state_rule(title, desc)
    if stan == UNKNOWN and re.search(
        r"\bplus\s?(?:plyta|plyty|motherboard|mobo)|\bz plyta\b|\bplyta\b.{0,20}\bprocesor", t
    ):
        stan = "zestaw"
    if X.has_fault(
        re.compile(r"\b(?:wygiet\w* pin\w*|krzyw\w* pin\w*|bent pins?|brak\w* pin\w*|ulaman\w* pin\w*)"),
        X.norm(f"{title}\n{desc}"),
    ):
        stan = "uszkodzona"
    return {
        "model": model,
        "sufiks": suffix,
        "stan": stan,
        "sztuk": P.rule_quantity({"title": title, "description": desc}),
    }


def cpu_part_tricky(spec, i):
    v = spec["variants"]
    a, b = v[i % len(v)], v[(i + 1) % len(v)]
    sufs = [s for s in spec["suffixes"] if s != "brak"]
    s = sufs[i % len(sufs)] if sufs else None
    num = a.key.split("_")[-1]
    brand = "Intel Core" if "intel" in spec["id"] else "AMD Ryzen"
    cases = [
        dict(
            title=f"{a.label} {s}" if s else a.label,
            description="Sam procesor, sprawny, piny proste.",
            expected={"model": a.key, "sufiks": s or "brak", "stan": "sprawna"},
        ),
        dict(
            title=f"Procesor {brand}",
            description=f"Model {b.label}, wersja bez litery na końcu, sprawny.",
            expected={"model": b.key, "sufiks": "brak"},
        ),
        dict(
            title=f"{a.label}{s or ''} + płyta",
            description="Zestaw procesor i płyta główna, działają.",
            expected={"stan": "zestaw"},
        ),
        dict(title=f"{b.label}", description="Wygięte dwa piny, nie testowany.", expected={"stan": "uszkodzona"}),
        dict(
            title=f"Chłodzenie do {a.label}",
            description="Sam cooler BOX, procesora brak.",
            expected={"stan": "czesc"},
            price=30,
        ),
        dict(title=f"{a.label}{s or ''} x2", description="Dwa procesory, cena za sztukę.", expected={"sztuk": "1"}),
    ]
    return _rotate(cases, i, 5, keep=2)


MOBO_DDR = q(
    "Jaki typ pamięci RAM obsługuje TA płyta? Ten sam chipset bywa w wersji DDR4 i DDR5 (np. B660, B760, "
    "Z690) - wersja jest w nazwie („D4”, „DDR4”) albo w opisie.",
    {
        "ddr2_starsza": "DDR2 albo starsza",
        "ddr3": "DDR3",
        "ddr4": "DDR4",
        "ddr5": "DDR5",
        UNKNOWN: "nie da się ustalić",
    },
)
MOBO_WIFI = q(
    "Czy płyta ma wbudowane Wi-Fi (w nazwie „WIFI”, „AX”, „AC”)? Karta Wi-Fi dokładana osobno się nie " "liczy.",
    {"tak": "z Wi-Fi", "nie": "bez Wi-Fi", UNKNOWN: "nie da się ustalić"},
)
MOBO_FORMAT = q(
    "Jaki format płyty? ATX (duża), micro ATX (mATX, „M” w nazwie, np. B450M), mini ITX (mała, „I”).",
    {"atx": "ATX", "matx": "micro ATX", "itx": "mini ITX", UNKNOWN: "nie da się ustalić"},
)
MOBO_STATE = q(
    "Co i w jakim stanie jest sprzedawane?",
    {
        "sprawna": "sprawna płyta główna do komputera",
        "uszkodzona": "uszkodzona (wygięte piny w gnieździe, nie startuje, na części)",
        "zestaw": "płyta razem z procesorem (i ew. RAM / chłodzeniem)",
        "inna_plyta": "płyta z laptopa, telewizora, konsoli, monitora, sprzętu AGD albo inna elektronika",
        "inna_rzecz": "inna rzecz (np. Raspberry Pi / Arduino w rodzinie płyt PC, kupię, zamienię)",
        UNKNOWN: "nie da się ustalić",
    },
)


def mobo_questions(spec):
    return {
        "chipset": model_q("chipset / model płyty", spec["variants"], {"inny": "inny chipset albo inna rzecz"}),
        "ddr": MOBO_DDR,
        "wifi": MOBO_WIFI,
        "format": MOBO_FORMAT,
        "stan": MOBO_STATE,
    }


def mobo_rules(spec, title, desc="", form=None):
    t, text = nrm(title), X.norm(f"{title}\n{desc}")
    ddr = set(re.findall(r"\bddr\s?([2345])\b", text)) | ({"4"} if re.search(r"\bd4\b|-d4\b", t) else set())
    ddr = {"ddr2_starsza" if d == "2" else f"ddr{d}" for d in ddr}
    wifi = "tak" if re.search(r"\bwi-?fi\b|\b(?:ax|ac)\b", t) else UNKNOWN
    chip = rule_variant(spec["variants"], title, desc)
    fmt = (
        UNKNOWN
        if chip in NO_RULE
        else (
            "itx"
            if re.search(r"\b(?:itx|mini-?itx)\b|\b[a-z]\d{3}i\b", t)
            else (
                "matx"
                if re.search(r"\b(?:matx|micro ?atx|m-?atx)\b|\b[a-z]\d{3}m\b", t)
                else "atx" if re.search(r"\batx\b", t) else UNKNOWN
            )
        )
    )
    if re.search(
        r"\b(?:laptop\w*|notebook|tv|telewizor\w*|monitor\w*|konsol\w*|ps[345]|xbox|t-?con|main ?board tv)\b", t
    ):
        state = "inna_plyta"
    elif re.search(r"\b(?:raspberry|arduino|orange pi|esp32|banana pi)\b", t):
        state = "inna_rzecz"
    elif re.search(r"\bplus\s?(?:procesor|cpu|intel|amd|ryzen|i[3579])|\bz procesorem\b|\bkit\b|\bzestaw\b", t):
        state = "zestaw"
    elif X.has_fault(
        re.compile(r"\b(?:wygiet\w*|krzyw\w*|bent)\b.{0,15}\bpin\w*|\bpin\w*.{0,10}\b(?:wygiet\w*|bent)"), text
    ) or X.has_fault(X.FOR_PARTS, text):
        state = "uszkodzona"
    else:
        state = UNKNOWN
    return {"chipset": chip, "ddr": _one(ddr), "wifi": wifi, "format": fmt, "stan": state}


def mobo_tricky(spec, i):
    v = spec["variants"]
    a, b = v[i % len(v)], v[(i + 1) % len(v)]
    cases = [
        dict(
            title=f"Płyta główna {a.label}",
            description=f"Chipset {a.label}, wersja DDR4, bez Wi-Fi, micro ATX.",
            expected={"chipset": a.key, "ddr": "ddr4", "wifi": "nie", "format": "matx"},
        ),
        dict(
            title="Płyta główna Gigabyte",
            description=f"Model z chipsetem {b.label}, format ATX, z Wi-Fi.",
            expected={"chipset": b.key, "format": "atx", "wifi": "tak"},
        ),
        dict(
            title=f"{a.label} + procesor", description="Zestaw płyta i procesor, działa.", expected={"stan": "zestaw"}
        ),
        dict(
            title=f"Płyta {b.label}",
            description="Wygięte piny w gnieździe procesora, nie testowana.",
            expected={"stan": "uszkodzona"},
        ),
        dict(
            title="Płyta główna z laptopa Lenovo",
            description="Płyta do laptopa IdeaPad, sprawna.",
            expected={"stan": "inna_plyta"},
        ),
    ]
    return _rotate(cases, i, 4, keep=2)


def bundle_questions(spec):
    P = _parts()
    cpu = {c: cpu_label(c) for c in spec["cpu"]}
    cpu.update({"inny": "inny procesor", UNKNOWN: "nie da się ustalić"})
    return {
        "procesor": q(
            "Jaki procesor jest w zestawie (rodzina i generacja)? i5-9400F = Intel Core i5 9. generacji, "
            "Ryzen 5 3600 = seria 3000.",
            cpu,
        ),
        "ram": q(
            "Ile GB RAM jest w zestawie (razem)? Bez RAM = 0.",
            {**{f"{r}gb": f"{r} GB" for r in (0, 4, 8, 16, 32, 64)}, UNKNOWN: "nie da się ustalić"},
        ),
        "co": q(
            "Co DOKŁADNIE jest w zestawie?",
            {
                "plyta_procesor": "płyta główna + procesor (ew. z chłodzeniem), bez RAM",
                "plyta_procesor_ram": "płyta główna + procesor + RAM",
                "komputer": "cały komputer (z obudową, zasilaczem, dyskiem)",
                "sama_czesc": "tylko jedna część (sama płyta albo sam procesor)",
                "inna_rzecz": "inna rzecz (Raspberry Pi, laptop, gry, kupię)",
                UNKNOWN: "nie da się ustalić",
            },
        ),
        "stan": q(
            "Czy zestaw działa?",
            {
                "sprawny": "sprawny",
                "uszkodzony": "uszkodzony / nie startuje / na części",
                UNKNOWN: "nie da się ustalić",
            },
        ),
    }


def bundle_rules(spec, title, desc="", form=None):
    t, d = X.norm(title), X.norm(desc)
    cpu = X.desktop_cpu(t) or X.desktop_cpu(d)
    cb = cpu_bucket(cpu.replace("ryzen ", "ryzen ").replace(" ", " ")) if cpu else None
    if cpu and cpu.startswith("ryzen"):
        m = re.match(r"ryzen (\d) (\d)", cpu)
        cb = f"ryzen{m.group(1)}_{m.group(2)}000" if m else None
    ram = re.search(r"\b(\d{1,2})\s*gb\b", t)
    ram = f"{ram.group(1)}gb" if ram and int(ram.group(1)) in (4, 8, 16, 32, 64) else UNKNOWN
    has_ram = ram != UNKNOWN or re.search(r"\bram\b|\bddr\d\b", t)
    co = (
        "inna_rzecz"
        if re.search(r"\b(?:raspberry|kupie|szukam)\b", t)
        else (
            "komputer"
            if re.search(r"\b(?:komputer|pc gamingowy|optiplex|elitedesk|thinkcentre|zasilacz|obudow\w*)\b", t)
            else "plyta_procesor_ram" if (cpu and has_ram) else "plyta_procesor" if cpu and X.chipset(t) else UNKNOWN
        )
    )
    stan = "uszkodzony" if X.has_fault(X.FOR_PARTS, f"{t}\n{d}") else UNKNOWN
    return {
        "procesor": cb if cb in spec["cpu"] else (UNKNOWN if cb is None else "inny"),
        "ram": ram,
        "co": co,
        "stan": stan,
    }


def bundle_tricky(spec, i):
    cpu = spec["cpu"]
    a = cpu[i % len(cpu)]
    return [
        dict(
            title="Zestaw płyta + procesor",
            description=f"Procesor {cpu_label(a)}, płyta B450, bez RAM.",
            expected={"procesor": a, "co": "plyta_procesor", "ram": "0gb"},
        ),
        dict(
            title="Kit i5-9400F + ASRock B365 + 16GB DDR4",
            description="Zestaw działa, zdjęty z komputera.",
            expected={"procesor": "intel_i5_9gen", "ram": "16gb", "co": "plyta_procesor_ram", "stan": "sprawny"},
        ),
        dict(title="Płyta z procesorem", description="Nie startuje, na części.", expected={"stan": "uszkodzony"}),
        dict(title="Raspberry Pi 4 4GB", description="Mini komputer z zasilaczem.", expected={"co": "inna_rzecz"}),
    ]


# ---------------------------------------------------------------------------------------------- kategorie → funkcje

CATEGORIES = {
    "phone": (phone_questions, phone_rules, phone_tricky),
    "tablet": (tablet_questions, tablet_rules, tablet_tricky),
    "console": (console_questions, console_rules, console_tricky),
    "laptop": (laptop_questions, laptop_rules, laptop_tricky),
    "gpu": (gpu_questions, gpu_rules, gpu_tricky),
    "ram": (ram_questions, ram_rules, ram_tricky),
    "storage": (storage_part_questions, storage_part_rules, storage_part_tricky),
    "cpu": (cpu_part_questions, cpu_part_rules, cpu_part_tricky),
    "motherboard": (mobo_questions, mobo_rules, mobo_tricky),
    "bundle": (bundle_questions, bundle_rules, bundle_tricky),
}


# ---------------------------------------------------------------------------------------------- budowa rodzin

FORM_KEYS = {
    "status": "stan",
    "brand": "marka",
    "model_nav": "model",
    "internal_memory_capacity": "pamięć",
    "battery_health": "bateria",
    "sim_lock": "blokada SIM",
    "video_game_platform": "platforma",
    "computer_cpu_line": "procesor",
    "computer_ram": "RAM",
    "computer_storage_capacity": "dysk",
    "laptop_display_size": "ekran",
    "laptop_charger_included": "ładowarka",
    "computer_operating_system": "system",
    "keyboard_layout": "klawiatura",
}
# Pytania o wariant (sygnały próbki „tytuł bez X” / „opis zmienia X”); stan, blokada, co - to pułapki językowe.
VARIANT_KEYS = (
    "model",
    "pamiec",
    "ram",
    "siec",
    "naped",
    "dock",
    "vram",
    "pamiec_typ",
    "procesor",
    "karta",
    "generacja",
    "rok",
    "dysk",
    "typ",
    "mhz",
    "forma",
    "pojemnosc",
    "sufiks",
    "chipset",
    "ddr",
    "lacznosc",
    "akcesoria",
    "pady",
    "gry",
    "sztuk",
)
_SPECS = None
DROPPED = []  # oczekiwane odpowiedzi przypadków testowych odrzucone przy budowie (test)


def _compile(spec, cat):
    s = dict(spec)
    s["cat"] = cat
    s["variants"] = make_variants(spec.get("variants") or [], spec.get("drop", ()))
    s["match_rx"] = re.compile(spec.get("match") or ".")
    s["ctx_rx"] = re.compile(spec["ctx"]) if spec.get("ctx") else None
    s["platform_rx"] = re.compile(spec["platform"]) if spec.get("platform") else None
    s["fallback"] = (spec.get("match") or ".") == "."
    from .basal_specs import PRICES

    s["price"] = PRICES.get(spec["id"]) or spec.get("price") or 500
    s.setdefault("short", spec["name"].split(" (")[0])
    return s


def specs():
    global _SPECS
    if _SPECS is None:
        from .basal_specs import ALL

        _SPECS = {cat: [_compile(sp, cat) for sp in lst] for cat, lst in ALL.items()}
    return _SPECS


def spec_of(family_id):
    return next((s for lst in specs().values() for s in lst if s["id"] == family_id), None)


def _flags(spec, cat):
    P = _parts()
    if cat == "phone" and spec.get("apple"):
        return dict(PHONE_FLAGS_APPLE)
    if cat in ("gpu", "ram", "storage", "cpu"):
        return dict(P.PART_FLAGS)
    return dict(spec.get("flags") or {})


def build_families():
    """Rodziny v2 w formacie basal_poc.FAMILIES (+ "v2", "spec"; rules(title, desc, form), przypadki testowe
    jako słowniki z formularzem)."""
    out = {}
    DROPPED.clear()
    for cat, lst in specs().items():
        questions_fn, rules_fn, tricky_fn = CATEGORIES[cat]
        for i, spec in enumerate(lst):
            qs = questions_fn(spec)
            tricky = []
            for case in tricky_fn(spec, i):
                expected = {}
                for k, v in case["expected"].items():
                    if k in qs and v in qs[k]["criteria"]:
                        expected[k] = v
                    else:
                        DROPPED.append((spec["id"], k, v, k in qs))
                if expected:
                    tricky.append({**case, "expected": expected})

            def rules(title, desc="", form=None, _s=spec, _f=rules_fn):
                return _f(_s, title, desc or "", form or {})

            out[spec["id"]] = {
                "name": spec["name"],
                "category": cat,
                "title": None,
                "v2": True,
                "spec": spec,
                "rules": rules,
                "questions": qs,
                "flags": _flags(spec, cat),
                "tricky": tricky,
                "price": spec.get("price", 500),
            }
    return out


def assign(category, title, form=None, brand=None):
    """Rodzina oferty: najpierw wzorzec rodziny w tytule, potem model / platforma z formularza, na końcu rodziny
    zbiorcze („.”). Marka (ctx) - w tytule, marce albo modelu z formularza."""
    form = form or {}
    t = nrm(title)
    nav = nrm(form.get("model_nav") or "")
    plat = X.norm(form.get("video_game_platform") or "")
    ctx_text = f"{t} {nrm(brand or form.get('brand') or '')} {nav}"
    lst = specs().get(category, [])
    ok = [s for s in lst if not s["ctx_rx"] or s["ctx_rx"].search(ctx_text)]
    for s in ok:
        if not s["fallback"] and s["match_rx"].search(t):
            return s["id"]
    for s in ok:
        if not s["fallback"] and (
            (nav and s["match_rx"].search(nav)) or (plat and s["platform_rx"] and s["platform_rx"].search(plat))
        ):
            return s["id"]
    return next((s["id"] for s in ok if s["fallback"]), None)


def form_of(attributes):
    return {k: v for k, v in (attributes or {}).items() if k in FORM_KEYS and v not in (None, "")}


def form_text(form):
    parts = [f"{FORM_KEYS[k]}: {v}" for k, v in form.items() if k in FORM_KEYS and k != "status" and str(v).strip()]
    return "; ".join(parts)


def variant_signals_v2(fam, title, desc, form):
    rules = fam["rules"]
    by_title = rules(title)
    by_all = rules(title, desc, form)
    out = []
    for key in VARIANT_KEYS:
        if key not in by_title:
            continue
        a, b = by_title[key], by_all.get(key)
        if a == UNKNOWN and b not in NO_RULE:
            out.append(f"tytuł bez: {key} (jest w opisie)")
        elif a == UNKNOWN and key in ("model", "pamiec", "vram", "mhz", "chipset"):
            out.append(f"tytuł bez: {key} (nigdzie)")
        elif a not in NO_RULE and b != a:
            out.append(f"opis zmienia: {key}")
    return out, by_all


def form_signals(fam, title, desc, form):
    out = []
    spec = fam["spec"]
    mem = X.norm(form.get("internal_memory_capacity") or "")
    if "mb" in mem:
        out.append("formularz: pamięć w MB")
    if spec.get("storage") and mem:
        by_title = storage_rule(spec["storage"], title)
        by_form = storage_rule(spec["storage"], "", "", form.get("internal_memory_capacity"))
        if by_title not in NO_RULE and by_form not in NO_RULE and by_title != by_form:
            out.append("formularz ≠ tytuł: pamięć")
    if form.get("model_nav") and spec.get("variants"):
        a = rule_variant(spec["variants"], title)
        b = rule_variant(spec["variants"], "", "", form["model_nav"])
        if a not in NO_RULE and b not in NO_RULE and a != b:
            out.append("formularz ≠ tytuł: model")
    ram = X._gb(form.get("computer_ram") or "") if form.get("computer_ram") else None
    if ram and ram > 64:
        out.append("formularz: dysk w polu RAM")
    disk = X._gb(form.get("computer_storage_capacity") or "") if form.get("computer_storage_capacity") else None
    if disk and disk < 32:
        out.append("formularz: RAM w polu dysku")
    if (
        spec.get("platform_rx")
        and form.get("video_game_platform")
        and not spec["platform_rx"].search(X.norm(form["video_game_platform"]))
    ):
        out.append("formularz: inna platforma")
    return out


def _is_variant_group(name):
    return name.startswith(("tytuł bez", "opis zmienia", "liczba sztuk", "formularz"))


def sample_all(conn, limit=20, seed=7, only=None, say=print):
    """Wszystkie rodziny v2 jednym przejściem bazy → {rodzina: (wiersze, liczby ofert na sygnał)}.
    W rodzinie po kolei z każdej grupy: pułapki wariantu i formularza, każdy wariant („wariant: X”), pułapki językowe;
    w grupie najpierw oferty z największą liczbą pułapek."""
    import json
    from . import basal_poc as P
    from .sample import redact

    fams = {k: v for k, v in P.FAMILIES.items() if v.get("v2") and (not only or k in only)}
    cats = sorted({f["category"] for f in fams.values()})
    groups = {fid: {} for fid in fams}
    signals_of = {}
    n = 0
    sql = (
        f"SELECT l.id, l.category, l.title, l.brand, d.description, d.attributes_json FROM listings l "
        f"JOIN details d ON d.listing_id = l.id WHERE d.description IS NOT NULL "
        f"AND l.category IN ({','.join('?' * len(cats))})"
    )
    for lid, cat, title, brand, desc, attrs in conn.execute(sql, cats):
        n += 1
        if n % 20000 == 0:
            say(f"  ... {n} ofert")
        try:
            form = form_of(json.loads(attrs) if attrs else {})
        except ValueError:
            form = {}
        fid = assign(cat, title or "", form, brand)
        if fid not in fams:
            continue
        fam = fams[fid]
        variant, by_all = variant_signals_v2(fam, title or "", desc or "", form)
        found = variant + form_signals(fam, title or "", desc or "", form)
        found += P.language_signals(title, desc, fid)
        model = by_all.get("model") or by_all.get("chipset") or by_all.get("procesor")
        if model not in NO_RULE:
            found.append(f"wariant: {model}")
        signals_of[lid] = (sum(_is_variant_group(g) for g in found), len(found), found)
        for name in found:
            groups[fid].setdefault(name, []).append(lid)
    rnd = random.Random(seed)
    picked_of = {}
    for fid, grp in groups.items():
        for ids in grp.values():
            rnd.shuffle(ids)
            ids.sort(key=lambda i: (-signals_of[i][0], -signals_of[i][1]))
        order = sorted(grp, key=lambda g: (0 if _is_variant_group(g) else 1 if g.startswith("wariant:") else 2, g))
        picked, seen, i = [], set(), 0
        while len(picked) < limit and any(i < len(grp[g]) for g in order):
            for name in order:
                if i < len(grp[name]) and len(picked) < limit and grp[name][i] not in seen:
                    seen.add(grp[name][i])
                    picked.append(grp[name][i])
            i += 1
        picked_of[fid] = picked
    rows_of = {}
    wanted = [i for ids in picked_of.values() for i in ids]
    for chunk in range(0, len(wanted), 500):
        ids = wanted[chunk : chunk + 500]
        q_ = (
            f"SELECT l.id, l.title, l.price_now, l.sold_price, l.state, l.status_label, d.description, "
            f"d.attributes_json FROM listings l JOIN details d ON d.listing_id = l.id "
            f"WHERE l.id IN ({','.join('?' * len(ids))})"
        )
        for r in conn.execute(q_, ids):
            rows_of[r[0]] = r
    out = {}
    for fid, ids in picked_of.items():
        rows = []
        for lid in ids:
            r = rows_of[lid]
            try:
                form = form_of(json.loads(r[7]) if r[7] else {})
            except ValueError:
                form = {}
            price = r[3] if r[4] == "sold" and r[3] else r[2]
            rows.append(
                {
                    "id": r[0],
                    "title": r[1],
                    "price": price,
                    "state": r[4],
                    "condition": r[5],
                    "hint": " + ".join(signals_of[lid][2]),
                    "form": form,
                    "description": redact((r[6] or "")[: P.DESCRIPTION_CHARS]),
                }
            )
        out[fid] = (rows, {k: len(v) for k, v in groups[fid].items()})
    return out


def save_all(samples, out_dir, stamp=None):
    from datetime import datetime
    from pathlib import Path
    from . import basal_poc as P

    stamp = stamp or f"{datetime.now():%Y%m%d}"
    folder = Path(out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for fid, (rows, _counts) in sorted(samples.items()):
        if not rows:
            continue
        path = folder / f"{fid}_{stamp}.jsonl"
        path.write_text("".join(P.dumps_line(r) + "\n" for r in rows), encoding="utf-8")
        paths.append(path)
    return paths


CATEGORY_NAMES = {
    "phone": "Telefony",
    "tablet": "Tablety",
    "console": "Konsole",
    "laptop": "Laptopy",
    "gpu": "Karty graficzne",
    "ram": "Pamięć RAM",
    "storage": "Dyski",
    "cpu": "Procesory",
    "motherboard": "Płyty główne",
    "bundle": "Zestawy",
}


def catalog_markdown(families):
    """Lista rodzin v2 do BASAL_RODZINY.md (`python -m analyzer basal-rodziny`)."""
    lines = []
    for cat, title in CATEGORY_NAMES.items():
        fams = [(fid, f) for fid, f in families.items() if f.get("v2") and f["category"] == cat]
        if not fams:
            continue
        lines += [
            f"### {title} ({len(fams)} rodzin)",
            "",
            "| rodzina | co obejmuje | warianty | pytania |",
            "|---|---|---|---|",
        ]
        for fid, f in fams:
            v = f["spec"]["variants"]
            shown = ", ".join(x.label for x in v[:6]) + (f" … (+{len(v) - 6})" if len(v) > 6 else "")
            lines.append(f"| `{fid}` | {f['name']} | {len(v)}: {shown} | {', '.join(f['questions'])} |")
        lines.append("")
    return "\n".join(lines)
