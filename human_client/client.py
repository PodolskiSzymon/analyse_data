"""Makieta klienta Vinted: przeglądarka (stały profil) tylko po ciastka, zapytania HTTP z odciskiem TLS Chrome.

Bez proxy - ruch idzie z Twojego łącza. Opis wszystkich ustawień i skąd wziąć tokeny: human_client/README.md.

    python -m human_client.client --dry-run          # symulacja harmonogramu (bez sieci, bez przeglądarki)
    python -m human_client.client --refresh-only     # tylko odświeżenie sesji w przeglądarce + zapis state.json
    python -m human_client.client                    # odświeżenie (gdy trzeba) + kilka stron katalogu w ludzkim tempie

Przepływ:
  1. secrets.json (wklejone przez Ciebie: x-csrf-token, x-anon-id, nagłówek Cookie) = tylko „zasiew” przy pierwszym
     uruchomieniu albo gdy profil przeglądarki jest pusty.
  2. Przeglądarka (Twój Chrome/Edge, stały profil w human_client/profile) otwiera vinted.pl z tymi ciastkami - strona
     sama odświeża access_token_web (refresh_token_web) i ciastko datadome. Zabieramy ciastka, token CSRF i PRAWDZIWY
     User-Agent / sec-ch-ua tej przeglądarki -> state.json.
  3. Zapytania HTTP idą przez curl_cffi z odciskiem TLS Chrome i nagłówkami tej samej przeglądarki.
  4. Co 15-60 min (losowo) albo po 401/403 - krok 2 od nowa (ten sam profil, „stary” refresh_token).
"""
import argparse
import base64
import json
import logging
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("human_client")

HERE = Path(__file__).resolve().parent
START_URL = "https://www.vinted.pl/"
CATALOG_URL = "https://api.vinted.pl/svc-catalogue/items"   # jak sniper/config.py (sprawdzone na żywo)
COOKIE_URLS = ["https://www.vinted.pl", "https://api.vinted.pl"]
TOKEN_HEADERS = ("x-csrf-token", "x-anon-id")

DEFAULT_CONFIG = {
    "browser": {
        "channel": "chrome",            # "chrome" | "msedge" | "" (wtedy executable_path albo Chromium Playwrighta)
        "executable_path": "",          # np. C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe
        "profile_dir": "human_client/profile",
        "headless": False,              # okno widoczne - najmniej podejrzane
        "keep_open": False,             # False = zamknij po odświeżeniu (oszczędza RAM na 4 GB)
        "warmup_url": "https://www.vinted.pl/catalog/3580",
    },
    "refresh_minutes": [15, 60],        # losowy odstęp między odświeżeniami sesji
    "pacing": {
        "gap_s": [2.0, 6.0],            # zwykły odstęp między zapytaniami
        "read_chance": 0.15,            # czasem dłuższe „czytanie”
        "read_s": [8.0, 25.0],
        "break_every_min": [25, 35],    # co tyle minut przerwa
        "break_s": [60, 240],
        "active_hours": [8, 23],        # poza tymi godzinami program śpi
        "max_requests_per_session": 300,
    },
    "http": {"impersonate": "chrome", "timeout_s": 30},
    "job": {"catalog_id": 3580, "pages": 3, "per_page": 96, "order": "newest_first"},
}

# Nagłówki jak w sniper/config.py (z cURL przeglądarki); user-agent i sec-ch-ua podmieniamy na prawdziwe z przeglądarki.
API_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "locale": "pl-PL",
    "origin": "https://www.vinted.pl",
    "platform": "web",
    "priority": "u=1, i",
    "referer": "https://www.vinted.pl/",
    "sec-ch-ua-mobile": "?0",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "x-next-app": "marketplace-web",
}


# ---------------------------------------------------------------- pliki

def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as e:
        sys.exit(f"Błędny JSON w {path}: {e}")


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(base[k], v) if isinstance(v, dict) and isinstance(base.get(k), dict) else v
    return out


