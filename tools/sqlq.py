#!/usr/bin/env python3
"""本地 SQLite 只读查询小工具。

用法：
  .venv/bin/python tools/sqlq.py
  .venv/bin/python tools/sqlq.py -c "SELECT * FROM llm_usage ORDER BY created_at DESC LIMIT 20"
  .venv/bin/python tools/sqlq.py -d market -c ".tables"
  .venv/bin/python tools/sqlq.py path/to/other.db

交互里可用：
  .tables / .schema [table] / .db / .quit
  或直接写 SQL（以分号结束；多行可续写）
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

# repo root on sys.path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.config import get_settings  # noqa: E402


def resolve_db(name_or_path: str) -> Path:
    s = get_settings()
    key = name_or_path.strip().lower()
    if key in ("app", "a"):
        return Path(s.app_db_path)
    if key in ("market", "m"):
        return Path(s.market_db_path)
    p = Path(name_or_path).expanduser()
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    return p


def connect_ro(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"数据库不存在: {path}")
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def print_rows(rows: list[sqlite3.Row], *, max_cell: int = 80) -> None:
    if not rows:
        print("(0 rows)")
        return
    cols = list(rows[0].keys())

    def cell(v: object) -> str:
        if v is None:
            s = "NULL"
        else:
            s = str(v).replace("\n", "\\n")
        if len(s) > max_cell:
            s = s[: max_cell - 1] + "…"
        return s

    data = [[cell(r[c]) for c in cols] for r in rows]
    widths = [len(c) for c in cols]
    for row in data:
        for i, v in enumerate(row):
            widths[i] = max(widths[i], len(v))

    def fmt(parts: list[str]) -> str:
        return " | ".join(p.ljust(widths[i]) for i, p in enumerate(parts))

    print(fmt(cols))
    print("-+-".join("-" * w for w in widths))
    for row in data:
        print(fmt(row))
    print(f"({len(rows)} rows)")


def run_sql(conn: sqlite3.Connection, sql: str) -> None:
    sql = sql.strip()
    if not sql:
        return
    if sql.endswith(";"):
        sql = sql[:-1].strip()
    cur = conn.execute(sql)
    if cur.description is None:
        print("(ok, no result set)")
        return
    rows = cur.fetchall()
    print_rows(rows)


def handle_meta(conn: sqlite3.Connection, line: str, db_path: Path) -> bool:
    """Return True if handled as meta command."""
    parts = line.strip().split()
    cmd = parts[0].lower()
    if cmd in (".quit", ".exit", "quit", "exit"):
        raise SystemExit(0)
    if cmd == ".db":
        print(db_path)
        return True
    if cmd == ".tables":
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        print("\n".join(r[0] for r in rows) or "(no tables)")
        return True
    if cmd == ".schema":
        if len(parts) >= 2:
            name = parts[1].replace("'", "''")
            rows = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type IN ('table','index') "
                "AND name=? COLLATE NOCASE",
                (name,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
        for r in rows:
            if r[0]:
                print(r[0] + ";")
        return True
    if cmd == ".help":
        print(
            "命令: .tables  .schema [表]  .db  .quit\n"
            "SQL 以分号结束；只读连接，不能写库。"
        )
        return True
    return False


def repl(conn: sqlite3.Connection, db_path: Path) -> None:
    print(f"Aletheia SQL (只读) — {db_path}")
    print("输入 .help 看命令；SQL 以 ; 结束。Ctrl-D 退出。")
    buf: list[str] = []
    while True:
        try:
            prompt = "... " if buf else "sql> "
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not buf and line.strip().startswith("."):
            if handle_meta(conn, line, db_path):
                continue
        if not buf and line.strip().lower() in ("quit", "exit"):
            break
        buf.append(line)
        text = "\n".join(buf)
        if ";" not in text:
            continue
        sql = text
        buf = []
        try:
            run_sql(conn, sql)
        except sqlite3.Error as e:
            print(f"error: {e}")


def main() -> None:
    p = argparse.ArgumentParser(description="Aletheia 本地 SQLite 只读查询")
    p.add_argument(
        "-d",
        "--db",
        default="app",
        help="app | market | 或文件路径（默认 app）",
    )
    p.add_argument("-c", "--command", help="执行一条 SQL 或 .tables/.schema 后退出")
    p.add_argument(
        "path",
        nargs="?",
        help="可选：直接指定 db 路径（覆盖 -d）",
    )
    args = p.parse_args()
    db_path = resolve_db(args.path or args.db)
    conn = connect_ro(db_path)
    try:
        if args.command:
            cmd = args.command.strip()
            if cmd.startswith("."):
                handle_meta(conn, cmd, db_path)
            else:
                run_sql(conn, cmd if cmd.endswith(";") else cmd + ";")
        else:
            repl(conn, db_path)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
