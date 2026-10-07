"""Заявки из виджета: проверка, сохранение в SQLite, уведомление менеджеру в Telegram."""
import html
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import aiohttp

DB = Path(os.getenv("LEADS_DB") or Path(__file__).parent / "leads.db")


def normalize_phone(raw: str) -> str | None:
    """Любой российский формат → +7XXXXXXXXXX; мусор → None."""
    d = re.sub(r"\D", "", raw or "")
    if len(d) == 11 and d[0] in "78":
        return "+7" + d[1:]
    if len(d) == 10 and d[0] == "9":
        return "+7" + d
    return None


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB)
    c.execute("""create table if not exists leads (
        id integer primary key, created_at text, name text, phone text, need text, dialog text, page text)""")
    return c


def save(name: str, phone: str, need: str, dialog: str, page: str) -> int:
    with _conn() as c:
        cur = c.execute("insert into leads (created_at, name, phone, need, dialog, page) values (?,?,?,?,?,?)",
                        (datetime.now().isoformat(timespec="seconds"), name, phone, need, dialog, page))
        return cur.lastrowid


def count() -> int:
    with _conn() as c:
        return c.execute("select count(*) from leads").fetchone()[0]


async def notify(lead_id: int, name: str, phone: str, need: str, dialog: str, page: str) -> bool:
    """Менеджеру в Telegram: заявка + последние реплики диалога (видно, о чём человек спрашивал)."""
    token, chat = os.getenv("BOT_TOKEN"), os.getenv("ADMIN_ID")
    if not token or not chat:
        return False
    e = html.escape
    text = (f"<b>🧱 Заявка с сайта №{lead_id}</b>\n{e(name)} · {e(phone)}\n"
            + (f"📝 {e(need)}\n" if need else "")
            + (f"\n<b>Диалог с ассистентом:</b>\n{e(dialog[-1500:])}\n" if dialog else "")
            + (f"\n🔗 {e(page)}" if page else ""))
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": chat, "text": text, "parse_mode": "HTML",
                                    "disable_web_page_preview": True}) as r:
                return r.status == 200
    except (aiohttp.ClientError, TimeoutError):
        return False   # заявка уже в базе — уведомление вторично, посетителю ошибку не показываем
