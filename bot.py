import asyncio
import html
import json
import logging
import os
import random
import re
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# Telethon bo'lmasa avtomatik o'rnatish (foydalanuvchi qo'lda pip install yozishi shart emas)
def _ensure_telethon() -> None:
    try:
        import telethon  # noqa: F401
    except ImportError:
        print("⏳ Telethon o'rnatilmoqda (profil ulash uchun zarur)...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "telethon>=1.36.0"]
        )
        print("✅ Telethon muvaffaqiyatli o'rnatildi!")


_ensure_telethon()

from telethon import TelegramClient  # noqa: E402
from telethon.errors import (  # noqa: E402
    AuthKeyUnregisteredError,
    ChannelPrivateError,
    ChatAdminRequiredError,
    ChatRestrictedError,
    ChatWriteForbiddenError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
    SlowModeWaitError,
    UserBannedInChannelError,
    UserDeactivatedBanError,
)
from telethon.sessions import StringSession  # noqa: E402
from telethon.tl.functions.account import GetPasswordRequest  # noqa: E402
from telethon.tl.types import Channel, Chat  # noqa: E402
from telethon.utils import get_peer_id  # noqa: E402

# ==============================================================================
# 1. SOZLAMALAR (CONFIGURATION)
# ==============================================================================
BASE_DIR = Path(__file__).resolve().parent


def _load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_env_file(BASE_DIR / ".env")

BOT_TOKEN: str = os.getenv(
    "BOT_TOKEN", "9175887544:AAGRYVXTg08dFx1gyou35jJxlPEyMMDipwo"
).strip()
_raw_admins: str = os.getenv("ADMIN_IDS", "7552962971")
ADMIN_IDS: List[int] = [
    int(x.strip()) for x in _raw_admins.split(",") if x.strip().isdigit()
]

# Telegram profil ulash (SMS / QR) uchun my.telegram.org dan olingan API_ID va API_HASH:
API_ID: int = int(os.getenv("API_ID", "0").strip() or "0")
API_HASH: str = os.getenv("API_HASH", "YOUR_API_HASH_HERE").strip()

TIMEZONE_OFFSET: int = int(os.getenv("TIMEZONE_OFFSET", "5"))
TZ = timezone(timedelta(hours=TIMEZONE_OFFSET))

DB_PATH = BASE_DIR / "autoxabar.db"
MEDIA_DIR = BASE_DIR / "media_cache"
MEDIA_DIR.mkdir(exist_ok=True)

# Bloklangan foydalanuvchiga yuboriladigan xabar matni
BLOCKED_USER_TEXT = (
    "🚫 <b>Kirish rad etildi</b>\n\n"
    "Afsuski, administrator tomonidan sizning botdan foydalanish so'rovingiz "
    "rad etildi va hisobingiz bloklandi.\n\n"
    "Shu sababli botning imkoniyatlaridan foydalana olmaysiz. "
    "Agar bu holatni xatolik deb hisoblasangiz, iltimos administrator bilan bog'laning."
)

PENDING_USER_TEXT = (
    "⏳ <b>So'rovingiz adminga yuborildi!</b>\n\n"
    "Botdan foydalanish uchun administrator tasdiqlashi talab etiladi. "
    "So'rovingiz ko'rib chiqilgach, natija haqida sizga shu yerda xabar beriladi.\n\n"
    "✨ <i>Tasdiqlangan barcha foydalanuvchilar uchun hamma funksiya 100% bepul!</i>"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("AutoXabarBot")


def now_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def esc(val: Any) -> str:
    return html.escape(str(val or ""))


def apply_spintax(text: str) -> str:
    """{variant1|variant2} ko'rinishidagi spintaxni tasodifiy tanlaydi."""
    pattern = re.compile(r"\{([^{}]+)\}")
    while True:
        m = pattern.search(text)
        if not m:
            break
        text = text[: m.start()] + random.choice(m.group(1).split("|")) + text[m.end() :]
    return text


# ==============================================================================
# 2. KUTUBXONASIZ TELEGRAM BOT API MIJOZI (URLLIB + ASYNCIO)
# ==============================================================================
class BotAPIError(Exception):
    def __init__(self, code: int, description: str):
        super().__init__(f"[{code}] {description}")
        self.code = code
        self.description = description


class BotAPI:
    def __init__(self, token: str) -> None:
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}/"
        self.file_url = f"https://api.telegram.org/file/bot{token}/"

    def _call_sync(
        self, method: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 35
    ) -> Any:
        data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + method,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                desc = json.loads(raw).get("description", raw)
            except Exception:
                desc = raw
            raise BotAPIError(e.code, desc) from None
        except urllib.error.URLError as e:
            raise BotAPIError(0, f"Tarmoq xatosi: {e.reason}") from None
        if not body.get("ok"):
            raise BotAPIError(body.get("error_code", 0), body.get("description", "Xato"))
        return body.get("result")

    async def call(
        self, method: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 35
    ) -> Any:
        return await asyncio.to_thread(self._call_sync, method, payload, timeout)

    async def get_me(self) -> Dict[str, Any]:
        return await self.call("getMe")

    async def get_updates(self, offset: int, timeout: int = 25) -> List[Dict[str, Any]]:
        return await self.call(
            "getUpdates",
            {
                "offset": offset,
                "timeout": timeout,
                "allowed_updates": ["message", "callback_query"],
            },
            timeout=timeout + 10,
        )

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self.call("sendMessage", payload)

    async def send_photo(
        self,
        chat_id: int,
        photo: str,
        caption: str = "",
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "photo": photo,
            "parse_mode": "HTML",
        }
        if caption:
            payload["caption"] = caption
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return await self.call("sendPhoto", payload)

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
    ) -> Any:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            return await self.call("editMessageText", payload)
        except BotAPIError as e:
            if "message is not modified" in e.description.lower():
                return None
            raise

    async def delete_message(self, chat_id: int, message_id: int) -> None:
        try:
            await self.call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        except BotAPIError:
            pass

    async def answer_callback(
        self, cid: str, text: str = "", show_alert: bool = False
    ) -> None:
        try:
            await self.call(
                "answerCallbackQuery",
                {"callback_query_id": cid, "text": text, "show_alert": show_alert},
            )
        except BotAPIError:
            pass

    async def copy_message(self, chat_id: int, from_chat_id: int, message_id: int) -> Any:
        return await self.call(
            "copyMessage",
            {"chat_id": chat_id, "from_chat_id": from_chat_id, "message_id": message_id},
        )

    async def download_file(self, file_id: str, dest: Path) -> Path:
        info = await self.call("getFile", {"file_id": file_id})
        url = self.file_url + info["file_path"]

        def _dl() -> None:
            with urllib.request.urlopen(url, timeout=60) as r:
                dest.write_bytes(r.read())

        await asyncio.to_thread(_dl)
        return dest


