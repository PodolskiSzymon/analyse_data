"""Pilnowanie proxy w watch i innych komendach przez proxy (2026-11-07, prośba użytkownika: „powiadomienie na ntfy
o padniętym proxy po iluś próbach”).

Licznik błędów z rzędu na całej sesji Vinted (katalog, szczegóły, resolver, odświeżanie sesji przeglądarką):
  * błąd połączenia / proxy (httpx.TransportError, nieudane odświeżenie sesji) → +1; każda odpowiedź HTTP (także
    404, 429, 403 - przyszła, więc proxy działa) → licznik od zera,
  * po ANALYZER_PROXY_ALERT_AFTER błędach z rzędu (domyślnie 20) - jedno powiadomienie ntfy; przy 407 (proxy
    odrzuca login / hasło, brak transferu) już po 3,
  * gdy dalej nie działa - przypomnienie co ANALYZER_PROXY_ALERT_REPEAT_H godzin (domyślnie 6),
  * pierwsza odpowiedź po alarmie → powiadomienie „proxy znów działa”.
Watch i tak ponawia sam (przerwy, wznawianie partycji) - to tylko informacja dla człowieka. Bez danych logowania
w treści (adres proxy z hasłem wycięty).
"""
import logging
import os
import re
import time

import httpx

log = logging.getLogger("analyzer.proxy")

_CREDENTIALS = re.compile(r"//[^@/\s]+@")


def _env_number(name, default):
    try:
        return float(os.getenv(name) or default)
    except ValueError:
        return float(default)


def _short(exc):
    text = (str(exc).splitlines() or [""])[0] or type(exc).__name__
    return _CREDENTIALS.sub("//***@", f"{type(exc).__name__}: {text}")[:200]


def is_auth_error(exc):
    return "407" in str(exc) or "Proxy Authentication" in str(exc) or "odrzuciło dane logowania" in str(exc) \
        or "odrzucił dane logowania" in str(exc)


class ProxyHealth:
    def __init__(self, after=None, after_auth=3, repeat_h=None, send=None, clock=time.monotonic, name="analyzer"):
        self.after = int(after if after is not None else _env_number("ANALYZER_PROXY_ALERT_AFTER", 20))
        self.after_auth = after_auth
        self.repeat_s = 3600 * (repeat_h if repeat_h is not None else _env_number("ANALYZER_PROXY_ALERT_REPEAT_H", 6))
        self._send = send
        self.clock = clock
        self.name = name
        self.failures = 0
        self.alerted_at = None
        self.last_error = None

    async def _notify(self, title, lines, priority):
        send = self._send
        if send is None:
            from .notify import send
        try:
            await send(title, lines, priority=priority, tags=("warning",) if priority >= 4 else ("white_check_mark",))
        except Exception:                    # powiadomienie nigdy nie zatrzymuje watch
            log.exception("[PROXY] Nie wysłałem powiadomienia.")

    async def failed(self, exc):
        self.failures += 1
        self.last_error = _short(exc)
        auth = is_auth_error(exc)
        need = self.after_auth if auth else self.after
        if self.failures < need:
            return
        now = self.clock()
        if self.alerted_at is not None and now - self.alerted_at < self.repeat_s:
            return
        first = self.alerted_at is None
        self.alerted_at = now
        log.error("[PROXY] %d błędów z rzędu przez proxy (ostatni: %s)%s.", self.failures, self.last_error,
                  " - proxy odrzuca dane logowania (407)" if auth else "")
        lines = [f"{self.failures} błędów z rzędu przez proxy ({self.name}).", f"Ostatni: {self.last_error}"]
        if auth:
            lines.append("407 = złe dane logowania albo brak transferu - sprawdź saldo / hasło w panelu dostawcy "
                         "i SNIPER_PROXY_HOST / SNIPER_PROXY_AUTH w .env.")
        else:
            lines.append("Sprawdź panel dostawcy proxy (saldo, ważność planu) i internet na serwerze.")
        lines.append("Program ponawia sam; dam znać, gdy proxy wróci." if first else "Dalej nie działa.")
        await self._notify("Analyzer: proxy nie działa" if first else "Analyzer: proxy dalej nie działa", lines, 4)

    async def ok(self):
        if self.alerted_at is not None:
            log.info("[PROXY] Proxy znów działa (po %d błędach z rzędu).", self.failures)
            await self._notify("Analyzer: proxy znów działa", [f"Po {self.failures} błędach z rzędu ({self.name}).",
                                                               "Zbieranie danych idzie dalej."], 3)
        self.failures, self.alerted_at = 0, None

    def attach(self, session):
        """Podpina licznik pod sesję: każde zapytanie HTTP (client.send) i odświeżanie sesji (refresh)."""
        from sniper.session import SessionExpired

        send, refresh = session.client.send, session.refresh

        async def watched_send(*args, **kwargs):
            try:
                response = await send(*args, **kwargs)
            except httpx.TransportError as exc:
                await self.failed(exc)
                raise
            await self.ok()
            return response

        async def watched_refresh(*args, **kwargs):
            try:
                return await refresh(*args, **kwargs)
            except SessionExpired as exc:
                await self.failed(exc)
                raise

        session.client.send = watched_send
        session.refresh = watched_refresh
        session.proxy_health = self
        return session
