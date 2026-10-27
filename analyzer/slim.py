"""Lekka kopia bazy do analizy przez Claude (2026-10-27): `python -m analyzer slim-db`.

Wszystkie tabele i indeksy analyzer.db BEZ surowych odpowiedzi API (`raw` - większość z ~1,3 GB) i nieużywanych
(`ai_cache`, `specs`) + tabele analysis.db (flagi, relisty, stan z AI) z przedrostkiem `a_`. Główna baza tylko do
odczytu (działa przy włączonym watch), kopiowanie strumieniowe tabela po tabeli, potem ZIP.
"""
import sqlite3
import zipfile
from pathlib import Path

from .progress import Bar

SKIP = {"raw", "ai_cache", "specs"}


def _tables(conn):
    return [(r[0], r[1]) for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")]


def _copy(src, out, name, sql, new_name=None, progress=True):
    new_name = new_name or name
    if new_name != name:
        sql = sql.replace(name, new_name, 1)
    out.execute(sql)
    cols = [r[1] for r in src.execute(f'PRAGMA table_info("{name}")')]
    total = src.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
    bar = Bar(f"{new_name:<16}", total) if progress and total else None
    cur, n = src.execute(f'SELECT * FROM "{name}"'), 0
    marks = ",".join("?" * len(cols))
    while True:
        rows = cur.fetchmany(5000)
        if not rows:
            break
        out.executemany(f'INSERT INTO "{new_name}" VALUES ({marks})', [tuple(r) for r in rows])
        n += len(rows)
        if bar:
            bar.update(n)
    if bar:
        bar.finish()
    out.commit()
    return n


def build(db_path, analysis_db, out_path, progress=True, say=print):
    out_path = Path(out_path)
    for p in (out_path, out_path.with_suffix(".zip")):
        if p.exists():
            p.unlink()
    src = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    out = sqlite3.connect(str(out_path))
    out.execute("PRAGMA journal_mode=OFF")
    out.execute("PRAGMA synchronous=OFF")
    counts = {}
    for name, sql in _tables(src):
        if name not in SKIP:
            counts[name] = _copy(src, out, name, sql, progress=progress)
    for (sql,) in src.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
        if not any(f" {t}(" in sql or f" {t} (" in sql for t in SKIP):
            out.execute(sql)
    src.close()
    if analysis_db and Path(analysis_db).exists():
        a = sqlite3.connect(Path(analysis_db).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
        for name, sql in _tables(a):
            counts["a_" + name] = _copy(a, out, name, sql, "a_" + name, progress)
        a.close()
    out.commit()
    out.execute("VACUUM")
    out.close()
    say("Pakuję do ZIP ...")
    with zipfile.ZipFile(out_path.with_suffix(".zip"), "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(out_path, out_path.name)
    return counts