# ==============================================================================
# 3. MA'LUMOTLAR BAZASI (SQLITE3)
# ==============================================================================
class Database:
    def __init__(self, path: Path) -> None:
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA foreign_keys=ON;")
        self._init_tables()

    def _init_tables(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                full_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending', -- pending | approved | blocked
                total_sent INTEGER NOT NULL DEFAULT 0,
                total_failed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                phone TEXT NOT NULL,
                account_name TEXT NOT NULL,
                account_username TEXT NOT NULL DEFAULT '',
                session_string TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'paused', -- running | paused | error
                error_text TEXT,
                interval_minutes INTEGER NOT NULL DEFAULT 15,
                delay_min INTEGER NOT NULL DEFAULT 3,
                delay_max INTEGER NOT NULL DEFAULT 7,
                work_start_hour INTEGER NOT NULL DEFAULT 0,
                work_end_hour INTEGER NOT NULL DEFAULT 24,
                sent_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                last_sent_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                is_selected INTEGER NOT NULL DEFAULT 1,
                is_blacklisted INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                UNIQUE(account_id, chat_id),
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                media_type TEXT NOT NULL DEFAULT 'none', -- none | photo | video
                media_path TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE
            );
            """
        )
        self.conn.commit()

    # --- Users ---
    def get_user(self, uid: int) -> Optional[Dict[str, Any]]:
        r = self.conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
        return dict(r) if r else None

    def upsert_user(
        self, uid: int, username: str, full_name: str, status: str
    ) -> Tuple[Dict[str, Any], bool]:
        existing = self.get_user(uid)
        ts = now_str()
        if existing is None:
            self.conn.execute(
                "INSERT INTO users (user_id, username, full_name, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, username, full_name, status, ts, ts),
            )
            self.conn.commit()
            return self.get_user(uid), True  # type: ignore
        self.conn.execute(
            "UPDATE users SET username = ?, full_name = ?, updated_at = ? WHERE user_id = ?",
            (username, full_name, ts, uid),
        )
        self.conn.commit()
        return self.get_user(uid), False  # type: ignore

    def set_user_status(self, uid: int, status: str) -> None:
        self.conn.execute(
            "UPDATE users SET status = ?, updated_at = ? WHERE user_id = ?",
            (status, now_str(), uid),
        )
        self.conn.commit()

    def list_users_by_status(self, status: str, limit: int = 25) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM users WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_approved_ids(self) -> List[int]:
        return [
            r["user_id"]
            for r in self.conn.execute("SELECT user_id FROM users WHERE status='approved'")
        ]

    def get_global_stats(self) -> Dict[str, int]:
        c = self.conn
        return {
            "u_total": c.execute("SELECT COUNT(*) FROM users").fetchone()[0],
            "u_approved": c.execute("SELECT COUNT(*) FROM users WHERE status='approved'").fetchone()[0],
            "u_pending": c.execute("SELECT COUNT(*) FROM users WHERE status='pending'").fetchone()[0],
            "u_blocked": c.execute("SELECT COUNT(*) FROM users WHERE status='blocked'").fetchone()[0],
            "acc_total": c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0],
            "acc_run": c.execute("SELECT COUNT(*) FROM accounts WHERE status='running'").fetchone()[0],
            "grp_total": c.execute("SELECT COUNT(*) FROM groups").fetchone()[0],
            "sent_sum": c.execute("SELECT COALESCE(SUM(total_sent), 0) FROM users").fetchone()[0],
            "fail_sum": c.execute("SELECT COALESCE(SUM(total_failed), 0) FROM users").fetchone()[0],
        }

    # --- Accounts ---
    def add_account(
        self, uid: int, phone: str, name: str, username: str, session_str: str
    ) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO accounts (user_id, phone, account_name, account_username, session_string, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (uid, phone, name, username, session_str, now_str()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_user_accounts(self, uid: int) -> List[Dict[str, Any]]:
        return [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM accounts WHERE user_id = ? ORDER BY id ASC", (uid,)
            )
        ]

    def get_account(self, aid: int) -> Optional[Dict[str, Any]]:
        r = self.conn.execute("SELECT * FROM accounts WHERE id = ?", (aid,)).fetchone()
        return dict(r) if r else None

    def get_running_accounts(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT a.* FROM accounts a
            JOIN users u ON u.user_id = a.user_id
            WHERE a.status = 'running' AND u.status = 'approved'
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def set_account_status(
        self, aid: int, status: str, error_text: Optional[str] = None
    ) -> None:
        self.conn.execute(
            "UPDATE accounts SET status = ?, error_text = ? WHERE id = ?",
            (status, error_text, aid),
        )
        self.conn.commit()

    def pause_user_accounts(self, uid: int) -> List[int]:
        ids = [
            r["id"]
            for r in self.conn.execute("SELECT id FROM accounts WHERE user_id = ?", (uid,))
        ]
        self.conn.execute("UPDATE accounts SET status = 'paused' WHERE user_id = ?", (uid,))
        self.conn.commit()
        return ids

    def update_account_settings(self, aid: int, **kwargs: Any) -> None:
        allowed = {
            "interval_minutes",
            "delay_min",
            "delay_max",
            "work_start_hour",
            "work_end_hour",
        }
        upd = {k: v for k, v in kwargs.items() if k in allowed}
        if not upd:
            return
        cols = ", ".join(f"{k} = ?" for k in upd)
        self.conn.execute(f"UPDATE accounts SET {cols} WHERE id = ?", list(upd.values()) + [aid])
        self.conn.commit()

    def delete_account(self, aid: int) -> None:
        self.conn.execute("DELETE FROM accounts WHERE id = ?", (aid,))
        self.conn.commit()

    def record_send(self, aid: int, uid: int, ok: bool) -> None:
        if ok:
            self.conn.execute(
                "UPDATE accounts SET sent_count = sent_count + 1, last_sent_at = ? WHERE id = ?",
                (now_str(), aid),
            )
            self.conn.execute(
                "UPDATE users SET total_sent = total_sent + 1 WHERE user_id = ?", (uid,)
            )
        else:
            self.conn.execute(
                "UPDATE accounts SET failed_count = failed_count + 1 WHERE id = ?", (aid,)
            )
            self.conn.execute(
                "UPDATE users SET total_failed = total_failed + 1 WHERE user_id = ?", (uid,)
            )
        self.conn.commit()

    # --- Groups ---
    def upsert_group(self, aid: int, chat_id: int, title: str, username: str = "") -> None:
        self.conn.execute(
            """
            INSERT INTO groups (account_id, chat_id, title, username, is_selected, is_blacklisted)
            VALUES (?, ?, ?, ?, 1, 0)
            ON CONFLICT(account_id, chat_id) DO UPDATE SET
                title = excluded.title,
                username = excluded.username
            """,
            (aid, chat_id, title, username),
        )
        self.conn.commit()

    def get_groups(self, aid: int, only_sendable: bool = False) -> List[Dict[str, Any]]:
        if only_sendable:
            q = "SELECT * FROM groups WHERE account_id = ? AND is_selected = 1 AND is_blacklisted = 0 ORDER BY title ASC"
        else:
            q = "SELECT * FROM groups WHERE account_id = ? ORDER BY is_blacklisted ASC, title ASC"
        return [dict(r) for r in self.conn.execute(q, (aid,))]

    def toggle_group(self, gid: int) -> None:
        self.conn.execute(
            "UPDATE groups SET is_selected = CASE WHEN is_selected = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (gid,),
        )
        self.conn.commit()

    def select_all_groups(self, aid: int, sel: bool) -> None:
        self.conn.execute(
            "UPDATE groups SET is_selected = ? WHERE account_id = ? AND is_blacklisted = 0",
            (1 if sel else 0, aid),
        )
        self.conn.commit()

    def blacklist_group(self, gid: int, reason: str) -> None:
        self.conn.execute(
            "UPDATE groups SET is_blacklisted = 1, last_error = ? WHERE id = ?",
            (reason[:200], gid),
        )
        self.conn.commit()

    def reset_blacklist(self, aid: int) -> int:
        cur = self.conn.execute(
            "UPDATE groups SET is_blacklisted = 0, last_error = NULL WHERE account_id = ? AND is_blacklisted = 1",
            (aid,),
        )
        self.conn.commit()
        return cur.rowcount

    # --- Messages ---
    def add_message(
        self, aid: int, text: str, media_type: str = "none", media_path: Optional[str] = None
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages (account_id, text, media_type, media_path, is_active, created_at) VALUES (?, ?, ?, ?, 1, ?)",
            (aid, text, media_type, media_path, now_str()),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_messages(self, aid: int, only_active: bool = False) -> List[Dict[str, Any]]:
        q = (
            "SELECT * FROM messages WHERE account_id = ? AND is_active = 1 ORDER BY id ASC"
            if only_active
            else "SELECT * FROM messages WHERE account_id = ? ORDER BY id DESC"
        )
        return [dict(r) for r in self.conn.execute(q, (aid,))]

    def toggle_message(self, mid: int) -> None:
        self.conn.execute(
            "UPDATE messages SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?",
            (mid,),
        )
        self.conn.commit()

    def delete_message(self, mid: int) -> None:
        r = self.conn.execute("SELECT media_path FROM messages WHERE id = ?", (mid,)).fetchone()
        if r and r["media_path"]:
            try:
                Path(r["media_path"]).unlink(missing_ok=True)
            except OSError:
                pass
        self.conn.execute("DELETE FROM messages WHERE id = ?", (mid,))
        self.conn.commit()


# ==============================================================================
# 4. TELETHON PROFIL VA AVTO-E'LON TARQATUVCHI MENEJER
# ==============================================================================
class ProfileManager:
    def __init__(self, api: BotAPI, db: Database) -> None:
        self.api = api
        self.db = db
        self.clients: Dict[int, TelegramClient] = {}
        self.tasks: Dict[int, asyncio.Task] = {}
        # Login jarayonlari: user_id -> dict(client, phone, phone_code_hash, qr_task)
        self.pending_logins: Dict[int, Dict[str, Any]] = {}

    async def get_client(self, aid: int) -> Optional[TelegramClient]:
        acc = self.db.get_account(aid)
        if not acc:
            return None
        client = self.clients.get(aid)
        if client and client.is_connected():
            return client
        client = TelegramClient(StringSession(acc["session_string"]), API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return None
        self.clients[aid] = client
        return client

    async def sync_groups(self, aid: int) -> Tuple[int, str]:
        client = await self.get_client(aid)
        if not client:
            self.db.set_account_status(aid, "error", "Sessiya uzilgan")
            return 0, "Sessiya muddati tugagan. Profilni qayta ulang."
        cnt = 0
        async for dialog in client.iter_dialogs():
            ent = dialog.entity
            is_grp = isinstance(ent, Chat) or (
                isinstance(ent, Channel) and getattr(ent, "megagroup", False)
            )
            if is_grp:
                self.db.upsert_group(
                    aid, dialog.id, dialog.title or "Nomsiz guruh", getattr(ent, "username", "") or ""
                )
                cnt += 1
        return cnt, "OK"

    async def add_group_by_link(self, aid: int, target: str) -> Tuple[bool, str]:
        client = await self.get_client(aid)
        if not client:
            return False, "❌ Profil sessiyasi ulanmadi."
        try:
            ent = await client.get_entity(target.strip())
            title = getattr(ent, "title", None) or target
            uname = getattr(ent, "username", "") or ""
            self.db.upsert_group(aid, int(get_peer_id(ent)), title, uname)
            return True, f"✅ <b>{esc(title)}</b> guruhi ro'yxatga qo'shildi!"
        except Exception as e:
            return False, f"❌ Guruh topilmadi: <code>{esc(e)}</code>"

    async def start_account(self, aid: int) -> Tuple[bool, str]:
        acc = self.db.get_account(aid)
        if not acc:
            return False, "Profil topilmadi."
        if not self.db.get_messages(aid, only_active=True):
            return False, "❌ Avval 💬 Xabar bo'limida e'lon matnini qo'shing!"
        if not self.db.get_groups(aid, only_sendable=True):
            return False, "❌ Kamida 1 ta tanlangan guruh bo'lishi kerak!"

        self.db.set_account_status(aid, "running")
        if aid in self.tasks and not self.tasks[aid].done():
            return True, "✅ Allaqachon ishlamoqda!"
        self.tasks[aid] = asyncio.create_task(self._worker(aid))
        return True, f"🚀 <b>{esc(acc['account_name'])}</b> e'lon tarqatishni boshladi!"

    async def stop_account(self, aid: int) -> None:
        self.db.set_account_status(aid, "paused")
        t = self.tasks.pop(aid, None)
        if t and not t.done():
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def disconnect_account(self, aid: int) -> None:
        await self.stop_account(aid)
        c = self.clients.pop(aid, None)
        if c:
            try:
                await c.disconnect()
            except Exception:
                pass

    async def cancel_pending_login(self, uid: int) -> None:
        info = self.pending_logins.pop(uid, None)
        if not info:
            return
        qr_t = info.get("qr_task")
        if qr_t and not qr_t.done():
            qr_t.cancel()
        try:
            await info["client"].disconnect()
        except Exception:
            pass

    async def resume_all(self) -> None:
        for acc in self.db.get_running_accounts():
            aid = acc["id"]
            if aid not in self.tasks or self.tasks[aid].done():
                self.tasks[aid] = asyncio.create_task(self._worker(aid))

    async def shutdown(self) -> None:
        for aid in list(self.tasks.keys()):
            t = self.tasks.pop(aid, None)
            if t and not t.done():
                t.cancel()
        for c in list(self.clients.values()):
            try:
                await c.disconnect()
            except Exception:
                pass
        self.clients.clear()

    async def _worker(self, aid: int) -> None:
        try:
            while True:
                acc = self.db.get_account(aid)
                if not acc or acc["status"] != "running":
                    break
                user = self.db.get_user(acc["user_id"])
                if not user or user["status"] != "approved":
                    self.db.set_account_status(aid, "paused")
                    break

                cur_h = datetime.now(TZ).hour
                sh, eh = acc["work_start_hour"], acc["work_end_hour"]
                in_hours = (sh <= cur_h < eh) if sh <= eh else (cur_h >= sh or cur_h < eh)
                if not in_hours:
                    await asyncio.sleep(60)
                    continue

                msgs = self.db.get_messages(aid, only_active=True)
                groups = self.db.get_groups(aid, only_sendable=True)
                if not msgs or not groups:
                    await asyncio.sleep(60)
                    continue

                client = await self.get_client(aid)
                if not client:
                    self.db.set_account_status(aid, "error", "Sessiya uzildi")
                    try:
                        await self.api.send_message(
                            acc["user_id"],
                            f"🔴 <b>{esc(acc['account_name'])}</b> sessiyasi uzildi. Profilni qayta ulang.",
                        )
                    except BotAPIError:
                        pass
                    break

                chosen = random.choice(msgs)
                text = apply_spintax(chosen["text"] or "")
                mtype = chosen["media_type"]
                mpath = chosen["media_path"]

                for g in groups:
                    fresh = self.db.get_account(aid)
                    if not fresh or fresh["status"] != "running":
                        return
                    try:
                        if mtype in ("photo", "video") and mpath and os.path.exists(mpath):
                            await client.send_file(
                                g["chat_id"], file=mpath, caption=text or None, parse_mode="html"
                            )
                        else:
                            await client.send_message(
                                g["chat_id"], text, parse_mode="html", link_preview=False
                            )
                        self.db.record_send(aid, acc["user_id"], True)

                    except FloodWaitError as e:
                        wait_s = int(e.seconds) + 3
                        if wait_s > 600:
                            self.db.set_account_status(aid, "error", f"FloodWait {wait_s}s")
                            try:
                                await self.api.send_message(
                                    acc["user_id"],
                                    f"⏳ <b>{esc(acc['account_name'])}</b> profilida FloodWait ({wait_s}s). "
                                    "Xavfsizlik uchun to'xtatildi.",
                                )
                            except BotAPIError:
                                pass
                            return
                        await asyncio.sleep(wait_s)

                    except SlowModeWaitError:
                        self.db.record_send(aid, acc["user_id"], False)

                    except (
                        ChatWriteForbiddenError,
                        ChannelPrivateError,
                        UserBannedInChannelError,
                        ChatRestrictedError,
                        ChatAdminRequiredError,
                    ) as e:
                        self.db.blacklist_group(g["id"], type(e).__name__)
                        self.db.record_send(aid, acc["user_id"], False)

                    except (AuthKeyUnregisteredError, UserDeactivatedBanError):
                        self.db.set_account_status(aid, "error", "Sessiya bekor qilindi")
                        return

                    except Exception as e:
                        logger.warning("Yuborishda xato (acc=%d, chat=%d): %s", aid, g["chat_id"], e)
                        self.db.record_send(aid, acc["user_id"], False)

                    dmin = max(1, fresh["delay_min"])
                    dmax = max(dmin + 1, fresh["delay_max"])
                    await asyncio.sleep(random.uniform(dmin, dmax))

                fresh = self.db.get_account(aid)
                await asyncio.sleep(max(1, (fresh["interval_minutes"] if fresh else 15)) * 60)
        except asyncio.CancelledError:
            raise


# ==============================================================================
# 5. KLAVIATURALAR (@AutoXabarBot USLUBIDA)
# ==============================================================================
def main_menu_kb(uid: int) -> Dict[str, Any]:
    rows = [
        [{"text": "👥 Profillar"}, {"text": "📊 Statistika"}],
        [{"text": "💬 Xabar"}, {"text": "📋 Guruhlar"}],
        [{"text": "▶️ Ishga tushirish"}, {"text": "⏱ Interval"}],
    ]
    if uid in ADMIN_IDS:
        rows.append([{"text": "👑 Admin panel"}])
    return {"keyboard": rows, "resize_keyboard": True}


def share_contact_kb() -> Dict[str, Any]:
    return {
        "keyboard": [
            [{"text": "📱 Share contact", "request_contact": True}],
            [{"text": "⬅️ Asosiy menyu"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": True,
    }


def remove_kb() -> Dict[str, Any]:
    return {"remove_keyboard": True}


def inline_kb(rows: List[List[Tuple[str, str]]]) -> Dict[str, Any]:
    return {
        "inline_keyboard": [
            [{"text": label, "callback_data": data} for label, data in row]
            for row in rows
        ]
    }


def admin_approval_kb(uid: int) -> Dict[str, Any]:
    return inline_kb(
        [[("✅ Ha, kirgizish", f"adm_approve:{uid}"), ("🚫 Bloklash", f"adm_block:{uid}")]]
    )


def status_dot(status: str) -> str:
    return {"running": "🟢", "paused": "🟡", "error": "🔴"}.get(status, "🟡")


# ==============================================================================
# 6. BOT KONTROLLERI
# ==============================================================================
class AutoXabarBot:
    def __init__(self, token: str) -> None:
        self.api = BotAPI(token)
        self.db = Database(DB_PATH)
        self.pm = ProfileManager(self.api, self.db)
        # user_id -> dict(step=..., account_id=...)
        self.states: Dict[int, Dict[str, Any]] = {}

    async def run(self) -> None:
        me = await self.api.get_me()
        logger.info("AutoXabarBot ishga tushdi: @%s | Adminlar: %s", me.get("username"), ADMIN_IDS)
        await self.pm.resume_all()

        offset = 0
        try:
            while True:
                try:
                    updates = await self.api.get_updates(offset=offset, timeout=25)
                    for upd in updates:
                        offset = upd["update_id"] + 1
                        asyncio.create_task(self._safe_handle(upd))
                except BotAPIError as e:
                    logger.warning("Polling xatosi: %s", e)
                    await asyncio.sleep(3)
                except Exception as e:
                    logger.exception("Kutilmagan polling xatosi: %s", e)
                    await asyncio.sleep(3)
        finally:
            await self.pm.shutdown()

    async def _safe_handle(self, upd: Dict[str, Any]) -> None:
        try:
            if "callback_query" in upd:
                await self._handle_callback(upd["callback_query"])
            elif "message" in upd:
                await self._handle_message(upd["message"])
        except Exception as e:
            logger.exception("Update qayta ishlashda xato: %s", e)

    # --- Kirish nazorati ---
    async def _check_access(
        self, from_user: Dict[str, Any], is_start: bool = False, cid: Optional[str] = None
    ) -> bool:
        uid = from_user["id"]
        uname = from_user.get("username") or ""
        fname = " ".join(filter(None, [from_user.get("first_name"), from_user.get("last_name")])) or str(uid)

        if uid in ADMIN_IDS:
            ex = self.db.get_user(uid)
            if not ex:
                self.db.upsert_user(uid, uname, fname, "approved")
            elif ex["status"] != "approved":
                self.db.set_user_status(uid, "approved")
            return True

        if is_start:
            return True

        row = self.db.get_user(uid)
        if row is None:
            if cid:
                await self.api.answer_callback(cid, "Avval /start bosing.", show_alert=True)
            else:
                await self.api.send_message(uid, "Botdan foydalanish uchun avval /start buyrug'ini bosing.")
            return False

        if row["status"] == "blocked":
            if cid:
                await self.api.answer_callback(cid, "Siz bloklangansiz!", show_alert=True)
            else:
                await self.api.send_message(uid, BLOCKED_USER_TEXT, reply_markup=remove_kb())
            return False

        if row["status"] == "pending":
            if cid:
                await self.api.answer_callback(cid, "So'rovingiz hali tasdiqlanmagan.", show_alert=True)
            else:
                await self.api.send_message(
                    uid, "⏳ So'rovingiz hali ko'rib chiqilmoqda. Administrator tasdiqlashini kuting."
                )
            return False

        return True

    async def _notify_admins_new_user(self, u: Dict[str, Any]) -> None:
        uname = f"@{u['username']}" if u["username"] else "Mavjud emas"
        text = (
            "🔔 <b>Yangi foydalanuvchi so'rovi!</b>\n\n"
            f"👤 <b>Ism:</b> {esc(u['full_name'])}\n"
            f"🔗 <b>Username:</b> {esc(uname)}\n"
            f"🆔 <b>ID:</b> <code>{u['user_id']}</code>\n"
            f"🕒 <b>Vaqt:</b> {esc(u['created_at'])}\n\n"
            "❓ <b>Foydalanuvchini botga kirgizasizmi?</b>"
        )
        kb = admin_approval_kb(u["user_id"])
        for aid in ADMIN_IDS:
            try:
                await self.api.send_message(aid, text, reply_markup=kb)
            except BotAPIError as e:
                logger.warning("Adminga (%d) xabar ketmadi: %s", aid, e)

    # --- Xabarlar ---
    async def _handle_message(self, msg: Dict[str, Any]) -> None:
        if (msg.get("chat") or {}).get("type") != "private":
            return
        from_user = msg.get("from") or {}
        uid = from_user.get("id")
        if not uid:
            return

        text = (msg.get("text") or "").strip()
        is_start = text.startswith("/start")
        if not await self._check_access(from_user, is_start=is_start):
            return

        if is_start:
            await self._cmd_start(from_user)
            return

        if text in ("/cancel", "⬅️ Asosiy menyu"):
            await self.pm.cancel_pending_login(uid)
            self.states.pop(uid, None)
            await self.api.send_message(uid, "🏠 Asosiy menyu", reply_markup=main_menu_kb(uid))
            return

        # Asosiy menyu tugmalari
        if text == "👥 Profillar":
            self.states.pop(uid, None)
            t, kb = self._view_profiles(uid)
            await self.api.send_message(uid, t, reply_markup=kb)
            return
        if text == "📊 Statistika":
            self.states.pop(uid, None)
            await self._send_stats(uid)
            return
        if text == "💬 Xabar":
            self.states.pop(uid, None)
            await self._open_messages_menu(uid)
            return
        if text == "📋 Guruhlar":
            self.states.pop(uid, None)
            await self._open_groups_menu(uid)
            return
        if text == "▶️ Ishga tushirish":
            self.states.pop(uid, None)
            await self._open_run_menu(uid)
            return
        if text == "⏱ Interval":
            self.states.pop(uid, None)
            await self._open_interval_menu(uid)
            return
        if text in ("👑 Admin panel", "/admin") and uid in ADMIN_IDS:
            self.states.pop(uid, None)
            await self.api.send_message(
                uid, self._admin_stats_text(), reply_markup=self._admin_panel_kb()
            )
            return

        # State handlerlari
        st = self.states.get(uid)
        if not st:
            await self.api.send_message(uid, "👇 Menyudan kerakli bo'limni tanlang:", reply_markup=main_menu_kb(uid))
            return

        step = st["step"]
        if step == "wait_phone":
            await self._step_phone(uid, msg)
        elif step == "wait_code":
            await self._step_code(uid, text)
        elif step == "wait_2fa":
            await self._step_2fa(uid, msg)
        elif step == "wait_msg":
            await self._step_add_message(uid, st["account_id"], msg)
        elif step == "wait_grp_link":
            await self._step_add_group(uid, st["account_id"], text)
        elif step == "wait_interval":
            await self._step_interval(uid, st["account_id"], text)
        elif step == "wait_delay":
            await self._step_delay(uid, st["account_id"], text)
        elif step == "wait_hours":
            await self._step_hours(uid, st["account_id"], text)
        elif step == "adm_find" and uid in ADMIN_IDS:
            await self._step_admin_find(uid, text)
        elif step == "adm_broadcast" and uid in ADMIN_IDS:
            await self._step_admin_broadcast(uid, msg)

    async def _cmd_start(self, from_user: Dict[str, Any]) -> None:
        uid = from_user["id"]
        self.states.pop(uid, None)
        uname = from_user.get("username") or ""
        fname = " ".join(filter(None, [from_user.get("first_name"), from_user.get("last_name")])) or str(uid)

        if uid in ADMIN_IDS:
            self.db.upsert_user(uid, uname, fname, "approved")
            await self.api.send_message(
                uid,
                f"👋 <b>Xush kelibsiz, Admin {esc(fname)}!</b>\n\n"
                "Profillar, xabarlar, guruhlar, statistika — hammasi <b>100% bepul</b>!\n"
                "👇 Menyudan kerakli bo'limni tanlang:",
                reply_markup=main_menu_kb(uid),
            )
            return

        ex = self.db.get_user(uid)
        if ex is None:
            row, _ = self.db.upsert_user(uid, uname, fname, "pending")
            await self.api.send_message(uid, PENDING_USER_TEXT, reply_markup=remove_kb())
            await self._notify_admins_new_user(row)
            return

        self.db.upsert_user(uid, uname, fname, ex["status"])
        if ex["status"] == "blocked":
            await self.api.send_message(uid, BLOCKED_USER_TEXT, reply_markup=remove_kb())
            return
        if ex["status"] == "pending":
            await self.api.send_message(
                uid,
                "⏳ <b>So'rovingiz allaqachon adminga yuborilgan.</b>\n"
                "Administrator tasdiqlagach, sizga avtomatik xabar keladi.",
                reply_markup=remove_kb(),
            )
            return

        await self.api.send_message(
            uid,
            f"👋 <b>Xush kelibsiz, {esc(fname)}!</b>\n\n"
            "Profillar, xabarlar, guruhlar va statistika — hammasi <b>100% bepul va cheklovsiz</b>!\n"
            "Akkaunt ulash, matn yozish va yuborishni yoqish bir necha bosishda 👇",
            reply_markup=main_menu_kb(uid),
        )

    # --- PROFILLAR VA SMS/QR/2FA LOGIN ---
    def _view_profiles(self, uid: int) -> Tuple[str, Dict[str, Any]]:
        accs = self.db.get_user_accounts(uid)
        lines = [
            "👥 <b>Profillar</b>\n",
            f"📌 <b>Limit:</b> {len(accs)} / Cheksiz (100% Bepul)",
            "🟢 Ishlayapti  🟡 Pauza  🔴 Xato\n",
        ]
        rows: List[List[Tuple[str, str]]] = []
        if not accs:
            lines.append("❌ Sizda profil yo'q.")
        else:
            for a in accs:
                dot = status_dot(a["status"])
                gcnt = len(self.db.get_groups(a["id"], only_sendable=True))
                lines.append(f"{dot} <b>{esc(a['account_name'])}</b> ({esc(a['phone'])}) — {gcnt} guruh")
                rows.append([(f"{dot} {a['account_name']}", f"pv:{a['id']}")])
        rows.append([("➕ Profil qo'shish", "p_add")])
        return "\n".join(lines), inline_kb(rows)

    def _view_profile_detail(self, aid: int) -> Optional[Tuple[str, Dict[str, Any]]]:
        a = self.db.get_account(aid)
        if not a:
            return None
        all_g = self.db.get_groups(aid)
        sel_g = [g for g in all_g if g["is_selected"] and not g["is_blacklisted"]]
        blk_g = [g for g in all_g if g["is_blacklisted"]]
        msgs = self.db.get_messages(aid, only_active=True)
        st_lbl = {"running": "🟢 Ishlayapti", "paused": "🟡 Pauza", "error": "🔴 Xato"}.get(a["status"], "🟡 Pauza")
        err_line = f"\n⚠️ <b>Xato:</b> {esc(a['error_text'])}" if a["error_text"] else ""
        text = (
            f"👤 <b>{esc(a['account_name'])}</b>\n"
            f"📞 <b>Raqam:</b> <code>{esc(a['phone'])}</code>\n"
            f"📡 <b>Holat:</b> {st_lbl}{err_line}\n"
            f"📋 <b>Guruhlar:</b> {len(sel_g)} / {len(all_g)} (🛡 {len(blk_g)} filtr)\n"
            f"💬 <b>Faol xabarlar:</b> {len(msgs)} ta\n"
            f"⏱ <b>Interval:</b> har {a['interval_minutes']} daq | 🛡 {a['delay_min']}–{a['delay_max']}s\n"
            f"🕒 <b>Ish soati:</b> {a['work_start_hour']:02d}:00 – {a['work_end_hour']:02d}:00\n"
            f"📊 <b>Yuborilgan:</b> {a['sent_count']} ✅ | {a['failed_count']} ❌"
        )
        toggle = ("⏹ To'xtatish", f"run_stop:{aid}") if a["status"] == "running" else ("▶️ Ishga tushirish", f"run_start:{aid}")
        kb = inline_kb(
            [
                [toggle],
                [("🔄 Guruhlarni yangilash", f"g_sync:{aid}"), ("📋 Guruhlar", f"g_pg:{aid}:0")],
                [("💬 Xabarlar", f"m_list:{aid}"), ("⏱ Interval", f"i_acc:{aid}")],
                [("🗑 O'chirish", f"p_del:{aid}"), ("⬅️ Orqaga", "p_list")],
            ]
        )
        return text, kb

    async def _step_phone(self, uid: int, msg: Dict[str, Any]) -> None:
        contact = msg.get("contact")
        raw = contact["phone_number"] if contact else (msg.get("text") or "")
        phone = re.sub(r"[^\d+]", "", raw)
        if phone and not phone.startswith("+"):
            phone = "+" + phone
        if len(phone) < 10:
            await self.api.send_message(
                uid, "❌ Noto'g'ri raqam! Masalan: <code>+998901234567</code> yoki <b>📱 Share contact</b> bosing:"
            )
            return

        await self.api.send_message(uid, "📩 Kod yuborilmoqda...", reply_markup=main_menu_kb(uid))
        await self.pm.cancel_pending_login(uid)

        client = TelegramClient(StringSession(), API_ID, API_HASH)
        try:
            await client.connect()
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError:
            await client.disconnect()
            await self.api.send_message(uid, "❌ Telefon raqam noto'g'ri. Qaytadan kiriting:")
            return
        except FloodWaitError as e:
            await client.disconnect()
            self.states.pop(uid, None)
            await self.api.send_message(uid, f"⏳ Telegram cheklovi: {e.seconds} soniyadan keyin urinib ko'ring.")
            return
        except Exception as e:
            await client.disconnect()
            self.states.pop(uid, None)
            await self.api.send_message(uid, f"❌ Xatolik: <code>{esc(e)}</code>")
            return

        self.pm.pending_logins[uid] = {
            "client": client,
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
        }
        self.states[uid] = {"step": "wait_code"}
        await self.api.send_message(
            uid,
            "✅ <b>Kod yuborildi.</b>\n\n"
            "📩 Telegram'dan kelgan kodni yuboring.\n"
            "🔸 Kodni nuqta (.) bilan yozing.\n"
            "✅ Masalan: <code>54.568</code>\n\n"
            "⏱ Agar kod 1 daqiqada kelmasa, pastdagi tugmani bosing:",
            reply_markup=inline_kb([[("❗ Kod kelmadi", "p_resend")], [("❌ Bekor qilish", "p_cancel")]]),
        )

    async def _step_code(self, uid: int, text: str) -> None:
        info = self.pm.pending_logins.get(uid)
        if not info:
            self.states.pop(uid, None)
            await self.api.send_message(uid, "❌ Sessiya tugagan. Qaytadan profil qo'shing.")
            return

        code = re.sub(r"\D", "", text)
        if len(code) < 5:
            await self.api.send_message(uid, "❌ Kodni nuqta bilan to'g'ri kiriting (masalan: <code>54.568</code>):")
            return

        client: TelegramClient = info["client"]
        phone: str = info["phone"]
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=info["phone_code_hash"])
        except SessionPasswordNeededError:
            hint = ""
            try:
                pwd = await client(GetPasswordRequest())
                hint = pwd.hint or ""
            except Exception:
                pass
            self.states[uid] = {"step": "wait_2fa"}
            hint_line = f"\n💡 Eslatma: <b>{esc(hint)}</b>" if hint else ""
            await self.api.send_message(uid, f"🔐 Ikki bosqichli parolni yuboring.{hint_line}")
            return
        except (PhoneCodeInvalidError, PhoneCodeExpiredError):
            await self.api.send_message(
                uid,
                "❌ Kod noto'g'ri yoki muddati tugagan! Qaytadan kiriting yoki <b>❗ Kod kelmadi</b> tugmasini bosing.",
                reply_markup=inline_kb([[("❗ Kod kelmadi", "p_resend")], [("❌ Bekor qilish", "p_cancel")]]),
            )
            return
        except Exception as e:
            await self.api.send_message(uid, f"❌ Xatolik: <code>{esc(e)}</code>")
            return

        await self._finish_login(uid, client, phone, used_2fa=False)

    async def _step_2fa(self, uid: int, msg: Dict[str, Any]) -> None:
        pwd = (msg.get("text") or "").strip()
        # Xavfsizlik uchun parol xabarini o'chiramiz
        await self.api.delete_message(uid, msg["message_id"])

        info = self.pm.pending_logins.get(uid)
        if not info:
            self.states.pop(uid, None)
            await self.api.send_message(uid, "❌ Sessiya topilmadi. Qaytadan boshlang.")
            return

        client: TelegramClient = info["client"]
        try:
            await client.sign_in(password=pwd)
        except PasswordHashInvalidError:
            await self.api.send_message(uid, "❌ Parol noto'g'ri! Qaytadan kiriting:")
            return
        except Exception as e:
            await self.api.send_message(uid, f"❌ Xatolik: <code>{esc(e)}</code>")
            return

        await self._finish_login(uid, client, info["phone"], used_2fa=True)

    async def _finish_login(
        self, uid: int, client: TelegramClient, phone: str, used_2fa: bool
    ) -> None:
        me = await client.get_me()
        full_name = " ".join(filter(None, [me.first_name, me.last_name])) or phone or "Profil"
        uname = me.username or ""
        real_phone = ("+" + me.phone) if getattr(me, "phone", None) else phone
        sess = client.session.save()

        aid = self.db.add_account(uid, real_phone, full_name, uname, sess)
        self.pm.clients[aid] = client
        self.pm.pending_logins.pop(uid, None)
        self.states.pop(uid, None)

        gcnt, _ = await self.pm.sync_groups(aid)
        tag = " (2FA)" if used_2fa else ""
        await self.api.send_message(
            uid,
            f"✅ <b>Profil qo'shildi{tag}.</b>\n\n"
            f"👤 <b>Nom:</b> {esc(full_name)}\n"
            f"📋 <b>Yuklangan guruhlar:</b> {gcnt} ta",
        )
        await self.api.send_message(uid, "👇 Menyu", reply_markup=main_menu_kb(uid))

    async def _start_qr_login(self, uid: int) -> None:
        await self.pm.cancel_pending_login(uid)
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        try:
            await client.connect()
            qr = await client.qr_login()
        except Exception as e:
            await client.disconnect()
            await self.api.send_message(uid, f"❌ QR kod yaratib bo'lmadi: <code>{esc(e)}</code>")
            return

        qr_img = "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=" + urllib.parse.quote(
            qr.url, safe=""
        )
        await self.api.send_photo(
            uid,
            qr_img,
            caption=(
                "📷 <b>QR kod orqali ulash</b>\n\n"
                "1. Telegram → <b>Sozlamalar</b> → <b>Qurilmalar</b> → <b>Qurilma ulash</b>\n"
                "2. Ushbu QR kodni 60 soniya ichida skanerlang!"
            ),
            reply_markup=inline_kb([[("❌ Bekor qilish", "p_cancel")]]),
        )

        async def _wait_qr() -> None:
            try:
                await qr.wait(timeout=60)
                await self._finish_login(uid, client, "", used_2fa=False)
            except SessionPasswordNeededError:
                hint = ""
                try:
                    p = await client(GetPasswordRequest())
                    hint = p.hint or ""
                except Exception:
                    pass
                self.states[uid] = {"step": "wait_2fa"}
                hint_line = f"\n💡 Eslatma: <b>{esc(hint)}</b>" if hint else ""
                await self.api.send_message(uid, f"🔐 Ikki bosqichli parolni yuboring.{hint_line}")
            except asyncio.TimeoutError:
                await self.pm.cancel_pending_login(uid)
                await self.api.send_message(uid, "⏱ QR kod muddati tugadi. Qaytadan urinib ko'ring.")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                await self.pm.cancel_pending_login(uid)
                await self.api.send_message(uid, f"❌ QR xatosi: <code>{esc(e)}</code>")

        task = asyncio.create_task(_wait_qr())
        self.pm.pending_logins[uid] = {"client": client, "phone": "", "qr_task": task}

    # --- GURUHLAR / XABARLAR / INTERVAL / ISHGA TUSHIRISH ---
    def _pick_account_view(self, uid: int, prefix: str, title: str) -> Tuple[str, Dict[str, Any]]:
        accs = self.db.get_user_accounts(uid)
        if not accs:
            return (
                "❌ Sizda hali profil yo'q. Avval <b>👥 Profillar</b> bo'limidan profil qo'shing.",
                inline_kb([[("➕ Profil qo'shish", "p_add")]]),
            )
        rows = [[(f"{status_dot(a['status'])} {a['account_name']}", f"{prefix}:{a['id']}")] for a in accs]
        return title, inline_kb(rows)

    async def _open_groups_menu(self, uid: int) -> None:
        accs = self.db.get_user_accounts(uid)
        if len(accs) == 1:
            t, kb = self._view_groups(accs[0]["id"], 0)
            await self.api.send_message(uid, t, reply_markup=kb)
            return
        t, kb = self._pick_account_view(uid, "g_open", "📋 <b>Qaysi profil guruhlarini tanlaysiz?</b>")
        await self.api.send_message(uid, t, reply_markup=kb)

    def _view_groups(self, aid: int, page: int, per_page: int = 8) -> Tuple[str, Dict[str, Any]]:
        a = self.db.get_account(aid)
        groups = self.db.get_groups(aid)
        total = len(groups)
        sel = sum(1 for g in groups if g["is_selected"] and not g["is_blacklisted"])
        blk = sum(1 for g in groups if g["is_blacklisted"])
        pages = max(1, (total + per_page - 1) // per_page)
        page = max(0, min(page, pages - 1))
        chunk = groups[page * per_page : (page + 1) * per_page]

        text = (
            f"📋 <b>Guruhlar — {esc(a['account_name'] if a else '')}</b>\n\n"
            f"📊 Jami: <b>{total}</b> | ✅ Tanlangan: <b>{sel}</b> | 🛡 Filtrlangan: <b>{blk}</b>\n"
            f"📄 Sahifa: {page + 1}/{pages}"
        )
        rows: List[List[Tuple[str, str]]] = []
        for g in chunk:
            ic = "🛡" if g["is_blacklisted"] else ("✅" if g["is_selected"] else "⬜")
            rows.append([(f"{ic} {g['title'][:32]}", f"g_tog:{aid}:{g['id']}:{page}")])
        nav: List[Tuple[str, str]] = []
        if page > 0:
            nav.append(("⬅️ Oldingi", f"g_pg:{aid}:{page - 1}"))
        if page < pages - 1:
            nav.append(("Keyingi ➡️", f"g_pg:{aid}:{page + 1}"))
        if nav:
            rows.append(nav)
        rows.append([("✅ Barchasi", f"g_all:{aid}:1"), ("⬜ O'chirish", f"g_all:{aid}:0")])
        rows.append([("🔄 Yangilash", f"g_sync:{aid}"), ("➕ Qo'lda qo'shish", f"g_add:{aid}")])
        if blk > 0:
            rows.append([(f"🛡 Filtrni tozalash ({blk})", f"g_unblk:{aid}")])
        rows.append([("⬅️ Profilga qaytish", f"pv:{aid}")])
        return text, inline_kb(rows)

    async def _open_messages_menu(self, uid: int) -> None:
        accs = self.db.get_user_accounts(uid)
        if len(accs) == 1:
            t, kb = self._view_messages(accs[0]["id"])
            await self.api.send_message(uid, t, reply_markup=kb)
            return
        t, kb = self._pick_account_view(uid, "m_list", "💬 <b>Qaysi profil e'lonini sozlaysiz?</b>")
        await self.api.send_message(uid, t, reply_markup=kb)

    def _view_messages(self, aid: int) -> Tuple[str, Dict[str, Any]]:
        a = self.db.get_account(aid)
        msgs = self.db.get_messages(aid)
        rows: List[List[Tuple[str, str]]] = []
        if not msgs:
            text = (
                f"💬 <b>Xabar — {esc(a['account_name'] if a else '')}</b>\n\n"
                "Hali e'lon matni qo'shilmagan. Matn, rasm yoki video qo'shing.\n"
                "💡 <i>Spintax: <code>{Salom|Assalomu alaykum}</code></i>"
            )
        else:
            lines = [f"💬 <b>E'lon shablonlari — {esc(a['account_name'] if a else '')}</b>\n"]
            for i, m in enumerate(msgs, 1):
                st = "✅" if m["is_active"] else "⏸"
                mt = {"none": "📝", "photo": "🖼", "video": "🎬"}.get(m["media_type"], "📝")
                prev = (m["text"] or "(media)").replace("\n", " ")[:38]
                lines.append(f"{i}. {st} {mt} {esc(prev)}")
                rows.append([(f"{st} #{i}", f"m_tog:{aid}:{m['id']}"), ("🗑 O'chirish", f"m_del:{aid}:{m['id']}")])
            text = "\n".join(lines)
        rows.append([("➕ Yangi e'lon qo'shish", f"m_add:{aid}")])
        rows.append([("⬅️ Profilga qaytish", f"pv:{aid}")])
        return text, inline_kb(rows)

    async def _open_run_menu(self, uid: int) -> None:
        accs = self.db.get_user_accounts(uid)
        if not accs:
            await self.api.send_message(uid, "❌ Avval <b>👥 Profillar</b> bo'limidan profil ulang.")
            return
        lines = ["▶️ <b>Avto-yuborishni boshqarish</b>\n"]
        rows: List[List[Tuple[str, str]]] = []
        for a in accs:
            dot = status_dot(a["status"])
            lines.append(f"{dot} <b>{esc(a['account_name'])}</b> — har {a['interval_minutes']} daq")
            if a["status"] == "running":
                rows.append([(f"⏹ To'xtatish — {a['account_name']}", f"run_stop:{a['id']}")])
            else:
                rows.append([(f"▶️ Ishga tushirish — {a['account_name']}", f"run_start:{a['id']}")])
        await self.api.send_message(uid, "\n".join(lines), reply_markup=inline_kb(rows))

    async def _open_interval_menu(self, uid: int) -> None:
        accs = self.db.get_user_accounts(uid)
        if len(accs) == 1:
            t, kb = self._view_interval(accs[0]["id"])
            await self.api.send_message(uid, t, reply_markup=kb)
            return
        t, kb = self._pick_account_view(uid, "i_acc", "⏱ <b>Qaysi profil intervalini sozlaysiz?</b>")
        await self.api.send_message(uid, t, reply_markup=kb)

    def _view_interval(self, aid: int) -> Tuple[str, Dict[str, Any]]:
        a = self.db.get_account(aid)
        text = (
            f"⏱ <b>Interval va sozlamalar — {esc(a['account_name'] if a else '')}</b>\n\n"
            f"⏱ <b>Interval:</b> har <b>{a['interval_minutes']}</b> daqiqada\n"
            f"🛡 <b>Anti-ban kechikish:</b> <b>{a['delay_min']}–{a['delay_max']}</b> soniya\n"
            f"🕒 <b>Ish soati (UTC+{TIMEZONE_OFFSET}):</b> <b>{a['work_start_hour']:02d}:00 – {a['work_end_hour']:02d}:00</b>"
        )
        kb = inline_kb(
            [
                [("5 daq", f"i_set:{aid}:5"), ("10 daq", f"i_set:{aid}:10"), ("15 daq", f"i_set:{aid}:15"), ("30 daq", f"i_set:{aid}:30"), ("60 daq", f"i_set:{aid}:60")],
                [("✏️ Boshqa interval", f"i_cust:{aid}")],
                [("🛡 Anti-ban kechikish", f"i_del:{aid}"), ("🕒 Ish soati", f"i_hrs:{aid}")],
                [("⬅️ Profilga qaytish", f"pv:{aid}")],
            ]
        )
        return text, kb

    async def _send_stats(self, uid: int) -> None:
        u = self.db.get_user(uid)
        accs = self.db.get_user_accounts(uid)
        run_cnt = sum(1 for a in accs if a["status"] == "running")
        grp_cnt = sum(len(self.db.get_groups(a["id"], only_sendable=True)) for a in accs)
        lines = [
            "📊 <b>Sizning statistikangiz</b>\n",
            f"👥 Profillar: <b>{len(accs)}</b> ta (🟢 ishlayapti: {run_cnt})",
            f"📋 Faol guruhlar: <b>{grp_cnt}</b> ta",
            f"✅ Yuborilgan e'lonlar: <b>{u['total_sent'] if u else 0}</b> ta",
            f"❌ Xatolik / o'tkazilgan: <b>{u['total_failed'] if u else 0}</b> ta",
            "💎 Tarif: <b>100% BEPUL (Cheksiz)</b>",
        ]
        await self.api.send_message(uid, "\n".join(lines))

    # --- Qolgan state step handlerlari ---
    async def _step_add_message(self, uid: int, aid: int, msg: Dict[str, Any]) -> None:
        mtype = "none"
        mpath: Optional[str] = None
        text = msg.get("text") or msg.get("caption") or ""
        if msg.get("photo"):
            mtype = "photo"
            dest = MEDIA_DIR / f"p_{aid}_{int(datetime.now().timestamp())}.jpg"
            await self.api.download_file(msg["photo"][-1]["file_id"], dest)
            mpath = str(dest)
        elif msg.get("video"):
            mtype = "video"
            dest = MEDIA_DIR / f"v_{aid}_{int(datetime.now().timestamp())}.mp4"
            await self.api.download_file(msg["video"]["file_id"], dest)
            mpath = str(dest)
        elif not text.strip():
            await self.api.send_message(uid, "❌ Matn, rasm yoki video yuboring!")
            return
        self.states.pop(uid, None)
        self.db.add_message(aid, text, mtype, mpath)
        t, kb = self._view_messages(aid)
        await self.api.send_message(uid, "✅ E'lon saqlandi!", reply_markup=main_menu_kb(uid))
        await self.api.send_message(uid, t, reply_markup=kb)

    async def _step_add_group(self, uid: int, aid: int, text: str) -> None:
        self.states.pop(uid, None)
        _, info = await self.pm.add_group_by_link(aid, text)
        await self.api.send_message(uid, info, reply_markup=main_menu_kb(uid))

    async def _step_interval(self, uid: int, aid: int, text: str) -> None:
        if not text.isdigit() or int(text) < 1:
            await self.api.send_message(uid, "❌ Musbat raqam kiriting (masalan: 20):")
            return
        self.states.pop(uid, None)
        self.db.update_account_settings(aid, interval_minutes=int(text))
        t, kb = self._view_interval(aid)
        await self.api.send_message(uid, "✅ Saqlandi!", reply_markup=main_menu_kb(uid))
        await self.api.send_message(uid, t, reply_markup=kb)

    async def _step_delay(self, uid: int, aid: int, text: str) -> None:
        m = re.match(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$", text)
        if not m or int(m.group(1)) < 1 or int(m.group(2)) <= int(m.group(1)):
            await self.api.send_message(uid, "❌ Format: <code>3-8</code>")
            return
        self.states.pop(uid, None)
        self.db.update_account_settings(aid, delay_min=int(m.group(1)), delay_max=int(m.group(2)))
        t, kb = self._view_interval(aid)
        await self.api.send_message(uid, "✅ Saqlandi!", reply_markup=main_menu_kb(uid))
        await self.api.send_message(uid, t, reply_markup=kb)

    async def _step_hours(self, uid: int, aid: int, text: str) -> None:
        m = re.match(r"^\s*(\d+)\s*[-–]\s*(\d+)\s*$", text)
        if not m or not (0 <= int(m.group(1)) <= 23 and 1 <= int(m.group(2)) <= 24):
            await self.api.send_message(uid, "❌ Format: <code>8-22</code> yoki <code>0-24</code>")
            return
        self.states.pop(uid, None)
        self.db.update_account_settings(aid, work_start_hour=int(m.group(1)), work_end_hour=int(m.group(2)))
        t, kb = self._view_interval(aid)
        await self.api.send_message(uid, "✅ Saqlandi!", reply_markup=main_menu_kb(uid))
        await self.api.send_message(uid, t, reply_markup=kb)

    # --- Admin panel ---
    def _admin_stats_text(self) -> str:
        s = self.db.get_global_stats()
        return (
            "👑 <b>Admin Panel</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{s['u_total']}</b>\n"
            f"  ├ ✅ Tasdiqlangan: <b>{s['u_approved']}</b>\n"
            f"  ├ ⏳ Kutilayotgan: <b>{s['u_pending']}</b>\n"
            f"  └ 🚫 Bloklangan: <b>{s['u_blocked']}</b>\n\n"
            f"📱 Profillar: <b>{s['acc_total']}</b> (🟢 faol: <b>{s['acc_run']}</b>)\n"
            f"📋 Guruhlar: <b>{s['grp_total']}</b>\n"
            f"📨 Jami yuborilgan: <b>{s['sent_sum']}</b> ✅ | <b>{s['fail_sum']}</b> ❌"
        )

    def _admin_panel_kb(self) -> Dict[str, Any]:
        return inline_kb(
            [
                [("⏳ Kutilayotganlar", "ap_pending"), ("🚫 Bloklanganlar", "ap_blocked")],
                [("🔍 ID bo'yicha boshqarish", "ap_find")],
                [("📢 Hammaga xabar yuborish", "ap_broadcast")],
                [("🔄 Yangilash", "ap_refresh")],
            ]
        )

    async def _step_admin_find(self, uid: int, text: str) -> None:
        if not text.isdigit():
            await self.api.send_message(uid, "❌ Raqamli ID kiriting:")
            return
        self.states.pop(uid, None)
        tid = int(text)
        u = self.db.get_user(tid)
        if not u:
            await self.api.send_message(uid, "❌ Topilmadi.")
            return
        uname = f"@{u['username']}" if u["username"] else "Yo'q"
        kb = inline_kb([[("🚫 Bloklash", f"adm_block:{tid}")]]) if u["status"] == "approved" else admin_approval_kb(tid)
        await self.api.send_message(
            uid,
            f"👤 {esc(u['full_name'])} ({esc(uname)})\n🆔 <code>{tid}</code> | 📌 <b>{esc(u['status'])}</b>",
            reply_markup=kb,
        )

    async def _step_admin_broadcast(self, uid: int, msg: Dict[str, Any]) -> None:
        self.states.pop(uid, None)
        ids = self.db.get_approved_ids()
        st = await self.api.send_message(uid, f"⏳ {len(ids)} ta foydalanuvchiga yuborilmoqda...")
        ok_c = fail_c = 0
        for tid in ids:
            try:
                await self.api.copy_message(tid, msg["chat"]["id"], msg["message_id"])
                ok_c += 1
            except BotAPIError:
                fail_c += 1
            await asyncio.sleep(0.05)
        await self.api.edit_message_text(
            uid, st["message_id"], f"✅ Yakunlandi!\n📨 Yuborildi: <b>{ok_c}</b> | ❌ Xato: <b>{fail_c}</b>"
        )

    # --- Callback Query Router ---
    async def _handle_callback(self, call: Dict[str, Any]) -> None:
        cid = call["id"]
        from_user = call.get("from") or {}
        uid = from_user.get("id")
        data = call.get("data") or ""
        msg = call.get("message") or {}
        chat_id = (msg.get("chat") or {}).get("id")
        msg_id = msg.get("message_id")

        if not uid or not await self._check_access(from_user, cid=cid):
            return

        # --- Admin tasdiqlash / bloklash ---
        if data.startswith("adm_approve:"):
            if uid not in ADMIN_IDS:
                await self.api.answer_callback(cid, "Siz admin emassiz!", show_alert=True)
                return
            tid = int(data.split(":")[1])
            self.db.set_user_status(tid, "approved")
            u = self.db.get_user(tid)
            try:
                await self.api.send_message(
                    tid,
                    "🎉 <b>Tabriklaymiz! So'rovingiz tasdiqlandi.</b>\n\n"
                    "Endi siz <b>Avto Xabar Bot</b>dan <b>100% bepul va cheklovsiz</b> foydalanishingiz mumkin!\n"
                    "Boshlash uchun <b>👥 Profillar</b> tugmasini bosing 👇",
                    reply_markup=main_menu_kb(tid),
                )
            except BotAPIError:
                pass
            uname = f"@{u['username']}" if (u and u["username"]) else "Yo'q"
            name = u["full_name"] if u else str(tid)
            await self.api.edit_message_text(
                chat_id,
                msg_id,
                f"✅ <b>Foydalanuvchi tasdiqlandi!</b>\n\n👤 {esc(name)} ({esc(uname)})\n🆔 <code>{tid}</code>",
                inline_kb([[("🚫 Bloklash", f"adm_block:{tid}")]]),
            )
            await self.api.answer_callback(cid, "✅ Botga kirgizildi!")
            return

        if data.startswith("adm_block:"):
            if uid not in ADMIN_IDS:
                await self.api.answer_callback(cid, "Siz admin emassiz!", show_alert=True)
                return
            tid = int(data.split(":")[1])
            if tid in ADMIN_IDS:
                await self.api.answer_callback(cid, "Adminni bloklab bo'lmaydi!", show_alert=True)
                return
            self.db.set_user_status(tid, "blocked")
            for aid in self.db.pause_user_accounts(tid):
                await self.pm.stop_account(aid)
            try:
                await self.api.send_message(tid, BLOCKED_USER_TEXT, reply_markup=remove_kb())
            except BotAPIError:
                pass
            u = self.db.get_user(tid)
            uname = f"@{u['username']}" if (u and u["username"]) else "Yo'q"
            name = u["full_name"] if u else str(tid)
            await self.api.edit_message_text(
                chat_id,
                msg_id,
                f"🚫 <b>Foydalanuvchi bloklandi!</b>\n\n👤 {esc(name)} ({esc(uname)})\n🆔 <code>{tid}</code>\n"
                "📩 Bloklanganlik haqida xabar yuborildi.",
                inline_kb([[("🔓 Blokdan chiqarish", f"adm_approve:{tid}")]]),
            )
            await self.api.answer_callback(cid, "🚫 Bloklandi va xabar yuborildi!")
            return

        # --- Profil callbacklari ---
        if data == "p_list":
            t, kb = self._view_profiles(uid)
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid)
            return

        if data == "p_add":
            if not API_ID or not API_HASH or API_HASH == "YOUR_API_HASH_HERE":
                await self.api.answer_callback(
                    cid, "API_ID va API_HASH kiritilmagan! Admin sozlashi kerak.", show_alert=True
                )
                return
            await self.api.edit_message_text(
                chat_id,
                msg_id,
                "👤 <b>Profil qo'shish</b>\n\nLogin usulini tanlang:",
                inline_kb(
                    [
                        [("📱 SMS kod orqali", "p_sms")],
                        [("📷 QR kod orqali", "p_qr")],
                        [("⬅️ Orqaga", "p_list")],
                    ]
                ),
            )
            await self.api.answer_callback(cid)
            return

        if data == "p_sms":
            self.states[uid] = {"step": "wait_phone"}
            await self.api.edit_message_text(
                chat_id,
                msg_id,
                "<b>SMS kod orqali ulash</b>\n\n"
                "Telefon raqamni xalqaro formatda yozing.\n"
                "Masalan: <code>+998901234567</code>",
                inline_kb([[("Orqaga", "p_add")]]),
            )
            await self.api.send_message(
                uid,
                "Raqamni yozing yoki pastdagi <b>Share contact</b> tugmasini bosing.",
                reply_markup=share_contact_kb(),
            )
            await self.api.answer_callback(cid)
            return

        if data == "p_qr":
            await self.api.answer_callback(cid, "QR kod tayyorlanmoqda...")
            await self._start_qr_login(uid)
            return

        if data == "p_resend":
            info = self.pm.pending_logins.get(uid)
            if not info:
                await self.api.answer_callback(cid, "Sessiya tugagan.", show_alert=True)
                return
            try:
                sent = await info["client"].send_code_request(info["phone"])
                info["phone_code_hash"] = sent.phone_code_hash
                await self.api.edit_message_text(
                    chat_id,
                    msg_id,
                    "✅ <b>Yangi kod yuborildi.</b>\n\n"
                    "📩 Telegram'dan kelgan YANGI kodni yuboring (eskisi endi ishlamaydi).\n"
                    "🔸 Kodni nuqta (.) bilan yozing.\n"
                    "✅ Masalan: <code>54.568</code>\n\n"
                    "⏱ Agar kod 1 daqiqada kelmasa, pastdagi tugmani bosing:",
                    inline_kb([[("❗ Kod kelmadi", "p_resend")], [("❌ Bekor qilish", "p_cancel")]]),
                )
                await self.api.answer_callback(cid, "✅ Yangi kod yuborildi!")
            except Exception as e:
                await self.api.answer_callback(cid, f"Xato: {e}", show_alert=True)
            return

        if data == "p_cancel":
            await self.pm.cancel_pending_login(uid)
            self.states.pop(uid, None)
            await self.api.send_message(uid, "❌ Bekor qilindi.", reply_markup=main_menu_kb(uid))
            await self.api.answer_callback(cid)
            return

        if data.startswith("pv:"):
            aid = int(data.split(":")[1])
            acc = self.db.get_account(aid)
            if not acc or acc["user_id"] != uid:
                await self.api.answer_callback(cid, "Topilmadi.", show_alert=True)
                return
            v = self._view_profile_detail(aid)
            if v:
                await self.api.edit_message_text(chat_id, msg_id, v[0], v[1])
            await self.api.answer_callback(cid)
            return

        if data.startswith("p_del:"):
            aid = int(data.split(":")[1])
            acc = self.db.get_account(aid)
            if acc and acc["user_id"] == uid:
                await self.pm.disconnect_account(aid)
                self.db.delete_account(aid)
            t, kb = self._view_profiles(uid)
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid, "🗑 Profil o'chirildi!")
            return

        # --- Ishga tushirish / To'xtatish ---
        if data.startswith("run_start:"):
            aid = int(data.split(":")[1])
            ok, info = await self.pm.start_account(aid)
            await self.api.answer_callback(cid, re.sub(r"<[^>]+>", "", info), show_alert=not ok)
            if ok:
                v = self._view_profile_detail(aid)
                if v:
                    await self.api.edit_message_text(chat_id, msg_id, v[0], v[1])
            return

        if data.startswith("run_stop:"):
            aid = int(data.split(":")[1])
            await self.pm.stop_account(aid)
            await self.api.answer_callback(cid, "⏹ To'xtatildi!", show_alert=True)
            v = self._view_profile_detail(aid)
            if v:
                await self.api.edit_message_text(chat_id, msg_id, v[0], v[1])
            return

        # --- Guruhlar ---
        if data.startswith("g_open:"):
            aid = int(data.split(":")[1])
            t, kb = self._view_groups(aid, 0)
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid)
            return
        if data.startswith("g_pg:"):
            _, a_s, p_s = data.split(":")
            t, kb = self._view_groups(int(a_s), int(p_s))
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid)
            return
        if data.startswith("g_tog:"):
            _, a_s, g_s, p_s = data.split(":")
            self.db.toggle_group(int(g_s))
            t, kb = self._view_groups(int(a_s), int(p_s))
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid)
            return
        if data.startswith("g_all:"):
            _, a_s, v_s = data.split(":")
            self.db.select_all_groups(int(a_s), v_s == "1")
            t, kb = self._view_groups(int(a_s), 0)
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid, "Yangilandi!")
            return
        if data.startswith("g_sync:"):
            aid = int(data.split(":")[1])
            await self.api.answer_callback(cid, "🔄 Guruhlar yuklanmoqda...")
            _, status = await self.pm.sync_groups(aid)
            if status != "OK":
                await self.api.send_message(uid, f"⚠️ {esc(status)}")
                return
            t, kb = self._view_groups(aid, 0)
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            return
        if data.startswith("g_unblk:"):
            aid = int(data.split(":")[1])
            cnt = self.db.reset_blacklist(aid)
            t, kb = self._view_groups(aid, 0)
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid, f"🛡 {cnt} ta guruh filtrdan chiqarildi!", show_alert=True)
            return
        if data.startswith("g_add:"):
            aid = int(data.split(":")[1])
            self.states[uid] = {"step": "wait_grp_link", "account_id": aid}
            await self.api.send_message(uid, "➕ Guruh <code>@username</code> yoki havolasini yuboring:\n<i>/cancel</i>")
            await self.api.answer_callback(cid)
            return

        # --- Xabarlar ---
        if data.startswith("m_list:"):
            aid = int(data.split(":")[1])
            t, kb = self._view_messages(aid)
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid)
            return
        if data.startswith("m_add:"):
            aid = int(data.split(":")[1])
            self.states[uid] = {"step": "wait_msg", "account_id": aid}
            await self.api.send_message(
                uid, "✍️ E'lon matni, rasm (+ izoh) yoki video (+ izoh) yuboring:\n<i>/cancel</i>"
            )
            await self.api.answer_callback(cid)
            return
        if data.startswith("m_tog:"):
            _, a_s, m_s = data.split(":")
            self.db.toggle_message(int(m_s))
            t, kb = self._view_messages(int(a_s))
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid)
            return
        if data.startswith("m_del:"):
            _, a_s, m_s = data.split(":")
            self.db.delete_message(int(m_s))
            t, kb = self._view_messages(int(a_s))
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid, "🗑 O'chirildi!")
            return

        # --- Interval ---
        if data.startswith("i_acc:"):
            aid = int(data.split(":")[1])
            t, kb = self._view_interval(aid)
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid)
            return
        if data.startswith("i_set:"):
            _, a_s, v_s = data.split(":")
            self.db.update_account_settings(int(a_s), interval_minutes=int(v_s))
            t, kb = self._view_interval(int(a_s))
            await self.api.edit_message_text(chat_id, msg_id, t, kb)
            await self.api.answer_callback(cid, f"✅ {v_s} daqiqa!")
            return
        if data.startswith("i_cust:"):
            aid = int(data.split(":")[1])
            self.states[uid] = {"step": "wait_interval", "account_id": aid}
            await self.api.send_message(uid, "⏱ Intervalni daqiqalarda kiriting (masalan: <code>20</code>):")
            await self.api.answer_callback(cid)
            return
        if data.startswith("i_del:"):
            aid = int(data.split(":")[1])
            self.states[uid] = {"step": "wait_delay", "account_id": aid}
            await self.api.send_message(uid, "🛡 Kechikishni <code>min-max</code> soniyada kiriting (masalan: <code>3-8</code>):")
            await self.api.answer_callback(cid)
            return
        if data.startswith("i_hrs:"):
            aid = int(data.split(":")[1])
            self.states[uid] = {"step": "wait_hours", "account_id": aid}
            await self.api.send_message(uid, "🕒 Ish soatini kiriting (masalan: <code>8-22</code> yoki <code>0-24</code>):")
            await self.api.answer_callback(cid)
            return

        # --- Admin Panel ---
        if uid not in ADMIN_IDS:
            await self.api.answer_callback(cid)
            return
        if data == "ap_refresh":
            await self.api.edit_message_text(chat_id, msg_id, self._admin_stats_text(), self._admin_panel_kb())
            await self.api.answer_callback(cid, "Yangilandi!")
            return
        if data == "ap_pending":
            users = self.db.list_users_by_status("pending")
            if not users:
                await self.api.answer_callback(cid, "⏳ Kutilayotganlar yo'q!", show_alert=True)
                return
            await self.api.answer_callback(cid)
            for u in users:
                un = f"@{u['username']}" if u["username"] else "Yo'q"
                await self.api.send_message(
                    uid,
                    f"⏳ {esc(u['full_name'])} ({esc(un)})\n🆔 <code>{u['user_id']}</code>",
                    reply_markup=admin_approval_kb(u["user_id"]),
                )
            return
        if data == "ap_blocked":
            users = self.db.list_users_by_status("blocked")
            if not users:
                await self.api.answer_callback(cid, "🚫 Bloklanganlar yo'q!", show_alert=True)
                return
            await self.api.answer_callback(cid)
            for u in users:
                un = f"@{u['username']}" if u["username"] else "Yo'q"
                await self.api.send_message(
                    uid,
                    f"🚫 {esc(u['full_name'])} ({esc(un)})\n🆔 <code>{u['user_id']}</code>",
                    reply_markup=inline_kb([[("🔓 Blokdan chiqarish", f"adm_approve:{u['user_id']}")]]),
                )
            return
        if data == "ap_find":
            self.states[uid] = {"step": "adm_find"}
            await self.api.send_message(uid, "🔍 Foydalanuvchi ID raqamini yuboring:")
            await self.api.answer_callback(cid)
            return
        if data == "ap_broadcast":
            self.states[uid] = {"step": "adm_broadcast"}
            await self.api.send_message(uid, "📢 Barcha tasdiqlangan foydalanuvchilarga yuboriladigan xabarni jo'nating:")
            await self.api.answer_callback(cid)
            return

        await self.api.answer_callback(cid)


if __name__ == "__main__":
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ BOT_TOKEN kiritilmagan!")
        sys.exit(1)
    asyncio.run(AutoXabarBot(BOT_TOKEN).run())
