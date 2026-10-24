"""Pasek postępu w terminalu (recheck): jedna linia odświeżana w miejscu (\\r), bez dodatkowych bibliotek.

Wpisy logu nie rozjeżdżają paska: filtr na konsolowym handlerze czyści linię przed każdym wpisem, a pasek rysuje się
od nowa przy następnej aktualizacji. Tylko znaki ASCII w pasku (konsola Windows).
"""
import logging
import shutil
import sys
import time


def _hms(seconds):
    seconds = int(max(seconds or 0, 0))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class ConsoleBar(logging.Filter):
    def __init__(self, stream=None, width=None):
        super().__init__()
        self.stream = stream or sys.stderr
        self.width = width
        self.started = time.monotonic()
        self.last = ""
        self.drawn = False

    def _cols(self):
        return self.width or max(40, shutil.get_terminal_size((100, 20)).columns - 1)

    def filter(self, record):          # przed wpisem logu: wyczyść linię paska
        self.clear()
        return True

    def clear(self):
        if self.drawn:
            self.stream.write("\r" + " " * self._cols() + "\r")
            self.stream.flush()
            self.drawn = False

    def line(self, ev):
        total, n = ev["total"], ev["n"]
        cols = self._cols()
        pct = n / total if total else 1.0
        bar_len = 20
        filled = int(bar_len * pct)
        bar = "#" * filled + "-" * (bar_len - filled)
        counts = " ".join(f"{k} {v}" for k, v in sorted(ev["counts"].items()))
        eta = f"zostało ~{_hms(ev['eta'])}" if ev.get("eta") is not None else "liczę czas..."
        head = f"[{bar}] {n}/{total} {pct:5.1%} | {_hms(time.monotonic() - self.started)} | {eta}"
        row = ev.get("row")
        title = "".join(ch for ch in ((row["title"] or "") if row is not None else "") if ord(ch) < 0x2000)
        title = " ".join(title.split())[:30]      # bez emoji (konsola Windows), pojedyncze spacje
        if ev["stage"] == "check":
            what = f"sprawdzam {row['id']} {title}"
        elif ev["stage"] == "done":
            what = f"{row['id']} -> {ev['key']}"
        else:
            what = f"{ev['label']}: {_hms(ev['left'])} (ostatnio: {self.last or '-'})"
        if ev["stage"] == "done":
            self.last = f"{row['id']} {ev['key']}"
        text = f"{head} | {counts} | {what}"
        return text[:cols].ljust(cols)

    def __call__(self, ev):
        self.stream.write("\r" + self.line(ev))
        self.stream.flush()
        self.drawn = True

    def finish(self):
        if self.drawn:
            self.stream.write("\n")
            self.stream.flush()
            self.drawn = False


class Bar:
    """Prosty pasek „etap n/total” dla komend analizy (report, export-analysis) - jedna linia odświeżana co
    `every` s, ASCII. total None = sam licznik."""

    def __init__(self, label, total=None, stream=None, every=0.5):
        self.label, self.total, self.every = label, total, every
        self.stream = stream or sys.stderr
        self.started = self.shown = time.monotonic()
        self.n = 0

    def update(self, n=None, force=False):
        self.n = self.n + 1 if n is None else n
        now = time.monotonic()
        if not force and now - self.shown < self.every:
            return
        self.shown = now
        if self.total:
            pct = min(self.n / self.total, 1.0)
            filled = int(20 * pct)
            text = f"  {self.label} [{'#' * filled}{'-' * (20 - filled)}] {self.n}/{self.total} {pct:5.1%}"
        else:
            text = f"  {self.label}: {self.n}"
        self.stream.write(f"\r{text} | {_hms(now - self.started)}   ")
        self.stream.flush()

    def finish(self):
        self.update(self.n, force=True)
        self.stream.write("\n")
        self.stream.flush()
