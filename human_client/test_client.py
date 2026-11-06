"""Testy makiety bez sieci i bez przeglądarki: python -m pytest human_client -q"""
import random
from datetime import datetime

from human_client import client as hc


def make_runner(tmp_path, statuses=None, refresh_minutes=(15, 60), pages=3):
    cfg = hc.merge(hc.DEFAULT_CONFIG, {"refresh_minutes": list(refresh_minutes), "job": {"pages": pages}})
    clock = hc.VirtualClock(datetime(2026, 11, 6, 9, 0).timestamp())
    runner = hc.Runner(cfg, hc.FakeBrowser(clock), hc.FakeHttp(statuses), tmp_path / "state.json",
                       {"x-anon-id": "anon"}, sleep=clock.sleep, clock=clock, rng=random.Random(1))
    return runner, clock


def test_parse_cookie_header():
    cookies = hc.parse_cookie_header("anon_id=abc; access_token_web=a.b.c; zly; v_udt=x=y")
    assert [(c["name"], c["value"]) for c in cookies] == [("anon_id", "abc"), ("access_token_web", "a.b.c"),
                                                          ("v_udt", "x=y")]
    assert all(c["domain"] == ".vinted.pl" for c in cookies)


def test_jwt_expiry():
    import base64, json
    body = base64.urlsafe_b64encode(json.dumps({"exp": 1893456000}).encode()).decode().rstrip("=")
    assert hc.jwt_expiry(f"h.{body}.s") == datetime.fromtimestamp(1893456000)
    assert hc.jwt_expiry("nie-jwt") is None


def test_sec_ch_ua():
    brands = [{"brand": "Chromium", "version": "154"}, {"brand": "Google Chrome", "version": "154"}]
    assert hc.sec_ch_ua(brands) == '"Chromium";v="154", "Google Chrome";v="154"'


def test_pacer_bounds_and_breaks():
    clock = hc.VirtualClock(datetime(2026, 11, 6, 9, 0).timestamp())
    pacer = hc.Pacer(hc.DEFAULT_CONFIG["pacing"], random.Random(2), clock)
    labels = []
    for _ in range(2000):
        pause, label = pacer.next()
        labels.append(label)
        if label is None:
            assert 2.0 <= pause <= 6.0
        elif label == "czytanie":
            assert 8.0 <= pause <= 25.0
        clock.sleep(pause)
    assert "przerwa" in labels and "czytanie" in labels


def test_sleep_outside_active_hours():
    clock = hc.VirtualClock(datetime(2026, 11, 6, 23, 30).timestamp())
    pacer = hc.Pacer(hc.DEFAULT_CONFIG["pacing"], random.Random(3), clock)
    wait = pacer.sleep_until_active()
    assert 8.5 * 3600 <= wait <= 9 * 3600      # do 8:00 + do 30 min losowo
    clock.t = datetime(2026, 11, 6, 12, 0).timestamp()
    assert pacer.sleep_until_active() == 0


def test_first_run_refreshes_and_saves_state(tmp_path):
    runner, _ = make_runner(tmp_path)
    items = runner.run(runner.cfg["job"])
    assert len(items) == 9 and runner.browser.calls == 1
    state = hc.load_json(tmp_path / "state.json")
    assert state["tokens"] == {"x-csrf-token": "csrf", "x-anon-id": "anon"}   # x-anon-id z secrets jako zapas


def test_refresh_after_time(tmp_path):
    runner, _ = make_runner(tmp_path, refresh_minutes=(15, 15), pages=400)
    runner.run(runner.cfg["job"])
    # 400 stron po ~2-25 s + przerwy => kilka odświeżeń co 15 min, nie przy każdym zapytaniu
    assert 3 <= runner.browser.calls < 100


def test_403_triggers_one_refresh_and_retry(tmp_path):
    runner, _ = make_runner(tmp_path, statuses=[200, 403, 200, 200], pages=3)
    items = runner.run(runner.cfg["job"])
    assert runner.browser.calls == 2 and len(items) == 9


def test_429_waits(tmp_path):
    runner, clock = make_runner(tmp_path, statuses=[429, 200], pages=1)
    start = clock()
    runner.run(runner.cfg["job"])
    assert clock() - start >= 300


def test_existing_state_is_reused(tmp_path):
    runner, clock = make_runner(tmp_path, pages=1)
    runner.run(runner.cfg["job"])
    again = hc.Runner(runner.cfg, hc.FakeBrowser(clock), hc.FakeHttp(), tmp_path / "state.json", {},
                      sleep=clock.sleep, clock=clock, rng=random.Random(4))
    again.run(again.cfg["job"])
    assert again.browser.calls == 0     # sesja świeża - bez otwierania przeglądarki


def test_seller_data_not_saved(tmp_path):
    runner, _ = make_runner(tmp_path, pages=1)
    runner.http.get = lambda url, params=None: _resp([{"id": 1, "title": "x", "user": {"login": "jan"}}])
    items = runner.run(runner.cfg["job"])
    assert items == [{"id": 1, "title": "x"}]


def _resp(items):
    r = hc._FakeResponse(200)
    r._items = items
    return r


def test_http_client_headers_from_browser():
    class S:
        class cookies:
            jar = []
            @staticmethod
            def clear(): pass
            @staticmethod
            def set(*a, **k): S.cookies.jar.append(a)
    http = hc.HttpClient({"impersonate": "chrome", "timeout_s": 5}, session=S())
    http.apply({"cookies": [{"name": "a", "value": "1"}], "tokens": {"x-csrf-token": "t"},
                "user_agent": "UA-z-przegladarki", "sec_ch_ua": '"Chromium";v="154"', "platform": "Windows"})
    assert http.headers["user-agent"] == "UA-z-przegladarki"
    assert http.headers["sec-ch-ua-platform"] == '"Windows"' and http.headers["x-csrf-token"] == "t"
