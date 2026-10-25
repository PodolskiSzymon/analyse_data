"""Zdalny włącznik z telefonu (prośba użytkownika 2026-10-25): `watch` (analizator) i Sniper na serwerze, sterowane
wiadomościami ntfy - bez otwierania portów i bez pulpitu zdalnego.

`python -m analyzer remote` (albo `remote.bat`; skrót w autostarcie Windows) - strażnik:
  * nasłuchuje tematu `ANALYZER_CONTROL_TOPIC` na serwerze ntfy (`SNIPER_NTFY_SERVER`, domyślnie https://ntfy.sh;
    token `SNIPER_NTFY_TOKEN`); w aplikacji ntfy na telefonie subskrybujesz ten temat i wysyłasz do niego wiadomość,
  * polecenia (wielkość liter i kolejność słów dowolna; z `ANALYZER_CONTROL_PIN` - PIN na początku, np. „1234 status”):
      status · start watch · stop watch · restart watch · start sniper · stop sniper · restart sniper ·
      start all · stop all · log watch · log sniper · pomoc   (także po polsku: „włącz/wyłącz/uruchom/zatrzymaj”),
  * odpowiedzi pilota (i „program się wyłączył”) idą do TEGO SAMEGO tematu, w którym piszesz polecenia (jak czat);
    pilot pomija własne wiadomości (`is_own`). Alarm „brak sprzedaży” i automat analizatora idą na
    `ANALYZER_NTFY_TOPIC` (bez niego na `SNIPER_NTFY_TOPIC` - temat okazji Snipera),
  * pilnuje programów: jeśli włączony program się wyłączy (błąd, brak sieci) - uruchamia go ponownie po 60 s
    i wysyła powiadomienie (jak pętla w watch.bat),
  * `ANALYZER_CONTROL_AUTOSTART=watch,sniper` - co uruchomić od razu przy starcie strażnika (np. po restarcie Windows).

Programy:
  * watch  - `python -m analyzer watch` w folderze tego repo (baza z ANALYZER_DB),
  * sniper - `python -m sniper` w folderze `SNIPER_DIR` (repo unreachable_sniper; Python z jego `.venv`, jeśli jest).
Wyjście programów → `<folder bazy>/remote/<nazwa>.log`. Zatrzymanie = zakończenie całego drzewa procesów (taskkill /T
- także przeglądarka Snipera); dane są bezpieczne (SQLite w transakcjach, przejście katalogu wznawia się).

Bezpieczeństwo: nazwa tematu działa jak hasło (długa, losowa, tylko w sniper/.env) + opcjonalny PIN.
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("analyzer.remote")

ROOT = Path(__file__).resolve().parent.parent
RESTART_AFTER_S = 60
CHECK_EVERY_S = 10

HELP = ["Polecenia: status · start/stop/restart watch · start/stop/restart sniper · start all · stop all · "
        "log watch · log sniper · wytyczne · pomoc"]
_START = ("start", "włącz", "wlacz", "uruchom", "on")
_STOP = ("stop", "wyłącz", "wylacz", "zatrzymaj", "off")
_RESTART = ("restart", "zrestartuj")


def parse(text, pin=""):
    """Wiadomość → (akcja, cel) albo (None, powód). akcja: status / start / stop / restart / log / help; cel: watch /
    sniper / all / None."""
    words = (text or "").strip().lower().replace(",", " ").split()
    if pin:
        if not words or words[0] != str(pin).lower():
            return None, "zły albo brak PIN-u"
        words = words[1:]
    if not words:
        return None, "pusta wiadomość"
    target = next((w for w in words if w in ("watch", "sniper", "all", "wszystko")), None)
    target = "all" if target == "wszystko" else target
    if any(w in ("status", "stan") for w in words):
        return "status", target
    if any(w in ("wytyczne", "guidelines", "guide", "guides") for w in words):
        return "guides", None
    if any(w in ("pomoc", "help", "?") for w in words):
        return "help", None
    if any(w == "log" or w == "logi" for w in words):
        return ("log", target) if target in ("watch", "sniper") else (None, "log czego? watch albo sniper")
    for action, keys in (("restart", _RESTART), ("start", _START), ("stop", _STOP)):
        if any(w in keys for w in words):
            return (action, target) if target else (None, f"{action} czego? watch / sniper / all")
    return None, "nieznane polecenie"


@dataclass
class Program:
    name: str
    cmd: list
    cwd: str
    log_path: Path
    wanted: bool = False
    proc: object = None
    started: float = 0.0
    restarts: int = 0
    down_since: float = None
    extra: dict = field(default_factory=dict)

    def running(self):
        return self.proc is not None and self.proc.poll() is None


def default_programs(cfg):
    """watch (to repo) i sniper (SNIPER_DIR) - tylko te, które da się uruchomić."""
    logs = Path(cfg.db_path).parent / "remote"
    programs = {"watch": Program("watch", [sys.executable, "-m", "analyzer", "watch"], str(ROOT), logs / "watch.log")}
    sniper_dir = os.getenv("SNIPER_DIR", "").strip()
    if sniper_dir:
        venv = Path(sniper_dir) / ".venv" / ("Scripts" if os.name == "nt" else "bin") / \
            ("python.exe" if os.name == "nt" else "python")
        python = str(venv) if venv.exists() else sys.executable
        programs["sniper"] = Program("sniper", [python, "-m", "sniper"], sniper_dir, logs / "sniper.log")
    return programs


def pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True)
        return str(int(pid)) in out.stdout
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def kill_pid(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(int(pid), 15)
        except OSError:
            pass


def _pid_file(program):
    return program.log_path.with_suffix(".pid")


def spawn(program):
    """Uruchamia program w tle (osobna grupa procesów), wyjście do pliku logu. Kopia z poprzedniego uruchomienia
    pilota (plik .pid, proces żyje) jest najpierw zamykana - nigdy dwa `watch` na jednej bazie."""
    program.log_path.parent.mkdir(parents=True, exist_ok=True)
    pid_file = _pid_file(program)
    if pid_file.exists():
        old = pid_file.read_text().strip()
        if old.isdigit() and pid_alive(int(old)):
            log.warning("[PILOT] %s: zamykam poprzednią kopię (PID %s).", program.name, old)
            kill_pid(int(old))
    out = open(program.log_path, "a", encoding="utf-8", errors="replace")
    out.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    out.flush()
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    proc = subprocess.Popen(program.cmd, cwd=program.cwd, stdout=out, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, creationflags=flags, env=env)
    pid_file.write_text(str(proc.pid))
    return proc


def kill(proc):
    """Całe drzewo procesów (Sniper uruchamia przeglądarkę)."""
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.terminate()
    try:
        proc.wait(timeout=20)
    except Exception:
        proc.kill()


def tail(path, lines=12):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ["(brak logu)"]
    return [line[-160:] for line in text[-lines:]] or ["(log pusty)"]


def _uptime(seconds):
    h, m = divmod(int(seconds) // 60, 60)
    return f"{h} h {m} min" if h else f"{m} min"


class Controller:
    """Stan programów + wykonywanie poleceń. spawn / kill / send / clock - do testów."""

    def __init__(self, programs, send, spawn_fn=spawn, kill_fn=kill, clock=time.monotonic, guides_fn=None):
        self.programs = programs
        self.send = send
        self.guides_fn = guides_fn
        self.spawn_fn, self.kill_fn, self.clock = spawn_fn, kill_fn, clock

    def _targets(self, target):
        if target in (None, "all"):
            return list(self.programs.values())
        return [self.programs[target]] if target in self.programs else []

    def start(self, program):
        program.wanted = True
        if not program.running():
            program.proc = self.spawn_fn(program)
            program.started = self.clock()
            program.down_since = None

    def stop(self, program):
        program.wanted = False
        self.kill_fn(program.proc)
        program.proc = None
        try:
            _pid_file(program).unlink()
        except OSError:
            pass

    def status_lines(self):
        out = []
        for p in self.programs.values():
            if p.running():
                out.append(f"{p.name}: DZIAŁA od {_uptime(self.clock() - p.started)} (PID {p.proc.pid}, "
                           f"restartów {p.restarts})")
            else:
                out.append(f"{p.name}: zatrzymany" + (" - czekam na ponowne uruchomienie" if p.wanted else ""))
        if "sniper" not in self.programs:
            out.append("sniper: brak SNIPER_DIR w sniper/.env")
        return out

    async def handle(self, text, pin=""):
        action, target = parse(text, pin)
        if action is None:
            await self.send("Pilot: nie rozumiem", [f"„{(text or '')[:60]}”: {target}"] + HELP, priority=2)
            return None
        if action == "guides":
            lines = await self.guides_fn() if self.guides_fn else ["Wysyłanie wytycznych niedostępne."]
            await self.send("Pilot: wytyczne", lines)
            return action
        if action == "help":
            await self.send("Pilot: pomoc", HELP)
            return action
        if action == "status":
            await self.send("Pilot: status", self.status_lines())
            return action
        programs = self._targets(target)
        if not programs:
            await self.send("Pilot: nieznany program", [f"{target}: brak (sniper wymaga SNIPER_DIR)"], priority=2)
            return None
        if action == "log":
            await self.send(f"Pilot: log {target}", tail(programs[0].log_path))
            return action
        for p in programs:
            if action in ("stop", "restart"):
                self.stop(p)
            if action in ("start", "restart"):
                self.start(p)
        await self.send(f"Pilot: {action} {target}", self.status_lines())
        return action

    async def watchdog(self):
        """Włączony program, który się wyłączył → ponowne uruchomienie po RESTART_AFTER_S + powiadomienie."""
        now = self.clock()
        for p in self.programs.values():
            if not p.wanted or p.running():
                continue
            if p.down_since is None:
                p.down_since = now
                code = p.proc.poll() if p.proc is not None else None
                await self.send(f"Pilot: {p.name} się wyłączył (kod {code})",
                                [f"Uruchomię ponownie za {RESTART_AFTER_S} s. Ostatnie linie logu:"]
                                + tail(p.log_path, 6), priority=4, tags=("warning",))
            elif now - p.down_since >= RESTART_AFTER_S:
                p.restarts += 1
                self.start(p)
                log.info("[PILOT] %s uruchomiony ponownie (%d. raz).", p.name, p.restarts)


OWN_TITLES = ("Pilot", "Analyzer")


def is_own(event):
    """Wiadomość wysłana przez pilota / analizator (ma tytuł „Pilot: …” / „Analyzer: …”) - nie polecenie. Pozwala
    ustawić ANALYZER_NTFY_TOPIC = ANALYZER_CONTROL_TOPIC (odpowiedzi w tym samym temacie, jak czat) bez pętli."""
    return str(event.get("title") or "").startswith(OWN_TITLES)


def guide_files(cfg, sniper_dir=None):
    """Aktualne wytyczne: plik, którego używa Sniper (`SNIPER_DIR/sniper/guidelines.md`), i najnowsze wygenerowane
    z danych (`reports/<data>/guides/*.md`)."""
    files = []
    sniper_dir = sniper_dir if sniper_dir is not None else os.getenv("SNIPER_DIR", "").strip()
    if sniper_dir and (Path(sniper_dir) / "sniper" / "guidelines.md").exists():
        files.append(Path(sniper_dir) / "sniper" / "guidelines.md")
    reports = Path(cfg.db_path).parent / "reports"
    latest = sorted(p for p in reports.glob("*/guides") if p.is_dir()) if reports.exists() else []
    if latest:
        files += sorted(latest[-1].glob("*.md"))
    return files


async def export_guides(cfg, send_file, gdrive_dir=None, sniper_dir=None):
    """Polecenie „wytyczne”: kopia na Dysk Google (`ANALYZER_GDRIVE_DIR`, np. G:\\Mój dysk\\program - folder
    synchronizowany przez aplikację Dysk Google na serwerze) + plik Snipera jako załącznik ntfy na telefon."""
    import shutil

    files = guide_files(cfg, sniper_dir)
    if not files:
        return ["Brak plików wytycznych (SNIPER_DIR / python -m analyzer sniper-guide)."]
    lines = []
    gdrive_dir = gdrive_dir if gdrive_dir is not None else os.getenv("ANALYZER_GDRIVE_DIR", "").strip()
    if gdrive_dir:
        target = Path(gdrive_dir) / "wytyczne"
        try:
            target.mkdir(parents=True, exist_ok=True)
            for f in files:
                name = "sniper_guidelines.md" if f.name == "guidelines.md" else f.name
                shutil.copy2(f, target / name)
            lines.append(f"Dysk Google: {len(files)} plików → {target}")
        except OSError as exc:
            lines.append(f"Dysk Google: błąd kopiowania ({exc})")
    else:
        lines.append("Dysk Google: ustaw ANALYZER_GDRIVE_DIR w sniper/.env (np. G:\\Mój dysk\\program)")
    first = files[0]
    sent = await send_file(first, f"Pilot: {first.name}")
    lines.append(f"Na telefon: {first.name} ({'wysłany' if sent else 'nie wysłano'}) - kliknij załącznik powyżej")
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(first.stat().st_mtime))
    lines.append(f"{first.name}: zmieniony {stamp}")
    return lines


async def listen(server, topic, token, on_message, since=None):
    """Strumień wiadomości z tematu ntfy (/json), ze wznawianiem po zerwaniu połączenia. Bezpośrednio, bez proxy.

    since - od kiedy: znacznik czasu uniksowego (domyślnie start pilota) albo ID ostatniej wiadomości (po zerwaniu
    połączenia - nic nie ginie). ntfy NIE przyjmuje „since=now” (400 Bad Request - u użytkownika 2026-10-25)."""
    import httpx

    since = since or str(int(time.time()))

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    wait = 5
    while True:
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=httpx.Timeout(10.0, read=None)) as client:
                async with client.stream("GET", f"{server}/{topic}/json", params={"since": since},
                                         headers=headers) as response:
                    response.raise_for_status()
                    wait = 5
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                        event = json.loads(line)
                        if event.get("event") == "message":
                            since = event.get("id") or since
                            if is_own(event):
                                continue
                            await on_message(event.get("message") or "")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("[PILOT] Połączenie z ntfy zerwane (%r) - ponawiam za %d s.", exc, wait)
            await asyncio.sleep(wait)
            wait = min(wait * 2, 300)


async def main(cfg):
    from . import notify

    topic = os.getenv("ANALYZER_CONTROL_TOPIC", "").strip()
    if not topic:
        raise SystemExit("Ustaw ANALYZER_CONTROL_TOPIC (długi, losowy) w sniper/.env - patrz PILOT.md")
    server = (os.getenv("SNIPER_NTFY_SERVER") or "https://ntfy.sh").strip().rstrip("/")
    token = (os.getenv("SNIPER_NTFY_TOKEN") or "").strip()
    pin = os.getenv("ANALYZER_CONTROL_PIN", "").strip()
    async def reply(title, lines, **kw):          # odpowiedzi pilota - w tym samym temacie, w którym piszesz polecenia
        return await notify.send(title, lines, topic_name=topic, **kw)

    async def send_file(path, title):
        return await notify.send_file(path, title, topic_name=topic)

    controller = Controller(default_programs(cfg), reply, guides_fn=lambda: export_guides(cfg, send_file))
    for name in (x.strip() for x in os.getenv("ANALYZER_CONTROL_AUTOSTART", "").split(",") if x.strip()):
        if name in controller.programs:
            controller.start(controller.programs[name])
    await reply("Pilot: uruchomiony", controller.status_lines() + HELP)
    log.info("[PILOT] Nasłuchuję poleceń na temacie ntfy (z PIN-em: %s).", "tak" if pin else "nie")

    async def on_message(text):
        log.info("[PILOT] Polecenie: %s", text[:80])
        await controller.handle(text, pin)

    async def guard():
        while True:
            await asyncio.sleep(CHECK_EVERY_S)
            try:
                await controller.watchdog()
            except Exception:
                log.exception("[PILOT] Błąd strażnika.")

    try:
        await asyncio.gather(listen(server, topic, token, on_message), guard())
    finally:
        for program in controller.programs.values():
            if program.running():
                log.info("[PILOT] Zostawiam %s uruchomiony (PID %s).", program.name, program.proc.pid)