# ---------------------------------------------------------------- tokeny i ciastka

def parse_cookie_header(header):
    """'a=1; b=2' (nagłówek Cookie z F12) -> lista ciastek dla Playwrighta / curl_cffi."""
    out = []
    for part in (header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            out.append({"name": name, "value": value, "domain": ".vinted.pl", "path": "/"})
    return out


def jwt_expiry(token):
    """Data wygaśnięcia JWT (pole exp) bez weryfikacji podpisu - tylko do informacji. None = nie JWT."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        return datetime.fromtimestamp(exp) if exp else None
    except (IndexError, ValueError, AttributeError):
        return None


def sec_ch_ua(brands):
    """navigator.userAgentData.brands -> nagłówek sec-ch-ua dokładnie taki, jaki wysyła ta przeglądarka."""
    return ", ".join(f'"{b["brand"]}";v="{b["version"]}"' for b in brands or [])


# ---------------------------------------------------------------- tempo

class Pacer:
    """Ludzkie tempo: nierówne odstępy, czasem „czytanie”, przerwy co ~pół godziny, sen poza godzinami aktywności."""

    def __init__(self, cfg, rng=None, clock=time.time):
        self.cfg, self.rng, self.clock = cfg, rng or random.Random(), clock
        self.requests = 0
        self.next_break = self.clock() + self._break_interval()

    def _break_interval(self):
        return self.rng.uniform(*self.cfg["break_every_min"]) * 60

    def sleep_until_active(self):
        """Sekundy do początku godzin aktywności (0 = teraz aktywne)."""
        start, end = self.cfg["active_hours"]
        now = datetime.fromtimestamp(self.clock())
        if start <= now.hour < end:
            return 0.0
        wake = now.replace(hour=start, minute=0, second=0, microsecond=0)
        if now.hour >= end:
            wake += timedelta(days=1)
        return (wake - now).total_seconds() + self.rng.uniform(0, 1800)   # nie punktualnie o 8:00

    def next(self):
        """(sekundy, opis) przed kolejnym zapytaniem."""
        self.requests += 1
        now = self.clock()
        if now >= self.next_break:
            pause = self.rng.uniform(*self.cfg["break_s"])
            self.next_break = now + pause + self._break_interval()
            return pause, "przerwa"
        if self.rng.random() < self.cfg["read_chance"]:
            return self.rng.uniform(*self.cfg["read_s"]), "czytanie"
        # Rozkład trójkątny: najczęściej bliżej dolnej granicy, czasem dłużej - mniej „maszynowo” niż równomierny.
        lo, hi = self.cfg["gap_s"]
        return self.rng.triangular(lo, hi, lo + (hi - lo) * 0.3), None

    def session_full(self):
        return self.requests >= self.cfg["max_requests_per_session"]


# ---------------------------------------------------------------- przeglądarka (odświeżanie sesji)

def _playwright():
    """Patchright (łata wycieków CDP), a gdy go nie ma - zwykły Playwright."""
    try:
        from patchright.sync_api import sync_playwright
        return sync_playwright, "patchright"
    except ImportError:
        from playwright.sync_api import sync_playwright
        return sync_playwright, "playwright"


class BrowserRefresher:
    def __init__(self, cfg, rng=None):
        self.cfg, self.rng = cfg, rng or random.Random()
        self._pw = self._ctx = None

    def _open(self):
        if self._ctx:
            return self._ctx
        factory, name = _playwright()
        self._pw = factory().start()
        opts = {"user_data_dir": str(Path(self.cfg["profile_dir"]).resolve()), "headless": self.cfg["headless"],
                "locale": "pl-PL", "timezone_id": "Europe/Warsaw", "no_viewport": True}
        if self.cfg.get("executable_path"):
            opts["executable_path"] = self.cfg["executable_path"]
        elif self.cfg.get("channel"):
            opts["channel"] = self.cfg["channel"]
        # Bez proxy i bez własnego user_agent: przeglądarka przedstawia się sama, zgodnie z prawdą.
        log.info("[BROWSER] %s, profil %s, %s", name, opts["user_data_dir"],
                 opts.get("executable_path") or opts.get("channel") or "Chromium")
        self._ctx = self._pw.chromium.launch_persistent_context(**opts)
        return self._ctx

    def close(self):
        if self._ctx:
            self._ctx.close()
        if self._pw:
            self._pw.stop()
        self._pw = self._ctx = None

    def _wait(self, page, lo, hi):
        page.wait_for_timeout(int(self.rng.uniform(lo, hi) * 1000))

    def refresh(self, seed_cookies=None):
        """Wejście na vinted.pl w stałym profilu -> (ciastka, tokeny, user_agent, sec_ch_ua, platforma)."""
        ctx = self._open()
        if seed_cookies:
            ctx.add_cookies(seed_cookies)
            log.info("[BROWSER] Zasiane ciastka z secrets.json: %d", len(seed_cookies))
        captured = {}

        def on_request(req):
            if "vinted.pl/api" in req.url or "api.vinted.pl" in req.url:
                for h in TOKEN_HEADERS:
                    if h in req.headers:
                        captured[h] = req.headers[h]

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("request", on_request)
        page.goto(START_URL, wait_until="load")
        self._wait(page, 2, 5)
        for _ in range(self.rng.randint(2, 4)):         # trochę ruchu jak człowiek: mysz + przewinięcie
            page.mouse.move(self.rng.randint(100, 900), self.rng.randint(100, 600), steps=self.rng.randint(8, 25))
            page.mouse.wheel(0, self.rng.randint(200, 700))
            self._wait(page, 0.8, 2.5)
        if self.cfg.get("warmup_url"):
            page.goto(self.cfg["warmup_url"], wait_until="load")
            self._wait(page, 3, 6)
        if "x-csrf-token" not in captured:
            token = page.evaluate("() => document.querySelector('meta[name=\"csrf-token\"]')?.content || null")
            if token:
                captured["x-csrf-token"] = token
        ua = page.evaluate("() => navigator.userAgent")
        brands = page.evaluate("() => navigator.userAgentData ? navigator.userAgentData.brands : null")
        platform = page.evaluate("() => navigator.userAgentData ? navigator.userAgentData.platform : null")
        cookies = ctx.cookies(COOKIE_URLS)
        page.remove_listener("request", on_request)
        if not self.cfg.get("keep_open"):
            self.close()
        return {"cookies": cookies, "tokens": captured, "user_agent": ua, "sec_ch_ua": sec_ch_ua(brands),
                "platform": platform, "refreshed_at": time.time()}


# ---------------------------------------------------------------- HTTP z odciskiem TLS Chrome

class HttpClient:
    def __init__(self, cfg, session=None):
        if session is None:
            from curl_cffi import requests as cffi
            # trust_env=False: ignoruj HTTP(S)_PROXY z systemu - świadomie bez proxy.
            session = cffi.Session(impersonate=cfg["impersonate"], trust_env=False)
        self.s, self.timeout = session, cfg["timeout_s"]
        self.headers = dict(API_HEADERS)

    def apply(self, state):
        self.s.cookies.clear()
        for c in state["cookies"]:
            self.s.cookies.set(c["name"], c["value"], domain=c.get("domain", ".vinted.pl"), path=c.get("path", "/"))
        self.headers = dict(API_HEADERS)
        self.headers["user-agent"] = state["user_agent"]
        if state.get("sec_ch_ua"):
            self.headers["sec-ch-ua"] = state["sec_ch_ua"]
        if state.get("platform"):
            self.headers["sec-ch-ua-platform"] = f'"{state["platform"]}"'
        self.headers.update(state.get("tokens") or {})

    def get(self, url, params=None):
        return self.s.get(url, params=params, headers=self.headers, timeout=self.timeout)

    def cookies_list(self):
        return [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path} for c in self.s.cookies.jar]


# ---------------------------------------------------------------- przebieg

def catalog_params(job, page):
    return {"page": page, "per_page": job["per_page"], "search_text": "", "currency": "PLN", "order": job["order"],
            "attribute_ids[catalog]": job["catalog_id"], "attribute_ids[brand]": "",
            "attribute_ids[brand_collection]": "", "attribute_ids[status]": ""}


class Runner:
    RATE_LIMIT_WAITS = (300, 900, 1800)

    def __init__(self, cfg, browser, http, state_path, secrets, sleep=time.sleep, clock=time.time, rng=None):
        self.cfg, self.browser, self.http = cfg, browser, http
        self.state_path, self.secrets = state_path, secrets or {}
        self.sleep, self.clock, self.rng = sleep, clock, rng or random.Random()
        self.pacer = Pacer(cfg["pacing"], self.rng, clock)
        self.state = load_json(state_path)
        self.next_refresh = 0.0
        if self.state:
            self.http.apply(self.state)
            self.next_refresh = self.state["refreshed_at"] + self._refresh_interval()

    def _refresh_interval(self):
        return self.rng.uniform(*self.cfg["refresh_minutes"]) * 60

    def refresh(self, reason):
        log.info("[SESJA] Odświeżenie w przeglądarce (%s)", reason)
        # Zasiew tylko, gdy nie mamy jeszcze żadnej sesji; potem profil przeglądarki ma własne ciastka.
        seed = parse_cookie_header(self.secrets.get("cookie")) if not self.state else None
        state = self.browser.refresh(seed)
        for h in TOKEN_HEADERS:                      # token z F12 jako zapas, gdy strona go nie wysłała
            if h not in state["tokens"] and self.secrets.get(h):
                state["tokens"][h] = self.secrets[h]
        self.state = state
        self.http.apply(state)
        save_json(self.state_path, state)
        self.next_refresh = self.clock() + self._refresh_interval()
        access = next((c["value"] for c in state["cookies"] if c["name"] == "access_token_web"), None)
        exp = jwt_expiry(access) if access else None
        log.info("[SESJA] Ciastek %d, tokeny: %s, UA: %s%s, następne odświeżenie za %.0f min",
                 len(state["cookies"]), ", ".join(sorted(state["tokens"])) or "brak", state["user_agent"][:60],
                 f", access_token_web ważny do {exp:%H:%M}" if exp else "", (self.next_refresh - self.clock()) / 60)

    def _save_cookies(self):
        # Odpowiedzi API mogą ustawić nowe ciastka (np. datadome) - zapisujemy, żeby następny start ich użył.
        self.state["cookies"] = self.http.cookies_list()
        save_json(self.state_path, self.state)

    def fetch(self, url, params):
        waits = iter(self.RATE_LIMIT_WAITS)
        refreshed = False
        while True:
            if self.clock() >= self.next_refresh:
                self.refresh("czas")
            r = self.http.get(url, params)
            if r.status_code in (401, 403) and not refreshed:
                refreshed = True
                self.refresh(f"HTTP {r.status_code}")
                continue
            if r.status_code == 429:
                wait = next(waits, None)
                if wait is None:
                    raise RuntimeError("HTTP 429 mimo przerw - koniec na dziś")
                log.warning("[HTTP] 429 - czekam %d min", wait // 60)
                self.sleep(wait)
                continue
            self._save_cookies()
            return r

    def run(self, job):
        out = []
        for page in range(1, job["pages"] + 1):
            idle = self.pacer.sleep_until_active()
            if idle:
                log.info("[TEMPO] Poza godzinami aktywności - śpię %.1f h", idle / 3600)
                self.sleep(idle)
            if self.pacer.session_full():
                log.info("[TEMPO] Limit zapytań na sesję - koniec")
                break
            r = self.fetch(CATALOG_URL, catalog_params(job, page))
            items = (r.json() or {}).get("items", []) if r.status_code == 200 else []
            log.info("[KATALOG] strona %d: HTTP %d, ofert %d, %.1f KB", page, r.status_code, len(items),
                     len(r.content) / 1024)
            # RODO: dane sprzedawcy (login, ID, zdjęcie profilu) nie trafiają do pliku.
            out.extend({k: v for k, v in it.items() if k != "user"} for it in items)
            if r.status_code != 200 or not items:
                break
            if page < job["pages"]:
                pause, label = self.pacer.next()
                log.info("[TEMPO] %s %.1f s", label or "odstęp", pause)
                self.sleep(pause)
        return out


# ---------------------------------------------------------------- symulacja (--dry-run)

class _FakeResponse:
    def __init__(self, status, items=()):
        self.status_code, self._items = status, list(items)
        self.content = json.dumps({"items": self._items}).encode()

    def json(self):
        return {"items": self._items}


class FakeBrowser:
    def __init__(self, clock):
        self.clock, self.calls = clock, 0

    def refresh(self, seed_cookies=None):
        self.calls += 1
        return {"cookies": [{"name": "access_token_web", "value": "x", "domain": ".vinted.pl", "path": "/"}],
                "tokens": {"x-csrf-token": "csrf"}, "user_agent": "Mozilla/5.0 (symulacja) Chrome/154.0.0.0",
                "sec_ch_ua": '"Chromium";v="154"', "platform": "Windows", "refreshed_at": self.clock()}


class FakeHttp:
    def __init__(self, statuses=None):
        self.statuses, self.calls = list(statuses or []), 0
        self._cookies = []

    def apply(self, state):
        self._cookies = list(state["cookies"])

    def get(self, url, params=None):
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else 200
        return _FakeResponse(status, [{"id": i} for i in range(3)] if status == 200 else [])

    def cookies_list(self):
        return self._cookies


class VirtualClock:
    def __init__(self, start):
        self.t = start

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(HERE / "config.json"))
    ap.add_argument("--secrets", default=str(HERE / "secrets.json"))
    ap.add_argument("--state", default=str(HERE / "state.json"))
    ap.add_argument("--dry-run", action="store_true", help="symulacja: bez sieci i przeglądarki, wirtualny zegar")
    ap.add_argument("--refresh-only", action="store_true", help="tylko odświeżenie sesji w przeglądarce")
    ap.add_argument("--pages", type=int, help="ile stron katalogu (nadpisuje config)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    cfg = merge(DEFAULT_CONFIG, load_json(args.config, {}))
    if args.pages:
        cfg["job"]["pages"] = args.pages
    secrets = load_json(args.secrets, {})

    if args.dry_run:
        clock = VirtualClock(datetime.now().replace(hour=9, minute=0).timestamp())
        state_path = Path(args.state).with_name("state.dry-run.json")
        state_path.unlink(missing_ok=True)
        runner = Runner(cfg, FakeBrowser(clock), FakeHttp(), state_path, secrets, sleep=clock.sleep, clock=clock)
        start = clock()
        items = runner.run(cfg["job"])
        state_path.unlink(missing_ok=True)
        log.info("[SYMULACJA] stron %d, ofert %d, czas wirtualny %.1f min, odświeżeń sesji %d",
                 runner.http.calls, len(items), (clock() - start) / 60, runner.browser.calls)
        return

    if not secrets and not Path(cfg["browser"]["profile_dir"]).exists():
        log.warning("Brak secrets.json i pustego profilu - przeglądarka wejdzie na Vinted jako nowy gość.")
    browser = BrowserRefresher(cfg["browser"])
    try:
        runner = Runner(cfg, browser, HttpClient(cfg["http"]), args.state, secrets)
        if args.refresh_only or not runner.state:
            runner.refresh("start" if not args.refresh_only else "ręcznie")
        if args.refresh_only:
            return
        items = runner.run(cfg["job"])
        out = HERE / "out" / f"catalog_{datetime.now():%Y%m%d_%H%M%S}.json"
        save_json(out, items)
        log.info("[KONIEC] ofert %d -> %s", len(items), out)
    finally:
        browser.close()


if __name__ == "__main__":
    main()
