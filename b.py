import base64
import datetime
import glob
import hashlib
import http.client
import json
import os
import queue
import random
import select
import shutil
import socket
import signal
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


# ============================================================================
# 1-BO'LIM: CONFIG (SOZLAMALAR)
# ============================================================================

import os


class Config:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    # Telegram Bot sozlamalari (@BotFather dan olingan token va Admin ID)
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8655952088:AAGZq3Z5u-5r9onDaib-KO2K089J4jTHxJc")
    ADMIN_ID = os.getenv("ADMIN_ID", "ADMIN_ID_SHU_YERGA_YOZILADI")
    BOT_USERNAME = os.getenv("BOT_USERNAME", "7552962971")

    # Sayt va Veb-server sozlamalari
    SITE_URL = os.getenv("SITE_URL", "localhost:8000")
    PORT = int(os.getenv("PORT", "8000"))

    # Ma'lumotlar bazasi va yordamchi papkalar (Avtomatik yaratiladi)
    SQLITE_PATH = os.path.join(BASE_DIR, "database.sqlite3")
    USER_DIR = os.path.join(BASE_DIR, "user")
    SET_DIR = os.path.join(BASE_DIR, "set")
    HOSTED_BOTS_DIR = os.path.join(BASE_DIR, "hosted_bots")


config = Config()
os.makedirs(config.USER_DIR, exist_ok=True)
os.makedirs(config.SET_DIR, exist_ok=True)
os.makedirs(config.HOSTED_BOTS_DIR, exist_ok=True)

API_KEY = config.BOT_TOKEN
ADMIN = str(config.ADMIN_ID)

# ============================================================================
# 2-BO'LIM: DATABASE VA RAM KESH (SQLite3 WAL + Tezkor Xotira)
# ============================================================================

"""
2-MODUL: database.py — Tezkor SQLite3 (WAL rejimida) va RAM keshli fayl/baza tizimi.
Barcha foydalanuvchi qadamlari (user/*.step) va buyurtmalar operativ xotirada (RAM) hamda SQLite bazada tezkor saqlanadi (0.0001s).
"""
import base64
import hashlib
import os
import random
import shutil
import sqlite3
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, Union



class _PersistentConnWrapper:
    """conn.close() chaqirilganda ulanishni yopmasdan saqlab qoluvchi o'ram."""
    def __init__(self, real_conn: sqlite3.Connection):
        self._conn = real_conn

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        pass

    def close(self):
        pass


_DB_LOCK = threading.RLock()
_PERSISTENT_SQLITE: Optional[_PersistentConnWrapper] = None
_SETTINGS_CACHE: Optional[Dict[str, Any]] = None
_USER_CACHE: Dict[str, Dict[str, Any]] = {}
_CATALOG_CACHE: Dict[str, Any] = {}


class DatabaseModule:
    @staticmethod
    def get_connection() -> _PersistentConnWrapper:
        global _PERSISTENT_SQLITE
        with _DB_LOCK:
            if _PERSISTENT_SQLITE is None:
                raw_conn = sqlite3.connect(
                    config.SQLITE_PATH,
                    check_same_thread=False,
                    isolation_level=None,
                )
                raw_conn.row_factory = sqlite3.Row
                try:
                    raw_conn.execute("PRAGMA journal_mode=MEMORY")
                    raw_conn.execute("PRAGMA synchronous=OFF")
                    raw_conn.execute("PRAGMA temp_store=MEMORY")
                    raw_conn.execute("PRAGMA cache_size=-16000")
                except Exception:
                    pass
                _PERSISTENT_SQLITE = _PersistentConnWrapper(raw_conn)
            return _PERSISTENT_SQLITE

    @classmethod
    def init_db(cls) -> None:
        conn = cls.get_connection()
        cur = conn.cursor()
        schema_statements = [
            """CREATE TABLE IF NOT EXISTS `categorys` (
                `category_id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `category_name` TEXT NOT NULL DEFAULT '',
                `category_status` TEXT NOT NULL DEFAULT 'ON'
            )""",
            """CREATE TABLE IF NOT EXISTS `cates` (
                `cate_id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `name` TEXT NOT NULL DEFAULT '',
                `category_id` TEXT NOT NULL DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS `myorder` (
                `order_id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `user_id` TEXT NOT NULL DEFAULT '',
                `retail` TEXT NOT NULL DEFAULT '0',
                `status` TEXT NOT NULL DEFAULT 'Pending',
                `service` TEXT NOT NULL DEFAULT '',
                `order_create` TEXT NOT NULL DEFAULT '',
                `last_check` TEXT NOT NULL DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS `orders` (
                `order_id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `api_order` TEXT NOT NULL DEFAULT '',
                `provider` TEXT NOT NULL DEFAULT '',
                `status` TEXT NOT NULL DEFAULT 'Pending'
            )""",
            """CREATE TABLE IF NOT EXISTS `payments` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `pay_name` TEXT NOT NULL DEFAULT '',
                `pay_id` TEXT NOT NULL DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS `percent` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `percent` TEXT NOT NULL DEFAULT '40'
            )""",
            """CREATE TABLE IF NOT EXISTS `providers` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `api_url` TEXT NOT NULL DEFAULT '',
                `api_key` TEXT NOT NULL DEFAULT '',
                `curr` TEXT NOT NULL DEFAULT 'UZS'
            )""",
            """CREATE TABLE IF NOT EXISTS `send` (
                `send_id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `time1` TEXT NOT NULL DEFAULT '',
                `time2` TEXT NOT NULL DEFAULT '',
                `start_id` TEXT NOT NULL DEFAULT '0',
                `stop_id` TEXT NOT NULL DEFAULT '0',
                `admin_id` TEXT NOT NULL DEFAULT '',
                `message_id` TEXT NOT NULL DEFAULT '',
                `reply_markup` TEXT NOT NULL DEFAULT '',
                `step` TEXT NOT NULL DEFAULT '',
                `time3` TEXT NOT NULL DEFAULT '',
                `time4` TEXT NOT NULL DEFAULT '',
                `time5` TEXT NOT NULL DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS `services` (
                `service_id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `service_edit` TEXT NOT NULL DEFAULT 'true',
                `category_id` TEXT NOT NULL DEFAULT '',
                `service_price` TEXT NOT NULL DEFAULT '0',
                `service_api` TEXT NOT NULL DEFAULT '',
                `api_service` TEXT NOT NULL DEFAULT '',
                `api_currency` TEXT NOT NULL DEFAULT '',
                `service_type` TEXT NOT NULL DEFAULT 'Default',
                `api_detail` TEXT NOT NULL DEFAULT '{}',
                `service_name` TEXT NOT NULL DEFAULT '',
                `service_desc` TEXT NOT NULL DEFAULT '',
                `service_min` TEXT NOT NULL DEFAULT '0',
                `service_max` TEXT NOT NULL DEFAULT '0',
                `service_status` TEXT NOT NULL DEFAULT 'on'
            )""",
            """CREATE TABLE IF NOT EXISTS `settings` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `site_style` TEXT NOT NULL DEFAULT 'theme8.0',
                `site_theme` TEXT NOT NULL DEFAULT 'Eternity',
                `ref_status` TEXT NOT NULL DEFAULT 'off',
                `referal` TEXT NOT NULL DEFAULT 'MTAw',
                `orders` TEXT NOT NULL DEFAULT '',
                `kabinet` TEXT NOT NULL DEFAULT '',
                `start` TEXT NOT NULL DEFAULT '',
                `status` TEXT NOT NULL DEFAULT 'active',
                `bonus` TEXT NOT NULL DEFAULT '4',
                `payme_id` TEXT NOT NULL DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS `users` (
                `user_id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `id` TEXT NOT NULL DEFAULT '',
                `status` TEXT NOT NULL DEFAULT 'active',
                `balance` TEXT NOT NULL DEFAULT '0',
                `outing` TEXT NOT NULL DEFAULT '0',
                `api_key` TEXT NOT NULL DEFAULT '',
                `referal` TEXT NOT NULL DEFAULT ''
            )""",
            """CREATE TABLE IF NOT EXISTS `saved_orders` (
                `saved_id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `user_id` TEXT NOT NULL DEFAULT '',
                `service_id` TEXT NOT NULL DEFAULT '',
                `service_name` TEXT NOT NULL DEFAULT '',
                `provider_id` TEXT NOT NULL DEFAULT '',
                `api_service` TEXT NOT NULL DEFAULT '',
                `quantity` TEXT NOT NULL DEFAULT '0',
                `link` TEXT NOT NULL DEFAULT '',
                `price` TEXT NOT NULL DEFAULT '0',
                `order_type` TEXT NOT NULL DEFAULT 'default',
                `created_at` TEXT NOT NULL DEFAULT ''
            )""",
            "CREATE INDEX IF NOT EXISTS `idx_users_tg_id` ON `users` (`id`)",
            "CREATE INDEX IF NOT EXISTS `idx_users_api_key` ON `users` (`api_key`)",
            "CREATE INDEX IF NOT EXISTS `idx_myorder_uid` ON `myorder` (`user_id`)",
            "CREATE INDEX IF NOT EXISTS `idx_services_cat` ON `services` (`category_id`)",
            "CREATE INDEX IF NOT EXISTS `idx_saved_orders_uid` ON `saved_orders` (`user_id`)",
            """CREATE TABLE IF NOT EXISTS `earn_channels` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `channel_username` TEXT NOT NULL DEFAULT '',
                `title` TEXT NOT NULL DEFAULT '',
                `reward` TEXT NOT NULL DEFAULT '100',
                `status` TEXT NOT NULL DEFAULT 'on'
            )""",
            """CREATE TABLE IF NOT EXISTS `earn_tasks` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `title` TEXT NOT NULL DEFAULT '',
                `description` TEXT NOT NULL DEFAULT '',
                `url` TEXT NOT NULL DEFAULT '',
                `reward` TEXT NOT NULL DEFAULT '150',
                `verify_type` TEXT NOT NULL DEFAULT 'auto',
                `status` TEXT NOT NULL DEFAULT 'on'
            )""",
            """CREATE TABLE IF NOT EXISTS `promocodes` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `code` TEXT NOT NULL DEFAULT '',
                `reward` TEXT NOT NULL DEFAULT '200',
                `max_uses` INTEGER NOT NULL DEFAULT 10,
                `used_count` INTEGER NOT NULL DEFAULT 0,
                `status` TEXT NOT NULL DEFAULT 'on'
            )""",
            """CREATE TABLE IF NOT EXISTS `earn_claims` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `user_id` TEXT NOT NULL DEFAULT '',
                `claim_type` TEXT NOT NULL DEFAULT '',
                `item_id` TEXT NOT NULL DEFAULT '',
                `claimed_at` TEXT NOT NULL DEFAULT ''
            )""",
            "CREATE INDEX IF NOT EXISTS `idx_earn_claims_user` ON `earn_claims` (`user_id`, `claim_type`, `item_id`)",
            """CREATE TABLE IF NOT EXISTS `hosted_bots` (
                `id` INTEGER PRIMARY KEY AUTOINCREMENT,
                `owner_id` TEXT NOT NULL DEFAULT '',
                `bot_category` TEXT NOT NULL DEFAULT 'smm',
                `tariff_plan` TEXT NOT NULL DEFAULT 'SMM',
                `bot_token` TEXT NOT NULL DEFAULT '',
                `bot_admin_id` TEXT NOT NULL DEFAULT '',
                `bot_username` TEXT NOT NULL DEFAULT '',
                `monthly_price` TEXT NOT NULL DEFAULT '10000',
                `is_trial` INTEGER NOT NULL DEFAULT 0,
                `status` TEXT NOT NULL DEFAULT 'active',
                `created_at` TEXT NOT NULL DEFAULT '',
                `expires_ts` REAL NOT NULL DEFAULT 0,
                `expires_str` TEXT NOT NULL DEFAULT '',
                `script_path` TEXT NOT NULL DEFAULT ''
            )""",
            "CREATE INDEX IF NOT EXISTS `idx_hosted_bots_owner` ON `hosted_bots` (`owner_id`)",
        ]
        for stmt in schema_statements:
            cur.execute(stmt)

        cur.execute("SELECT COUNT(*) AS cnt FROM `percent`")
        if cur.fetchone()["cnt"] == 0:
            cur.execute("INSERT INTO `percent` (`id`, `percent`) VALUES (1, '40')")

        cur.execute("SELECT COUNT(*) AS cnt FROM `settings`")
        if cur.fetchone()["cnt"] == 0:
            cur.execute(
                """INSERT INTO `settings`
                (`id`, `site_style`, `site_theme`, `ref_status`, `referal`, `orders`, `kabinet`, `start`, `status`, `bonus`, `payme_id`)
                VALUES (
                    1, 'theme8.0', 'Eternity', 'off', 'MTAw',
                    '4pyFIEJ1eXVydG1hIHFhYnVsIHFpbGluZGkKCvCfhpQgQnV5dXJ0bWEgSURzaTogPHByZT57b3JkZXJ9PC9wcmU+CvCfj7cgSG9sYXRpOiA8Yj5KYXJheW9uZGE8L2I+CvCfk7QgQnV5dXJ0bWEgdGFya2liaTogPGI+e3NlcnZpY2V9PC9iPgrwn5SiIEJ1eXVydG1hIG1pcWRvcmk6IDxiPnthbW91bnR9IHRhPC9iPgrwn5K1IEJ1eXVydG1hIG5hcnhpOiA8Yj57cHJpY2V9IHNv4oCYbTwvYj4=',
                    '8J+StSBIaXNvYmluZ2l6OiA8Yj57YmFsYW5jZX0gc2/igJhtPC9iPgrirIbvuI8gS2lyaXRnYW4gcHVsbGFyaW5naXo6IDxiPntvdXRpbmd9IHNv4oCYbTwvYj4K8J+UrSBTaXpuaW5nIElEIHJhcWFtaW5naXo6IDxjb2RlPntpZH08L2NvZGU+',
                    '8J+WpSBBc29zaXkgbWVueXVkYXNpeg==',
                    'active', '4', ''
                )"""
            )
        else:
            # Mavjud bazadagi eski xato shablonlarni avtomatik to'g'irlash (Ijyonda -> Jarayonda, {users} qatorini olib tashlash)
            cur.execute("SELECT `id`, `orders`, `kabinet` FROM `settings` LIMIT 1")
            srow = cur.fetchone()
            if srow:
                cur_ord = srow["orders"] or ""
                cur_kab = srow["kabinet"] or ""
                try:
                    dec_ord = base64.b64decode(cur_ord).decode("utf-8", errors="replace")
                except Exception:
                    dec_ord = ""
                if not dec_ord or "Ij" in dec_ord or "\ufffd" in dec_ord:
                    cur.execute("UPDATE `settings` SET `orders` = ? WHERE `id` = ?", ('4pyFIEJ1eXVydG1hIHFhYnVsIHFpbGluZGkKCvCfhpQgQnV5dXJ0bWEgSURzaTogPHByZT57b3JkZXJ9PC9wcmU+CvCfj7cgSG9sYXRpOiA8Yj5KYXJheW9uZGE8L2I+CvCfk7QgQnV5dXJ0bWEgdGFya2liaTogPGI+e3NlcnZpY2V9PC9iPgrwn5SiIEJ1eXVydG1hIG1pcWRvcmk6IDxiPnthbW91bnR9IHRhPC9iPgrwn5K1IEJ1eXVydG1hIG5hcnhpOiA8Yj57cHJpY2V9IHNv4oCYbTwvYj4=', srow["id"]))
                try:
                    dec_kab = base64.b64decode(cur_kab).decode("utf-8", errors="replace")
                except Exception:
                    dec_kab = ""
                if not dec_kab or "{users}" in dec_kab or "umumiy foydalanuvchilar" in dec_kab or "Syzning" in dec_kab:
                    cur.execute("UPDATE `settings` SET `kabinet` = ? WHERE `id` = ?", ('8J+StSBIaXNvYmluZ2l6OiA8Yj57YmFsYW5jZX0gc2/igJhtPC9iPgrirIbvuI8gS2lyaXRnYW4gcHVsbGFyaW5naXo6IDxiPntvdXRpbmd9IHNv4oCYbTwvYj4K8J+UrSBTaXpuaW5nIElEIHJhcWFtaW5naXo6IDxjb2RlPntpZH08L2NvZGU+', srow["id"]))

    @classmethod
    def fetch_one(cls, sql: str, params: Tuple[Any, ...] = ()) -> Optional[Dict[str, Any]]:
        global _SETTINGS_CACHE
        with _DB_LOCK:
            if "FROM `settings`" in sql and _SETTINGS_CACHE is not None:
                return dict(_SETTINGS_CACHE)
            if sql == "SELECT * FROM `users` WHERE `id` = ?" and params:
                uid = str(params[0])
                if uid in _USER_CACHE:
                    return dict(_USER_CACHE[uid])
            conn = cls.get_connection()
            cur = conn.cursor()
            cur.execute(sql, params)
            row = cur.fetchone()
            res = dict(row) if row is not None else None
            if res is not None:
                if "FROM `settings`" in sql:
                    _SETTINGS_CACHE = dict(res)
                elif sql == "SELECT * FROM `users` WHERE `id` = ?" and params:
                    _USER_CACHE[str(params[0])] = dict(res)
            return res

    @classmethod
    def fetch_all(cls, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        cache_key = None
        if any(tbl in sql for tbl in ("FROM `categorys`", "FROM `cates`", "FROM `services`")):
            cache_key = f"{sql}::{params}"
        with _DB_LOCK:
            if cache_key and cache_key in _CATALOG_CACHE:
                return [dict(r) for r in _CATALOG_CACHE[cache_key]]
            conn = cls.get_connection()
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = [dict(r) for r in cur.fetchall()]
            if cache_key:
                _CATALOG_CACHE[cache_key] = rows
            return [dict(r) for r in rows]

    @classmethod
    def execute(cls, sql: str, params: Tuple[Any, ...] = ()) -> int:
        global _SETTINGS_CACHE
        with _DB_LOCK:
            if "`settings`" in sql or "settings" in sql:
                _SETTINGS_CACHE = None
            if "`users`" in sql or "users" in sql:
                _USER_CACHE.clear()
            if any(tbl in sql for tbl in ("`categorys`", "`cates`", "`services`")):
                _CATALOG_CACHE.clear()
            conn = cls.get_connection()
            cur = conn.cursor()
            cur.execute(sql, params)
            return cur.lastrowid or cur.rowcount

    @classmethod
    def count_rows(cls, table: str, where: Optional[Dict[str, Any]] = None) -> int:
        sql = f"SELECT COUNT(*) AS cnt FROM `{table}`"
        params: List[Any] = []
        if where:
            clauses = [f"`{k}` = ?" for k in where]
            params.extend(where.values())
            sql += " WHERE " + " AND ".join(clauses)
        row = cls.fetch_one(sql, tuple(params))
        return int(row["cnt"]) if row else 0

    @classmethod
    def get_settings(cls) -> Dict[str, Any]:
        row = cls.fetch_one("SELECT * FROM `settings` WHERE `id` = 1")
        return row or {
            "site_theme": "Eternity",
            "site_style": "theme8.0",
            "ref_status": "off",
            "referal": "MTAw",
            "orders": "",
            "kabinet": "",
            "start": "",
            "id": 1,
            "status": "active",
            "bonus": "4",
            "payme_id": "",
        }


database = DatabaseModule()
database.init_db()


# ============================================================================
# Yordamchi funksiyalar va RAM keshli fayl tizimi
# ============================================================================

def enc(action: str, value: Optional[str]) -> str:
    """Base64 kodlash va dekodlash (PHP enc() analogi)."""
    if not value:
        return ""
    action = action.strip()
    if action == "encode":
        return base64.b64encode(value.encode("utf-8")).decode("utf-8")
    if action == "decode":
        try:
            padded = value + "=" * (-len(value) % 4)
            return base64.b64decode(padded.encode("utf-8")).decode("utf-8", errors="replace")
        except Exception:
            return ""
    return str(value)


def number_fmt(val: Union[int, float, str]) -> str:
    """Sonlarni 1 000 ko'rinishida formatlash."""
    try:
        return f"{int(float(val)):,}".replace(",", " ")
    except Exception:
        return str(val)


def fmt_money(val: Union[int, float, str]) -> str:
    """Pul miqdorini 0.23800000000000002 kabi xatolarsiz toza ko'rinishda formatlaydi."""
    try:
        num = round(float(val or 0), 4)
    except (ValueError, TypeError):
        return "0"
    if abs(num - round(num)) < 1e-9:
        return str(int(round(num)))
    # 2 xonagacha yaxlitlab, agar juda kichik kasr bo'lsa 4 xonagacha ko'rsatamiz
    r2 = round(num, 2)
    if r2 > 0:
        return f"{r2:.2f}".rstrip("0").rstrip(".")
    return f"{num:.4f}".rstrip("0").rstrip(".")


def format_kabinet_msg(kabinet_tpl: str, rew: Dict[str, Any], fallback_id: str = "") -> str:
    """Balans xabaridan {users} qatorini olib tashlaydi va summalarni toza formatlaydi."""
    bal_str = fmt_money(rew.get("balance", "0"))
    out_str = fmt_money(rew.get("outing", "0"))
    uid_str = str(rew.get("user_id") or fallback_id or "")
    if not kabinet_tpl:
        kabinet_tpl = (
            "💵 Hisobingiz: <b>{balance} so‘m</b>\n"
            "⬆️ Kiritgan pullaringiz: <b>{outing} so‘m</b>\n"
            "🔭 Sizning ID raqamingiz: <code>{id}</code>"
        )
    cleaned_lines = []
    for line in kabinet_tpl.splitlines():
        if "{users}" in line or "umumiy foydalanuvchilar" in line.lower():
            continue
        cleaned_lines.append(line.replace("Syzning", "Sizning"))
    msg = "\n".join(cleaned_lines)
    return (
        msg.replace("{outing}", out_str)
        .replace("{balance}", bal_str)
        .replace("{id}", uid_str)
    )


def format_order_confirmed_msg(
    order_tpl: str,
    or_id: Union[int, str],
    api_order_id: Union[int, str],
    service_name: str,
    amount: Union[int, str],
    price: Union[int, float, str],
) -> str:
    """Buyurtma qabul qilinganda {order}, {service}, {amount}, {price} va Ijyonda xatolarini to'liq to'g'irlaydi."""
    if not order_tpl or "Ij" in order_tpl or "\ufffd" in order_tpl:
        order_tpl = (
            "✅ Buyurtma qabul qilindi\n\n"
            "🆔 Buyurtma IDsi: <pre>{order}</pre>\n"
            "🏷 Holati: <b>Jarayonda</b>\n"
            "📴 Buyurtma tarkibi: <b>{service}</b>\n"
            "🔢 Buyurtma miqdori: <b>{amount} ta</b>\n"
            "💵 Buyurtma narxi: <b>{price} so‘m</b>"
        )
    price_clean = fmt_money(price)
    return (
        order_tpl.replace("Ij\ufffdyonda", "Jarayonda")
        .replace("Ijyonda", "Jarayonda")
        .replace("{order}", str(or_id))
        .replace("{order_api}", str(api_order_id))
        .replace("{service}", str(service_name or "Xizmat"))
        .replace("{amount}", str(amount))
        .replace("{price}", price_clean)
    )


def _resolve_path(rel_path: str) -> str:
    clean = rel_path.lstrip("./")
    return os.path.join(config.BASE_DIR, clean)


_FILE_CACHE: Dict[str, str] = {}
_FILE_LOCK = threading.RLock()
_HTTP_GET_FALLBACK: Optional[Callable[[str], str]] = None


def set_http_get_handler(fn: Callable[[str], str]) -> None:
    global _HTTP_GET_FALLBACK
    _HTTP_GET_FALLBACK = fn


def get_file(rel_path: str) -> str:
    """file_get_contents analogi (RAM kesh bilan 0.0001 soniyada ishlaydi)."""
    if rel_path.startswith("http://") or rel_path.startswith("https://"):
        return _HTTP_GET_FALLBACK(rel_path) if _HTTP_GET_FALLBACK else ""
    full = _resolve_path(rel_path)
    with _FILE_LOCK:
        if full in _FILE_CACHE:
            return _FILE_CACHE[full]
        if not os.path.exists(full):
            _FILE_CACHE[full] = ""
            return ""
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                val = f.read()
            _FILE_CACHE[full] = val
            return val
        except Exception:
            return ""


def put_file(rel_path: str, content: Union[str, int, float], append: bool = False) -> None:
    """file_put_contents analogi (RAM keshni darhol yangilaydi)."""
    full = _resolve_path(rel_path)
    str_val = str(content)
    with _FILE_LOCK:
        if append:
            prev = _FILE_CACHE.get(full)
            if prev is None:
                prev = get_file(rel_path)
            _FILE_CACHE[full] = prev + str_val
        else:
            _FILE_CACHE[full] = str_val
        os.makedirs(os.path.dirname(full), exist_ok=True)
        mode = "a" if append else "w"
        with open(full, mode, encoding="utf-8") as f:
            f.write(str_val)


def unlink_file(rel_path: str) -> None:
    """unlink analogi."""
    full = _resolve_path(rel_path)
    with _FILE_LOCK:
        _FILE_CACHE[full] = ""
        try:
            if os.path.exists(full):
                os.remove(full)
        except Exception:
            pass


def rmdir_pro(rel_path: str) -> None:
    """rmdirPro analogi."""
    full = _resolve_path(rel_path)
    with _FILE_LOCK:
        for k in list(_FILE_CACHE.keys()):
            if k.startswith(full):
                del _FILE_CACHE[k]
        if os.path.exists(full):
            shutil.rmtree(full, ignore_errors=True)


def generate_ref_code() -> str:
    """7 xonali tasodifiy referal kod yaratadi."""
    chars = "ABCDEFGHIJKLMNOPRSTUVXYZ1234567890"
    return "".join(random.choice(chars) for _ in range(7))


def adduser(cid: Union[str, int]) -> None:
    """Yangi foydalanuvchini users jadvaliga qo'shadi."""
    if not cid:
        return
    row = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (str(cid),))
    if not row:
        key = hashlib.md5(uuid.uuid4().hex.encode("utf-8")).hexdigest()
        ref = generate_ref_code()
        total = database.count_rows("users")
        new_uid = total + 1
        database.execute(
            """INSERT INTO `users`
            (`user_id`, `id`, `status`, `balance`, `outing`, `api_key`, `referal`)
            VALUES (?, ?, 'active', '0', '0', ?, ?)""",
            (new_uid, str(cid), key, ref),
        )


def strip_provider_domain(api_url: str) -> str:
    """Provayder URL manzilidan domen yoki @bot nomini ajratib oladi."""
    if not api_url:
        return "Telegram Bot"
    for token in ("/api/adapter/default/index", "/stubs/handler_api.php", "/api/v1", "/api/v2", "https://", "http://"):
        api_url = api_url.replace(token, "")
    return api_url.strip("/")

# ============================================================================
# 3-BO'LIM: NETWORK (Keep-Alive SSL Havzasi va HTTP Tarmoq Tizimi)
# ============================================================================

"""
3-MODUL: network.py — Telegram Bot API Keep-Alive havzasi va tezkor HTTP so'rovlar tizimi.
"""
import glob
import http.client
import json
import os
import queue
import select
import socket
import ssl
import threading
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple, Union


# Windows da IPv6 (AAAA) kutib qolishini oldini olish va DNS ni RAM da keshlab turish
_orig_getaddrinfo = socket.getaddrinfo
_dns_cache: Dict[Tuple[Any, Any], Any] = {}
_dns_lock = threading.Lock()


def _ipv4_first_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    cache_key = (host, port, type, proto)
    if cache_key in _dns_cache:
        return _dns_cache[cache_key]
    try:
        res = _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
        if res:
            with _dns_lock:
                _dns_cache[cache_key] = res
            return res
    except Exception:
        pass
    res = _orig_getaddrinfo(host, port, family, type, proto, flags)
    with _dns_lock:
        _dns_cache[cache_key] = res
    return res


socket.getaddrinfo = _ipv4_first_getaddrinfo

# Global Keep-Alive HTTPS ulanishlar havzasi
_SSL_CTX = ssl.create_default_context()
_UNVERIFIED_SSL_CTX = ssl.create_default_context()
_UNVERIFIED_SSL_CTX.check_hostname = False
_UNVERIFIED_SSL_CTX.verify_mode = ssl.CERT_NONE

_API_CONN_POOL: "queue.Queue[Tuple[http.client.HTTPSConnection, float]]" = queue.Queue(maxsize=16)
_POLL_CONN: Optional[http.client.HTTPSConnection] = None
_POLL_LOCK = threading.Lock()
_BG_CONN: Optional[http.client.HTTPSConnection] = None
_BG_QUEUE: "queue.Queue[Tuple[str, Dict[str, Any]]]" = queue.Queue()

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "uz-UZ,uz;q=0.9,ru;q=0.8,en;q=0.7",
}


def _create_fast_https_conn(timeout_sec: float = 3.5) -> http.client.HTTPSConnection:
    conn = http.client.HTTPSConnection("api.telegram.org", 443, timeout=timeout_sec, context=_SSL_CTX)
    conn.connect()
    if conn.sock:
        try:
            conn.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            conn.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception:
            pass
    return conn


def _is_conn_alive(conn: Optional[http.client.HTTPSConnection], created_ts: float = 0.0) -> bool:
    if conn is None or conn.sock is None:
        return False
    if created_ts > 0 and (time.time() - created_ts) > 45.0:
        return False
    try:
        r, _, _ = select.select([conn.sock], [], [], 0.0)
        if r:
            return False
        return True
    except Exception:
        return False


def _prewarm_connections(target_count: int = 4) -> None:
    valid_items: List[Tuple[http.client.HTTPSConnection, float]] = []
    while True:
        try:
            conn, ts = _API_CONN_POOL.get_nowait()
            if _is_conn_alive(conn, ts):
                valid_items.append((conn, ts))
            else:
                try:
                    conn.close()
                except Exception:
                    pass
        except queue.Empty:
            break
    while len(valid_items) < target_count:
        try:
            valid_items.append((_create_fast_https_conn(3.5), time.time()))
        except Exception:
            break
    for item in valid_items:
        try:
            _API_CONN_POOL.put_nowait(item)
        except queue.Full:
            try:
                item[0].close()
            except Exception:
                pass


def _conn_warmer_worker() -> None:
    while True:
        time.sleep(15)
        try:
            _prewarm_connections(4)
        except Exception:
            pass


def _borrow_alive_api_conn() -> http.client.HTTPSConnection:
    while True:
        try:
            conn, ts = _API_CONN_POOL.get_nowait()
            if _is_conn_alive(conn, ts):
                return conn
            try:
                conn.close()
            except Exception:
                pass
        except queue.Empty:
            return _create_fast_https_conn(3.5)


def _send_telegram_http(method: str, body_bytes: bytes, headers: Dict[str, str], is_poll: bool) -> Dict[str, Any]:
    global _POLL_CONN
    path = f"/bot{API_KEY}/{method}"
    if is_poll:
        with _POLL_LOCK:
            for attempt in range(2):
                try:
                    if not _is_conn_alive(_POLL_CONN):
                        if _POLL_CONN:
                            try:
                                _POLL_CONN.close()
                            except Exception:
                                pass
                        _POLL_CONN = _create_fast_https_conn(25.0)
                    _POLL_CONN.request("POST", path, body=body_bytes, headers=headers)
                    resp = _POLL_CONN.getresponse()
                    raw_resp = resp.read().decode("utf-8", errors="replace")
                    return json.loads(raw_resp)
                except Exception as exc:
                    try:
                        if _POLL_CONN:
                            _POLL_CONN.close()
                    except Exception:
                        pass
                    _POLL_CONN = None
                    if attempt == 1:
                        return {"ok": False, "description": str(exc)}
        return {"ok": False}

    for attempt in range(2):
        conn: Optional[http.client.HTTPSConnection] = None
        try:
            conn = _borrow_alive_api_conn() if attempt == 0 else _create_fast_https_conn(3.5)
            conn.request("POST", path, body=body_bytes, headers=headers)
            resp = conn.getresponse()
            raw_resp = resp.read().decode("utf-8", errors="replace")
            try:
                _API_CONN_POOL.put_nowait((conn, time.time()))
            except queue.Full:
                conn.close()
            res_json = json.loads(raw_resp)
            if not res_json.get("ok") and method not in ("answerCallbackQuery", "deleteMessage"):
                print(f"[Telegram API ogohlantirishi] {method}: {res_json.get('description', res_json)}")
            return res_json
        except Exception as exc:
            try:
                if conn:
                    conn.close()
            except Exception:
                pass
            if attempt == 1:
                return {"ok": False, "description": str(exc)}
    return {"ok": False}


def bot(method: str, datas: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Telegram Bot API ga tayyor Keep-Alive havza orqali bir zumda so'rov yuboradi."""
    if not API_KEY or API_KEY in ("TOKEN", "TOKEN_SHU_YERGA_YOZILADI"):
        return {"ok": False, "description": "BOT_TOKEN o'rnatilmagan"}

    payload_dict: Dict[str, Any] = {}
    if datas:
        for k, v in datas.items():
            if v is not None and v != "":
                if k == "reply_markup" and isinstance(v, str):
                    try:
                        parsed_rm = json.loads(v) if v else None
                        if parsed_rm:
                            payload_dict[k] = parsed_rm
                    except Exception:
                        payload_dict[k] = v
                else:
                    payload_dict[k] = v

    if method == "answerCallbackQuery" and not payload_dict.get("show_alert") and not payload_dict.get("text"):
        _BG_QUEUE.put((method, payload_dict))
        return {"ok": True}

    body_bytes = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body_bytes)),
        "Connection": "keep-alive",
    }
    return _send_telegram_http(method, body_bytes, headers, is_poll=(method == "getUpdates"))


def _bg_worker() -> None:
    """deleteMessage va answerCallbackQuery so'rovlarini alohida soketda fonda bajaradi."""
    global _BG_CONN
    while True:
        try:
            method, payload_dict = _BG_QUEUE.get()
            if method == "deleteMessage":
                time.sleep(0.03)
            body_bytes = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
            path = f"/bot{API_KEY}/{method}"
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "Content-Length": str(len(body_bytes)),
                "Connection": "keep-alive",
            }
            for attempt in range(2):
                try:
                    if not _is_conn_alive(_BG_CONN):
                        if _BG_CONN:
                            try:
                                _BG_CONN.close()
                            except Exception:
                                pass
                        _BG_CONN = _create_fast_https_conn(3.5)
                    _BG_CONN.request("POST", path, body=body_bytes, headers=headers)
                    resp = _BG_CONN.getresponse()
                    resp.read()
                    break
                except Exception:
                    try:
                        if _BG_CONN:
                            _BG_CONN.close()
                    except Exception:
                        pass
                    _BG_CONN = None
        except Exception:
            pass


def start_network_workers() -> None:
    threading.Thread(target=_bg_worker, daemon=True).start()
    _prewarm_connections(4)
    threading.Thread(target=_conn_warmer_worker, daemon=True).start()


def http_get(url: str, extra_headers: Optional[Dict[str, str]] = None) -> str:
    """To'liq Chrome User-Agent bilan SSL tekshiruvisiz tezkor HTTP GET so'rovi."""
    if not url or not url.startswith("http"):
        return ""
    hdrs = dict(_BROWSER_HEADERS)
    if extra_headers:
        hdrs.update(extra_headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, context=_UNVERIFIED_SSL_CTX, timeout=5) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


set_http_get_handler(http_get)


def api_query(url: str) -> str:
    content = http_get(url)
    return content if content else json.dumps({"balance": " ?"})


_CACHED_BOT_USERNAME: Optional[str] = None


def get_bot_username() -> str:
    global _CACHED_BOT_USERNAME
    if _CACHED_BOT_USERNAME:
        return _CACHED_BOT_USERNAME
    if config.BOT_USERNAME and config.BOT_USERNAME != "special_smm_bot":
        _CACHED_BOT_USERNAME = config.BOT_USERNAME
        return _CACHED_BOT_USERNAME
    res = bot("getMe")
    if res.get("ok") and isinstance(res.get("result"), dict):
        _CACHED_BOT_USERNAME = res["result"].get("username", config.BOT_USERNAME)
        return _CACHED_BOT_USERNAME
    return config.BOT_USERNAME


def trans(text: str) -> str:
    if not text:
        return ""
    url = (
        "http://translate.googleapis.com/translate_a/single?client=gtx&sl=auto&tl=uz&dt=t&q="
        + urllib.parse.quote(text)
    )
    raw = http_get(url)
    try:
        parsed = json.loads(raw)
        return parsed[0][0][0]
    except Exception:
        return text


def del_msg(chat_id: Union[str, int], message_id: Union[str, int]) -> Dict[str, Any]:
    if chat_id and message_id:
        _BG_QUEUE.put(("deleteMessage", {"chat_id": chat_id, "message_id": message_id}))
    return {"ok": True}


def edit(
    chat_id: Union[str, int],
    message_id: Union[str, int],
    text: str,
    reply_markup: Optional[str] = None,
) -> Dict[str, Any]:
    return bot(
        "editMessageText",
        {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": reply_markup,
        },
    )


def sms(
    chat_id: Union[str, int],
    text: str,
    reply_markup: Optional[str] = None,
) -> Dict[str, Any]:
    return bot(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
            "reply_markup": reply_markup,
        },
    )


BOT_CODE_PRICE = 70000.0


_HOSTED_BOT_PROCS: Dict[int, subprocess.Popen] = {}
_HOSTED_LOCK = threading.RLock()


def get_clean_bot_code_bytes() -> bytes:
    """Asosiy bot kodining toza nusxasini (tokenlarsiz) qaytaradi."""
    try:
        with open(os.path.abspath(__file__), "r", encoding="utf-8", errors="replace") as f:
            src = f.read()
        if API_KEY and API_KEY not in ("TOKEN", "TOKEN_SHU_YERGA_YOZILADI"):
            src = src.replace(API_KEY, "TOKEN_SHU_YERGA_YOZILADI")
        if ADMIN and ADMIN not in ("ADMIN_ID", "ADMIN_ID_SHU_YERGA_YOZILADI") and len(ADMIN) > 4:
            src = src.replace(f'"{ADMIN}"', '"ADMIN_ID_SHU_YERGA_YOZILADI"')
        return src.encode("utf-8")
    except Exception:
        return b"# Telegram SMM Bot Code\n"


def validate_telegram_bot_token(token_str: str) -> Optional[Dict[str, Any]]:
    """@BotFather tokenini getMe orqali tekshiradi va bot ma'lumotlarini qaytaradi."""
    t_clean = token_str.strip()
    if ":" not in t_clean or len(t_clean) < 20:
        return None
    raw = http_get(f"https://api.telegram.org/bot{t_clean}/getMe")
    try:
        data = json.loads(raw)
        if data.get("ok") and isinstance(data.get("result"), dict):
            return data["result"]
    except Exception:
        pass
    return None


def download_telegram_file_bytes(file_id: str) -> Optional[bytes]:
    """Foydalanuvchi yuborgan .py faylni Telegram serveridan yuklab oladi."""
    res = bot("getFile", {"file_id": file_id})
    if not res.get("ok") or not isinstance(res.get("result"), dict):
        return None
    f_path = res["result"].get("file_path", "")
    if not f_path:
        return None
    url = f"https://api.telegram.org/file/bot{API_KEY}/{f_path}"
    req = urllib.request.Request(url, headers=_BROWSER_HEADERS)
    try:
        with urllib.request.urlopen(req, context=_UNVERIFIED_SSL_CTX, timeout=15) as resp:
            return resp.read()
    except Exception:
        return None


def _stop_hosted_bot_proc(bot_id: int) -> None:
    with _HOSTED_LOCK:
        proc = _HOSTED_BOT_PROCS.pop(int(bot_id), None)
        if proc:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass


def _is_hosted_bot_running(bot_id: int) -> bool:
    with _HOSTED_LOCK:
        proc = _HOSTED_BOT_PROCS.get(int(bot_id))
        return bool(proc and proc.poll() is None)


def deploy_and_start_hosted_bot(bot_row: Dict[str, Any], custom_py_bytes: Optional[bytes] = None) -> bool:
    """Foydalanuvchi botini (SMM Bot yoki Server Tarif botini) avtomatik sozlab, fonda ishga tushiradi."""
    bot_id = int(bot_row["id"])
    _stop_hosted_bot_proc(bot_id)

    bot_dir = os.path.join(config.HOSTED_BOTS_DIR, f"bot_{bot_id}")
    os.makedirs(os.path.join(bot_dir, "user"), exist_ok=True)
    os.makedirs(os.path.join(bot_dir, "set"), exist_ok=True)

    b_token = str(bot_row.get("bot_token", "")).strip()
    b_admin = str(bot_row.get("bot_admin_id", "")).strip()
    b_uname = str(bot_row.get("bot_username", "")).strip().lstrip("@")
    runner_path = os.path.join(bot_dir, "runner_bot.py")

    if custom_py_bytes is not None:
        with open(runner_path, "wb") as f:
            f.write(custom_py_bytes)
    elif not os.path.exists(runner_path) or bot_row.get("bot_category") == "smm":
        # Asosiy SMM bot dvigatelidan avtomatik sozlangan nusxa yaratamiz (kod foydalanuvchiga berilmaydi!)
        base_src = get_clean_bot_code_bytes().decode("utf-8", errors="replace")
        # Child bot o'z tokeni, o'z admin IDsi va o'z username'i bilan ishlaydi
        base_src = base_src.replace(
            'BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKEN_SHU_YERGA_YOZILADI")',
            f'BOT_TOKEN = "{b_token}"',
        )
        base_src = base_src.replace(
            'ADMIN_ID = os.getenv("ADMIN_ID", "ADMIN_ID_SHU_YERGA_YOZILADI")',
            f'ADMIN_ID = "{b_admin}"',
        )
        base_src = base_src.replace(
            'BOT_USERNAME = os.getenv("BOT_USERNAME", "special_smm_bot")',
            f'BOT_USERNAME = "{b_uname}"',
        )
        base_src = base_src.replace(
            'PORT = int(os.getenv("PORT", "8000"))',
            'PORT = 0',
        )
        with open(runner_path, "w", encoding="utf-8") as f:
            f.write(base_src)

    put_file_admin = os.path.join(bot_dir, "set", "admin_id.txt")
    try:
        with open(put_file_admin, "w", encoding="utf-8") as af:
            af.write(b_admin)
    except Exception:
        pass

    env = os.environ.copy()
    env["BOT_TOKEN"] = b_token
    env["ADMIN_ID"] = b_admin
    env["BOT_USERNAME"] = b_uname
    env["PORT"] = "0"

    try:
        log_file = open(os.path.join(bot_dir, "bot.log"), "a", encoding="utf-8")
        proc = subprocess.Popen(
            [sys.executable, runner_path],
            cwd=bot_dir,
            env=env,
            stdout=log_file,
            stderr=log_file,
        )
        with _HOSTED_LOCK:
            _HOSTED_BOT_PROCS[bot_id] = proc
        database.execute("UPDATE `hosted_bots` SET `status` = 'active', `script_path` = ? WHERE `id` = ?", (runner_path, bot_id))
        return True
    except Exception as exc:
        print(f"[Hosted Bot xatoligi #{bot_id}]: {exc}")
        return False


def restore_all_active_hosted_bots() -> None:
    """Asosiy bot yonganda barcha faol mijoz botlarini avtomatik ishga tushiradi."""
    try:
        rows = database.fetch_all("SELECT * FROM `hosted_bots` WHERE `status` = 'active'")
        now_ts = time.time()
        for r in rows:
            if float(r.get("expires_ts") or 0) > now_ts:
                deploy_and_start_hosted_bot(r)
    except Exception as exc:
        print(f"[Hosted bots restore]: {exc}")


def check_hosted_bots_expiry() -> None:
    """Har daqiqada serverdagi botlar muddatini tekshiradi: muddati tugasa avto-uzaytiradi yoki to'xtatadi."""
    rows = database.fetch_all("SELECT * FROM `hosted_bots` WHERE `status` = 'active'")
    now_ts = time.time()
    for r in rows:
        exp_ts = float(r.get("expires_ts") or 0)
        if exp_ts > 0 and now_ts >= exp_ts:
            b_id = int(r["id"])
            owner_id = str(r["owner_id"])
            m_price = float(r.get("monthly_price") or 10000)
            u_row = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (owner_id,)) or {}
            u_bal = float(u_row.get("balance") or 0)
            b_uname = r.get("bot_username", "")
            if u_bal >= m_price:
                new_bal = round(u_bal - m_price, 2)
                new_exp_ts = now_ts + (30 * 86400)
                new_exp_str = datetime.datetime.fromtimestamp(new_exp_ts).strftime("%Y.%m.%d %H:%M")
                database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_bal), owner_id))
                database.execute(
                    "UPDATE `hosted_bots` SET `expires_ts` = ?, `expires_str` = ?, `is_trial` = 0 WHERE `id` = ?",
                    (new_exp_ts, new_exp_str, b_id),
                )
                sms(
                    owner_id,
                    f"🔄 <b>Serverdagi @{b_uname} botingiz muddati avtomatik 30 kunga uzaytirildi!</b>\n"
                    f"💵 Hisobingizdan yechildi: <b>{fmt_money(m_price)} so‘m</b>\n"
                    f"⏳ Yangi muddat: <code>{new_exp_str}</code> gacha",
                )
            else:
                _stop_hosted_bot_proc(b_id)
                database.execute("UPDATE `hosted_bots` SET `status` = 'expired' WHERE `id` = ?", (b_id,))
                sms(
                    owner_id,
                    f"⚠️ <b>Diqqat! @{b_uname} botingizning faol (yoki 7 kunlik tekin) muddati tugadi!</b>\n\n"
                    f"🔴 Botingiz vaqtincha to‘xtatildi.\n"
                    f"💰 Oyiga: <b>{fmt_money(m_price)} so‘m</b>\n"
                    f"👉 Davom ettirish uchun hisobingizni to‘ldirib, <b>🤝 Hamkorlik dasturi ➡️ 🤖 Bo‘t yaratish ➡️ 📂 Mening bo‘tlarim</b> bo‘limidan uzaytiring!",
                )


def send_document(
    chat_id: Union[str, int],
    file_bytes: bytes,
    filename: str,
    caption: str = "",
    reply_markup: Optional[str] = None,
) -> Dict[str, Any]:
    """Telegram Bot API orqali fayl (document) yuboradi (multipart/form-data)."""
    if not API_KEY or API_KEY in ("TOKEN", "TOKEN_SHU_YERGA_YOZILADI"):
        return {"ok": False, "description": "BOT_TOKEN o'rnatilmagan"}
    boundary = f"----TelegramBotBoundary{uuid.uuid4().hex}"
    parts: List[bytes] = []

    def _add_field(name: str, val: str) -> None:
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{val}\r\n".encode("utf-8")
        )

    _add_field("chat_id", str(chat_id))
    _add_field("parse_mode", "HTML")
    if caption:
        _add_field("caption", caption)
    if reply_markup:
        _add_field("reply_markup", reply_markup)

    parts.append(
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="document"; filename="{filename}"\r\n'
        f"Content-Type: text/x-python; charset=utf-8\r\n\r\n".encode("utf-8")
    )
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body_bytes = b"".join(parts)
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body_bytes)),
        "Connection": "keep-alive",
    }
    return _send_telegram_http("sendDocument", body_bytes, headers, is_poll=False)


def arr(provider_id: Union[str, int]) -> Dict[str, Any]:
    s = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (provider_id,))
    if not s:
        return {"error": 1}
    raw = http_get(f"{s['api_url']}?key={s['api_key']}&action=services")
    try:
        data = json.loads(raw)
    except Exception:
        return {"error": 1}
    if not isinstance(data, list):
        return {"error": 1}

    values = []
    seen = []
    co = 0
    for value in data:
        if isinstance(value, dict):
            cat = value.get("category")
            if cat and cat not in seen:
                seen.append(cat)
                co += 1
                values.append({"id": co, "name": cat})
    return {"count": co, "results": values} if values else {"error": 1}


def referal_top(limit: int = 10) -> str:
    rev: List[tuple] = []
    for path in glob.glob(os.path.join(config.USER_DIR, "*.users")):
        uid = os.path.basename(path).replace(".users", "")
        try:
            with open(path, "r", encoding="utf-8") as f:
                cnt = float(f.read().strip() or "0")
        except ValueError:
            cnt = 0.0
        rev.append((cnt, uid))

    rev.sort(key=lambda x: x[0], reverse=True)
    lines = []
    for i, (cnt, uid) in enumerate(rev[:limit], start=1):
        chat_res = bot("getChat", {"chat_id": uid})
        ism = (
            chat_res.get("result", {}).get("first_name", f"User {uid}")
            if isinstance(chat_res.get("result"), dict)
            else f"User {uid}"
        )
        lines.append(
            f"<b>{i}</b>. <a href='tg://user?id={uid}'>{ism}</a> - <code>{int(cnt)}</code> <b> ta</b>"
        )
    return "\n".join(lines) if lines else "Hozircha ishtirokchilar yo'q."


top_raiting = referal_top

_JOINCHAT_CACHE: Dict[str, float] = {}


def joinchat(user_id: Union[str, int]) -> bool:
    uid_str = str(user_id)
    if uid_str == ADMIN:
        return True
    ch_text = (get_file("set/channel").strip() or get_file("set/channel.txt").strip())
    if not ch_text:
        return True
    now_ts = time.time()
    if _JOINCHAT_CACHE.get(uid_str, 0.0) > now_ts:
        return True
    channels = [line.strip() for line in ch_text.split("\n") if line.strip()]
    if not channels:
        return True

    inline_kb: List[List[Dict[str, str]]] = []
    uns = False
    for ch in channels:
        clean_ch = ch.lstrip("@")
        ret = bot("getChatMember", {"chat_id": f"@{clean_ch}", "user_id": user_id})
        stat = (
            ret.get("result", {}).get("status", "")
            if isinstance(ret.get("result"), dict)
            else ""
        )
        if stat in ("creator", "administrator", "member"):
            inline_kb.append([{"text": f"✅ @{clean_ch}", "url": f"https://t.me/{clean_ch}"}])
        else:
            inline_kb.append([{"text": f"❌ @{clean_ch}", "url": f"https://t.me/{clean_ch}"}])
            uns = True

    inline_kb.append([{"text": "🔄 Tekshirish", "callback_data": "result"}])
    if uns:
        _JOINCHAT_CACHE.pop(uid_str, None)
        bot(
            "sendMessage",
            {
                "chat_id": user_id,
                "text": "⚠️ <b>Botdan foydalanish uchun, quyidagi kanallarga obuna bo'ling:</b>",
                "parse_mode": "HTML",
                "reply_markup": json.dumps({"inline_keyboard": inline_kb}, ensure_ascii=False),
            },
        )
        return False
    _JOINCHAT_CACHE[uid_str] = time.time() + 120.0
    return True

# ============================================================================
# 4-BO'LIM: KEYBOARDS (Barcha Menyular va Davlatlar Ro'yxati)
# ============================================================================

"""
4-MODUL: keyboards.py — Barcha Reply va Inline klaviaturalar hamda SMS-Activate davlatlar ro'yxati.
"""
import json
from typing import Any, Dict, List, Optional, Union



def keyboard(inline_rows: List[List[Dict[str, Any]]]) -> str:
    """Inline klaviatura JSON satrini qaytaradi."""
    return json.dumps({"inline_keyboard": inline_rows}, ensure_ascii=False)


def reply_keyboard(rows: List[List[Dict[str, Any]]], resize: bool = True) -> str:
    """Oddiy (Reply) klaviatura JSON satrini qaytaradi."""
    return json.dumps({"resize_keyboard": resize, "keyboard": rows}, ensure_ascii=False)


def chunk_list(items: List[Any], size: int) -> List[List[Any]]:
    """PHP array_chunk analogi."""
    if size <= 0:
        return [items]
    return [items[i : i + size] for i in range(0, len(items), size)]


ORT_KB = reply_keyboard([[{"text": "➡️ Orqaga"}]])
ORDER_ORT_KB = reply_keyboard([[{"text": "❌ Bekor qilish"}, {"text": "➡️ Orqaga"}]])
BALANS_KB = keyboard([[{"text": "💳 Pul kiritish", "callback_data": "menu=tolov"}, {"text": "💾 Saqlanganlar", "callback_data": "menu=saved"}]])
AORT_KB = reply_keyboard([[{"text": "🗄️ Boshqaruv"}]])

PANEL_KB = reply_keyboard([
    [{"text": "⚙️ Asosiy sozlamalar"}, {"text": "💳 Hamyonlar sozlamalari"}],
    [{"text": "💵 Pul ishlash sozlamalari"}],
    [{"text": "🔔 Xabar yuborish"}, {"text": "📊 Statistika"}],
    [{"text": "👤 Foydalanuvchini boshqarish"}],
    [{"text": "🇺🇿 Valyuta kursi"}, {"text": "⏰ Cron sozlamasi"}],
    [{"text": "⏪ Orqaga"}],
])

PANEL2_KB = reply_keyboard([
    [{"text": "🛍 Buyurtmalarni sozlash"}],
    [{"text": "💵 Kursni o‘rnatish"}, {"text": "⚖️ Foizni o‘rnatish"}],
    [{"text": "📊 Buyurtmani tekshirish"}],
    [{"text": "📎 Majburiy obunalar"}, {"text": "🔑 API Sozlamalari"}],
    [{"text": "⚙️ Boshqa sozlamalar"}],
    [{"text": "🗄️ Boshqaruv"}],
])

MENU_USER_KB = reply_keyboard([
    [{"text": "➕ Buyurtma berish"}],
    [{"text": "🛒 Buyurtmalar"}, {"text": "💵 Pul ishlash"}],
    [{"text": "💳 Balans"}, {"text": "💳 Pul kiritish"}],
    [{"text": "☎️ Yordam"}, {"text": "🤝 Hamkorlik dasturi"}],
])

MENU_ADMIN_KB = reply_keyboard([
    [{"text": "➕ Buyurtma berish"}],
    [{"text": "🛒 Buyurtmalar"}, {"text": "💵 Pul ishlash"}],
    [{"text": "💳 Balans"}, {"text": "💳 Pul kiritish"}],
    [{"text": "☎️ Yordam"}, {"text": "🤝 Hamkorlik dasturi"}],
    [{"text": "🗄️ Boshqaruv"}],
])

# ============================================================================
# 5-BO'LIM: SERVICES (Payme P2P, Cron, Avto- Yangilash va API v2 Server)
# ============================================================================

"""
5-MODUL: services.py — Payme P2P, SMM Provayder narx sinxronizatsiyasi, Cron va API v2 serveri.
"""
import datetime
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable, Dict, List



def handle_payme_request(params: Dict[str, str]) -> Dict[str, Any]:
    act = params.get("action", "")
    sum_val = params.get("sum", "0")
    cheque_id = params.get("id", "")
    my_card = params.get("card", "")
    desc = params.get("desc", "")

    if act == "create":
        try:
            sum_float = float(sum_val)
        except ValueError:
            sum_float = 0.0
        sum1 = int(sum_float * 100)
        payload = json.dumps({
            "method": "p2p.create",
            "params": {"card_id": my_card, "amount": sum1, "description": desc},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://payme.uz/api/p2p.create",
            data=payload,
            headers={
                "device": "6Fk1rB;",
                "user-agent": "Mozilla/57.36",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            res = {"error": str(exc)}

        cid = res.get("result", {}).get("cheque", {}).get("_id", "")
        csv_data = {
            "_id": cid,
            "_url": "https://checkout.paycom.uz",
            "_pay_amount": f"{sum_val} UZS",
            "_pay_url": f"https://checkout.paycom.uz/{cid}" if cid else "https://checkout.paycom.uz/",
        }
        return {"_result": {"_details": csv_data}}

    if act == "info":
        payload = json.dumps({
            "method": "cheque.get",
            "params": {"id": cheque_id},
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://payme.uz/api/cheque.get",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                res = json.loads(resp.read().decode("utf-8"))
        except Exception:
            res = {}
        pay_time = res.get("result", {}).get("cheque", {}).get("pay_time")
        return {"mess": pay_time}

    return {"error": "Unknown action"}


def synchronize_services() -> Dict[str, Any]:
    updates: List[Dict[str, Any]] = []
    services = database.fetch_all("SELECT * FROM `services` WHERE `service_edit` = 'true'")
    percent_row = database.fetch_one("SELECT * FROM `percent` WHERE `id` = 1")
    try:
        foiz = float(percent_row["percent"]) if percent_row else 40.0
    except ValueError:
        foiz = 40.0

    for do in services:
        prv = do.get("api_service")
        if not prv:
            continue
        provider = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (prv,))
        if not provider:
            continue

        aurl = provider["api_url"]
        akey = provider["api_key"]
        curr = provider["curr"]
        service_api = str(do["service_api"])
        doi = do["service_id"]

        curr_file = os.path.join(config.SET_DIR, str(curr))
        rate = 1.0
        if curr_file and os.path.exists(curr_file):
            try:
                with open(curr_file, "r", encoding="utf-8") as f:
                    rate = float(f.read().strip() or "1")
            except Exception:
                rate = 1.0

        req_url = f"{aurl}?key={urllib.parse.quote(akey)}&action=services"
        try:
            req = urllib.request.Request(req_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                serv_list = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            continue

        if isinstance(serv_list, list):
            for item in serv_list:
                if str(item.get("service")) == service_api:
                    try:
                        api_rate = float(item.get("rate", 0))
                    except ValueError:
                        api_rate = 0.0
                    base_price = api_rate * rate
                    up = (base_price / 100.0) * foiz
                    rp = round(base_price + up, 2)
                    min_val = str(item.get("min", do["service_min"]))
                    max_val = str(item.get("max", do["service_max"]))
                    database.execute(
                        """UPDATE `services`
                        SET `service_price` = ?, `service_min` = ?, `service_max` = ?
                        WHERE `service_id` = ?""",
                        (str(rp), min_val, max_val, doi),
                    )
                    updates.append({
                        "service_id": doi,
                        "new_order_price": rp,
                        "new_order_min": min_val,
                        "new_order_max": max_val,
                    })

    return {"status": True, "cron": "Synchronize service: min, max, price", "updates": updates}


def cron_send() -> Dict[str, Any]:
    """Ommaviy xabar yuborish cron vazifasi (?update=send)."""
    row = database.fetch_one("SELECT * FROM `send` LIMIT 1")
    if not row:
        return {"status": True, "cron": "No active broadcast"}

    now_hm = datetime.datetime.now().strftime("%H:%M")
    scheduled_times = {
        row.get("time1"), row.get("time2"), row.get("time3"), row.get("time4"), row.get("time5")
    }
    start_id = int(row.get("start_id") or 0)
    stop_id = str(row.get("stop_id") or "")
    admin_id = str(row.get("admin_id") or ADMIN)
    mied = int(row.get("message_id") or 0)
    tugma = row.get("reply_markup") or ""
    reply_markup = "" if tugma in ("bnVsbA==", "null", "") else enc("decode", tugma)
    limit = 150

    if now_hm in scheduled_times:
        users = database.fetch_all(f"SELECT * FROM `users` LIMIT {start_id}, {limit}")
        for a in users:
            uid = str(a["id"])
            bot(
                "copyMessage",
                {
                    "chat_id": uid,
                    "from_chat_id": admin_id,
                    "message_id": mied,
                    "disable_web_page_preview": True,
                    "reply_markup": reply_markup if reply_markup else None,
                },
            )
            if uid == stop_id:
                sms(admin_id, "<b>✅ ️Xabar barcha bot foydalanuvchilariga yuborildi!</b>")
                database.execute("DELETE FROM `send`")
                return {"status": True, "cron": "Broadcast completed"}

        now = datetime.datetime.now()
        t1 = (now + datetime.timedelta(minutes=1)).strftime("%H:%M")
        t2 = (now + datetime.timedelta(minutes=2)).strftime("%H:%M")
        t3 = (now + datetime.timedelta(minutes=3)).strftime("%H:%M")
        t4 = (now + datetime.timedelta(minutes=4)).strftime("%H:%M")
        t5 = (now + datetime.timedelta(minutes=5)).strftime("%H:%M")
        next_start = start_id + limit
        database.execute(
            """UPDATE `send`
            SET `time1`=?, `time2`=?, `time3`=?, `time4`=?, `time5`=?, `start_id`=?""",
            (t1, t2, t3, t4, t5, str(next_start)),
        )
        sms(admin_id, f"<b>✅ Yuborildi: {next_start}</b>")

    return {"status": True, "cron": "Sending message"}


def cron_status() -> Dict[str, Any]:
    """Buyurtmalar holatini provayderdan tekshirish cron vazifasi (?update=status)."""
    orders_rows = database.fetch_all("SELECT * FROM `orders`")
    for mys in orders_rows:
        if mys.get("status") in ("Canceled", "Completed"):
            continue
        prv = mys.get("provider")
        api_order = mys.get("api_order")
        uorder = mys.get("order_id")

        mysa = database.fetch_one("SELECT * FROM `myorder` WHERE `order_id` = ?", (uorder,))
        if not mysa:
            continue
        adm = mysa.get("user_id")
        try:
            retail = float(mysa.get("retail") or 0)
        except ValueError:
            retail = 0.0

        m = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (prv,))
        if not m:
            continue
        sav = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
        raw = http_get(f"{m['api_url']}?key={m['api_key']}&action=status&order={api_order}")
        try:
            j = json.loads(raw)
        except Exception:
            continue

        status = j.get("status")
        if status:
            database.execute("UPDATE `orders` SET `status` = ? WHERE `order_id` = ?", (status, uorder))
            database.execute(
                "UPDATE `myorder` SET `status` = ?, `last_check` = ? WHERE `order_id` = ?",
                (status, sav, uorder),
            )

        if "error" in j:
            database.execute("DELETE FROM `myorder` WHERE `order_id` = ?", (uorder,))
        elif status == "Completed":
            sms(adm, f"✅ Sizning {uorder} raqamli buyurtmangiz bajarildi")
        elif status == "Canceled":
            sms(
                adm,
                f"❌ Sizning {uorder} raqamli buyurtmangiz bekor qilindi\n\n💳 Hisobingizga {retail} so‘m qaytarildi",
            )
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (str(adm),))
            if rew:
                try:
                    cur_bal = float(rew.get("balance") or 0)
                except ValueError:
                    cur_bal = 0.0
                new_bal = cur_bal + retail
                database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (str(new_bal), str(adm)))

    return {"status": True, "cron": "Orders status"}


def _get_order_And_user_stats() -> Dict[str, int]:
    users = database.fetch_all("SELECT * FROM `users`")
    orders = database.fetch_all("SELECT * FROM `orders`")
    stats = {
        "users_total": len(users),
        "users_active": sum(1 for u in users if u.get("status") == "active"),
        "users_deactive": sum(1 for u in users if u.get("status") == "deactive"),
        "orders_total": len(orders),
        "Pending": 0,
        "Completed": 0,
        "Canceled": 0,
        "Failed": 0,
        "In progress": 0,
        "Partial": 0,
        "Processing": 0,
        "services_total": database.count_rows("services"),
    }
    for o in orders:
        st = o.get("status", "")
        if st in stats:
            stats[st] += 1
    return stats


def _cron_worker() -> None:
    """Har 60 soniyada xabar yuborish, buyurtma holati va xizmat narxlarini yangilaydi."""
    while True:
        time.sleep(60)
        try:
            cron_send()
            cron_status()
            synchronize_services()
            check_hosted_bots_expiry()
        except Exception:
            pass


def handle_api_v2(params: Dict[str, Any]) -> Any:
    """app/controller/api.php mantiqi (balance, add, services, orders, status)."""
    key = str(params.get("key", ""))
    service = str(params.get("service", ""))
    action = str(params.get("action", ""))
    link = str(params.get("link", ""))
    order = str(params.get("order", ""))
    orders_param = params.get("orders")
    quantity_raw = params.get("quantity", "0")

    if action == "balance":
        res = database.fetch_one("SELECT * FROM `users` WHERE `api_key` = ?", (key,))
        if res:
            return {"balance": res["balance"], "currency": "UZS"}
        return {"error": "Incorrect API key"}

    if action == "add":
        res = database.fetch_one("SELECT * FROM `users` WHERE `api_key` = ? AND `status` = 'active'", (key,))
        if not res:
            return {"error": "invalid API key"}
        resy = database.fetch_one("SELECT * FROM `services` WHERE `service_id` = ? AND `service_status` = 'on'", (service,))
        if not resy:
            return {"error": "Incorrect service ID"}
        if not link:
            return {"error": "Bad link"}
        try:
            quantity = float(quantity_raw)
            s_min = float(resy.get("service_min", 0))
            s_max = float(resy.get("service_max", 0))
            s_price = float(resy.get("service_price", 0))
            u_balance = float(res.get("balance", 0))
        except (ValueError, TypeError):
            return {"error": "Invalid quantity"}

        if quantity < s_min:
            return {"error": f"Quantity less than minimal {resy['service_min']}"}
        if quantity > s_max:
            return {"error": f"Quantity less than maximum {resy['service_max']}"}
        narxi = (s_price / 1000.0) * quantity
        if u_balance < narxi:
            return {"error": "Not enough funds on balance"}

        api_id = resy.get("api_service")
        m = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (api_id,))
        if not m:
            return {"error": "Unknown error, please try again later"}
        query_url = (
            f"{m['api_url']}?key={urllib.parse.quote(str(m['api_key']))}"
            f"&action=add&service={urllib.parse.quote(str(resy['service_api']))}"
            f"&link={urllib.parse.quote(link)}"
            f"&quantity={int(quantity) if quantity == int(quantity) else quantity}"
        )
        try:
            j = json.loads(http_get(query_url) or "{}")
        except Exception:
            j = {}
        jid = j.get("order")
        if not jid:
            return {"error": "Unknown error, please try again later"}

        order_id = database.count_rows("orders") + 1
        ball = u_balance - narxi
        sav = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
        database.execute("UPDATE `users` SET `balance` = ? WHERE `api_key` = ?", (str(ball), key))
        database.execute(
            "INSERT INTO `myorder` (`order_id`, `user_id`, `retail`, `status`, `service`, `order_create`, `last_check`) VALUES (?, ?, ?, 'Pending', ?, ?, ?)",
            (order_id, str(res["id"]), str(narxi), service, sav, sav),
        )
        database.execute(
            "INSERT INTO `orders` (`api_order`, `order_id`, `provider`, `status`) VALUES (?, ?, ?, 'Pending')",
            (str(jid), order_id, str(api_id)),
        )
        return {"order": order_id, "charge": narxi, "currency": "UZS"}

    if action == "services":
        res = database.fetch_one("SELECT * FROM `users` WHERE `api_key` = ?", (key,))
        if not res:
            return {"error": "Incorrect API key"}
        rows = database.fetch_all("SELECT * FROM `services`")
        arr_out = []
        for a in rows:
            cid = a.get("category_id")
            ca = database.fetch_one("SELECT * FROM `cates` WHERE `cate_id` = ?", (cid,)) if cid else None
            categ = ca.get("category_id") if ca else ""
            cas = database.fetch_one("SELECT * FROM `categorys` WHERE `category_id` = ?", (categ,)) if categ else None
            cat_name = enc("decode", cas.get("category_name")) if cas else ""
            sub_name = enc("decode", ca.get("name")) if ca else ""
            try:
                detail = json.loads(a.get("api_detail") or "{}")
            except Exception:
                detail = {}
            arr_out.append({
                "service": a.get("service_id"),
                "category": f"{cat_name} {sub_name}".strip(),
                "name": enc("decode", a.get("service_name")),
                "rate": a.get("service_price"),
                "min": a.get("service_min"),
                "max": a.get("service_max"),
                "type": a.get("service_type"),
                "refill": detail.get("refill"),
                "cancel": detail.get("cancel"),
                "dripfeed": detail.get("dripfeed"),
            })
        return arr_out

    if action == "orders":
        res = database.fetch_one("SELECT * FROM `users` WHERE `api_key` = ?", (key,))
        if not res:
            return {"error": "Incorrect API Key"}
        rows = database.fetch_all("SELECT * FROM `myorder` WHERE `user_id` = ?", (str(res["id"]),))
        h = [
            {
                "customer": d["user_id"],
                "service": d["service"],
                "order": d["order_id"],
                "status": d["status"],
                "charge": d["retail"],
                "currency": "UZS",
            }
            for d in rows
        ]
        return h if h else {"error": "No orders"}

    if action == "status":
        res = database.fetch_one("SELECT * FROM `users` WHERE `api_key` = ?", (key,))
        if not res:
            return {"error": "Incorrect API key"}
        uid = str(res["id"])
        if isinstance(orders_param, str) and orders_param:
            data_out: Dict[str, Any] = {}
            for oid in [x.strip() for x in orders_param.split(",") if x.strip()]:
                if not oid.isdigit():
                    data_out[oid] = {"error": f"{oid} is not a number"}
                    continue
                rew = database.fetch_one("SELECT * FROM `myorder` WHERE `order_id` = ? AND `user_id` = ?", (int(oid), uid))
                if not rew:
                    data_out[oid] = {"error": "Incorrect order ID"}
                    continue
                data_out[oid] = {
                    "order": oid,
                    "status": rew["status"],
                    "start_count": "0",
                    "remains": "0",
                    "charge": rew["retail"],
                    "currency": "UZS",
                }
            return data_out if data_out else {"error": "Invalid order ID"}
        elif order and order.isdigit():
            rew = database.fetch_one("SELECT * FROM `myorder` WHERE `order_id` = ? AND `user_id` = ?", (int(order), uid))
            if not rew:
                return {"error": "Incorrect order ID"}
            return {
                "order": order,
                "status": rew["status"],
                "start_count": "0",
                "remains": "0",
                "charge": rew["retail"],
                "currency": "UZS",
            }
        return {"error": "Invalid order ID"}

    return {"error": "Incorrect request"}


def start_http_server_background(update_handler: Callable[[Dict[str, Any], str], None]) -> None:
    class BuiltinPanelHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _send_json(self, obj: Any, status: int = 200) -> None:
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            if parsed.path in ("/api/v2", "/api"):
                self._send_json(handle_api_v2(params))
            elif parsed.path in ("/payme", "/payme.php"):
                self._send_json(handle_payme_request(params))
            elif parsed.path in ("/bot/update.php", "/bot/update"):
                self._send_json(synchronize_services())
            elif parsed.path in ("/bot/bot.php", "/bot/webhook"):
                upd = params.get("update")
                if upd == "send":
                    self._send_json(cron_send())
                elif upd == "status":
                    self._send_json(cron_status())
                else:
                    self._send_json({"status": "Bot active"})
            else:
                self._send_json({"status": "SMM Panel & Bot Server Active", "users": database.count_rows("users")})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            length = int(self.headers.get("Content-Length", "0"))
            raw_body = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else ""
            if parsed.path in ("/bot/bot.php", "/bot/webhook"):
                try:
                    upd_json = json.loads(raw_body or "{}")
                except Exception:
                    upd_json = {}
                update_handler(upd_json, self.headers.get("Host", config.SITE_URL))
                self._send_json({"ok": True})
            elif parsed.path in ("/api/v2", "/api"):
                for k, v in urllib.parse.parse_qs(raw_body).items():
                    params[k] = v[0]
                self._send_json(handle_api_v2(params))
            else:
                self._send_json({"error": "Not found"}, status=404)

    if config.PORT <= 0:
        return
    try:
        srv = HTTPServer(("0.0.0.0", config.PORT), BuiltinPanelHandler)
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        print(f"🌐 HTTP API/Payme server http://localhost:{config.PORT} manzilida ishga tushdi.")
    except Exception as exc:
        print(f"HTTP server ogohlantirishi: {exc}")

# ============================================================================
# 6-BO'LIM: ASOSIY HANDLER VA WORKER POOL (handle_update + run_polling)
# ============================================================================

# Doimiy tayyor turuvchi Worker Pool (har bir xabarda yangi Thread ochishga vaqt ketmaydi!)
_UPDATE_QUEUE: "queue.Queue[Dict[str, Any]]" = queue.Queue()


def _update_worker_loop() -> None:
    while True:
        upd = _UPDATE_QUEUE.get()
        try:
            handle_update(upd)
        except Exception as exc:
            print(f"[Worker xatoligi]: {exc}")
        finally:
            _UPDATE_QUEUE.task_done()


def handle_update(update: Dict[str, Any], host: str = "") -> None:
    """Telegram update obyektini tezkor va xavfsiz qayta ishlaydi."""
    if not update:
        return
    t0 = time.time()
    cb = update.get("callback_query") or {}
    qid_auto = str(cb.get("id", "")) if cb else ""
    try:
        _handle_update_core(update, host)
    except Exception as exc:
        print(f"[XATOLIK] handle_update ichida xato: {exc}")
        traceback.print_exc()
    finally:
        if qid_auto:
            _BG_QUEUE.put(("answerCallbackQuery", {"callback_query_id": qid_auto}))
        elapsed = time.time() - t0
        if cb:
            print(f"⚡ [TUGMA] data='{cb.get('data')}' ({elapsed:.2f}s)")
        elif update.get("message"):
            msg_t = (update["message"].get("text") or "<media>")[:40]
            print(f"⚡ [XABAR] text='{msg_t}' ({elapsed:.2f}s)")


def _handle_update_core(update: Dict[str, Any], host: str = "") -> None:
    if not update:
        return

    host = host or config.SITE_URL
    time_hm = datetime.datetime.now().strftime("%H:%M")

    # my_chat_member (bot bloklanganda foydalanuvchini deactive qilish)
    my_chat_member = update.get("my_chat_member")
    if my_chat_member:
        new_cm = my_chat_member.get("new_chat_member", {})
        botdel_id = str(my_chat_member.get("from", {}).get("id", ""))
        if new_cm.get("status") == "kicked" and botdel_id:
            database.execute("UPDATE `users` SET `status` = 'deactive' WHERE `id` = ?", (botdel_id,))
        return

    message = update.get("message") or {}
    callback = update.get("callback_query") or {}
    cb_msg = callback.get("message") or {}

    cid = str(message.get("chat", {}).get("id", "")) if message else ""
    from_id = str(message.get("from", {}).get("id", "")) if message else ""
    mid = message.get("message_id")
    name = message.get("from", {}).get("first_name", "") or message.get("chat", {}).get("first_name", "")
    text = message.get("text")
    tx = text
    photo = message.get("photo")
    document = message.get("document")

    chat_id = str(cb_msg.get("chat", {}).get("id") or callback.get("from", {}).get("id") or "") if callback else ""
    message_id = cb_msg.get("message_id")
    cid2 = chat_id
    mid2 = message_id
    data = callback.get("data", "") if callback else ""
    qid = str(callback.get("id", "")) if callback else ""
    cqid = qid

    active_uid = cid or chat_id
    if not active_uid:
        return

    # Yangi foydalanuvchini ro'yxatga olish
    if message and cid:
        # /start user<id> uchun oldin mavjudligini eslab qolamiz
        existing_user = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (cid,))
    else:
        existing_user = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (active_uid,))

    if existing_user and existing_user.get("status") == "deactive":
        return

    if get_file("status.txt").strip() == "frozen":
        sms(active_uid, "🥶 Panel vaqtincha muzlatilgan")
        return

    global ADMIN
    # Agar ADMIN_ID hali o'rnatilmagan bo'lsa (yoki raqam bo'lmasa), birinchi foydalanuvchini avtomatik Admin qilamiz
    saved_admin = get_file("set/admin_id.txt").strip()
    if saved_admin and (not ADMIN.isdigit()):
        ADMIN = saved_admin
    if not ADMIN.isdigit():
        ADMIN = str(active_uid)
        put_file("set/admin_id.txt", ADMIN)
        print(f"Avtomatik Admin belgilandi! ADMIN_ID = {ADMIN}")

    # Emoji variation selector (\ufe0f) va turli apostrof (', ‘, ’, `) farqlarini yo'qotish
    if text:
        clean_t = (
            text.replace("\ufe0f", "")
            .replace("’", "'")
            .replace("‘", "'")
            .replace("ʻ", "'")
            .replace("`", "'")
            .strip()
        )
        button_aliases = {
            "🗄 Boshqaruv": "🗄️ Boshqaruv",
            "⚙ Asosiy sozlamalar": "⚙️ Asosiy sozlamalar",
            "⚙ Boshqa sozlamalar": "⚙️ Boshqa sozlamalar",
            "⚖ Foizni o'rnatish": "⚖️ Foizni o‘rnatish",
            "💵 Kursni o'rnatish": "💵 Kursni o‘rnatish",
            "☎ Yordam": "☎️ Yordam",
            "➡ Orqaga": "➡️ Orqaga",
            "🗑 O'chirish": "🗑️ O‘chirish",
            "❌ Bekor qilish": "❌ Bekor qilish",
        }
        if clean_t in button_aliases:
            text = button_aliases[clean_t]

    setting = database.get_settings()
    step = get_file(f"user/{cid}.step").strip() if cid else ""
    stepc = get_file(f"user/{chat_id}.step").strip() if chat_id else ""
    saved = get_file("user/us.id").strip()

    is_admin = (cid == ADMIN) or (chat_id == ADMIN)
    m_kb = MENU_ADMIN_KB if is_admin else MENU_USER_KB

    # /admin yoki Boshqaruv tugmasi bosilganda agar ADMIN_ID boshqa bo'lsa, foydalanuvchiga ID sini ko'rsatamiz
    if text in ("/admin", "/panel"):
        if cid == ADMIN:
            sms(cid, "🖥️ Boshqaruv paneli", PANEL_KB)
            unlink_file(f"user/{cid}.step")
        else:
            sms(cid, f"⚠️ Siz Admin emassiz.\nSizning Telegram ID raqamingiz: <code>{cid}</code>\n(Admin bo'lish uchun tg.py dagi ADMIN_ID qatoriga ushbu ID ni yozing).")
        return

    if text == "🗄️ Boshqaruv" and cid != ADMIN:
        sms(cid, f"⚠️ Boshqaruv paneliga kirish uchun tg.py faylidagi <b>ADMIN_ID</b> ga o'z ID raqamingizni yozing:\n\nSizning ID raqamingiz: <code>{cid}</code>")
        return

    # /start user<ref_id> referal tizimi
    if text and text.startswith("/start user"):
        ref_user_num = text.replace("/start user", "").strip()
        ref_row = database.fetch_one("SELECT * FROM `users` WHERE `user_id` = ?", (ref_user_num,))
        refid = str(ref_row["id"]) if ref_row else ""
        adduser(cid)
        if refid:
            if refid == cid:
                sms(cid, "⚠️ Siz o‘zingizga referal bo‘lishingiz mumkin emas", m_kb)
                return
            elif existing_user:
                sms(cid, "⚠️ Siz bizning botimizda allaqachon mavjudsiz.", m_kb)
                return
            else:
                put_file(f"user/{cid}.inviter", refid)
                if joinchat(cid):
                    ref_u = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (refid,))
                    cur_bal = float(ref_u["balance"]) if ref_u else 0.0
                    bonus = float(enc("decode", setting.get("referal", "MTAw")) or 0)
                    database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (str(cur_bal + bonus), refid))
                    ref_msg = (
                        f"📳 <b>Sizda yangi</b> <a href='tg://user?id={cid}'>taklif</a> <b>mavjud!</b>\n\n"
                        f"Hisobingizga {enc('decode', setting.get('referal', 'MTAw'))} so‘m qo'shildi!"
                    )
                    cnt = int(float(get_file(f"user/{refid}.users") or 0))
                    put_file(f"user/{refid}.users", str(cnt + 1))
                else:
                    put_file(f"user/{cid}.id", refid)
                    ref_msg = f"📳 <b>Sizda yangi</b> <a href='tg://user?id={cid}'>taklif</a> <b>mavjud!</b>"
                sms(cid, "🖥 Asosiy menyudasiz", m_kb)
                sms(refid, ref_msg)
                return

    if message and cid and not existing_user:
        adduser(cid)

    # Orqaga / Boshqaruv
    # Agar foydalanuvchi asosiy menyu tugmalaridan birini bossa, eski tugallanmagan step'ni tozalaymiz
    MAIN_BUTTONS = {
        "/start", "/admin", "/panel", "➡️ Orqaga", "⏪ Orqaga", "🗄️ Boshqaruv",
        "⚙️ Asosiy sozlamalar", "💳 Hamyonlar sozlamalari", "💵 Pul ishlash sozlamalari", "🔔 Xabar yuborish",
        "📊 Statistika", "👤 Foydalanuvchini boshqarish", "🇺🇿 Valyuta kursi",
        "⏰ Cron sozlamasi", "🛍 Buyurtmalarni sozlash",
        "💵 Kursni o‘rnatish", "⚖️ Foizni o‘rnatish", "📊 Buyurtmani tekshirish",
        "📎 Majburiy obunalar", "🔑 API Sozlamalari", "⚙️ Boshqa sozlamalar",
        "➕ Buyurtma berish", "🛒 Buyurtmalar", "💵 Pul ishlash",
        "💳 Balans", "💳 Pul kiritish", "☎️ Yordam", "🤝 Hamkorlik dasturi",
    }
    if text in MAIN_BUTTONS and step:
        unlink_file(f"user/{cid}.step")
        step = ""

    if text == "❌ Bekor qilish" and joinchat(cid):
        for ext in ("step", "params", "si", "qu", "ur"):
            unlink_file(f"user/{cid}.{ext}")
        sms(cid, "❌ Buyurtma bekor qilindi! 🖥️ Asosiy menyudasiz", m_kb)
        return

    if text in ("➡️ Orqaga", "⏪ Orqaga") and joinchat(cid):
        for ext in ("step", "params", "si", "qu", "ur"):
            unlink_file(f"user/{cid}.{ext}")
        sms(cid, "🖥️ Asosiy menyudasiz", m_kb)
        return

    if text == "🗄️ Boshqaruv" and cid == ADMIN:
        sms(cid, "🖥️ Boshqaruv paneli", PANEL_KB)
        unlink_file(f"user/{cid}.step")
        return

    if text == "⚙️ Asosiy sozlamalar" and cid == ADMIN:
        sms(cid, text, PANEL2_KB)
        return

    if text == "/start" and joinchat(cid):
        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (cid,)) or {"balance": "0"}
        start_tpl = enc("decode", setting.get("start", "")) or "🖥 Asosiy menyudasiz"
        start_msg = (
            start_tpl.replace("{name}", name)
            .replace("{balance}", fmt_money(rew.get("balance", "0")))
            .replace("{time}", time_hm)
        )
        sms(cid, start_msg, m_kb)
        return

    # Majburiy obuna tekshirish ("result")
    if data == "result" and joinchat(chat_id):
        usid = get_file(f"user/{chat_id}.id").strip()
        if usid:
            ref_u = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (usid,))
            if ref_u:
                bonus = float(enc("decode", setting.get("referal", "MTAw")) or 0)
                new_b = float(ref_u.get("balance") or 0) + bonus
                database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (str(new_b), usid))
                sms(
                    usid,
                    f"<a href='tg://user?id={chat_id}'>✅ Foydalanuvchi</a> <b> botimizdan foydalanib boshladi!</b>\n\n"
                    f"Hisobingizga {enc('decode', setting.get('referal', 'MTAw'))} so‘m qo'shildi!",
                    m_kb,
                )
                cnt = int(float(get_file(f"user/{usid}.users") or 0))
                put_file(f"user/{usid}.users", str(cnt + 1))
                unlink_file(f"user/{chat_id}.id")
        del_msg(chat_id, message_id)
        sms(chat_id, "🖥️ Asosiy menyudasiz", m_kb)
        return

    if text == "⏰ Cron sozlamasi" and cid == ADMIN:
        sms(
            cid,
            f"📝 Quyidagi manzillarni cron qiling\n"
            f"<pre>https://{host}/bot/bot.php?update=send</pre> \n- Pochta xabari uchun cron (1 daqiqa)\n\n"
            f"<pre>https://{host}/bot/bot.php?update=status</pre>\n- Buyurtma xolati uchun cron (1 daqiqa)\n\n"
            f"<pre>https://{host}/bot/update.php</pre> \n- Narxlarni avtomatik yangilash uchun cron (1 daqiqa)",
            PANEL_KB,
        )
        return

    if text == "📊 Statistika" and cid == ADMIN:
        st = _get_order_And_user_stats()
        sms(
            cid,
            f"<b>📊 Statistika</b>\n"
            f"• Jami foydalanuvchilar: {st['users_total']} ta\n"
            f"• Aktiv foydalanuvchilar: {st['users_active']} ta\n"
            f"• O'chirilgan foydalanuvchilar: {st['users_deactive']} ta\n\n"
            f"<b>📊 Buyurtmalar</b>\n"
            f"• Jami buyurtmalar: {st['orders_total']} ta\n"
            f"• Bajarilgan buyurtmalar: {st['Completed']} ta\n"
            f"• Kutilayotgan buyurtmalar: {st['Pending']} ta\n"
            f"• Jarayondagi buyurtmalar: {st['In progress']} ta\n"
            f"• Bekor qilingan buyurtmalar: {st['Canceled']} ta\n"
            f"• Muvaffaqiyatsiz buyurtmalar: {st['Failed']} ta\n"
            f"• Qisman bajarilgan buyurtmalar: {st['Partial']} ta\n"
            f"• Qayta ishlangan buyurtmalar: {st['Processing']} ta\n\n"
            f"<b>📊 Xizmatlar</b>:\n"
            f"• Barcha xizmatlar: {st['services_total']} ta",
            keyboard([[{"text": "♻️ Buyurtmalar xolatini yangilash", "callback_data": "update=orders"}]]),
        )
        unlink_file(f"user/{cid}.step")
        return

    if data.startswith("update="):
        st = _get_order_And_user_stats()
        parts = data.split("=")
        res = parts[1] if len(parts) > 1 else ""
        if res == "orders":
            del_msg(cid2, mid2)
            sms(
                cid2,
                f"📊 Buyurtmalar ro'yxati:\n\n"
                f"• Jami buyurtmalar: {st['orders_total']} ta\n"
                f"• Bajarilgan buyurtmalar: {st['Completed']} ta\n"
                f"• Kutilayotgan buyurtmalar: {st['Pending']} ta\n"
                f"• Jarayondagi buyurtmalar: {st['In progress']} ta\n"
                f"• Bekor qilingan buyurtmalar: {st['Canceled']} ta\n"
                f"• Muvaffaqiyatsiz buyurtmalar: {st['Failed']} ta\n"
                f"• Qisman bajarilgan buyurtmalar: {st['Partial']} ta\n"
                f"• Qayta ishlangan buyurtmalar: {st['Processing']} ta",
                keyboard([
                    [{"text": "Kutilayotgan buyurtmalarni yangilash", "callback_data": "update=pending"}],
                    [{"text": "Jarayondagi buyurtmalarni yangilash", "callback_data": "update=In progress"}],
                    [{"text": "Qisman bajarilgan buyurtmalarni yangilash", "callback_data": "update=partial"}],
                    [{"text": "Qayta ishlangan buyurtmalarni yangilash", "callback_data": "update=processing"}],
                ]),
            )
        elif res == "pending":
            del_msg(cid2, mid2)
            sms(
                cid2,
                f"📊 Buyurtmalar ro'yxati:\n\n• Kutilayotgan buyurtmalar: {st['Pending']} ta",
                keyboard([
                    [{"text": "Bajarilgan xolatga o‘tkazish", "callback_data": "update=new=Pending=Completed"}],
                    [{"text": "Jarayondagi xolatga o‘tkazish", "callback_data": "update=new=Pending=In progress"}],
                    [{"text": "Orqaga", "callback_data": "update=orders"}],
                ]),
            )
        elif res == "processing":
            del_msg(cid2, mid2)
            sms(
                cid2,
                f"📊 Buyurtmalar ro'yxati:\n\n• qayta ishlangan buyurtmalar: {st['Processing']} ta",
                keyboard([
                    [{"text": "Bajarilgan xolatga o‘tkazish", "callback_data": "update=new=Processing=Completed"}],
                    [{"text": "Jarayondagi xolatga o‘tkazish", "callback_data": "update=new=Processing=In progress"}],
                    [{"text": "Orqaga", "callback_data": "update=orders"}],
                ]),
            )
        elif res == "partial":
            del_msg(cid2, mid2)
            sms(
                cid2,
                f"📊 Buyurtmalar ro'yxati:\n\n• Qisman bajarilgan buyurtmalar: {st['Partial']} ta",
                keyboard([
                    [{"text": "Bajarilgan xolatga o‘tkazish", "callback_data": "update=new=Partial=Completed"}],
                    [{"text": "Jarayondagi xolatga o‘tkazish", "callback_data": "update=new=Partial=In progress"}],
                    [{"text": "Orqaga", "callback_data": "update=orders"}],
                ]),
            )
        elif res == "In progress":
            del_msg(cid2, mid2)
            sms(
                cid2,
                f"📊 Buyurtmalar ro'yxati:\n\n• Jarayondagi buyurtmalar: {st['In progress']} ta",
                keyboard([
                    [{"text": "Bajarilgan xolatga o‘tkazish", "callback_data": "update=new=In progress=Completed"}],
                    [{"text": "Kutilayotgan xolatga o‘tkazish", "callback_data": "update=new=In progress=Pending"}],
                    [{"text": "Orqaga", "callback_data": "update=orders"}],
                ]),
            )
        elif res == "new" and len(parts) >= 4:
            out_st, inp_st = parts[2], parts[3]
            rows = database.fetch_all("SELECT * FROM `orders` WHERE `status` = ?", (out_st,))
            sav = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
            for r in rows:
                io = r["order_id"]
                mysa = database.fetch_one("SELECT * FROM `myorder` WHERE `order_id` = ?", (io,))
                adm = mysa["user_id"] if mysa else None
                database.execute("UPDATE `orders` SET `status` = ? WHERE `order_id` = ?", (inp_st, io))
                if inp_st == "Completed":
                    database.execute(
                        "UPDATE `myorder` SET `status` = ?, `last_check` = ? WHERE `order_id` = ?",
                        (inp_st, sav, io),
                    )
                    if adm:
                        sms(adm, f"✅ Sizning {io} raqamli buyurtmangiz bajarildi")
                else:
                    database.execute("UPDATE `myorder` SET `status` = ? WHERE `order_id` = ?", (inp_st, io))
            del_msg(cid2, mid2)
            sms(cid2, "✅ Jarayon tugallandi.")
        return

    if text == "🔔 Xabar yuborish" and cid == ADMIN:
        row = database.fetch_one("SELECT * FROM `send` LIMIT 1")
        if not row:
            sms(cid, "<b>📤 Foydalanuvchilarga yuboriladigan xabarni botga yuboring!</b>", AORT_KB)
            put_file(f"user/{cid}.step", "send")
        else:
            sms(
                cid,
                "<b>📑 Hozirda botda xabar yuborish jarayoni davom etmoqda. Yangi xabar yuborish uchun eski yuborilayotgan xabar barcha foydalanuvchilarga yuborilishini kuting!</b>",
                PANEL_KB,
            )
        return

    if step == "send" and cid == ADMIN and message:
        stat = database.count_rows("users")
        last_user = database.fetch_one("SELECT * FROM `users` WHERE `user_id` = ?", (stat,))
        stop_uid = str(last_user["id"]) if last_user else "0"
        now = datetime.datetime.now()
        t1 = (now + datetime.timedelta(minutes=1)).strftime("%H:%M")
        t2 = (now + datetime.timedelta(minutes=2)).strftime("%H:%M")
        rm_json = json.dumps(message.get("reply_markup")) if message.get("reply_markup") else "null"
        rm_b64 = enc("encode", rm_json)
        database.execute(
            """INSERT INTO `send`
            (`time1`, `time2`, `start_id`, `stop_id`, `admin_id`, `message_id`, `reply_markup`, `step`, `time3`, `time4`, `time5`)
            VALUES (?, ?, '0', ?, ?, ?, ?, 'send', '', '', '')""",
            (t1, t2, stop_uid, ADMIN, str(mid), rm_b64),
        )
        sms(
            ADMIN,
            f"<b>\n📋 Saqlandi!\n📑 Xabar foydalanuvchilarga {t1} da yuborish boshlanadi!</b>",
            PANEL_KB,
        )
        unlink_file(f"user/{cid}.step")
        return

    # ========================================================================
    # ADMIN PANEL: Boshqa sozlamalar (Matnlar, Hamyonlar, Avto to'lov, Referal)
    # ========================================================================

    if text == "💳 Hamyonlar sozlamalari" and cid == ADMIN:
        delturi = get_file("set/payments.txt")
        lines = [ln.strip() for ln in delturi.split("\n") if ln.strip()]
        kb_rows = [[{"text": f"🗑️ {title} - ni o'chirish", "callback_data": f"delPayMethod-{title}"}] for title in lines]
        kb_rows.append([{"text": "➕ Yangi to'lov tizimi (karta) qo'shish", "callback_data": "new"}])
        kb_rows.append([{"text": "💳 PAYME avto-to'lovni sozlash", "callback_data": "autopay=payme"}])
        sms(cid, "<b>💳 To'lov tizimlari va kartalar sozlamalari:</b>", keyboard(kb_rows))
        return

    if text == "⚙️ Boshqa sozlamalar" and cid == ADMIN:
        sms(
            cid,
            "⭐ Kerakli bo'limni tanlang:",
            keyboard([
                [{"text": "💵 Pul ishlash sozlamalari", "callback_data": "adm_earn=home"}],
                [{"text": "📑 Matnlar sozlamalari", "callback_data": "birlamch=matn"}],
                [{"text": "💳 Hamyonlar sozlamalari", "callback_data": "birlamch=cards"}],
                [{"text": "💳 Avto tolov sozlamalari", "callback_data": "birlamch=autopays"}],
            ]),
        )
        return

    if data.startswith("birlamch="):
        res = data.split("=")[1]
        if res == "matn":
            edit(
                chat_id,
                message_id,
                "👉 Sozlama turini tanlang:",
                keyboard([
                    [{"text": "📑 Nomini o‘zgartirish", "callback_data": "birlamch=editM"}],
                    [{"text": "Orqaga", "callback_data": "birlamch=exit"}],
                ]),
            )
        elif res == "tugma":
            edit(
                chat_id,
                message_id,
                "👉 Sozlama turini tanlang:",
                keyboard([
                    [{"text": "📑 Nomini o‘zgartirish", "callback_data": "birlamch=editT"}],
                    [{"text": "Orqaga", "callback_data": "birlamch=exit"}],
                ]),
            )
        elif res == "exit":
            del_msg(chat_id, message_id)
            sms(
                chat_id,
                "⭐ Kerakli bo'limni tanlang:",
                keyboard([
                    [{"text": "📑 Matnlarni sozlash", "callback_data": "birlamch=matn"}],
                    [{"text": "💳 Hamyonlar sozlamalari", "callback_data": "birlamch=cards"}],
                    [{"text": "💳 Avto tolov sozlamalari", "callback_data": "birlamch=autopays"}],
                ]),
            )
        elif res == "editM":
            edit(
                chat_id,
                message_id,
                "📑 Kerakli matnni tanlang:\n\n1. /start uchun matn\n2. Yangi buyurtma uchun matn\n3. Kabinet uchun matn\n4. Referal narxi",
                keyboard([
                    [{"text": "1", "callback_data": "birlamchi=start"}],
                    [{"text": "2", "callback_data": "birlamchi=orders"}, {"text": "3", "callback_data": "birlamchi=kabinet"}],
                    [{"text": "4", "callback_data": "birlamchi=referal"}],
                    [{"text": "Orqaga", "callback_data": "birlamch=matn"}],
                ]),
            )
        elif res == "ref":
            edit(
                chat_id,
                mid2,
                "⚙️ Sozlama turini tanlang:",
                keyboard([
                    [{"text": "🎁 Referal tugma xolati", "callback_data": "referr=xolati"}],
                    [{"text": "🎁 Bonusni o‘zgartirish", "callback_data": "referr=edit"}],
                    [{"text": "Orqaga", "callback_data": "birlamch=exit"}],
                ]),
            )
        elif res == "cards":
            del_msg(cid2, mid2)
            delturi = get_file("set/payments.txt")
            lines = [ln.strip() for ln in delturi.split("\n") if ln.strip()]
            kb_rows = [[{"text": f"{title} - ni o'chirish", "callback_data": f"delPayMethod-{title}"}] for title in lines]
            kb_rows.append([{"text": "➕ Yangi to'lov tizimi qo'shish", "callback_data": "new"}])
            kb_rows.append([{"text": "Orqaga", "callback_data": "birlamch=exit"}])
            if cid2 == ADMIN:
                sms(cid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard(kb_rows))
        elif res == "autopays":
            edit(
                cid2,
                mid2,
                "👉 Kerakli tolov tizimini tanlang:",
                keyboard([
                    [{"text": "💳 PAYME", "callback_data": "autopay=payme"}],
                    [{"text": "Orqaga", "callback_data": "birlamch=exit"}],
                ]),
            )
        return

    if data.startswith("autopay="):
        ex = data.split("=")[1]
        if ex == "payme":
            payme_id = setting.get("payme_id", "")
            if not payme_id or payme_id == "null":
                edit(
                    cid2,
                    mid2,
                    "👉 Kerakli sozlamani tanlang:",
                    keyboard([
                        [{"text": "➕ Karta IDsini qo‘shish", "callback_data": "autopay=payme_id"}],
                        [{"text": "Orqaga", "callback_data": "birlamch=exit"}],
                    ]),
                )
            else:
                edit(
                    cid2,
                    mid2,
                    f"👉 Kerakli sozlamani tanlang\n\n🆔 Hozirgi karta IDsi: {payme_id}",
                    keyboard([
                        [{"text": "➕ Karta IDsini o‘zgartirish", "callback_data": "autopay=payme_id"}],
                        [{"text": "Orqaga", "callback_data": "birlamch=exit"}],
                    ]),
                )
        elif ex == "payme_id":
            del_msg(cid2, mid2)
            sms(
                cid2,
                "1 - «<b>Kartalarim</b>» tugmasini bosing\n"
                "2 - «<b>Kerakli karta</b>» ni tanlab ustiga bosing\n"
                "3 - «<b>Havolani ko‘chirib olish</b>» ga bosib linkni saqlab oling va shu yerga kiriting.\n\n"
                "💳 Kartangizning unikal manzilini kiriting\n✅ Ma'lumotlaringiz 100% maxfiy saqlanadi.",
                AORT_KB,
            )
            put_file(f"user/{cid2}.step", "%%₹_-#")
        return

    if step == "%%₹_-#" and cid == ADMIN and text:
        clean_payme = text.strip()
        if "payme.uz/" in clean_payme or "paycom.uz/" in clean_payme:
            card = clean_payme.rstrip("/").split("/")[-1]
        else:
            card = clean_payme
        if card:
            database.execute("UPDATE `settings` SET `payme_id` = ? WHERE `id` = 1", (card,))
            sms(cid, f"✅ Payme karta ID muvaffaqiyatli saqlandi: <code>{card}</code>", PANEL_KB)
            unlink_file(f"user/{cid}.step")
        else:
            sms(cid, "⚠️ Karta havolasini yoki ID raqamini to'g'ri kiriting:", AORT_KB)
        return

    if data.startswith("delPayMethod-"):
        ex = data.split("-", 1)[1]
        delturi = get_file("set/payments.txt").replace(f"\n{ex}", "")
        put_file("set/payments.txt", delturi)
        del_msg(cid2, mid2)
        sms(cid2, "🗑️ <b>To'lov tizimi o'chirildi!</b>", PANEL_KB)
        rmdir_pro(f"set/pay/{ex}")
        return

    if data == "new":
        del_msg(cid2, mid2)
        sms(cid2, "🔠 <b>Yangi to'lov tizimi nomini yuboring:</b>", AORT_KB)
        put_file(f"user/{cid2}.step", "turi")
        return

    if step == "turi" and cid == ADMIN and text:
        put_file("set/title.txt", text)
        sms(cid, "🔢 <b>Ushbu to'lov tizimidagi hamyoningiz raqamini yuboring:</b>")
        put_file(f"user/{cid}.step", "wallet")
        return

    if step == "wallet" and cid == ADMIN and text:
        put_file("set/wallet.txt", text)
        sms(
            cid,
            "✅ <b>Ushbu to'lov tizimi orqali hisobni to'ldirish bo'yicha ma'lumotni yuboring:</b>\n\n"
            "<i>Misol uchun, \"Ushbu to'lov tizimi orqali pul yuborish jarayonida izoh kirita olmasligingiz mumkin. Ushbu holatda, biz bilan bog'laning.\"</i>",
        )
        put_file(f"user/{cid}.step", "addition")
        return

    if step == "addition" and cid == ADMIN and text:
        ttest = get_file("set/title.txt").strip()
        put_file("set/payments.txt", f"\n{ttest}", append=True)
        put_file(f"set/pay/{ttest}/addition.txt", text)
        put_file(f"set/pay/{ttest}/wallet.txt", get_file("set/wallet.txt"))
        sms(cid, f"✅ <b>{ttest} to'lov tizimi qo'shildi!</b>", PANEL_KB)
        unlink_file(f"user/{cid}.step")
        return

    if data.startswith("referr="):
        parts = data.split("=")
        res = parts[1] if len(parts) > 1 else ""
        fo = parts[2] if len(parts) > 2 else ""
        if res in ("xolati", "ok"):
            if res == "ok":
                database.execute("UPDATE `settings` SET `ref_status` = ? WHERE `id` = 1", (fo,))
            cur_st = database.get_settings().get("ref_status", "off")
            tx_icon = "✅" if cur_st == "on" else "❌"
            toggle_btn = (
                {"text": "«❌»", "callback_data": "referr=ok=off"}
                if cur_st == "on"
                else {"text": "«✅»", "callback_data": "referr=ok=on"}
            )
            edit(
                cid2,
                mid2,
                f"🎁 Referal tugma xolati: {tx_icon}",
                keyboard([[toggle_btn], [{"text": "Orqaga", "callback_data": "birlamch=exit"}]]),
            )
        elif res == "edit":
            bonus_val = database.get_settings().get("bonus", "4")
            del_msg(cid2, mid2)
            sms(cid2, f"🔢 Referal bonus miqdorini kiriting. (raqamlarda)\n\n📝 Hozirgi xolati: {bonus_val}%", AORT_KB)
            put_file(f"user/{cid2}.step", "*##")
        return

    if step == "*##" and cid == ADMIN and text and text.isdigit():
        database.execute("UPDATE `settings` SET `bonus` = ? WHERE `id` = 1", (text,))
        sms(cid, "✅ O‘zgarish saqlandi", PANEL_KB)
        unlink_file(f"user/{cid}.step")
        return

    if data.startswith("birlamchi="):
        res = data.split("=")[1]
        hints = {
            "start": "<code>{balance} </code> - Foydalanuvchi hisobi\n<pre>{name}</pre> - Foydalanuvchi ismi\n<pre>{time} </pre> - Hozirgi vaqt (UTC+5 / UZ)",
            "kabinet": "<pre>{id}</pre> - Foydalanuvchi IDsi\n<pre>{balance}</pre> - Foydalanuvchi hisobi\n<pre>{outing}</pre> - Kiritgan pullar miqdori",
            "referal": "1 ta taklif uchun tolov miqdorini kiriting:",
            "orders": "<pre>{order}</pre> - Buyurtma IDsi (standard)\n<pre>{order_api}</pre> - Buyurtma IDsi (API)",
        }
        put_file("bir.txt", res)
        del_msg(chat_id, message_id)
        sms(chat_id, f"📝 Yangi matnlarni kiriting.\n\n⚙️ O‘zgaruvchilar:\n{hints.get(res, '')}\n\n📝 Hozirgi matnlar", AORT_KB)
        cur_val = database.get_settings().get(res, "")
        sms(chat_id, enc("decode", cur_val))
        put_file(f"user/{chat_id}.step", "!?+-")
        return

    if step == "!?+-" and cid == ADMIN and text:
        vq = get_file("bir.txt").strip()
        if vq in ("start", "kabinet", "referal", "orders"):
            vo = enc("encode", text)
            database.execute(f"UPDATE `settings` SET `{vq}` = ? WHERE `id` = 1", (vo,))
        sms(cid, "✅ O‘zgartirishlar saqlandi", PANEL_KB)
        unlink_file("bir.txt")
        unlink_file(f"user/{cid}.step")
        return

    # ========================================================================
    # ADMIN PANEL: Buyurtmani tekshirish va API Sozlamalari (Provayderlar)
    # ========================================================================

    if text == "📊 Buyurtmani tekshirish" and joinchat(cid):
        stati = database.count_rows("orders")
        sms(cid, f"🔢 Barcha buyurtmalar: {stati} ta\n\n➡️ Buyurtma IDsini kiriting:", AORT_KB)
        put_file(f"user/{cid}.step", "orders2")
        return

    if step == "orders2" and cid == ADMIN and text and text.isdigit():
        stati = database.fetch_one("SELECT * FROM `orders` WHERE `order_id` = ?", (int(text),))
        if not stati:
            sms(cid, "❌ Buyurtma topilmadi.", AORT_KB)
        else:
            m = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (stati["provider"],))
            if m:
                raw = http_get(f"{m['api_url']}?key={m['api_key']}&action=status&order={stati['api_order']}")
                try:
                    api_res = json.loads(raw)
                except Exception:
                    api_res = {}
                prtxt = strip_provider_domain(m["api_url"])
                sms(
                    cid,
                    f"*️⃣ Server: {prtxt}\n🔢 Buyurtma IDsi: <code>{stati['api_order']}</code>\n"
                    f"✅ Buyurtma xolati ({prtxt}): <code>{api_res.get('status', 'N/A')}</code>",
                    PANEL2_KB,
                )
            unlink_file(f"user/{cid}.step")
        return

    if (text == "🔑 API Sozlamalari" and cid == ADMIN) or data == "api1":
        target_chat = cid if text else chat_id
        if data == "api1":
            del_msg(chat_id, message_id)
        sms(
            target_chat,
            "Quyidagi bo'limlardan birini tanlang:",
            keyboard([
                [{"text": "➕ API qo‘shish", "callback_data": "api"}],
                [{"text": "💵 Balansni ko'rish", "callback_data": "balans"}],
                [{"text": "🗑️ O‘chirish", "callback_data": "deleteapi"}],
                [{"text": "📝 Taxrirlash", "callback_data": "apio=taxrirlash"}],
            ]),
        )
        return

    if data.startswith("apio="):
        parts = data.split("=")
        res = parts[1] if len(parts) > 1 else ""
        if res == "taxrirlash":
            edit(
                cid2,
                mid2,
                "📝 Taxrirlash menyusini tanlang",
                keyboard([
                    [{"text": "🔑 Kalitni o‘zgartirish", "callback_data": "apio=kalit"}],
                    [{"text": "⬅️ Orqaga", "callback_data": "api1"}],
                ]),
            )
        elif res == "kalit":
            providers = database.fetch_all("SELECT * FROM `providers`")
            if not providers:
                bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Provayderlar topilmadi!", "show_alert": True})
            else:
                prs_lines = []
                btns = []
                for idx, s in enumerate(providers, start=1):
                    prtxt = strip_provider_domain(s["api_url"])
                    prs_lines.append(f"{idx}: <b>{prtxt}</b>")
                    btns.append({"text": str(idx), "callback_data": f"apio=edit={s['id']}"})
                kb_rows = chunk_list(btns, 3)
                kb_rows.append([{"text": "Orqaga", "callback_data": "api1"}])
                edit(chat_id, message_id, "Provayderni tanlang:\n\n" + "\n".join(prs_lines), keyboard(kb_rows))
        elif res == "edit" and len(parts) > 2:
            co = parts[2]
            del_msg(cid2, mid2)
            sms(cid2, "🔠 Yangi kalitni kiriting:", AORT_KB)
            put_file(f"user/{cid2}.step", f"kalitnew={co}")
        return

    if step.startswith("kalitnew=") and cid == ADMIN and text:
        io = step.split("=")[1]
        database.execute("UPDATE `providers` SET `api_key` = ? WHERE `id` = ?", (text, io))
        sms(cid, "✅ O‘zgartirish muvaffaqiyatli amalga oshirildi.", PANEL_KB)
        unlink_file(f"user/{cid}.step")
        return

    if data == "deleteapi":
        providers = database.fetch_all("SELECT * FROM `providers`")
        if not providers:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Provayderlar topilmadi!", "show_alert": True})
        else:
            prs_lines = []
            btns = []
            for idx, s in enumerate(providers, start=1):
                prtxt = strip_provider_domain(s["api_url"])
                prs_lines.append(f"{idx}: <b>{prtxt}</b>")
                btns.append({"text": str(idx), "callback_data": f"apidel={s['id']}"})
            kb_rows = chunk_list(btns, 3)
            kb_rows.append([{"text": "Orqaga", "callback_data": "api1"}])
            edit(chat_id, message_id, "Provayderni tanlang:\n\n" + "\n".join(prs_lines), keyboard(kb_rows))
        return

    if data.startswith("apidel="):
        res = data.split("=")[1]
        del_msg(cid2, mid2)
        database.execute("DELETE FROM `providers` WHERE `id` = ?", (res,))
        database.execute("DELETE FROM `services` WHERE `api_service` = ?", (res,))
        sms(cid2, "🗑️ Provayderni o‘chirish yakunlandi.")
        return

    if data == "api":
        del_msg(chat_id, message_id)
        sms(chat_id, "<b>API manzilini yuboring:\n\nNamuna:</b> <pre>https://apiseen.uz/api/v2</pre>", AORT_KB)
        put_file(f"user/{chat_id}.step", "api_url")
        return

    if step == "api_url" and cid == ADMIN and text:
        if "https://" in text:
            put_file("set/api_url", text.strip())
            sms(cid, f"{text} <b>qabul qilindi!</b>\n\nEndi esa ushbu saytdan olingan API_KEY'ni kiriting:")
            put_file(f"user/{cid}.step", "api")
        else:
            sms(cid, "<b>API manzilini yuboring:\n\nNamuna:</b> <pre>https://apiseen.uz/api/v2</pre>")
        return

    if step == "api" and cid == ADMIN and text:
        api_url = get_file("set/api_url").strip()
        raw = http_get(f"{api_url}?key={text.strip()}&action=balance")
        try:
            balans = json.loads(raw)
        except Exception:
            balans = {"error": True}
        if "error" in balans or "balance" not in balans:
            admsg = "⚠️ Balansni olish imkoni bo'lmadi\n\nEhtimol API kalit mavjud emas"
        else:
            admsg = f"💵 API balansi: {balans.get('balance')} {balans.get('currency', '')}"
            database.execute("INSERT INTO `providers` (`api_url`, `api_key`) VALUES (?, ?)", (api_url, text.strip()))
        sms(cid, f"<b>{admsg}</b>", PANEL_KB)
        unlink_file(f"user/{cid}.step")
        return

    if data == "balans":
        providers = database.fetch_all("SELECT * FROM `providers`")
        if not providers:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Provayderlar topilmadi!", "show_alert": True})
        else:
            prs_lines = []
            btns = []
            for idx, s in enumerate(providers, start=1):
                prtxt = strip_provider_domain(s["api_url"])
                try:
                    sa = json.loads(api_query(f"{s['api_url']}?key={s['api_key']}&action=balance"))
                except Exception:
                    sa = {"balance": "?", "currency": ""}
                prs_lines.append(f"<b>{idx}</b>: {prtxt} - {sa.get('balance', '?')} {sa.get('currency', '')}")
                btns.append({"text": str(idx), "url": f"{s['api_url']}?key={s['api_key']}&action=balance"})
            kb_rows = chunk_list(btns, 3)
            kb_rows.append([{"text": "Orqaga", "callback_data": "api1"}])
            edit(chat_id, message_id, "Provayderni tanlang:\n\n" + "\n".join(prs_lines), keyboard(kb_rows))
        return

    # ========================================================================
    # FOYDALANUVCHI: Hamkorlik dasturi (Bo'tni serverga qo'yish + SMM BOTNI serverga qo'yish + SMM API)
    # ========================================================================

    def _get_server_tariffs() -> Dict[str, float]:
        return {
            "GO": float(get_file("set/tariff_go.txt").strip() or 15000),
            "PRO": float(get_file("set/tariff_pro.txt").strip() or 30000),
            "PLUS": float(get_file("set/tariff_plus.txt").strip() or 50000),
            "SMM": float(get_file("set/smm_bot_monthly.txt").strip() or 10000),
        }

    def _has_used_smm_trial(uid_str: str) -> bool:
        if get_file(f"user/{uid_str}.smm_trial_used").strip() == "1":
            return True
        existing_smm = database.fetch_one(
            "SELECT `id` FROM `hosted_bots` WHERE `owner_id` = ? AND `bot_category` = 'smm'",
            (str(uid_str),),
        )
        return bool(existing_smm)

    if text == "🤝 Hamkorlik dasturi" and joinchat(cid):
        sms(
            cid,
            "🤝 <b>Hamkorlik dasturi</b>\n\n"
            "👇 O‘zingizga kerakli bo‘limni tanlang:",
            keyboard([
                [
                    {"text": "🤖 Bo‘t yaratish", "callback_data": "hamkor=bot"},
                    {"text": "🔑 SMM API", "callback_data": "hamkor=api"},
                ]
            ]),
        )
        return

    if data.startswith("hamkor=") and joinchat(chat_id):
        sub = data.split("=", 1)[1]
        if sub == "back":
            edit(
                chat_id,
                message_id,
                "🤝 <b>Hamkorlik dasturi</b>\n\n"
                "👇 O‘zingizga kerakli bo‘limni tanlang:",
                keyboard([
                    [
                        {"text": "🤖 Bo‘t yaratish", "callback_data": "hamkor=bot"},
                        {"text": "🔑 SMM API", "callback_data": "hamkor=api"},
                    ]
                ]),
            )
        elif sub == "api":
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
            edit(
                chat_id,
                message_id,
                f"🔑 <b>SMM API bo‘limi</b>\n\n"
                f"<b>⭐ Sizning API kalitingiz:\n<code>{rew.get('api_key', '')}</code>\n\n"
                f"💵 API hisobi:\n<b>{fmt_money(rew.get('balance', '0'))}</b> so‘m</b>",
                keyboard([
                    [{"text": "📝 Qo‘llanma", "callback_data": "apidetail=qoll"}],
                    [{"text": "🔄 APIni yangilash", "callback_data": "apidetail=newkey"}],
                    [{"text": "⬅️ Orqaga", "callback_data": "hamkor=back"}],
                ]),
            )
        elif sub == "bot":
            my_bots_cnt = len(database.fetch_all("SELECT `id` FROM `hosted_bots` WHERE `owner_id` = ?", (chat_id,)))
            edit(
                chat_id,
                message_id,
                "🤖 <b>Bo‘t yaratish va Serverga joylash</b>\n\n"
                "🖥 <b>1. Bo‘tni serverga qo‘yish:</b> O‘zingizning istalgan Telegram botingizni 24/7 tezkor serverimizga (<b>GO / PRO / PLUS</b> tariflarida) joylashtiring.\n\n"
                "🚀 <b>2. SMM BOTNI serverga qo‘yish:</b> Hech qanday kod yozmasdan, faqat <b>Token + Admin ID + Bot useri</b> ni kiritib shaxsiy SMM botingizni avtomatik ishga tushiring (🎁 <b>Birinchi marta 7 kun TEKIN</b>, keyin oyiga <b>10 000 so‘m</b>)!\n\n"
                "👇 <i>Kerakli bo‘limni tanlang:</i>",
                keyboard([
                    [{"text": "🖥 Bo‘tni serverga qo‘yish", "callback_data": "hamkor=host_bot"}],
                    [{"text": "🚀 SMM BOTNI serverga qo‘yish", "callback_data": "hamkor=smm_bot"}],
                    [{"text": f"📂 Mening serverdagi bo‘tlarim ({my_bots_cnt} ta)", "callback_data": "hamkor=my_bots"}],
                    [{"text": "⬅️ Orqaga", "callback_data": "hamkor=back"}],
                ]),
            )
        elif sub == "host_bot":
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
            u_bal_str = fmt_money(rew.get("balance", "0"))
            trfs = _get_server_tariffs()
            go_p = fmt_money(trfs["GO"])
            pro_p = fmt_money(trfs["PRO"])
            plus_p = fmt_money(trfs["PLUS"])
            edit(
                chat_id,
                message_id,
                f"🖥 <b>Bo‘tni serverga qo‘yish — Server Tariflari</b>\n\n"
                f"🟢 <b>GO Tarifi — {go_p} so‘m / oy</b>\n"
                f"• ⚙️ 1 ta Telegram Bot (24/7 uzluksiz ishlash)\n"
                f"• 💾 512 MB RAM | 5 GB SSD xotira\n"
                f"• 🔄 Avto-restart tizimi\n\n"
                f"🔵 <b>PRO Tarifi — {pro_p} so‘m / oy</b>\n"
                f"• ⚡ Yuqori tezlik (TURBO 24/7)\n"
                f"• 💾 1 GB RAM | 15 GB NVMe SSD xotira\n"
                f"• 🛡 DDoS himoya + Avto-restart + Log nazorati\n\n"
                f"🟣 <b>PLUS Tarifi — {plus_p} so‘m / oy</b>\n"
                f"• 👑 VIP Dedicated quvvat (Maksimal tezlik)\n"
                f"• 💾 2 GB RAM | 30 GB NVMe SSD xotira\n"
                f"• 🚀 100% Uptime kafolati + VIP yordam\n\n"
                f"💵 <b>Sizning balansingiz:</b> <b>{u_bal_str} so‘m</b>\n\n"
                f"👇 <i>O‘zingizga mos server tarifini tanlang:</i>",
                keyboard([
                    [{"text": f"🟢 GO — {go_p} so‘m / oy", "callback_data": "buy_tariff=GO"}],
                    [{"text": f"🔵 PRO — {pro_p} so‘m / oy", "callback_data": "buy_tariff=PRO"}],
                    [{"text": f"🟣 PLUS — {plus_p} so‘m / oy", "callback_data": "buy_tariff=PLUS"}],
                    [{"text": "💳 Pul kiritish", "callback_data": "menu=tolov"}],
                    [{"text": "⬅️ Orqaga", "callback_data": "hamkor=bot"}],
                ]),
            )
        elif sub == "smm_bot":
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
            u_bal_str = fmt_money(rew.get("balance", "0"))
            trfs = _get_server_tariffs()
            smm_p = fmt_money(trfs["SMM"])
            trial_days = int(float(get_file("set/smm_bot_trial_days.txt").strip() or 7))
            used_trial = _has_used_smm_trial(chat_id)
            if not used_trial:
                trial_badge = f"🎁 <b>Birinchi marta kirganingiz uchun {trial_days} KUN TEKIN!</b> (Keyin oyiga {smm_p} so‘m)"
                start_btn_text = f"🚀 SMM Botni ishga tushirish (🎁 {trial_days} kun TEKIN)"
            else:
                trial_badge = f"💰 <b>Server to‘lovi:</b> Oyiga <b>{smm_p} so‘m</b> (30 kun)"
                start_btn_text = f"🚀 SMM Botni ishga tushirish ({smm_p} so‘m / oy)"

            edit(
                chat_id,
                message_id,
                f"🚀 <b>SMM BOTNI Serverga Qo‘yish (Avtomatik)</b>\n\n"
                f"✨ <b>Qanday ishlaydi?</b>\n"
                f"• Sizga bot kodi berilmaydi va dasturlash talab qilinmaydi!\n"
                f"• Faqatgina @BotFather dan olgan <b>Token</b>, <b>Admin ID</b> va <b>Bot useri (@username)</b> ni yuborasiz.\n"
                f"• Serverimiz botingizni <b>avtomatik to‘g‘irlab, 24/7 rejimda darhol ishga tushirib beradi!</b>\n\n"
                f"{trial_badge}\n"
                f"💵 <b>Sizning balansingiz:</b> <b>{u_bal_str} so‘m</b>\n\n"
                f"👇 <i>Boshlash uchun quyidagi tugmani bosing:</i>",
                keyboard([
                    [{"text": start_btn_text, "callback_data": "smm_deploy=start"}],
                    [{"text": "📂 Mening serverdagi bo‘tlarim", "callback_data": "hamkor=my_bots"}],
                    [{"text": "💳 Pul kiritish", "callback_data": "menu=tolov"}],
                    [{"text": "⬅️ Orqaga", "callback_data": "hamkor=bot"}],
                ]),
            )
        elif sub == "my_bots":
            my_rows = database.fetch_all("SELECT * FROM `hosted_bots` WHERE `owner_id` = ? ORDER BY `id` DESC", (chat_id,))
            if not my_rows:
                edit(
                    chat_id,
                    message_id,
                    "📂 <b>Mening serverdagi bo‘tlarim</b>\n\n"
                    "🤷‍♂️ Sizda hozircha serverga ulangan botlar yo‘q.\n"
                    "<i>«🚀 SMM BOTNI serverga qo‘yish» yoki «🖥 Bo‘tni serverga qo‘yish» bo‘limidan yangi bot qo‘shishingiz mumkin!</i>",
                    keyboard([[{"text": "⬅️ Orqaga", "callback_data": "hamkor=bot"}]]),
                )
            else:
                lines = ["📂 <b>Sizning serverdagi bo‘tlaringiz:</b>\n"]
                kb_rows = []
                for b in my_rows:
                    bid = int(b["id"])
                    running = _is_hosted_bot_running(bid) and b.get("status") == "active"
                    st_txt = "🟢 Ishlamoqda" if running else ("🔴 Muddati tugagan" if b.get("status") == "expired" else "⏸ To‘xtatilgan")
                    trial_lbl = " (🎁 7 kun tekin)" if int(b.get("is_trial") or 0) == 1 else ""
                    lines.append(
                        f"🤖 <b>#{bid} | @{b['bot_username'].lstrip('@')}</b>\n"
                        f"   🏷 Tarif: <b>{b['tariff_plan']}{trial_lbl}</b> ({fmt_money(b['monthly_price'])} so‘m/oy)\n"
                        f"   👑 Admin ID: <code>{b['bot_admin_id']}</code> | Holati: <b>{st_txt}</b>\n"
                        f"   ⏳ Muddati: <code>{b['expires_str']}</code> gacha"
                    )
                    kb_rows.append([
                        {"text": f"🔄 Restart (#{bid})", "callback_data": f"mybot_act=restart={bid}"},
                        {"text": f"{'⏹ To‘xtatish' if running else '▶️ Yoqish'} (#{bid})", "callback_data": f"mybot_act=toggle={bid}"},
                    ])
                    kb_rows.append([
                        {"text": f"⏳ +30 kun uzaytirish ({fmt_money(b['monthly_price'])} so‘m)", "callback_data": f"mybot_act=renew={bid}"},
                        {"text": f"🗑️ O‘chirish (#{bid})", "callback_data": f"mybot_act=del={bid}"},
                    ])
                kb_rows.append([{"text": "⬅️ Orqaga", "callback_data": "hamkor=bot"}])
                edit(chat_id, message_id, "\n\n".join(lines), keyboard(kb_rows))
        return

    # ------------------------------------------------------------------------
    # 1) SERVER TARIFLARI ("GO - PRO - PLUS") BO'YICHA BOT QO'YISH OQIMI
    # ------------------------------------------------------------------------
    if data.startswith("buy_tariff=") and joinchat(chat_id):
        plan_name = data.split("=", 1)[1].strip().upper()
        trfs = _get_server_tariffs()
        price = trfs.get(plan_name, 15000.0)
        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
        u_bal = float(rew.get("balance") or 0)
        if u_bal < price:
            bot(
                "answerCallbackQuery",
                {
                    "callback_query_id": cqid,
                    "text": f"⛔️ Hisobingizda mablag‘ yetarli emas!\n\n🏷 {plan_name} tarifi narxi: {fmt_money(price)} so‘m / oy\n💵 Balansingiz: {fmt_money(u_bal)} so‘m",
                    "show_alert": True,
                },
            )
            return
        put_file(f"user/{chat_id}.host_plan", plan_name)
        del_msg(chat_id, message_id)
        sms(
            chat_id,
            f"🖥 <b>Server Tarifi: {plan_name} ({fmt_money(price)} so‘m / oy)</b>\n\n"
            f"🔑 <b>1-qadam:</b> @BotFather dan olgan botingizning <b>TOKEN</b>ini yuboring:\n\n"
            f"<i>Namuna: 1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw</i>",
            ORT_KB,
        )
        put_file(f"user/{chat_id}.step", "host_tariff_token")
        return

    if step == "host_tariff_token" and text and joinchat(cid):
        me_data = validate_telegram_bot_token(text)
        if not me_data:
            sms(cid, "❌ <b>Token xato yoki mavjud emas!</b>\nIltimos, @BotFather dan olingan to‘g‘ri tokenni yuboring:", ORT_KB)
            return
        put_file(f"user/{cid}.host_token", text.strip())
        put_file(f"user/{cid}.host_uname", me_data.get("username", "bot"))
        sms(
            cid,
            f"✅ <b>Token tasdiqlandi!</b> Bot: @{me_data.get('username', '')}\n\n"
            f"📁 <b>2-qadam:</b> Endi serverga joylamoqchi bo‘lgan <b>Python (.py) bot faylingizni</b> yuboring (yoki tayyor bot sifatida avtomatik ulash uchun <b>Admin ID</b> raqamingizni yozib yuboring: <code>{cid}</code>):",
            ORT_KB,
        )
        put_file(f"user/{cid}.step", "host_tariff_file")
        return

    if step == "host_tariff_file" and (document or text) and joinchat(cid):
        plan_name = get_file(f"user/{cid}.host_plan").strip() or "GO"
        b_token = get_file(f"user/{cid}.host_token").strip()
        b_uname = get_file(f"user/{cid}.host_uname").strip() or "bot"
        trfs = _get_server_tariffs()
        price = trfs.get(plan_name, 15000.0)
        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (cid,)) or {}
        u_bal = float(rew.get("balance") or 0)
        if u_bal < price:
            sms(cid, f"❌ Hisobingizda mablag‘ yetarli emas! Kerak: {fmt_money(price)} so‘m.", m_kb)
            unlink_file(f"user/{cid}.step")
            return

        custom_bytes: Optional[bytes] = None
        admin_for_bot = cid
        if document:
            fname = str(document.get("file_name", "bot.py"))
            if not fname.endswith(".py"):
                sms(cid, "⚠️ Faqat <code>.py</code> formatdagi Python bot faylini yuboring!", ORT_KB)
                return
            custom_bytes = download_telegram_file_bytes(str(document.get("file_id", "")))
            if not custom_bytes:
                sms(cid, "⚠️ Faylni yuklab olishda xatolik yuz berdi, qaytadan yuboring:", ORT_KB)
                return
        elif text and text.strip().isdigit():
            admin_for_bot = text.strip()
        else:
            sms(cid, "⚠️ Iltimos, <code>.py</code> bot faylini yuboring yoki Admin ID raqamingizni kiriting:", ORT_KB)
            return

        new_bal = round(u_bal - price, 2)
        database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_bal), cid))
        now_str = datetime.datetime.now().strftime("%Y.%m.%d %H:%M")
        exp_ts = time.time() + (30 * 86400)
        exp_str = datetime.datetime.fromtimestamp(exp_ts).strftime("%Y.%m.%d %H:%M")

        new_bid = database.execute(
            """INSERT INTO `hosted_bots`
            (`owner_id`, `bot_category`, `tariff_plan`, `bot_token`, `bot_admin_id`, `bot_username`,
             `monthly_price`, `is_trial`, `status`, `created_at`, `expires_ts`, `expires_str`, `script_path`)
            VALUES (?, 'custom', ?, ?, ?, ?, ?, 0, 'active', ?, ?, ?, '')""",
            (cid, plan_name, b_token, admin_for_bot, b_uname, str(int(price)), now_str, exp_ts, exp_str),
        )
        bot_row = database.fetch_one("SELECT * FROM `hosted_bots` WHERE `id` = ?", (new_bid,))
        if bot_row:
            deploy_and_start_hosted_bot(bot_row, custom_py_bytes=custom_bytes)

        for ext in ("step", "host_plan", "host_token", "host_uname"):
            unlink_file(f"user/{cid}.{ext}")

        sms(
            cid,
            f"🎉 <b>Tabriklaymiz! Botingiz {plan_name} server tarifida ishga tushirildi!</b>\n\n"
            f"🤖 Bot: @{b_uname.lstrip('@')}\n"
            f"🏷 Tarif: <b>{plan_name} ({fmt_money(price)} so‘m / oy)</b>\n"
            f"⏳ Faol muddati: <code>{exp_str}</code> gacha (30 kun)\n"
            f"🟢 Holati: <b>Serverda 24/7 ishlamoqda!</b>",
            m_kb,
        )
        if str(cid) != str(ADMIN):
            sms(
                ADMIN,
                f"🖥 <b>Serverga yangi bot joylandi ({plan_name})!</b>\n"
                f"👤 Foydalanuvchi: <a href='tg://user?id={cid}'>{cid}</a>\n"
                f"🤖 Bot: @{b_uname.lstrip('@')} | 💰 To‘lov: {fmt_money(price)} so‘m",
            )
        return

    # ------------------------------------------------------------------------
    # 2) SMM BOTNI SERVERGA QO'YISH (KOD BERILMAYDI, TOKEN + ADMIN ID + USER SO'RALADI,
    #    1-MARTA 7 KUN TEKIN, KEYIN OYIGA 10 000 SO'M!)
    # ------------------------------------------------------------------------
    if data == "smm_deploy=start" and joinchat(chat_id):
        trfs = _get_server_tariffs()
        smm_price = trfs["SMM"]
        used_trial = _has_used_smm_trial(chat_id)
        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
        u_bal = float(rew.get("balance") or 0)

        if used_trial and u_bal < smm_price:
            bot(
                "answerCallbackQuery",
                {
                    "callback_query_id": cqid,
                    "text": f"⛔️ Siz 7 kunlik tekin sinov muddatidan foydalangansiz!\n\n💰 SMM Bot oylik narxi: {fmt_money(smm_price)} so‘m\n💵 Balansingiz: {fmt_money(u_bal)} so‘m",
                    "show_alert": True,
                },
            )
            return

        del_msg(chat_id, message_id)
        trial_note = "🎁 <b>Siz uchun 7 kun TEKIN sinov muddati faollashadi!</b>" if not used_trial else f"💰 <b>Oylik to‘lov: {fmt_money(smm_price)} so‘m</b>"
        sms(
            chat_id,
            f"🚀 <b>SMM BOTNI Serverga Qo‘yish (1/3 qadam)</b>\n"
            f"{trial_note}\n\n"
            f"🔑 <b>1-qadam: @BotFather dan olgan botingizning TOKENini yuboring:</b>\n\n"
            f"<i>Namuna: 1234567890:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw</i>",
            ORT_KB,
        )
        put_file(f"user/{chat_id}.step", "smm_step1_token")
        return

    if step == "smm_step1_token" and text and joinchat(cid):
        me_data = validate_telegram_bot_token(text)
        if not me_data:
            sms(
                cid,
                "❌ <b>Token noto‘g‘ri yoki faol emas!</b>\n\n"
                "Iltimos, @BotFather ga kirib yangi bot oching va berilgan API Tokenni to‘liq nusxalab yuboring:",
                ORT_KB,
            )
            return
        put_file(f"user/{cid}.smm_token", text.strip())
        put_file(f"user/{cid}.smm_detected_uname", me_data.get("username", ""))
        sms(
            cid,
            f"✅ <b>Token qabul qilindi!</b>\n\n"
            f"👤 <b>2-qadam (2/3): Botingiz uchun ADMIN ID raqamini yuboring:</b>\n\n"
            f"💡 <i>Sizning o‘z Telegram ID raqamingiz:</i> <code>{cid}</code>\n"
            f"(Nusxalab yuborishingiz mumkin):",
            ORT_KB,
        )
        put_file(f"user/{cid}.step", "smm_step2_admin")
        return

    if step == "smm_step2_admin" and text and joinchat(cid):
        adm_id_input = text.strip()
        if not adm_id_input.isdigit():
            sms(cid, f"⚠️ <b>Admin ID faqat raqamlardan iborat bo‘lishi kerak!</b>\nMasalan: <code>{cid}</code>", ORT_KB)
            return
        put_file(f"user/{cid}.smm_admin_id", adm_id_input)
        det_u = get_file(f"user/{cid}.smm_detected_uname").strip()
        hint_u = f"@{det_u}" if det_u else "@mening_smm_botim"
        sms(
            cid,
            f"✅ <b>Admin ID (<code>{adm_id_input}</code>) saqlandi!</b>\n\n"
            f"🤖 <b>3-qadam (3/3): Botingizning userini (@username) yuboring:</b>\n\n"
            f"💡 <i>Botingiz useri:</i> <code>{hint_u}</code>",
            ORT_KB,
        )
        put_file(f"user/{cid}.step", "smm_step3_user")
        return

    if step == "smm_step3_user" and text and joinchat(cid):
        raw_uname = text.strip().replace("https://t.me/", "").lstrip("@").strip()
        if not raw_uname or " " in raw_uname:
            sms(cid, "⚠️ Bot userini to‘g‘ri yuboring (masalan: <code>@smm_bot</code>):", ORT_KB)
            return

        b_token = get_file(f"user/{cid}.smm_token").strip()
        b_admin = get_file(f"user/{cid}.smm_admin_id").strip() or cid
        trfs = _get_server_tariffs()
        smm_price = trfs["SMM"]
        trial_days = int(float(get_file("set/smm_bot_trial_days.txt").strip() or 7))
        used_trial = _has_used_smm_trial(cid)

        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (cid,)) or {}
        u_bal = float(rew.get("balance") or 0)

        now_ts = time.time()
        now_str = datetime.datetime.now().strftime("%Y.%m.%d %H:%M")

        if not used_trial:
            is_trial_flag = 1
            exp_ts = now_ts + (trial_days * 86400)
            period_label = f"🎁 {trial_days} kun TEKIN sinov muddati"
            put_file(f"user/{cid}.smm_trial_used", "1")
        else:
            if u_bal < smm_price:
                sms(cid, f"❌ Hisobingizda mablag‘ yetarli emas! Oyiga: {fmt_money(smm_price)} so‘m.", m_kb)
                unlink_file(f"user/{cid}.step")
                return
            is_trial_flag = 0
            new_bal = round(u_bal - smm_price, 2)
            database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_bal), cid))
            exp_ts = now_ts + (30 * 86400)
            period_label = f"✅ 30 kunlik faol muddat ({fmt_money(smm_price)} so‘m/oy)"

        exp_str = datetime.datetime.fromtimestamp(exp_ts).strftime("%Y.%m.%d %H:%M")
        new_bid = database.execute(
            """INSERT INTO `hosted_bots`
            (`owner_id`, `bot_category`, `tariff_plan`, `bot_token`, `bot_admin_id`, `bot_username`,
             `monthly_price`, `is_trial`, `status`, `created_at`, `expires_ts`, `expires_str`, `script_path`)
            VALUES (?, 'smm', 'SMM BOT', ?, ?, ?, ?, ?, 'active', ?, ?, ?, '')""",
            (cid, b_token, b_admin, raw_uname, str(int(smm_price)), is_trial_flag, now_str, exp_ts, exp_str),
        )
        bot_row = database.fetch_one("SELECT * FROM `hosted_bots` WHERE `id` = ?", (new_bid,))
        ok_started = deploy_and_start_hosted_bot(bot_row) if bot_row else False

        for ext in ("step", "smm_token", "smm_admin_id", "smm_detected_uname"):
            unlink_file(f"user/{cid}.{ext}")

        sms(
            cid,
            f"🎉 <b>Tabriklaymiz! SMM Botingiz avtomatik sozlandi va serverda ishga tushdi!</b>\n\n"
            f"🤖 <b>Bot useri:</b> @{raw_uname}\n"
            f"👑 <b>Bot Admin ID:</b> <code>{b_admin}</code>\n"
            f"🎁 <b>Tarif:</b> {period_label}\n"
            f"💰 <b>Keyingi oylik to‘lov:</b> {fmt_money(smm_price)} so‘m / oy\n"
            f"⏳ <b>Faol muddati:</b> <code>{exp_str}</code> gacha\n"
            f"🟢 <b>Holati:</b> {'Serverda 24/7 ishlamoqda!' if ok_started else 'Sozlandi (Faol)'}\n\n"
            f"👉 Hoziroq @{raw_uname} botingizga kirib <code>/start</code> bosing — <b>«🗄️ Boshqaruv»</b> admin paneli siz uchun tayyor!",
            m_kb,
        )
        if str(cid) != str(ADMIN):
            sms(
                ADMIN,
                f"🚀 <b>Yangi SMM Bot serverga ulandi!</b>\n"
                f"👤 Egasi: <a href='tg://user?id={cid}'>{cid}</a>\n"
                f"🤖 Bot: @{raw_uname} | Admin ID: <code>{b_admin}</code>\n"
                f"🏷 Holat: {period_label}",
            )
        return

    # ------------------------------------------------------------------------
    # 3) FOYDALANUVCHINING SERVERDAGI BOTLARINI BOSHQARISH (RESTART / TOGGLE / RENEW / DELETE)
    # ------------------------------------------------------------------------
    if data.startswith("mybot_act=") and joinchat(chat_id):
        parts = data.split("=")
        act_name = parts[1] if len(parts) > 1 else ""
        bid = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
        b_row = database.fetch_one("SELECT * FROM `hosted_bots` WHERE `id` = ? AND (`owner_id` = ? OR ? = ?)", (bid, chat_id, chat_id, ADMIN))
        if not b_row:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Bot topilmadi!", "show_alert": True})
            return

        if act_name == "restart":
            if float(b_row.get("expires_ts") or 0) <= time.time():
                bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⛔️ Bot muddati tugagan! Avval +30 kunga uzaytiring.", "show_alert": True})
                return
            deploy_and_start_hosted_bot(b_row)
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": f"🔄 @{b_row['bot_username']} qayta ishga tushirildi!", "show_alert": True})
        elif act_name == "toggle":
            if _is_hosted_bot_running(bid):
                _stop_hosted_bot_proc(bid)
                database.execute("UPDATE `hosted_bots` SET `status` = 'stopped' WHERE `id` = ?", (bid,))
                bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⏹ Bot to‘xtatildi!"})
            else:
                if float(b_row.get("expires_ts") or 0) <= time.time():
                    bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⛔️ Bot muddati tugagan! Avval +30 kunga uzaytiring.", "show_alert": True})
                    return
                deploy_and_start_hosted_bot(b_row)
                bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "▶️ Bot ishga tushirildi!"})
        elif act_name == "renew":
            m_price = float(b_row.get("monthly_price") or 10000)
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
            u_bal = float(rew.get("balance") or 0)
            if u_bal < m_price:
                bot(
                    "answerCallbackQuery",
                    {
                        "callback_query_id": cqid,
                        "text": f"⛔️ Hisobingizda mablag‘ yetarli emas!\nUzaytirish (+30 kun): {fmt_money(m_price)} so‘m",
                        "show_alert": True,
                    },
                )
                return
            new_bal = round(u_bal - m_price, 2)
            base_ts = max(time.time(), float(b_row.get("expires_ts") or 0))
            new_exp_ts = base_ts + (30 * 86400)
            new_exp_str = datetime.datetime.fromtimestamp(new_exp_ts).strftime("%Y.%m.%d %H:%M")
            database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_bal), chat_id))
            database.execute(
                "UPDATE `hosted_bots` SET `expires_ts` = ?, `expires_str` = ?, `status` = 'active', `is_trial` = 0 WHERE `id` = ?",
                (new_exp_ts, new_exp_str, bid),
            )
            b_row_updated = database.fetch_one("SELECT * FROM `hosted_bots` WHERE `id` = ?", (bid,))
            if b_row_updated:
                deploy_and_start_hosted_bot(b_row_updated)
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": f"✅ Bot muddati +30 kunga ({new_exp_str} gacha) uzaytirildi!", "show_alert": True})
        elif act_name == "del":
            _stop_hosted_bot_proc(bid)
            database.execute("DELETE FROM `hosted_bots` WHERE `id` = ?", (bid,))
            shutil.rmtree(os.path.join(config.HOSTED_BOTS_DIR, f"bot_{bid}"), ignore_errors=True)
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "🗑️ Bot serverdan o‘chirildi!"})

        # Refresh "my_bots" view
        my_rows = database.fetch_all("SELECT * FROM `hosted_bots` WHERE `owner_id` = ? ORDER BY `id` DESC", (chat_id,))
        if not my_rows:
            edit(
                chat_id,
                message_id,
                "📂 <b>Mening serverdagi bo‘tlarim</b>\n\n🤷‍♂️ Sizda hozircha serverga ulangan botlar yo‘q.",
                keyboard([[{"text": "⬅️ Orqaga", "callback_data": "hamkor=bot"}]]),
            )
        else:
            lines = ["📂 <b>Sizning serverdagi bo‘tlaringiz:</b>\n"]
            kb_rows = []
            for b in my_rows:
                b_i = int(b["id"])
                running = _is_hosted_bot_running(b_i) and b.get("status") == "active"
                st_txt = "🟢 Ishlamoqda" if running else ("🔴 Muddati tugagan" if b.get("status") == "expired" else "⏸ To‘xtatilgan")
                lines.append(
                    f"🤖 <b>#{b_i} | @{b['bot_username'].lstrip('@')}</b>\n"
                    f"   🏷 Tarif: <b>{b['tariff_plan']}</b> ({fmt_money(b['monthly_price'])} so‘m/oy)\n"
                    f"   👑 Admin ID: <code>{b['bot_admin_id']}</code> | Holati: <b>{st_txt}</b>\n"
                    f"   ⏳ Muddati: <code>{b['expires_str']}</code> gacha"
                )
                kb_rows.append([
                    {"text": f"🔄 Restart (#{b_i})", "callback_data": f"mybot_act=restart={b_i}"},
                    {"text": f"{'⏹ To‘xtatish' if running else '▶️ Yoqish'} (#{b_i})", "callback_data": f"mybot_act=toggle={b_i}"},
                ])
                kb_rows.append([
                    {"text": f"⏳ +30 kun uzaytirish ({fmt_money(b['monthly_price'])} so‘m)", "callback_data": f"mybot_act=renew={b_i}"},
                    {"text": f"🗑️ O‘chirish (#{b_i})", "callback_data": f"mybot_act=del={b_i}"},
                ])
            kb_rows.append([{"text": "⬅️ Orqaga", "callback_data": "hamkor=bot"}])
            edit(chat_id, message_id, "\n\n".join(lines), keyboard(kb_rows))
        return

    if data.startswith("apidetail="):
        res = data.split("=")[1]
        if res == "newkey":
            newkey = hashlib.md5(uuid.uuid4().hex.encode("utf-8")).hexdigest()
            database.execute("UPDATE `users` SET `api_key` = ? WHERE `id` = ?", (newkey, chat_id))
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
            edit(
                chat_id,
                message_id,
                f"<b>✅ API kalit yangilandi.\n\n<code>{rew.get('api_key', '')}</code>\n\n"
                f"💵 API hisobi:\n<b>{fmt_money(rew.get('balance', '0'))}</b> so‘m</b>",
                keyboard([
                    [{"text": "📝 Qo‘llanma", "callback_data": "apidetail=qoll"}],
                    [{"text": "🔄 APIni yangilash", "callback_data": "apidetail=newkey"}],
                    [{"text": "⬅️ Orqaga", "callback_data": "hamkor=back"}],
                ]),
            )
        elif res == "qoll":
            edit(
                chat_id,
                message_id,
                f"<b>❓ API nima?</b>\nBotimizdagi xizmatlarni o'z botingiz yoki saytingizga ulab ishlatishingiz mumkin.\n\n"
                f"🔗 <b>API manzili:</b> <code>http://{host}/api/v2</code>\n"
                f"📌 <b>So'rov turlari (action):</b> <code>services</code>, <code>add</code>, <code>status</code>, <code>balance</code>\n\n"
                f"⚠️ Diqqat: API kalitni begona kishiga bermang!",
                keyboard([
                    [{"text": "🔄 APIni yangilash", "callback_data": "apidetail=newkey"}],
                    [{"text": "⬅️ Orqaga", "callback_data": "hamkor=api"}],
                ]),
            )
        return

    # ========================================================================
    # ADMIN PANEL: Bo'limlar, Ichki bo'limlar va Xizmatlarni sozlash
    # ========================================================================

    if (text == "🛍 Buyurtmalarni sozlash" and cid == ADMIN) or data == "xsetting":
        target = ADMIN if text else chat_id
        if data == "xsetting":
            del_msg(chat_id, message_id)
        sms(
            target,
            "<b>Quyidagilardan birini tanlang:</b>",
            keyboard([
                [{"text": "📂 Bo'limlarni sozlash", "callback_data": "bolim"}],
                [{"text": "📂 Ichki bo'limlarni sozlash", "callback_data": "ichki"}],
                [{"text": "🛍 Xizmatlarni sozlash", "callback_data": "xizmat"}],
            ]),
        )
        return

    if data == "bolim":
        edit(
            chat_id,
            message_id,
            "<b>Quyidagilardan birini tanlang:</b>",
            keyboard([
                [{"text": "Yangi bo'lim qo'shish", "callback_data": "newFol"}],
                [{"text": "Tahrirlash", "callback_data": "editFol"}],
                [{"text": "O'chirish", "callback_data": "delFol"}],
                [{"text": "Orqaga", "callback_data": "xsetting"}],
            ]),
        )
        return

    if data == "editFol":
        edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard([[{"text": "Nomini o'zgartirish", "callback_data": "editFols"}]]))
        return

    if data == "editFols":
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Bo'limlar topilmadi!", "show_alert": True})
        else:
            btns = [{"text": enc("decode", s["category_name"]), "callback_data": f"editFolss-{s['category_id']}"} for s in cats]
            edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard(chunk_list(btns, 3)))
        return

    if data.startswith("editFolss-"):
        ex = data.split("-")[1]
        del_msg(cid2, mid2)
        sms(cid2, "<b>Yangi qiymatni kiriting:</b>", AORT_KB)
        put_file(f"user/{cid2}.step", f"editFol-{ex}")
        return

    if step.startswith("editFol-") and text:
        ex = step.split("-")[1]
        database.execute("UPDATE `categorys` SET `category_name` = ? WHERE `category_id` = ?", (enc("encode", text), ex))
        sms(cid, "<b>Muvaffaqiyatli o'zgartirildi.</b>", PANEL2_KB)
        unlink_file(f"user/{cid}.step")
        return

    if data == "delFol":
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Bo‘limlar topilmadi!", "show_alert": True})
        else:
            btns = [[{"text": enc("decode", s["category_name"]), "callback_data": f"delFols={s['category_id']}"}] for s in cats]
            edit(chat_id, message_id, "👉 O‘zingizga kerakli tarmoqni tanlang:", keyboard(btns))
        return

    if data.startswith("delFols="):
        ex = data.split("=")[1]
        qd = database.fetch_one("SELECT * FROM `cates` WHERE `category_id` = ?", (ex,))
        if qd:
            database.execute("DELETE FROM `services` WHERE `category_id` = ?", (qd["cate_id"],))
        database.execute("DELETE FROM `cates` WHERE `category_id` = ?", (ex,))
        database.execute("DELETE FROM `categorys` WHERE `category_id` = ?", (ex,))
        del_msg(chat_id, message_id)
        sms(chat_id, "Bo'lim olib tashlandi!", PANEL2_KB)
        return

    if data == "newFol":
        del_msg(chat_id, message_id)
        sms(chat_id, "<b>Yangi bo'lim nomini yuboring:</b>", AORT_KB)
        put_file(f"user/{chat_id}.step", "newFol")
        return

    if step == "newFol" and text:
        database.execute("INSERT INTO `categorys` (`category_name`, `category_status`) VALUES (?, 'ON')", (enc("encode", text),))
        sms(cid, "Bo'lim qo'shildi!", PANEL2_KB)
        unlink_file(f"user/{cid}.step")
        return

    # Ichki bo'limlar (cates)
    if data == "ichki":
        edit(
            chat_id,
            message_id,
            "<b>Quyidagilardan birini tanlang:</b>",
            keyboard([
                [{"text": "Yangi ichki bo'lim qo'shish", "callback_data": "newFold"}],
                [{"text": "Tahrirlash", "callback_data": "editFold"}],
                [{"text": "O'chirish", "callback_data": "delFold"}],
                [{"text": "Orqaga", "callback_data": "xsetting"}],
            ]),
        )
        return

    if data == "editFold":
        edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard([[{"text": "Nomini o'zgartirish", "callback_data": "editFolds"}]]))
        return

    if data == "editFolds":
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Avval asosiy bo'lim qo'shing!", "show_alert": True})
            return
        btns = [[{"text": enc("decode", s["category_name"]), "callback_data": f"editFolds-{s['category_id']}"}] for s in cats]
        btns.append([{"text": "Orqaga", "callback_data": "ichki"}])
        edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard(btns))
        return

    if data.startswith("editFolds-"):
        n = data.split("-")[1]
        cates = database.fetch_all("SELECT * FROM `cates` WHERE `category_id` = ?", (n,))
        if not cates:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu bo'lim uchun xizmat turlari topilmadi!", "show_alert": True})
        else:
            seen = set()
            btns = []
            for s in cates:
                nm = enc("decode", s["name"])
                if nm not in seen:
                    seen.add(nm)
                    btns.append([{"text": nm, "callback_data": f"editFoldm-{s['cate_id']}"}])
            edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard(btns))
        return

    if data.startswith("editFoldm-"):
        ex = data.split("-")[1]
        del_msg(cid2, mid2)
        sms(cid2, "<b>Yangi qiymatni kiriting:</b>", AORT_KB)
        put_file(f"user/{cid2}.step", f"editFoldms-{ex}")
        return

    if step.startswith("editFoldms-") and text:
        ex = step.split("-")[1]
        database.execute("UPDATE `cates` SET `name` = ? WHERE `cate_id` = ?", (enc("encode", text), ex))
        sms(cid, "<b>Muvaffaqiyatli o'zgartirildi.</b>", PANEL2_KB)
        unlink_file(f"user/{cid}.step")
        return

    if data == "delFold":
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Avval asosiy bo'lim qo'shing!", "show_alert": True})
            return
        btns = [{"text": enc("decode", s["category_name"]), "callback_data": f"delFolds={s['category_id']}"} for s in cats]
        kb_rows = chunk_list(btns, 3)
        kb_rows.append([{"text": "Orqaga", "callback_data": "ichki"}])
        edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard(kb_rows))
        return

    if data.startswith("delFolds="):
        bolim = data.split("=")[1]
        cates = database.fetch_all("SELECT * FROM `cates` WHERE `category_id` = ?", (bolim,))
        if not cates:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu bo'lim uchun xizmat turlari topilmadi!", "show_alert": True})
        else:
            seen = set()
            btns = []
            for s in cates:
                nm = enc("decode", s["name"])
                if nm not in seen:
                    seen.add(nm)
                    btns.append([{"text": nm, "callback_data": f"delFolm={s['cate_id']}"}])
            btns.append([{"text": "Orqaga", "callback_data": "absd"}])
            edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard(btns))
        return

    if data.startswith("delFolm="):
        ex = data.split("=")[1]
        database.execute("DELETE FROM `services` WHERE `category_id` = ?", (ex,))
        database.execute("DELETE FROM `cates` WHERE `cate_id` = ?", (ex,))
        del_msg(cid2, mid2)
        sms(cid2, "Ichki bo'lim olib tashlandi!", PANEL2_KB)
        return

    if data == "newFold":
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Avval «Bo'limlarni sozlash» dan asosiy bo'lim qo'shing!", "show_alert": True})
            return
        btns = [{"text": enc("decode", s["category_name"]), "callback_data": f"adFol={s['category_id']}"} for s in cats]
        kb_rows = chunk_list(btns, 3)
        kb_rows.append([{"text": "Orqaga", "callback_data": "ichki"}])
        edit(chat_id, message_id, "<b>Quyidagilardan birini tanlang:</b>", keyboard(kb_rows))
        return

    if data.startswith("adFol="):
        ex = data.split("=")[1]
        put_file("set/c.txt", ex)
        del_msg(chat_id, message_id)
        sms(chat_id, "<b>Yangi ichki bo'lim nomini yuboring:</b>", AORT_KB)
        put_file(f"user/{chat_id}.step", "newFold")
        return

    if step == "newFold" and text:
        ci = get_file("set/c.txt").strip()
        database.execute("INSERT INTO `cates` (`name`, `category_id`) VALUES (?, ?)", (enc("encode", text), ci))
        sms(cid, "Ichki bo'lim qo'shildi!", PANEL2_KB)
        unlink_file(f"user/{cid}.step")
        return

    # Xizmatlar (services)
    if data == "xizmat":
        edit(
            chat_id,
            message_id,
            "<b>Quyidagilardan birini tanlang:</b>",
            keyboard([
                [{"text": "Yangi xizmat qo'shish", "callback_data": "newXiz"}],
                [{"text": "Xizmatlarni yuklab olish", "callback_data": "uplXiz"}],
                [{"text": "Tahrirlash", "callback_data": "editXiz"}],
                [{"text": "O'chirish", "callback_data": "delXiz"}],
                [{"text": "Orqaga", "callback_data": "xsetting"}],
            ]),
        )
        return

    if data == "uplXiz":
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Bo‘limlar topilmadi!", "show_alert": True})
        else:
            btns = [{"text": enc("decode", s["category_name"]), "callback_data": f"uplad={s['category_id']}"} for s in cats]
            edit(chat_id, message_id, "<b>Quyidagilardan birini tanlang:</b>", keyboard(chunk_list(btns, 3)))
        return

    if data.startswith("uplad="):
        n = data.split("=")[1]
        try:
            upx = json.loads(get_file("set/upladd.json") or "{}")
        except Exception:
            upx = {}
        upx["category_id"] = n
        put_file("set/upladd.json", json.dumps(upx, indent=2))
        cates = database.fetch_all("SELECT * FROM `cates` WHERE `category_id` = ?", (n,))
        if not cates:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu bo'lim uchun xizmat turlari topilmadi!", "show_alert": True})
        else:
            seen = set()
            btns = []
            for s in cates:
                nm = enc("decode", s["name"])
                if nm not in seen:
                    seen.add(nm)
                    btns.append([{"text": nm, "callback_data": f"uplads-{s['cate_id']}"}])
            btns.append([{"text": "Orqaga", "callback_data": "uplXiz"}])
            edit(chat_id, message_id, "<b>Quyidagilardan birini tanlang:</b>", keyboard(btns))
        return

    if data.startswith("uplads-"):
        n = data.split("-")[1]
        try:
            upx = json.loads(get_file("set/upladd.json") or "{}")
        except Exception:
            upx = {}
        upx["cate_id"] = n
        put_file("set/upladd.json", json.dumps(upx, indent=2))
        providers = database.fetch_all("SELECT * FROM `providers`")
        if not providers:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Provayderlar topilmadi!", "show_alert": True})
        else:
            del_msg(chat_id, message_id)
            prs_lines = []
            btns = []
            for idx, s in enumerate(providers, start=1):
                prs_lines.append(f"<b>{idx}</b>: {strip_provider_domain(s['api_url'])}")
                btns.append({"text": str(idx), "callback_data": f"uplprv-{s['id']}"})
            sms(chat_id, "Provayderni tanlang:\n \n" + "\n".join(prs_lines), keyboard(chunk_list(btns, 3)))
        return

    if data.startswith("uplprv-"):
        n = data.split("-")[1]
        try:
            upx = json.loads(get_file("set/upladd.json") or "{}")
        except Exception:
            upx = {}
        upx["provider"] = n
        put_file("set/upladd.json", json.dumps(upx, indent=2))
        edit(
            chat_id,
            message_id,
            "Provayderning API valyutasini tanlang:",
            keyboard([
                [{"text": "UZS", "callback_data": f"uplval-UZS-{n}"}],
                [{"text": "USD", "callback_data": f"uplval-USD-{n}"}],
                [{"text": "RUB", "callback_data": f"uplval-RUB-{n}"}],
                [{"text": "INR", "callback_data": f"uplval-INR-{n}"}],
                [{"text": "TRY", "callback_data": f"uplval-TRY-{n}"}],
            ]),
        )
        return

    if data.startswith("uplval-"):
        parts = data.split("-")
        curr, prv = parts[1], parts[2]
        try:
            upx = json.loads(get_file("set/upladd.json") or "{}")
        except Exception:
            upx = {}
        upx["currency"] = curr
        put_file("set/upladd.json", json.dumps(upx, indent=2))
        h = arr(prv)
        if h.get("error"):
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Serverda nosozlik\n\nQaytadan urining", "show_alert": True})
            return
        results = h.get("results", [])
        rows = [[{"text": item["name"], "callback_data": f"apload={i}={prv}"}] for i, item in enumerate(results[:23]) if item.get("name")]
        rows.append([{"text": "Orqaga", "callback_data": "xizmat"}, {"text": "▶️ Keyingi", "callback_data": f"nexti=next={prv}=1=23"}])
        edit(chat_id, message_id, "Kerakli xizmat turini tanlang", keyboard(rows))
        return

    if data.startswith("nexti="):
        parts = data.split("=")
        res, prv, ko, kl = parts[1], parts[2], int(parts[3]), int(parts[4])
        h = arr(prv)
        if h.get("error"):
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Serverda nosozlik\n\nQaytadan urining", "show_alert": True})
            return
        results = h.get("results", [])
        ma = kl * 2
        rows = []
        for i in range(kl, min(ma + 1, len(results))):
            if results[i].get("name"):
                rows.append([{"text": results[i]["name"], "callback_data": f"apload={i}={prv}"}])
        rows.append([{"text": "Orqaga", "callback_data": "xizmat"}, {"text": "▶️ Keyingi", "callback_data": f"nexti=next={prv}={kl}={ma + 1}"}])
        edit(chat_id, message_id, "Kerakli xizmat turini tanlang:", keyboard(rows))
        return

    if data.startswith("apload="):
        parts = data.split("=")
        qa = int(parts[1]) + 1
        prv = parts[2]
        h = arr(prv)
        if h.get("error"):
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Serverda nosozlik\n\nQaytadan urining", "show_alert": True})
            return
        nq = ""
        for vs in h.get("results", []):
            if vs.get("id") == qa:
                nq = vs.get("name", "")
                break
        bot("answerCallbackQuery", {"callback_query_id": qid, "text": f"{nq} - uchun xizmatlar qidirilmoqda\n\nIltimos kuting...", "show_alert": True})
        try:
            upx = json.loads(get_file("set/upladd.json") or "{}")
        except Exception:
            upx = {}
        upx["category"] = nq
        put_file("set/upladd.json", json.dumps(upx, indent=2, ensure_ascii=False))
        s = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (prv,))
        raw = http_get(f"{s['api_url']}?key={s['api_key']}&action=services") if s else "[]"
        try:
            j = json.loads(raw)
        except Exception:
            j = []
        rows = []
        for el in j:
            if el.get("category") == nq:
                rows.append([{"text": el.get("name", ""), "callback_data": f"couple={el.get('service')}"}])
        if not rows:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Serverda nosozlik\n\nQaytadan urining", "show_alert": True})
            return
        rows.append([{"text": "✅ Barchasini yuklab olish", "callback_data": f"allapl={prv}"}])
        rows.append([{"text": "Orqaga", "callback_data": "xizmat"}])
        edit(chat_id, message_id, f"\n{nq}\n\n🔢 Xizmatlar soni: {len(rows) - 2} - ta", keyboard(rows))
        return

    if data.startswith("allapl="):
        del_msg(chat_id, message_id)
        prv = data.split("=")[1]
        sent = sms(chat_id, "📂 Yuklab olish boshlandi!..\n\n🔔 Iltimos kuting.")
        mas = sent.get("result", {}).get("message_id") if isinstance(sent.get("result"), dict) else None
        try:
            upx = json.loads(get_file("set/upladd.json") or "{}")
        except Exception:
            upx = {}
        s = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (prv,))
        raw = http_get(f"{s['api_url']}?key={s['api_key']}&action=services") if s else ""
        try:
            j = json.loads(raw)
        except Exception:
            j = []
        if not j:
            if mas:
                edit(cid2, mas, "⚠️ Serverda nosozlik\n\nQaytadan urining")
            return
        percent_row = database.fetch_one("SELECT * FROM `percent` WHERE `id` = 1")
        foiz = float(percent_row["percent"]) if percent_row else 40.0
        curr = str(upx.get("currency", "UZS")).upper()
        fr = float(get_file(f"set/{curr.lower()}") or 1) if curr in ("USD", "RUB", "INR", "TRY") else 1.0

        for el in j:
            if el.get("category") == upx.get("category"):
                el_name = el.get("name", "")
                tas = str(el.get("service", ""))
                min_v = str(el.get("min", "0"))
                max_v = str(el.get("max", "0"))
                rate = float(el.get("rate", 0)) * fr
                rp = (rate / 100.0) * foiz + rate
                stype = str(el.get("type", "Default"))
                detail_json = json.dumps({
                    "name": el_name,
                    "min": min_v,
                    "max": max_v,
                    "type": stype,
                    "cancel": "true" if el.get("cancel") else "false",
                    "refill": "true" if el.get("refill") else "false",
                    "dripfeed": "true" if el.get("dripfeed") else "false",
                }, ensure_ascii=False)
                sname_b64 = enc("encode", trans(el_name))
                database.execute(
                    """INSERT INTO `services`
                    (`service_status`, `service_edit`, `service_price`, `category_id`, `service_api`, `api_service`,
                     `api_currency`, `service_type`, `api_detail`, `service_name`, `service_desc`, `service_min`, `service_max`)
                    VALUES ('on', 'true', ?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?)""",
                    (str(rp), str(upx.get("cate_id", "")), tas, str(prv), curr, stype, detail_json, sname_b64, min_v, max_v),
                )
        if mas:
            edit(chat_id, mas, "✅ Yuklab olish jarayoni tugallandi.")
        unlink_file(f"user/{cid2}.step")
        return

    if data == "editXiz":
        edit(
            cid2,
            mid2,
            "<b>Quyidagilardan birini tanlang:</b>",
            keyboard([
                [{"text": "API xizmat IDsini o'zgartirish", "callback_data": "editXizmat-service_api"}],
                [{"text": "Xizmat nomini o'zgartirish", "callback_data": "editXizmat-service_name"}],
                [{"text": "Malumotlarni o'zgartirish", "callback_data": "editXizmat-service_desc"}],
                [{"text": "Narxini o‘zgartirish", "callback_data": "editXizmat-service_price"}],
                [{"text": ".Min buyurtmani o‘zgartirish", "callback_data": "editXizmat-service_min"}],
                [{"text": ".Max buyurtmani o‘zgartirish", "callback_data": "editXizmat-service_max"}],
                [{"text": "Orqaga", "callback_data": "xizmat"}],
            ]),
        )
        return

    if data.startswith("editXizmat-"):
        nomi = data.split("-", 1)[1]
        put_file(f"user/{cid2}.txt", nomi)
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Tarmoqlar topilmadi!", "show_alert": True})
        else:
            btns = [{"text": enc("decode", s["category_name"]), "callback_data": f"editXizmats-{s['category_id']}"} for s in cats]
            kb_rows = chunk_list(btns, 3)
            kb_rows.append([{"text": "Orqaga", "callback_data": "editXiz"}])
            edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard(kb_rows))
        return

    if data.startswith("editXizmats-"):
        bolim = data.split("-")[1]
        cates = database.fetch_all("SELECT * FROM `cates` WHERE `category_id` = ?", (bolim,))
        if not cates:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu bo'lim uchun xizmat turlari topilmadi!", "show_alert": True})
        else:
            seen = set()
            btns = []
            for s in cates:
                nm = enc("decode", s["name"])
                if nm not in seen:
                    seen.add(nm)
                    btns.append([{"text": nm, "callback_data": f"editXt-{s['cate_id']}"}])
            btns.append([{"text": "Orqaga", "callback_data": f"editXizmat-{bolim}"}])
            edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:</b>", keyboard(btns))
        return

    if data.startswith("editXt-"):
        n = data.split("-")[1]
        srvs = database.fetch_all("SELECT * FROM `services` WHERE `category_id` = ?", (n,))
        if not srvs:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu bo'lim uchun xizmatlar topilmadi!", "show_alert": True})
        else:
            txts = []
            btns = []
            for idx, s in enumerate(srvs, start=1):
                txts.append(f"<b>{idx}</b>: {enc('decode', s['service_name'])}")
                btns.append({"text": str(idx), "callback_data": f"editXts-{s['service_id']}"})
            kb_rows = chunk_list(btns, 3)
            kb_rows.append([{"text": "Orqaga", "callback_data": f"editXizmats-{n}"}])
            edit(cid2, mid2, "<b>Quyidagilardan birini tanlang:\n\n" + "\n".join(txts) + "</b>", keyboard(kb_rows))
        return

    if data.startswith("editXts-"):
        xiz = data.split("-")[1]
        del_msg(cid2, mid2)
        sms(cid2, "<b>Yangi qiymatni kiriting:</b>", AORT_KB)
        put_file(f"user/{cid2}.step", f"editXizmatlar-{xiz}")
        return

    if step.startswith("editXizmatlar-") and cid == ADMIN and text:
        xiz = step.split("-")[1]
        ex = get_file(f"user/{cid}.txt").strip()
        if ex == "service_desc":
            database.execute("UPDATE `services` SET `service_desc` = ? WHERE `service_id` = ?", (enc("encode", text), xiz))
        elif ex == "service_name":
            database.execute("UPDATE `services` SET `service_name` = ? WHERE `service_id` = ?", (enc("encode", text), xiz))
        elif ex in ("service_id", "service_api"):
            database.execute("UPDATE `services` SET `service_api` = ? WHERE `service_id` = ?", (text, xiz))
        elif ex == "service_price":
            database.execute("UPDATE `services` SET `service_edit` = 'false', `service_price` = ? WHERE `service_id` = ?", (text, xiz))
        elif ex == "service_min":
            database.execute("UPDATE `services` SET `service_edit` = 'false', `service_min` = ? WHERE `service_id` = ?", (text, xiz))
        elif ex == "service_max":
            database.execute("UPDATE `services` SET `service_edit` = 'false', `service_max` = ? WHERE `service_id` = ?", (text, xiz))
        sms(cid, "<b> Muvaffaqiyatli o'zgartirildi.</b>", PANEL2_KB)
        unlink_file(f"user/{cid}.step")
        unlink_file(f"user/{cid}.txt")
        return

    if data == "delXiz":
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Bo‘limlar topilmadi!", "show_alert": True})
        else:
            btns = [{"text": enc("decode", s["category_name"]), "callback_data": f"deleteXiz-{s['category_id']}"} for s in cats]
            edit(chat_id, message_id, "<b>Quyidagilardan birini tanlang:</b>", keyboard(chunk_list(btns, 3)))
        return

    if data.startswith("deleteXiz-"):
        n = data.split("-")[1]
        cates = database.fetch_all("SELECT * FROM `cates` WHERE `category_id` = ?", (n,))
        if not cates:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu bo'lim uchun xizmat turlari topilmadi!", "show_alert": True})
        else:
            seen = set()
            btns = []
            for s in cates:
                nm = enc("decode", s["name"])
                if nm not in seen:
                    seen.add(nm)
                    btns.append([{"text": nm, "callback_data": f"delx-{s['cate_id']}"}])
            btns.append([{"text": "Orqaga", "callback_data": "newXiz"}])
            edit(chat_id, message_id, "<b>Quyidagilardan birini tanlang:</b>", keyboard(btns))
        return

    if data.startswith("delx-"):
        n = data.split("-")[1]
        srvs = database.fetch_all("SELECT * FROM `services` WHERE `category_id` = ?", (n,))
        if not srvs:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu bo'lim uchun xizmatlar topilmadi!", "show_alert": True})
        else:
            txts = []
            btns = []
            for idx, s in enumerate(srvs, start=1):
                txts.append(f"<b>{idx}</b>: {enc('decode', s['service_name'])} {s['service_price']} - so‘m")
                btns.append({"text": str(idx), "callback_data": f"delmat-{s['service_id']}"})
            edit(chat_id, message_id, "👉 O‘zingizga kerakli xizmatni tanlang:\n\n" + "\n".join(txts), keyboard(chunk_list(btns, 5)))
        return

    if data.startswith("delmat-"):
        ichki = data.split("-")[1]
        database.execute("DELETE FROM `services` WHERE `service_id` = ?", (ichki,))
        del_msg(cid2, mid2)
        sms(cid2, "Xizmat o‘chirildi!", PANEL_KB)
        return

    if data == "newXiz":
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Bo‘limlar topilmadi!", "show_alert": True})
        else:
            btns = [{"text": enc("decode", s["category_name"]), "callback_data": f"add={s['category_id']}"} for s in cats]
            edit(chat_id, message_id, "<b>Quyidagilardan birini tanlang:</b>", keyboard(chunk_list(btns, 3)))
        return

    if data.startswith("add="):
        n = data.split("=")[1]
        put_file("set/c.txt", n)
        cates = database.fetch_all("SELECT * FROM `cates` WHERE `category_id` = ?", (n,))
        if not cates:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu bo'lim uchun xizmat turlari topilmadi!", "show_alert": True})
        else:
            seen = set()
            btns = []
            for s in cates:
                nm = enc("decode", s["name"])
                if nm not in seen:
                    seen.add(nm)
                    btns.append([{"text": nm, "callback_data": f"adds-{s['cate_id']}"}])
            btns.append([{"text": "Orqaga", "callback_data": "newXiz"}])
            edit(chat_id, message_id, "<b>Quyidagilardan birini tanlang:</b>", keyboard(btns))
        return

    if data.startswith("adds-"):
        pw = data.split("-")[1]
        providers = database.fetch_all("SELECT * FROM `providers`")
        if not providers:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Provayderlar topilmadi!", "show_alert": True})
        else:
            adds = {"cate_id": pw, "category_id": get_file("set/c.txt").strip()}
            put_file("set/adds.json", json.dumps(adds, ensure_ascii=False))
            del_msg(chat_id, message_id)
            sms(chat_id, "<b>Yangi xizmat nomini yuboring:</b>", AORT_KB)
            put_file(f"user/{chat_id}.step", "servisw")
        return

    if step == "servisw" and text:
        providers = database.fetch_all("SELECT * FROM `providers`")
        if not providers:
            sms(cid, "⚠️ Provayderlar topilmadi!")
        else:
            prs_lines = []
            btns = []
            for idx, s in enumerate(providers, start=1):
                prs_lines.append(f"<b>{idx}</b>: {strip_provider_domain(s['api_url'])}")
                btns.append({"text": str(idx), "callback_data": f"checkC-{s['id']}"})
            sms(cid, "Provayderni tanlang:\n \n" + "\n".join(prs_lines), keyboard(chunk_list(btns, 3)))
            put_file("set/adds.json.name", text)
            put_file(f"user/{cid}.step", "servis0")
        return

    if data.startswith("checkC-") and stepc == "servis0" and chat_id == ADMIN:
        pw = data.split("-")[1]
        sms(
            chat_id,
            "Provayderning API xizmatlari bolimida korsatilgan valyutani tanlang:",
            keyboard([
                [{"text": "UZS ", "callback_data": "checkP-UZS"}],
                [{"text": "USD ", "callback_data": "checkP-USD"}],
                [{"text": "RUB ", "callback_data": "checkP-RUB"}],
                [{"text": "INR ", "callback_data": "checkP-INR"}],
                [{"text": "TRY ", "callback_data": "checkP-TRY"}],
            ]),
        )
        adds = json.loads(get_file("set/adds.json") or "{}")
        adds["api_service"] = pw
        put_file("set/adds.json", json.dumps(adds, ensure_ascii=False))
        put_file(f"user/{chat_id}.step", "servis1")
        return

    if data.startswith("checkP-") and stepc == "servis1" and chat_id == ADMIN:
        pw = data.split("-")[1]
        del_msg(chat_id, message_id)
        sms(
            chat_id,
            "📝 Xizmat xaqida malumotlar kiriting:\n\n⚠️ Ma'lumot kiritishni xohlamasangiz <b>Kiritilmagan</b> tugmasini bosing",
            reply_keyboard([[{"text": "Kiritilmagan"}], [{"text": "🗄️ Boshqaruv"}]]),
        )
        adds = json.loads(get_file("set/adds.json") or "{}")
        adds["api_currency"] = pw
        put_file("set/adds.json", json.dumps(adds, ensure_ascii=False))
        put_file(f"user/{chat_id}.step", "servis2")
        return

    if step == "servis2" and cid == ADMIN and text:
        sms(cid, "💵 Buyurtma narxini yuboring (1000 ta) uchun", AORT_KB)
        put_file("set/adds.json.desc", "" if text == "Kiritilmagan" else text)
        put_file(f"user/{cid}.step", "servis3")
        return

    if step == "servis3" and cid == ADMIN and text and text.replace(".", "", 1).isdigit():
        sms(cid, "🆔 Xizmat IDsini yuboring:", AORT_KB)
        adds = json.loads(get_file("set/adds.json") or "{}")
        adds["service_price"] = text
        put_file("set/adds.json", json.dumps(adds, ensure_ascii=False))
        put_file(f"user/{cid}.step", "servisID")
        return

    if step == "servisID" and text and text.isdigit():
        pw = json.loads(get_file("set/adds.json") or "{}")
        ap = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (pw.get("api_service"),))
        raw = http_get(f"{ap['api_url']}?key={ap['api_key']}&action=services") if ap else "[]"
        try:
            j = json.loads(raw)
        except Exception:
            j = []
        matched = None
        for el in j:
            if str(el.get("service")) == text:
                matched = el
                break
        if not matched or (not matched.get("min") and not matched.get("max")):
            sms(cid, "🔕 Noma'lum xatolik yuz berdi.\n\nQaytadan xizmat IDsini yuboring:")
        else:
            detail_json = json.dumps({
                "name": matched.get("name", ""),
                "min": str(matched.get("min", "0")),
                "max": str(matched.get("max", "0")),
                "type": str(matched.get("type", "Default")),
                "cancel": "true" if matched.get("cancel") else "false",
                "refill": "true" if matched.get("refill") else "false",
                "dripfeed": "true" if matched.get("dripfeed") else "false",
            }, ensure_ascii=False)
            database.execute(
                """INSERT INTO `services`
                (`service_status`, `service_price`, `service_edit`, `category_id`, `service_api`, `api_service`,
                 `api_currency`, `service_type`, `api_detail`, `service_name`, `service_desc`, `service_min`, `service_max`)
                VALUES ('on', ?, 'true', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(pw.get("service_price", "0")),
                    str(pw.get("cate_id", "")),
                    text,
                    str(pw.get("api_service", "")),
                    str(pw.get("api_currency", "UZS")),
                    str(matched.get("type", "Default")),
                    detail_json,
                    enc("encode", get_file("set/adds.json.name")),
                    enc("encode", get_file("set/adds.json.desc")),
                    str(matched.get("min", "0")),
                    str(matched.get("max", "0")),
                ),
            )
            sms(cid, "✅ Yangi xizmat qo'shildi.", PANEL2_KB)
            unlink_file(f"user/{cid}.step")
        return

    # ========================================================================
    # ADMIN PANEL: Kurs, Foiz, Foydalanuvchini boshqarish, Valyuta kursi
    # ========================================================================

    if text == "💵 Kursni o‘rnatish" and cid == ADMIN:
        r_usd = get_file("set/usd").strip() or "0"
        r_rub = get_file("set/rub").strip() or "0"
        r_inr = get_file("set/inr").strip() or "0"
        r_try = get_file("set/try").strip() or "0"
        sms(
            cid,
            "👉 <b>Kerakli valyutani tanlang:</b>",
            keyboard([
                [{"text": f"🇺🇸 AQSH dollari ($): {r_usd} so'm", "callback_data": "course=usd"}],
                [{"text": f"🇷🇺 Rossiya rubli (₽): {r_rub} so'm", "callback_data": "course=rub"}],
                [{"text": f"🇮🇳 Hindiston rupiysi (₹): {r_inr} so'm", "callback_data": "course=inr"}],
                [{"text": f"🇹🇷 Turkiya lirasi (₺): {r_try} so'm", "callback_data": "course=try"}],
            ]),
        )
        return

    if data.startswith("course="):
        val = data.split("=")[1]
        cur_rate = get_file(f"set/{val}").strip() or "0"
        del_msg(chat_id, message_id)
        sms(chat_id, f"💵 <b>1 {val.upper()} narxini kiriting (faqat raqamda):</b>\n\n♻️ Joriy narx: <code>{cur_rate}</code> so‘m", AORT_KB)
        put_file(f"user/{chat_id}.step", f"course={val}")
        return

    if step.startswith("course=") and text:
        clean_num = text.strip().replace(" ", "").replace(",", ".")
        if clean_num.replace(".", "", 1).isdigit():
            val = step.split("=")[1]
            put_file(f"set/{val}", clean_num)
            sms(cid, f"✅ <b>1 {val.upper()} narxi {clean_num} so‘mga o‘zgardi!</b>", PANEL2_KB)
            unlink_file(f"user/{cid}.step")
        else:
            sms(cid, "⚠️ Faqat raqam kiriting (masalan: <code>12800</code>):", AORT_KB)
        return

    if text == "⚖️ Foizni o‘rnatish" and cid == ADMIN:
        p_row = database.fetch_one("SELECT * FROM `percent` WHERE `id` = 1")
        cur_p = p_row["percent"] if p_row else "0"
        sms(cid, f"⭐ Bot xizmatlari uchun foizni kiriting\n\n♻️ Joriy foiz: {cur_p}%", AORT_KB)
        put_file(f"user/{cid}.step", "updFoiz")
        return

    if step == "updFoiz" and text and text.replace(".", "", 1).isdigit():
        database.execute("UPDATE `percent` SET `percent` = ? WHERE `id` = 1", (text,))
        sms(cid, "✅ O‘zgartirish muvaffaqiyatli bajarildi.", PANEL_KB)
        put_file(f"user/{cid}.step", "")
        return

    if text == "👤 Foydalanuvchini boshqarish" and cid == ADMIN:
        sms(cid, "<b>Kerakli foydalanuvchining ID raqamini kiriting:</b>", AORT_KB)
        put_file(f"user/{cid}.step", "iD")
        return

    if step == "iD" and cid == ADMIN and text:
        rew = database.fetch_one("SELECT * FROM `users` WHERE `user_id` = ? OR `id` = ?", (text, text))
        if rew:
            idi = str(rew["id"])
            put_file("user/us.id", idi)
            pul = rew["balance"]
            bans = "🔔 Banlash" if rew.get("status") == "active" else "🔕 Bandan olish"
            sms(
                cid,
                f"<b>Foydalanuvchi topildi!\n\nID:</b> <a href='tg://user?id={idi}'>{text}</a>\n<b>Balans: {pul} so‘m</b>",
                keyboard([
                    [{"text": bans, "callback_data": "ban"}],
                    [{"text": "➕ Pul qo'shish", "callback_data": "plus"}, {"text": "➖ Pul ayirish", "callback_data": "minus"}],
                ]),
            )
            unlink_file(f"user/{cid}.step")
        else:
            sms(cid, "<b>Foydalanuvchi topilmadi.</b>\n\nQayta urinib ko'ring:")
        return

    if data == "plus":
        sms(chat_id, f"<a href='tg://user?id={saved}'>{saved}</a> <b>ning hisobiga qancha pul qo'shmoqchisiz?</b>", AORT_KB)
        put_file(f"user/{chat_id}.step", "plus")
        return

    if step == "plus" and cid == ADMIN and text:
        if text.lstrip("-").replace(".", "", 1).isdigit():
            val = float(text)
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (saved,))
            if rew:
                miqdor = float(rew.get("balance") or 0) + val
                p2 = float(rew.get("outing") or 0) + val
                database.execute("UPDATE `users` SET `balance` = ?, `outing` = ? WHERE `id` = ?", (str(miqdor), str(p2), saved))
                # Referal keshbek bonusi (agar yoqilgan bo'lsa)
                inviter_id = get_file(f"user/{saved}.inviter").strip()
                if inviter_id and setting.get("ref_status") == "on" and val > 0:
                    bonus_pct = float(setting.get("bonus") or 0)
                    if bonus_pct > 0:
                        ref_bonus_amt = round(val * (bonus_pct / 100.0), 2)
                        inv_row = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (inviter_id,))
                        if inv_row and ref_bonus_amt > 0:
                            inv_bal = round(float(inv_row.get("balance") or 0) + ref_bonus_amt, 2)
                            database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (str(inv_bal), inviter_id))
                            sms(inviter_id, f"🎁 <b>Referal bonusi!</b>\nSiz taklif qilgan foydalanuvchi hisobini to‘ldirdi va sizga <b>+{fmt_money(ref_bonus_amt)} so‘m ({bonus_pct}%)</b> bonus berildi!")
            sms(saved, f"<b>Adminlar tomonidan hisobingiz {text} so‘m to'ldirildi</b>", MENU_USER_KB)
            sms(cid, f"<b>Foydalanuvchi hisobiga {text} so‘m qo'shildi!</b>", PANEL_KB)
            unlink_file(f"user/{cid}.step")
        else:
            sms(cid, "<b>Faqat raqamlardan foydalaning!</b>")
        return

    if data == "minus":
        sms(chat_id, f"<a href='tg://user?id={saved}'>{saved}</a> <b>ning hisobidan qancha pul ayirmoqchisiz?</b>", AORT_KB)
        put_file(f"user/{chat_id}.step", "minus")
        return

    if step == "minus" and cid == ADMIN and text:
        if text.lstrip("-").replace(".", "", 1).isdigit():
            val = float(text)
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (saved,))
            if rew:
                miqdor = float(rew.get("balance") or 0) - val
                p2 = float(rew.get("outing") or 0) - val
                database.execute("UPDATE `users` SET `balance` = ?, `outing` = ? WHERE `id` = ?", (str(miqdor), str(p2), saved))
            sms(saved, f"<b>Adminlar tomonidan hisobingizdan {text} so‘m olindi.</b>", MENU_USER_KB)
            sms(cid, f"<b>Foydalanuvchi hisobidan {text} so‘m olindi!</b>", PANEL_KB)
            unlink_file(f"user/{cid}.step")
        else:
            sms(cid, "<b>Faqat raqamlardan foydalaning!</b>")
        return

    if data == "ban":
        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (saved,))
        if ADMIN != saved and rew:
            if rew.get("status") == "deactive":
                database.execute("UPDATE `users` SET `status` = 'active' WHERE `id` = ?", (saved,))
                sms(chat_id, f"<b>Foydalanuvchi ({saved}) bandan olindi!</b>", PANEL_KB)
            else:
                database.execute("UPDATE `users` SET `status` = 'deactive' WHERE `id` = ?", (saved,))
                sms(chat_id, f"<b>Foydalanuvchi ({saved}) banlandi!</b>", PANEL_KB)
        else:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "Bloklash mumkin emas!", "show_alert": True})
        return

    if text == "🇺🇿 Valyuta kursi" and cid == ADMIN:
        raw = http_get("https://cbu.uz/uz/arkhiv-kursov-valyut/json/")
        rates = {"USD": "?", "RUB": "?", "INR": "?", "TRY": "?"}
        try:
            for item in json.loads(raw):
                ccy = item.get("Ccy")
                if ccy in rates:
                    rates[ccy] = item.get("Rate", "?")
        except Exception:
            pass
        sms(
            cid,
            f"<b> \n1 $(USD) - {rates['USD']} UZS\n1 ₽(RUB) - {rates['RUB']} UZS\n"
            f"1 ₹(INR) - {rates['INR']} UZS\n1 ₺(TRY) - {rates['TRY']} UZS\n</b>",
            PANEL_KB,
        )
        return

    # ========================================================================
    # ADMIN PANEL: Majburiy obunalar
    # ========================================================================

    if text == "📎 Majburiy obunalar" and cid == ADMIN:
        sms(
            cid,
            text,
            keyboard([
                [{"text": "➕ Qo‘shish", "callback_data": "kanal=add"}],
                [{"text": "*️⃣ Ro‘yxat", "callback_data": "kanal=list"}, {"text": "🗑️ O'chirish", "callback_data": "kanal=dl"}],
            ]),
        )
        return

    if data.startswith("kanal="):
        rp = data.split("=", 1)[1]
        ops = get_file("set/channel").strip()
        if rp == "list":
            if not ops:
                sms(chat_id, "🤷‍♂️ Xechqanday kanal topilmadi.")
            else:
                chs = [c.strip() for c in ops.split("\n") if c.strip()]
                btns = [{"text": c, "url": f"https://t.me/{c.lstrip('@')}"} for c in chs]
                sms(chat_id, "👉 Barcha kanallar:", keyboard(chunk_list(btns, 2)))
        elif rp == "dl":
            if not ops:
                sms(chat_id, "🤷‍♂️ Xechqanday kanal topilmadi.")
            else:
                chs = [c.strip() for c in ops.split("\n") if c.strip()]
                btns = [{"text": c, "callback_data": f"kanal=del{c}"} for c in chs]
                sms(chat_id, "🗑️ O‘chiriladigan kanalni tanlang:", keyboard(chunk_list(btns, 2)))
        elif rp.startswith("del@"):
            target_ch = "@" + rp.split("@", 1)[1]
            chs = [c.strip() for c in ops.split("\n") if c.strip() and c.strip() != target_ch]
            if not chs:
                unlink_file("set/channel")
            else:
                put_file("set/channel", "\n".join(chs))
            del_msg(chat_id, message_id)
            sms(chat_id, "✅ O‘chirildi")
        elif rp == "add":
            del_msg(chat_id, message_id)
            sms(chat_id, "♻️ Kanal userini kiriting\n\nNamuna: @username", AORT_KB)
            put_file(f"user/{chat_id}.step", "kanal_add")
        return

    if step == "kanal_add" and text and "@" in text:
        kanal = get_file("set/channel").strip()
        put_file("set/channel", f"{kanal}\n{text.strip()}" if kanal else text.strip())
        sms(cid, "✅ Saqlandi!", PANEL_KB)
        unlink_file(f"user/{cid}.step")
        return

    # ========================================================================
    # FOYDALANUVCHI: Pul ishlash (Referal), Buyurtmalar, Yordam, Balans va To'lov
    # ========================================================================

    # ========================================================================
    # KENGAYTIRILGAN PUL ISHLASH TIZIMI + ADMIN BOSHQARUVI (100% SOZLANUVCHI)
    # ========================================================================

    def _build_earn_main_view(target_uid: str) -> Tuple[str, str]:
        u_row = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (target_uid,)) or {}
        myid = u_row.get("user_id", "1")
        u_bal = fmt_money(u_row.get("balance", "0"))
        bot_user = get_bot_username()
        st_now = database.get_settings()
        ref_reward = enc("decode", st_now.get("referal", "MTAw")) or "100"
        ref_bonus_pct = st_now.get("bonus", "4")
        ref_bonus_on = st_now.get("ref_status", "off") == "on"
        daily_amt = get_file("set/daily_bonus.txt").strip() or "50"
        daily_on = (get_file("set/daily_status.txt").strip() or "on") == "on"
        my_refs = int(float(get_file(f"user/{target_uid}.users") or 0))

        # Count available channels & tasks for this user
        all_chs = database.fetch_all("SELECT * FROM `earn_channels` WHERE `status` = 'on'")
        all_tsks = database.fetch_all("SELECT * FROM `earn_tasks` WHERE `status` = 'on'")
        claimed_rows = database.fetch_all("SELECT `claim_type`, `item_id` FROM `earn_claims` WHERE `user_id` = ?", (target_uid,))
        claimed_set = {(r["claim_type"], str(r["item_id"])) for r in claimed_rows}
        avail_ch_cnt = sum(1 for c in all_chs if ("channel", str(c["id"])) not in claimed_set)
        avail_tsk_cnt = sum(1 for t in all_tsks if ("task", str(t["id"])) not in claimed_set)

        ref_link = f"https://t.me/{bot_user}?start=user{myid}"
        share_url = f"https://t.me/share/url?url={urllib.parse.quote(ref_link)}&text={urllib.parse.quote('🚀 Eng arzon va tezkor SMM xizmatlar boti! Kirib bonus oling:')}"

        custom_header = get_file("set/earn_header.txt").strip()
        header_line = custom_header if custom_header else "💸 <b>Pul ishlash bo‘limiga xush kelibsiz!</b>"

        msg_lines = [
            header_line,
            "",
            f"🔗 <b>Sizning referal havolangiz:</b>",
            f"{ref_link}",
            "",
            f"👥 Har bir taklif qilgan referalingiz uchun: <b>{ref_reward} so‘m</b>",
        ]
        if ref_bonus_on:
            msg_lines.append(f"📈 Referalingiz hisob to‘ldirganda keshbek: <b>+{ref_bonus_pct}%</b>")
        if daily_on:
            msg_lines.append(f"🎁 Har 24 soatda kunlik bepul bonus: <b>+{daily_amt} so‘m</b>")
        msg_lines.extend([
            f"📊 Siz taklif qilgan do‘stlar: <b>{my_refs} ta</b>",
            f"💵 Joriy balansingiz: <b>{u_bal} so‘m</b>",
            f"👤 ID raqam: <code>{myid}</code>",
            "",
            "👇 <i>Quyidagi barcha usullar orqali hisobingizga bepul pul ishlashingiz mumkin:</i>",
        ])

        kb_rows: List[List[Dict[str, Any]]] = [
            [{"text": "📤 Referal havolani ulashish", "url": share_url}],
        ]
        row2: List[Dict[str, Any]] = []
        if daily_on:
            row2.append({"text": f"🎁 Kunlik bonus (+{daily_amt} so‘m)", "callback_data": "earn=daily"})
        row2.append({"text": f"📢 Obuna bo‘lish ({avail_ch_cnt} ta)", "callback_data": "earn=channels"})
        kb_rows.append(row2)

        kb_rows.append([
            {"text": f"📋 Vazifalar ({avail_tsk_cnt} ta)", "callback_data": "earn=tasks"},
            {"text": "🎟️ Promokod kiritish", "callback_data": "earn=promo"},
        ])
        kb_rows.append([
            {"text": "💎 Konkurs (🏆 TOP 10)", "callback_data": "konkurs"},
        ])
        return "\n".join(msg_lines), keyboard(kb_rows)

    if text == "💵 Pul ishlash" and joinchat(cid):
        msg_txt, kb_json = _build_earn_main_view(cid)
        sms(cid, msg_txt, kb_json)
        return

    if data == "earn=menu" and joinchat(chat_id):
        msg_txt, kb_json = _build_earn_main_view(chat_id)
        edit(chat_id, message_id, msg_txt, kb_json)
        return

    if data == "konkurs" and joinchat(chat_id):
        konkurs_header = get_file("set/konkurs_text.txt").strip() or (
            "💎 <b>Referal Konkurs (🏆 TOP 10 Reyting)</b>\n\n"
            "🎁 <b>Ko‘proq do‘stlaringizni taklif qiling va sovrinlarni yutib oling!</b>"
        )
        my_refs = int(float(get_file(f"user/{chat_id}.users") or 0))
        top_txt = referal_top(10)
        full_konkurs = (
            f"{konkurs_header}\n\n"
            f"🏆 <b>TOP 10 Ishtirokchilar:</b>\n{top_txt}\n\n"
            f"📊 <b>Sizning natijangiz:</b> <code>{my_refs}</code> ta taklif"
        )
        edit(
            cid2,
            mid2,
            full_konkurs,
            keyboard([[{"text": "⬅️ Orqaga (Pul ishlash)", "callback_data": "earn=menu"}]]),
        )
        return

    if data == "earn=daily" and joinchat(chat_id):
        daily_on = (get_file("set/daily_status.txt").strip() or "on") == "on"
        if not daily_on:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Kunlik bonus vaqtincha o‘chirilgan!", "show_alert": True})
            return
        last_ts = float(get_file(f"user/{chat_id}.daily_ts").strip() or 0)
        now_ts = time.time()
        diff = now_ts - last_ts
        if diff < 86400:
            rem = int(86400 - diff)
            rem_h = rem // 3600
            rem_m = (rem % 3600) // 60
            bot(
                "answerCallbackQuery",
                {
                    "callback_query_id": cqid,
                    "text": f"⏳ Siz bugungi kunlik bonusni olgansiz!\n\nKeyingi bonusni {rem_h} soat {rem_m} daqiqadan so‘ng olishingiz mumkin.",
                    "show_alert": True,
                },
            )
            return
        daily_amt = float(get_file("set/daily_bonus.txt").strip() or 50)
        u_row = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
        new_b = round(float(u_row.get("balance") or 0) + daily_amt, 2)
        database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_b), chat_id))
        put_file(f"user/{chat_id}.daily_ts", str(now_ts))
        bot(
            "answerCallbackQuery",
            {
                "callback_query_id": cqid,
                "text": f"🎉 Tabriklaymiz! Hisobingizga +{fmt_money(daily_amt)} so‘m kunlik bonus qo‘shildi!",
                "show_alert": True,
            },
        )
        msg_txt, kb_json = _build_earn_main_view(chat_id)
        edit(chat_id, message_id, msg_txt, kb_json)
        return

    if data == "earn=channels" and joinchat(chat_id):
        all_chs = database.fetch_all("SELECT * FROM `earn_channels` WHERE `status` = 'on'")
        claimed_rows = database.fetch_all(
            "SELECT `item_id` FROM `earn_claims` WHERE `user_id` = ? AND `claim_type` = 'channel'",
            (chat_id,),
        )
        claimed_ids = {str(r["item_id"]) for r in claimed_rows}
        avail = [c for c in all_chs if str(c["id"]) not in claimed_ids]
        if not avail:
            edit(
                chat_id,
                message_id,
                "📢 <b>Kanalga obuna bo‘lib pul ishlash</b>\n\n"
                "🤷‍♂️ Hozircha siz uchun yangi pullik kanallar yo‘q (yoki barchasidan bonus olgansiz).\n"
                "<i>Tez orada yangi kanallar qo‘shiladi!</i>",
                keyboard([[{"text": "⬅️ Orqaga", "callback_data": "earn=menu"}]]),
            )
            return
        kb_rows = []
        lines = ["📢 <b>Quyidagi kanallarga obuna bo‘ling va «✅ Tekshirish» tugmasini bosib pul oling:</b>\n"]
        for idx, c in enumerate(avail, start=1):
            ch_user = c["channel_username"].lstrip("@")
            rew_str = fmt_money(c["reward"])
            title_str = c.get("title") or f"@{ch_user}"
            lines.append(f"<b>{idx}. {title_str}</b> (@{ch_user}) — 💰 <b>+{rew_str} so‘m</b>")
            kb_rows.append([
                {"text": f"📢 {idx}. Kanalga kirish (@{ch_user})", "url": f"https://t.me/{ch_user}"},
                {"text": f"✅ Tekshirish (+{rew_str} so‘m)", "callback_data": f"earn_chk_ch={c['id']}"},
            ])
        kb_rows.append([{"text": "⬅️ Orqaga", "callback_data": "earn=menu"}])
        edit(chat_id, message_id, "\n".join(lines), keyboard(kb_rows))
        return

    if data.startswith("earn_chk_ch=") and joinchat(chat_id):
        ch_id = data.split("=", 1)[1]
        already = database.fetch_one(
            "SELECT * FROM `earn_claims` WHERE `user_id` = ? AND `claim_type` = 'channel' AND `item_id` = ?",
            (chat_id, ch_id),
        )
        if already:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Siz ushbu kanal uchun bonusni allaqachon olgansiz!", "show_alert": True})
            return
        ch_row = database.fetch_one("SELECT * FROM `earn_channels` WHERE `id` = ? AND `status` = 'on'", (ch_id,))
        if not ch_row:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Kanal topilmadi yoki faol emas!", "show_alert": True})
            return
        clean_ch = ch_row["channel_username"].lstrip("@")
        ret = bot("getChatMember", {"chat_id": f"@{clean_ch}", "user_id": chat_id})
        stat = ret.get("result", {}).get("status", "") if isinstance(ret.get("result"), dict) else ""
        if stat not in ("creator", "administrator", "member"):
            bot(
                "answerCallbackQuery",
                {
                    "callback_query_id": cqid,
                    "text": f"❌ Siz hali @{clean_ch} kanaliga obuna bo‘lmagansiz!\nAvval kanalga a'zo bo‘lib, so‘ng Tekshirishni bosing.",
                    "show_alert": True,
                },
            )
            return
        rew_val = float(ch_row.get("reward") or 0)
        u_row = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
        new_b = round(float(u_row.get("balance") or 0) + rew_val, 2)
        database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_b), chat_id))
        database.execute(
            "INSERT INTO `earn_claims` (`user_id`, `claim_type`, `item_id`, `claimed_at`) VALUES (?, 'channel', ?, ?)",
            (chat_id, str(ch_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        bot(
            "answerCallbackQuery",
            {
                "callback_query_id": cqid,
                "text": f"✅ Obuna tasdiqlandi! Hisobingizga +{fmt_money(rew_val)} so‘m qo‘shildi!",
                "show_alert": True,
            },
        )
        msg_txt, kb_json = _build_earn_main_view(chat_id)
        edit(chat_id, message_id, msg_txt, kb_json)
        return

    if data == "earn=tasks" and joinchat(chat_id):
        all_tsks = database.fetch_all("SELECT * FROM `earn_tasks` WHERE `status` = 'on'")
        claimed_rows = database.fetch_all(
            "SELECT `item_id` FROM `earn_claims` WHERE `user_id` = ? AND `claim_type` = 'task'",
            (chat_id,),
        )
        claimed_ids = {str(r["item_id"]) for r in claimed_rows}
        avail = [t for t in all_tsks if str(t["id"]) not in claimed_ids]
        if not avail:
            edit(
                chat_id,
                message_id,
                "📋 <b>Vazifa bajarib pul ishlash</b>\n\n"
                "🤷‍♂️ Hozircha yangi vazifalar yo‘q (yoki barcha vazifalarni bajargansiz).\n"
                "<i>Yangi vazifalar qo‘shilishi bilan shu yerda chiqadi!</i>",
                keyboard([[{"text": "⬅️ Orqaga", "callback_data": "earn=menu"}]]),
            )
            return
        lines = ["📋 <b>Mavjud vazifalar ro‘yxati:</b>\n"]
        kb_rows = []
        for idx, t in enumerate(avail, start=1):
            rew_str = fmt_money(t["reward"])
            v_label = "⚡ Avto-tekshirish" if t.get("verify_type") == "auto" else "📸 Skrinshot bilan"
            lines.append(
                f"🔹 <b>{idx}. {t['title']}</b> (+<b>{rew_str} so‘m</b> | {v_label})\n"
                f"   📝 Shart: {t.get('description') or 'Havolaga o‘tib vazifani bajaring'}"
            )
            row_btns = []
            if t.get("url") and ("http://" in t["url"] or "https://" in t["url"] or "t.me/" in t["url"]):
                u_link = t["url"] if t["url"].startswith("http") else f"https://{t['url']}"
                row_btns.append({"text": f"🔗 {idx}-vazifaga o‘tish", "url": u_link})
            row_btns.append({"text": f"✅ Bajarildi (+{rew_str} so‘m)", "callback_data": f"earn_do_task={t['id']}"})
            kb_rows.append(row_btns)
        kb_rows.append([{"text": "⬅️ Orqaga", "callback_data": "earn=menu"}])
        edit(chat_id, message_id, "\n\n".join(lines), keyboard(kb_rows))
        return

    if data.startswith("earn_do_task=") and joinchat(chat_id):
        tsk_id = data.split("=", 1)[1]
        already = database.fetch_one(
            "SELECT * FROM `earn_claims` WHERE `user_id` = ? AND `claim_type` = 'task' AND `item_id` = ?",
            (chat_id, tsk_id),
        )
        if already:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Siz bu vazifani allaqachon bajargansiz!", "show_alert": True})
            return
        t_row = database.fetch_one("SELECT * FROM `earn_tasks` WHERE `id` = ? AND `status` = 'on'", (tsk_id,))
        if not t_row:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Vazifa topilmadi!", "show_alert": True})
            return
        if t_row.get("verify_type") == "auto":
            rew_val = float(t_row.get("reward") or 0)
            u_row = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
            new_b = round(float(u_row.get("balance") or 0) + rew_val, 2)
            database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_b), chat_id))
            database.execute(
                "INSERT INTO `earn_claims` (`user_id`, `claim_type`, `item_id`, `claimed_at`) VALUES (?, 'task', ?, ?)",
                (chat_id, str(tsk_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            bot(
                "answerCallbackQuery",
                {
                    "callback_query_id": cqid,
                    "text": f"✅ Vazifa bajarildi! Hisobingizga +{fmt_money(rew_val)} so‘m qo‘shildi!",
                    "show_alert": True,
                },
            )
            msg_txt, kb_json = _build_earn_main_view(chat_id)
            edit(chat_id, message_id, msg_txt, kb_json)
        else:
            del_msg(chat_id, message_id)
            sms(
                chat_id,
                f"📸 <b>«{t_row['title']}»</b> vazifasini bajarganingizni tasdiqlovchi <b>skrinshot (rasm)</b> yoki izohni yuboring.\n\n"
                f"💰 Mukofot: <b>{fmt_money(t_row['reward'])} so‘m</b>",
                ORT_KB,
            )
            put_file(f"user/{chat_id}.step", f"task_proof={tsk_id}")
        return

    if step.startswith("task_proof=") and (photo or text) and joinchat(cid):
        tsk_id = step.split("=", 1)[1]
        t_row = database.fetch_one("SELECT * FROM `earn_tasks` WHERE `id` = ?", (tsk_id,))
        if t_row:
            bot("forwardMessage", {"chat_id": ADMIN, "from_chat_id": cid, "message_id": mid})
            sms(
                ADMIN,
                f"📋 <b>Vazifa tekshiruvi!</b>\n"
                f"👤 Foydalanuvchi: <a href='tg://user?id={cid}'>{cid}</a>\n"
                f"📌 Vazifa: <b>{t_row['title']}</b>\n"
                f"💰 Mukofot: <b>{fmt_money(t_row['reward'])} so‘m</b>",
                keyboard([
                    [
                        {"text": f"✅ Tasdiqlash (+{fmt_money(t_row['reward'])} so‘m)", "callback_data": f"task_ok={cid}={tsk_id}"},
                        {"text": "❌ Rad etish", "callback_data": f"task_no={cid}={tsk_id}"},
                    ]
                ]),
            )
        sms(cid, "✅ Ma'lumot Adminga yuborildi! Tekshirilib tasdiqlangach hisobingizga pul qo‘shiladi.", m_kb)
        unlink_file(f"user/{cid}.step")
        return

    if data.startswith("task_ok=") and chat_id == ADMIN:
        parts = data.split("=")
        u_target, tsk_id = parts[1], parts[2]
        already = database.fetch_one(
            "SELECT * FROM `earn_claims` WHERE `user_id` = ? AND `claim_type` = 'task' AND `item_id` = ?",
            (u_target, tsk_id),
        )
        if already:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Allaqachon tasdiqlangan!", "show_alert": True})
            return
        t_row = database.fetch_one("SELECT * FROM `earn_tasks` WHERE `id` = ?", (tsk_id,))
        rew_val = float(t_row.get("reward") or 0) if t_row else 0.0
        u_row = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (u_target,)) or {}
        new_b = round(float(u_row.get("balance") or 0) + rew_val, 2)
        database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_b), u_target))
        database.execute(
            "INSERT INTO `earn_claims` (`user_id`, `claim_type`, `item_id`, `claimed_at`) VALUES (?, 'task', ?, ?)",
            (u_target, str(tsk_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        edit(chat_id, message_id, f"✅ Foydalanuvchi ({u_target}) vazifasi tasdiqlandi va +{fmt_money(rew_val)} so‘m berildi!")
        sms(u_target, f"🎉 <b>Vazifangiz Admin tomonidan tasdiqlandi!</b>\n💰 Hisobingizga <b>+{fmt_money(rew_val)} so‘m</b> qo‘shildi!")
        return

    if data.startswith("task_no=") and chat_id == ADMIN:
        parts = data.split("=")
        u_target = parts[1]
        edit(chat_id, message_id, f"❌ Foydalanuvchi ({u_target}) vazifasi rad etildi.")
        sms(u_target, "❌ Siz yuborgan vazifa tasdiqlanmadi. Shartlarni to‘liq bajarib qayta urinib ko‘ring.")
        return

    if data == "earn=promo" and joinchat(chat_id):
        del_msg(chat_id, message_id)
        sms(chat_id, "🎟️ <b>Promokodni kiriting:</b>\n\n<i>Agar sizda promokod bo‘lsa, uni shu yerga yozib yuboring va bonus pul oling:</i>", ORT_KB)
        put_file(f"user/{chat_id}.step", "enter_promo")
        return

    if step == "enter_promo" and text and joinchat(cid):
        code_str = text.strip()
        p_row = database.fetch_one("SELECT * FROM `promocodes` WHERE UPPER(`code`) = UPPER(?) AND `status` = 'on'", (code_str,))
        if not p_row:
            sms(cid, "❌ Bunday promokod topilmadi yoki muddati tugagan! Qaytadan tekshirib yozing:", ORT_KB)
            return
        if int(p_row.get("used_count") or 0) >= int(p_row.get("max_uses") or 0):
            sms(cid, "⚠️ Ushbu promokodning foydalanish limiti tugagan!", m_kb)
            unlink_file(f"user/{cid}.step")
            return
        already = database.fetch_one(
            "SELECT * FROM `earn_claims` WHERE `user_id` = ? AND `claim_type` = 'promo' AND `item_id` = ?",
            (cid, str(p_row["id"])),
        )
        if already:
            sms(cid, "⚠️ Siz ushbu promokoddan allaqachon foydalangansiz!", m_kb)
            unlink_file(f"user/{cid}.step")
            return
        rew_val = float(p_row.get("reward") or 0)
        u_row = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (cid,)) or {}
        new_b = round(float(u_row.get("balance") or 0) + rew_val, 2)
        database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_b), cid))
        database.execute("UPDATE `promocodes` SET `used_count` = `used_count` + 1 WHERE `id` = ?", (p_row["id"],))
        database.execute(
            "INSERT INTO `earn_claims` (`user_id`, `claim_type`, `item_id`, `claimed_at`) VALUES (?, 'promo', ?, ?)",
            (cid, str(p_row["id"]), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        unlink_file(f"user/{cid}.step")
        sms(
            cid,
            f"🎉 <b>Promokod (<code>{p_row['code']}</code>) muvaffaqiyatli faollashtirildi!</b>\n\n"
            f"💰 Hisobingizga: <b>+{fmt_money(rew_val)} so‘m</b> qo‘shildi!\n"
            f"💵 Yangi balansingiz: <b>{fmt_money(new_b)} so‘m</b>",
            m_kb,
        )
        return

    # ========================================================================
    # ADMIN PANEL: 💵 PUL ISHLASH SOZLAMALARI (HAMMASINI BOSHQARISH)
    # ========================================================================

    def _build_admin_earn_panel() -> Tuple[str, str]:
        st_now = database.get_settings()
        ref_reward = enc("decode", st_now.get("referal", "MTAw")) or "100"
        ref_bonus_pct = st_now.get("bonus", "4")
        ref_on = st_now.get("ref_status", "off") == "on"
        daily_amt = get_file("set/daily_bonus.txt").strip() or "50"
        daily_on = (get_file("set/daily_status.txt").strip() or "on") == "on"
        bot_price = fmt_money(get_file("set/bot_price.txt").strip() or BOT_CODE_PRICE)
        ch_cnt = database.count_rows("earn_channels")
        tsk_cnt = database.count_rows("earn_tasks")
        prm_cnt = database.count_rows("promocodes")

        txt = (
            "💵 <b>Pul ishlash bo‘limi — To‘liq Admin Boshqaruvi</b>\n\n"
            f"1️⃣ <b>Referal mukofoti (1 ta taklif):</b> <code>{ref_reward} so‘m</code>\n"
            f"2️⃣ <b>Referal depozit keshbek foizi:</b> <code>{ref_bonus_pct}%</code> ({'✅ Yoqilgan' if ref_on else '❌ O‘chirilgan'})\n"
            f"3️⃣ <b>Kunlik bepul bonus:</b> <code>{daily_amt} so‘m</code> ({'✅ Yoqilgan' if daily_on else '❌ O‘chirilgan'})\n"
            f"4️⃣ <b>Pullik obuna kanallari:</b> <code>{ch_cnt} ta</code>\n"
            f"5️⃣ <b>Maxsus vazifalar:</b> <code>{tsk_cnt} ta</code>\n"
            f"6️⃣ <b>Promokodlar:</b> <code>{prm_cnt} ta</code>\n"
            f"7️⃣ <b>Hamkorlikdagi Bo‘t kodi narxi:</b> <code>{bot_price} so‘m</code>\n\n"
            "👇 <i>O‘zgartirmoqchi bo‘lgan bo‘limingizni tanlang:</i>"
        )
        kb = keyboard([
            [
                {"text": f"👥 Referal narxi ({ref_reward} so‘m)", "callback_data": "adm_earn=ref_price"},
                {"text": f"📈 Depozit foizi ({ref_bonus_pct}%)", "callback_data": "adm_earn=ref_bonus"},
            ],
            [
                {"text": f"🎁 Kunlik bonus ({daily_amt} so‘m)", "callback_data": "adm_earn=daily"},
                {"text": f"Kunlik: {'✅ ON' if daily_on else '❌ OFF'}", "callback_data": "adm_earn=toggle_daily"},
            ],
            [
                {"text": f"📢 Obuna kanallar ({ch_cnt})", "callback_data": "adm_earn=channels"},
                {"text": f"📋 Vazifalar ({tsk_cnt})", "callback_data": "adm_earn=tasks"},
            ],
            [
                {"text": f"🎟️ Promokodlar ({prm_cnt})", "callback_data": "adm_earn=promos"},
                {"text": "💎 Konkurs sozlamalari", "callback_data": "adm_earn=konkurs"},
            ],
            [
                {"text": "📝 Pul ishlash sarlavha matni", "callback_data": "adm_earn=header"},
                {"text": "🖥 Server & SMM Bot tariflari", "callback_data": "adm_earn=tariffs"},
            ],
        ])
        return txt, kb

    if text == "💵 Pul ishlash sozlamalari" and cid == ADMIN:
        p_txt, p_kb = _build_admin_earn_panel()
        sms(cid, p_txt, p_kb)
        return

    if data.startswith("adm_earn=") and chat_id == ADMIN:
        act = data.split("=", 1)[1]
        if act == "home":
            p_txt, p_kb = _build_admin_earn_panel()
            edit(chat_id, message_id, p_txt, p_kb)
        elif act == "ref_price":
            cur_ref = enc("decode", setting.get("referal", "MTAw")) or "100"
            del_msg(chat_id, message_id)
            sms(chat_id, f"👥 <b>1 ta taklif qilingan referal uchun mukofot summasini kiriting (so‘mda):</b>\n\nJoriy narx: <code>{cur_ref}</code> so‘m", AORT_KB)
            put_file(f"user/{chat_id}.step", "adm_set_ref_price")
        elif act == "ref_bonus":
            cur_st = database.get_settings().get("ref_status", "off")
            cur_b = database.get_settings().get("bonus", "4")
            edit(
                chat_id,
                message_id,
                f"📈 <b>Referal hisob to‘ldirganda beriladigan keshbek foizi:</b> <code>{cur_b}%</code>\n"
                f"Holati: {'✅ Yoqilgan' if cur_st == 'on' else '❌ O‘chirilgan'}",
                keyboard([
                    [{"text": "🔄 Yoqish / O‘chirish (ON/OFF)", "callback_data": "adm_earn=toggle_ref_st"}],
                    [{"text": "✏️ Foizni (%) o‘zgartirish", "callback_data": "referr=edit"}],
                    [{"text": "⬅️ Orqaga", "callback_data": "adm_earn=home"}],
                ]),
            )
        elif act == "toggle_ref_st":
            cur_st = database.get_settings().get("ref_status", "off")
            new_st = "off" if cur_st == "on" else "on"
            database.execute("UPDATE `settings` SET `ref_status` = ? WHERE `id` = 1", (new_st,))
            p_txt, p_kb = _build_admin_earn_panel()
            edit(chat_id, message_id, p_txt, p_kb)
        elif act == "toggle_daily":
            cur_d = (get_file("set/daily_status.txt").strip() or "on")
            put_file("set/daily_status.txt", "off" if cur_d == "on" else "on")
            p_txt, p_kb = _build_admin_earn_panel()
            edit(chat_id, message_id, p_txt, p_kb)
        elif act == "daily":
            cur_amt = get_file("set/daily_bonus.txt").strip() or "50"
            del_msg(chat_id, message_id)
            sms(chat_id, f"🎁 <b>Kunlik bonus miqdorini kiriting (so‘mda):</b>\n\nJoriy miqdor: <code>{cur_amt}</code> so‘m", AORT_KB)
            put_file(f"user/{chat_id}.step", "adm_set_daily_amt")
        elif act == "tariffs":
            go_p = fmt_money(get_file("set/tariff_go.txt").strip() or 15000)
            pro_p = fmt_money(get_file("set/tariff_pro.txt").strip() or 30000)
            plus_p = fmt_money(get_file("set/tariff_plus.txt").strip() or 50000)
            smm_p = fmt_money(get_file("set/smm_bot_monthly.txt").strip() or 10000)
            hosted_cnt = database.count_rows("hosted_bots")
            edit(
                chat_id,
                message_id,
                f"🖥 <b>Server va SMM Bot Tariflari Boshqaruvi:</b>\n\n"
                f"🟢 <b>GO tarifi:</b> <code>{go_p} so‘m/oy</code>\n"
                f"🔵 <b>PRO tarifi:</b> <code>{pro_p} so‘m/oy</code>\n"
                f"🟣 <b>PLUS tarifi:</b> <code>{plus_p} so‘m/oy</code>\n"
                f"🚀 <b>SMM Bot oylik narxi:</b> <code>{smm_p} so‘m/oy</code> (1-marta 7 kun tekin)\n"
                f"🤖 <b>Jami ulangan botlar:</b> <code>{hosted_cnt} ta</code>",
                keyboard([
                    [
                        {"text": f"🟢 GO ({go_p})", "callback_data": "adm_trf=tariff_go.txt"},
                        {"text": f"🔵 PRO ({pro_p})", "callback_data": "adm_trf=tariff_pro.txt"},
                    ],
                    [
                        {"text": f"🟣 PLUS ({plus_p})", "callback_data": "adm_trf=tariff_plus.txt"},
                        {"text": f"🚀 SMM Bot ({smm_p})", "callback_data": "adm_trf=smm_bot_monthly.txt"},
                    ],
                    [{"text": "⬅️ Orqaga", "callback_data": "adm_earn=home"}],
                ]),
            )
        elif act == "header":
            del_msg(chat_id, message_id)
            sms(chat_id, "📝 <b>Pul ishlash bo‘limi sarlavha matnini yuboring:</b>", AORT_KB)
            put_file(f"user/{chat_id}.step", "adm_set_earn_header")
        elif act == "channels":
            chs = database.fetch_all("SELECT * FROM `earn_channels`")
            kb_rows = [[{"text": f"🗑️ @{c['channel_username'].lstrip('@')} ({c['reward']} so‘m) — O‘chirish", "callback_data": f"adm_del_ech={c['id']}"}] for c in chs]
            kb_rows.append([{"text": "➕ Yangi pullik kanal qo‘shish", "callback_data": "adm_earn=add_ch"}])
            kb_rows.append([{"text": "⬅️ Orqaga", "callback_data": "adm_earn=home"}])
            edit(chat_id, message_id, "📢 <b>Pullik obuna kanallari ro‘yxati:</b>\n<i>Foydalanuvchi shu kanallarga a'zo bo‘lib mukofot oladi (bot kanalda admin bo‘lishi kerak).</i>", keyboard(kb_rows))
        elif act == "add_ch":
            del_msg(chat_id, message_id)
            sms(chat_id, "📢 <b>Kanal username va mukofot summasini quyidagi formatda yuboring:</b>\n\n<code>@kanal_user 200 Kanal Nomi</code>\n\n<i>Masalan:</i> <code>@antaarab_smm 150 Antaarab Rasmiy Kanali</code>", AORT_KB)
            put_file(f"user/{chat_id}.step", "adm_add_earn_ch")
        elif act == "tasks":
            tsks = database.fetch_all("SELECT * FROM `earn_tasks`")
            kb_rows = [[{"text": f"🗑️ {t['title']} ({t['reward']} so‘m) — O‘chirish", "callback_data": f"adm_del_etsk={t['id']}"}] for t in tsks]
            kb_rows.append([{"text": "➕ Yangi vazifa qo‘shish (Avto)", "callback_data": "adm_earn=add_tsk_auto"}])
            kb_rows.append([{"text": "➕ Yangi vazifa qo‘shish (Skrinshot bilan)", "callback_data": "adm_earn=add_tsk_proof"}])
            kb_rows.append([{"text": "⬅️ Orqaga", "callback_data": "adm_earn=home"}])
            edit(chat_id, message_id, "📋 <b>Pul ishlash vazifalari boshqaruvi:</b>", keyboard(kb_rows))
        elif act in ("add_tsk_auto", "add_tsk_proof"):
            v_mode = "auto" if act == "add_tsk_auto" else "proof"
            put_file("set/tmp_tsk_mode.txt", v_mode)
            del_msg(chat_id, message_id)
            sms(
                chat_id,
                "📋 <b>Yangi vazifa ma'lumotlarini 4 qatorda yuboring:</b>\n\n"
                "1-qator: Vazifa nomi\n"
                "2-qator: Vazifa sharti (izoh)\n"
                "3-qator: Havola (https://...)\n"
                "4-qator: Mukofot summasi (faqat raqam, masalan: 250)",
                AORT_KB,
            )
            put_file(f"user/{chat_id}.step", "adm_add_earn_tsk")
        elif act == "promos":
            prms = database.fetch_all("SELECT * FROM `promocodes`")
            kb_rows = [
                [{"text": f"🗑️ {p['code']} ({p['reward']} so‘m | {p['used_count']}/{p['max_uses']}) — O‘chirish", "callback_data": f"adm_del_prm={p['id']}"}]
                for p in prms
            ]
            kb_rows.append([{"text": "➕ Yangi promokod yaratish", "callback_data": "adm_earn=add_prm"}])
            kb_rows.append([{"text": "⬅️ Orqaga", "callback_data": "adm_earn=home"}])
            edit(chat_id, message_id, "🎟️ <b>Promokodlar ro‘yxati va boshqaruvi:</b>", keyboard(kb_rows))
        elif act == "add_prm":
            del_msg(chat_id, message_id)
            sms(
                chat_id,
                "🎟️ <b>Yangi promokod ma'lumotlarini bo‘sh joy bilan yuboring:</b>\n\n"
                "<code>KOD SUMMA LIMIT</code>\n\n"
                "<i>Masalan (50 kishi uchun 500 so‘mlik promokod):</i>\n"
                "<code>BONUS2026 500 50</code>",
                AORT_KB,
            )
            put_file(f"user/{chat_id}.step", "adm_add_promo")
        elif act == "konkurs":
            edit(
                chat_id,
                message_id,
                "💎 <b>Konkurs (🏆 TOP 10) sozlamalari:</b>",
                keyboard([
                    [{"text": "📝 Konkurs matni va sovrinlarini o‘zgartirish", "callback_data": "adm_earn=edit_konkurs_txt"}],
                    [{"text": "🔄 Konkurs reytingini 0 ga tushirish", "callback_data": "adm_earn=reset_konkurs"}],
                    [{"text": "⬅️ Orqaga", "callback_data": "adm_earn=home"}],
                ]),
            )
        elif act == "edit_konkurs_txt":
            del_msg(chat_id, message_id)
            sms(
                chat_id,
                "💎 <b>Konkurs bo‘limi uchun yangi matn va sovrinlar ro‘yxatini yuboring:</b>\n\n"
                "<i>Masalan:\n🏆 Konkurs sovrinlari:\n🥇 1-o‘rin: 50 000 so‘m\n🥈 2-o‘rin: 30 000 so‘m\n🥉 3-o‘rin: 15 000 so‘m</i>",
                AORT_KB,
            )
            put_file(f"user/{chat_id}.step", "adm_set_konkurs_txt")
        elif act == "reset_konkurs":
            for path in glob.glob(os.path.join(config.USER_DIR, "*.users")):
                try:
                    os.remove(path)
                except OSError:
                    pass
            for k in list(_FILE_CACHE.keys()):
                if k.endswith(".users"):
                    del _FILE_CACHE[k]
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "✅ Konkurs TOP-10 reytingi 0 ga tushirildi!", "show_alert": True})
            p_txt, p_kb = _build_admin_earn_panel()
            edit(chat_id, message_id, p_txt, p_kb)
        return

    if data.startswith("adm_del_ech=") and chat_id == ADMIN:
        ch_id = data.split("=", 1)[1]
        database.execute("DELETE FROM `earn_channels` WHERE `id` = ?", (ch_id,))
        bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "🗑️ Kanal o‘chirildi!"})
        p_txt, p_kb = _build_admin_earn_panel()
        edit(chat_id, message_id, p_txt, p_kb)
        return

    if data.startswith("adm_del_etsk=") and chat_id == ADMIN:
        t_id = data.split("=", 1)[1]
        database.execute("DELETE FROM `earn_tasks` WHERE `id` = ?", (t_id,))
        bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "🗑️ Vazifa o‘chirildi!"})
        p_txt, p_kb = _build_admin_earn_panel()
        edit(chat_id, message_id, p_txt, p_kb)
        return

    if data.startswith("adm_del_prm=") and chat_id == ADMIN:
        p_id = data.split("=", 1)[1]
        database.execute("DELETE FROM `promocodes` WHERE `id` = ?", (p_id,))
        bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "🗑️ Promokod o‘chirildi!"})
        p_txt, p_kb = _build_admin_earn_panel()
        edit(chat_id, message_id, p_txt, p_kb)
        return

    if step == "adm_set_ref_price" and cid == ADMIN and text:
        clean_v = text.strip().replace(" ", "")
        if clean_v.replace(".", "", 1).isdigit():
            database.execute("UPDATE `settings` SET `referal` = ? WHERE `id` = 1", (enc("encode", clean_v),))
            unlink_file(f"user/{cid}.step")
            sms(cid, f"✅ Referal mukofoti <b>{clean_v} so‘m</b> etib saqlandi!", PANEL_KB)
        else:
            sms(cid, "⚠️ Faqat raqam kiriting (masalan: 200):", AORT_KB)
        return

    if step == "adm_set_daily_amt" and cid == ADMIN and text:
        clean_v = text.strip().replace(" ", "")
        if clean_v.replace(".", "", 1).isdigit():
            put_file("set/daily_bonus.txt", clean_v)
            unlink_file(f"user/{cid}.step")
            sms(cid, f"✅ Kunlik bonus miqdori <b>{clean_v} so‘m</b> etib saqlandi!", PANEL_KB)
        else:
            sms(cid, "⚠️ Faqat raqam kiriting (masalan: 100):", AORT_KB)
        return

    if data.startswith("adm_trf=") and chat_id == ADMIN:
        fname = data.split("=", 1)[1]
        put_file("set/tmp_trf_file.txt", fname)
        del_msg(chat_id, message_id)
        sms(chat_id, f"💰 <b>Yangi oylik narxni kiriting (so‘mda, faqat raqam):</b>", AORT_KB)
        put_file(f"user/{chat_id}.step", "adm_set_trf_price")
        return

    if step == "adm_set_trf_price" and cid == ADMIN and text:
        clean_v = text.strip().replace(" ", "")
        fname = get_file("set/tmp_trf_file.txt").strip()
        if clean_v.replace(".", "", 1).isdigit() and fname:
            put_file(f"set/{fname}", clean_v)
            unlink_file(f"user/{cid}.step")
            sms(cid, f"✅ Tarif narxi <b>{fmt_money(clean_v)} so‘m / oy</b> etib saqlandi!", PANEL_KB)
        else:
            sms(cid, "⚠️ Faqat raqam kiriting (masalan: 10000):", AORT_KB)
        return

    if step == "adm_set_earn_header" and cid == ADMIN and text:
        put_file("set/earn_header.txt", text.strip())
        unlink_file(f"user/{cid}.step")
        sms(cid, "✅ Pul ishlash bo‘limi sarlavha matni yangilandi!", PANEL_KB)
        return

    if step == "adm_set_konkurs_txt" and cid == ADMIN and text:
        put_file("set/konkurs_text.txt", text.strip())
        unlink_file(f"user/{cid}.step")
        sms(cid, "✅ Konkurs matni va sovrinlari saqlandi!", PANEL_KB)
        return

    if step == "adm_add_earn_ch" and cid == ADMIN and text:
        parts = text.strip().split(None, 2)
        if len(parts) >= 2 and parts[1].replace(".", "", 1).isdigit():
            ch_u = parts[0].strip()
            rew_v = parts[1].strip()
            ch_title = parts[2].strip() if len(parts) >= 3 else ch_u
            database.execute(
                "INSERT INTO `earn_channels` (`channel_username`, `title`, `reward`, `status`) VALUES (?, ?, ?, 'on')",
                (ch_u, ch_title, rew_v),
            )
            unlink_file(f"user/{cid}.step")
            sms(cid, f"✅ Pullik obuna kanali (<b>{ch_u}</b> — +{rew_v} so‘m) qo‘shildi!", PANEL_KB)
        else:
            sms(cid, "⚠️ Format xato! Namuna: <code>@kanal_user 200 Kanal Nomi</code>", AORT_KB)
        return

    if step == "adm_add_earn_tsk" and cid == ADMIN and text:
        lines = [ln.strip() for ln in text.strip().split("\n") if ln.strip()]
        if len(lines) >= 4 and lines[3].replace(".", "", 1).isdigit():
            v_mode = get_file("set/tmp_tsk_mode.txt").strip() or "auto"
            database.execute(
                "INSERT INTO `earn_tasks` (`title`, `description`, `url`, `reward`, `verify_type`, `status`) VALUES (?, ?, ?, ?, ?, 'on')",
                (lines[0], lines[1], lines[2], lines[3], v_mode),
            )
            unlink_file(f"user/{cid}.step")
            sms(cid, f"✅ Yangi vazifa («<b>{lines[0]}</b>» — +{lines[3]} so‘m) qo‘shildi!", PANEL_KB)
        else:
            sms(cid, "⚠️ Iltimos, ma'lumotlarni to‘liq 4 qatorda va 4-qatorda faqat raqam bilan yuboring!", AORT_KB)
        return

    if step == "adm_add_promo" and cid == ADMIN and text:
        parts = text.strip().split()
        if len(parts) >= 3 and parts[1].replace(".", "", 1).isdigit() and parts[2].isdigit():
            p_code, p_rew, p_lim = parts[0], parts[1], int(parts[2])
            database.execute(
                "INSERT INTO `promocodes` (`code`, `reward`, `max_uses`, `used_count`, `status`) VALUES (?, ?, ?, 0, 'on')",
                (p_code, p_rew, p_lim),
            )
            unlink_file(f"user/{cid}.step")
            sms(cid, f"✅ Promokod <code>{p_code}</code> (+{p_rew} so‘m, {p_lim} ta limit) yaratildi!", PANEL_KB)
        else:
            sms(cid, "⚠️ Format xato! Namuna: <code>BONUS2026 500 50</code>", AORT_KB)
        return

    if text == "🛒 Buyurtmalar" and joinchat(cid):
        rows = database.fetch_all("SELECT * FROM `myorder` WHERE `user_id` = ?", (cid,))
        if not rows:
            sms(cid, "🤷‍♂️ Sizda xechqanday buyurtma topilmadi.")
        else:
            btns = [{"text": str(my["order_id"])} for my in rows]
            kb_rows = chunk_list(btns, 3)
            kb_rows.append([{"text": "➡️ Orqaga"}])
            sms(cid, "👉 Barcha buyurtmalaringiz:", reply_keyboard(kb_rows))
            put_file(f"user/{cid}.step", "orders")
        return

    if step == "orders" and text and text.isdigit() and joinchat(cid):
        rew = database.fetch_one("SELECT * FROM `orders` WHERE `order_id` = ?", (int(text),))
        if not rew:
            sms(cid, "❌ Buyurtma topilmadi!", m_kb)
            unlink_file(f"user/{cid}.step")
            return
        ap = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (rew["provider"],))
        err = None
        if ap:
            raw = http_get(f"{ap['api_url']}?key={ap['api_key']}&action=status&order={rew['api_order']}")
            try:
                err = json.loads(raw).get("error")
            except Exception:
                pass
        status_map = {
            "Completed": "bajarilgan",
            "In progress": "bajarilmoqda",
            "Partial": "qayta ishlanmoqda",
            "Pending": "bajarilmoqda",
            "Processing": "bajarilmoqda",
            "Canceled": "bekor qilingan",
        }
        st_uz = status_map.get(rew.get("status", ""), rew.get("status", ""))
        if err:
            sms(cid, "❌ Buyurtma topilmadi!", m_kb)
        else:
            sms(cid, f"\n✅ Buyurtma xolati: {st_uz}", m_kb)
        unlink_file(f"user/{cid}.step")
        return

    if text == "☎️ Yordam" and joinchat(cid):
        sms(cid, "⭐ Bizga savollaringiz bormi?\n\n📑 Murojaat matnini yozib yuboring.", ORT_KB)
        put_file(f"user/{cid}.step", "murojaat")
        return

    if step == "murojaat" and message:
        sms(cid, "✅ Murojaatingiz qabul qilindi", m_kb)
        bot(
            "copyMessage",
            {
                "chat_id": ADMIN,
                "from_chat_id": cid,
                "message_id": mid,
                "reply_markup": keyboard([
                    [{"text": "👁️ Ko‘rish", "url": f"tg://user?id={cid}"}],
                    [{"text": "📑 Javob yozish", "callback_data": f"javob={cid}"}],
                ]),
            },
        )
        put_file(f"user/{cid}.step", "")
        return

    if data.startswith("javob="):
        ida = data.split("=")[1]
        sms(ADMIN, f"{ida} Foydalanuvchiga yuboriladigan xabaringizni kiriting.", ORT_KB)
        put_file(f"user/{cid2}.step", f"ticket={ida}")
        return

    if step.startswith("ticket=") and cid == ADMIN and message:
        ida = step.split("=")[1]
        res = bot("copyMessage", {"chat_id": ida, "from_chat_id": ADMIN, "message_id": mid})
        if res.get("ok"):
            sms(cid, "✅ Xabar yuborildi", PANEL_KB)
        else:
            sms(cid, "❌ Xabar yuborilmadi, ehtimol botni bloklagan.", PANEL_KB)
        unlink_file(f"user/{cid}.step")
        return

    if text == "💳 Balans" and joinchat(cid):
        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (cid,)) or {}
        kabinet_tpl = enc("decode", setting.get("kabinet", ""))
        kabinet_msg = format_kabinet_msg(kabinet_tpl, rew, cid)
        sms(cid, kabinet_msg, BALANS_KB)
        return

    if text == "💳 Pul kiritish" and joinchat(cid):
        ops = get_file("set/payments.txt")
        methods = [ln.strip() for ln in ops.split("\n") if ln.strip()]
        btns = [{"text": m_name, "callback_data": f"payBot={m_name}"} for m_name in methods]
        kb_rows = chunk_list(btns, 2)
        kb_rows.append([{"text": "💳 PAYME", "callback_data": "menu=PAYME"}])
        sms(cid, "💳 Kerakli to‘lov tizimini tanlang:", keyboard(kb_rows))
        return

    if data.startswith("menu=") and joinchat(chat_id):
        res = data.split("=")[1]
        if res == "tolov":
            ops = get_file("set/payments.txt")
            methods = [ln.strip() for ln in ops.split("\n") if ln.strip()]
            btns = [{"text": m_name, "callback_data": f"payBot={m_name}"} for m_name in methods]
            kb_rows = chunk_list(btns, 2)
            kb_rows.append([{"text": "💳 PAYME", "callback_data": "menu=PAYME"}])
            kb_rows.append([{"text": "➡️ Orqaga", "callback_data": "menu=back"}])
            edit(chat_id, message_id, "💳 Kerakli to‘lov tizimini tanlang:", keyboard(kb_rows))
        elif res == "saved":
            saved_rows = database.fetch_all(
                "SELECT * FROM `saved_orders` WHERE `user_id` = ? ORDER BY `saved_id` DESC LIMIT 15",
                (chat_id,),
            )
            if not saved_rows:
                edit(
                    chat_id,
                    message_id,
                    "💾 <b>Saqlangan buyurtmalar</b>\n\n🤷‍♂️ Sizda hozircha saqlab qo‘yilgan buyurtmalar yo‘q.\n"
                    "<i>Buyurtma berish jarayonida «💾 Saqlab qo‘yish» tugmasini bosib buyurtmalarni shu yerga saqlashingiz mumkin.</i>",
                    keyboard([[{"text": "➡️ Orqaga", "callback_data": "menu=back"}]]),
                )
            else:
                lines = ["💾 <b>Saqlangan buyurtmalaringiz:</b>\n"]
                kb_rows = []
                for sv in saved_rows:
                    sv_id = sv["saved_id"]
                    s_name = sv.get("service_name") or f"Xizmat #{sv.get('service_id')}"
                    s_qty = sv.get("quantity", "1")
                    s_price = fmt_money(sv.get("price", "0"))
                    s_link = sv.get("link", "")
                    lines.append(
                        f"🔹 <b>#{sv_id} | {s_name}</b>\n"
                        f"   🔢 Miqdor: <b>{s_qty} ta</b> | 💵 Narx: <b>{s_price} so‘m</b>\n"
                        f"   📎 Manzil: <code>{s_link}</code>"
                    )
                    kb_rows.append([
                        {"text": f"🚀 Yuborish (#{sv_id})", "callback_data": f"send_saved={sv_id}"},
                        {"text": f"🗑️ O‘chirish (#{sv_id})", "callback_data": f"del_saved={sv_id}"},
                    ])
                kb_rows.append([{"text": "➡️ Orqaga", "callback_data": "menu=back"}])
                edit(chat_id, message_id, "\n\n".join(lines), keyboard(kb_rows))
        elif res == "back":
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
            kabinet_tpl = enc("decode", setting.get("kabinet", ""))
            kabinet_msg = format_kabinet_msg(kabinet_tpl, rew, chat_id)
            edit(chat_id, message_id, kabinet_msg, BALANS_KB)
        elif res == "PAYME":
            payme_id = setting.get("payme_id", "")
            if not payme_id or payme_id.lower() == "null":
                bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Ushbu tolov tizimidagi kerakli malumotlar yetishmaydi", "show_alert": True})
            else:
                del_msg(chat_id, message_id)
                sms(chat_id, "💵 To‘lov miqdorini kiriting:\n\n⬇️ Minimal 10000 so‘m\n⬆️ Maksimal 12000000 so‘m", ORT_KB)
                put_file(f"user/{chat_id}.step", "payme")
        return

    if data.startswith("del_saved=") and joinchat(chat_id):
        sv_id = data.split("=", 1)[1]
        database.execute("DELETE FROM `saved_orders` WHERE `saved_id` = ? AND `user_id` = ?", (sv_id, chat_id))
        bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "🗑️ Saqlangan buyurtma o‘chirildi!"})
        saved_rows = database.fetch_all(
            "SELECT * FROM `saved_orders` WHERE `user_id` = ? ORDER BY `saved_id` DESC LIMIT 15",
            (chat_id,),
        )
        if not saved_rows:
            edit(
                chat_id,
                message_id,
                "💾 <b>Saqlangan buyurtmalar</b>\n\n🤷‍♂️ Sizda hozircha saqlab qo‘yilgan buyurtmalar yo‘q.",
                keyboard([[{"text": "➡️ Orqaga", "callback_data": "menu=back"}]]),
            )
        else:
            lines = ["💾 <b>Saqlangan buyurtmalaringiz:</b>\n"]
            kb_rows = []
            for sv in saved_rows:
                sid_i = sv["saved_id"]
                s_name = sv.get("service_name") or f"Xizmat #{sv.get('service_id')}"
                lines.append(
                    f"🔹 <b>#{sid_i} | {s_name}</b>\n"
                    f"   🔢 Miqdor: <b>{sv.get('quantity', '1')} ta</b> | 💵 Narx: <b>{fmt_money(sv.get('price', '0'))} so‘m</b>\n"
                    f"   📎 Manzil: <code>{sv.get('link', '')}</code>"
                )
                kb_rows.append([
                    {"text": f"🚀 Yuborish (#{sid_i})", "callback_data": f"send_saved={sid_i}"},
                    {"text": f"🗑️ O‘chirish (#{sid_i})", "callback_data": f"del_saved={sid_i}"},
                ])
            kb_rows.append([{"text": "➡️ Orqaga", "callback_data": "menu=back"}])
            edit(chat_id, message_id, "\n\n".join(lines), keyboard(kb_rows))
        return

    if data.startswith("send_saved=") and joinchat(chat_id):
        sv_id = data.split("=", 1)[1]
        sv = database.fetch_one("SELECT * FROM `saved_orders` WHERE `saved_id` = ? AND `user_id` = ?", (sv_id, chat_id))
        if not sv:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Saqlangan buyurtma topilmadi!", "show_alert": True})
            return
        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
        cost = round(float(sv.get("price") or 0), 4)
        u_bal = float(rew.get("balance") or 0)
        if u_bal < cost:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": f"❌ Hisobingizda mablag‘ yetarli emas! Kerak: {fmt_money(cost)} so‘m", "show_alert": True})
            return
        m = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (sv.get("provider_id"),))
        if not m:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Provayder topilmadi!", "show_alert": True})
            return
        si = str(sv.get("api_service", "")).strip()
        ur = urllib.parse.quote(str(sv.get("link", "")).strip())
        qu = str(sv.get("quantity", "1")).strip()
        raw = http_get(f"{m['api_url']}?key={m['api_key']}&action=add&service={si}&link={ur}&quantity={qu}")
        try:
            j = json.loads(raw)
        except Exception:
            j = {}
        jid = j.get("order")
        if not jid:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ API provayderda xatolik yuz berdi. Keyinroq urinib ko‘ring!", "show_alert": True})
            return
        or_id = database.count_rows("orders") + 1
        sav = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
        database.execute(
            """INSERT INTO `myorder`
            (`order_id`, `user_id`, `retail`, `status`, `service`, `order_create`, `last_check`)
            VALUES (?, ?, ?, 'Pending', ?, ?, ?)""",
            (or_id, chat_id, fmt_money(cost), sv.get("service_id", ""), sav, sav),
        )
        database.execute(
            """INSERT INTO `orders`
            (`api_order`, `order_id`, `provider`, `status`)
            VALUES (?, ?, ?, 'Pending')""",
            (str(jid), or_id, sv.get("provider_id", "")),
        )
        new_bal = round(u_bal - cost, 4)
        database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_bal), chat_id))
        order_tpl = enc("decode", setting.get("orders", ""))
        order_msg = format_order_confirmed_msg(
            order_tpl,
            or_id,
            jid,
            sv.get("service_name") or f"Xizmat #{sv.get('service_id')}",
            qu,
            cost,
        )
        bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "✅ Buyurtma muvaffaqiyatli yuborildi!"})
        sms(chat_id, order_msg)
        return

    if data.startswith("payBot="):
        h = data.split("=", 1)[1]
        card = get_file(f"set/pay/{h}/wallet.txt")
        info = get_file(f"set/pay/{h}/addition.txt")
        edit(
            cid2,
            mid2,
            f"To'lov tizimi: {h}\n\nHamyon: {card}\nIzoh: {cid2}\n   \n{info}",
            keyboard([
                [{"text": "✅ To‘lov qildim", "callback_data": "tolovqldm"}],
                [{"text": "➡️ Orqaga", "callback_data": "menu=tolov"}],
            ]),
        )
        return

    if data == "tolovqldm":
        sms(chat_id, "💳 To‘lov cheki yoki rasmini yuboring", ORT_KB)
        put_file(f"user/{chat_id}.step", "tolovqldm")
        return

    if step == "tolovqldm" and (text or photo):
        sms(cid, "✅ Hisobni to‘ldirish arizangiz qabul qilindi.", m_kb)
        put_file("user/us.id", cid)
        bot("forwardMessage", {"chat_id": ADMIN, "from_chat_id": cid, "message_id": mid})
        sms(ADMIN, "👤 Kerakli tugmani tanlang", keyboard([[{"text": "Pul qo‘shish", "callback_data": "plus"}]]))
        unlink_file(f"user/{cid}.step")
        return

    if step == "payme" and text:
        try:
            amount_val = float(text)
        except ValueError:
            amount_val = 0.0
        if 10000 <= amount_val <= 12000000:
            bot_user = get_bot_username()
            res = handle_payme_request({
                "action": "create",
                "card": setting.get("payme_id", ""),
                "sum": text,
                "desc": f"@{bot_user}",
            })
            checkout_url = res.get("_result", {}).get("_details", {}).get("_pay_url", "")
            checkid = checkout_url.replace("https://checkout.paycom.uz/", "")
            sms(
                cid,
                f"💵 To‘lov miqdori: {text} so‘m",
                keyboard([
                    [{"text": "💵 To‘lovga o‘tish", "url": checkout_url}],
                    [{"text": "💵 Shuyerda to‘lash", "web_app": {"url": checkout_url}}],
                    [{"text": "✅ Tekshirish", "callback_data": f"checkout={checkid}={text}"}],
                ]),
            )
            sms(cid, "🖥️ Asosiy menyudasiz", MENU_USER_KB)
            unlink_file(f"user/{cid}.step")
        else:
            sms(cid, "⬇️ Minimal 10000 so‘m\n⬆️ Maksimal 12000000 so‘m", ORT_KB)
        return

    if data.startswith("checkout=") and joinchat(chat_id):
        parts = data.split("=")
        checkid = parts[1] if len(parts) > 1 else ""
        plus = float(parts[2]) if len(parts) > 2 else 0.0
        checkids = get_file("payments.txt")
        if checkid and checkid in checkids:
            bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ To‘lov bajarilgan.", "show_alert": True})
        else:
            js = handle_payme_request({"action": "info", "id": checkid})
            pay_time = js.get("mess")
            if not pay_time:
                bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ To‘lov bajarilmagan.", "show_alert": True})
            else:
                del_msg(chat_id, message_id)
                sms(chat_id, f"💳 Hisobingizga {plus} so‘m qo‘shildi", MENU_USER_KB)
                rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,))
                if rew:
                    miqdor = float(rew.get("balance") or 0) + plus
                    p2 = float(rew.get("outing") or 0) + plus
                    database.execute("UPDATE `users` SET `balance` = ?, `outing` = ? WHERE `id` = ?", (str(miqdor), str(p2), chat_id))
                put_file("payments.txt", f"\n{checkid}", append=True)
                sms(ADMIN, f"💳 Hisob to'ldirildi\n👤 Foydalanuvchi: {chat_id}\n💰 Summa: {plus} so'm")
        return

    # ========================================================================
    # FOYDALANUVCHI: Buyurtma berish oqimi
    # ========================================================================

    if text == "➕ Buyurtma berish" and joinchat(cid):
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            sms(cid, "⚠️ Tarmoqlar topilmadi.")
        else:
            btns = [{"text": enc("decode", s["category_name"]), "callback_data": f"tanla1={s['category_id']}"} for s in cats]
            kb_rows = chunk_list(btns, 2)
            if "." in host and "localhost" not in host:
                kb_rows.append([{"text": "📝 Barcha xizmatlar", "url": f"https://{host}/services"}])
            sms(cid, "👉 O‘zingizga kerakli tarmoqni tanlang:", keyboard(kb_rows))
        return

    if data == "absd" and joinchat(chat_id):
        cats = database.fetch_all("SELECT * FROM `categorys`")
        if not cats:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Tarmoqlar topilmadi!", "show_alert": True})
        else:
            btns = [{"text": enc("decode", s["category_name"]), "callback_data": f"tanla1={s['category_id']}"} for s in cats]
            kb_rows = chunk_list(btns, 2)
            if "." in host and "localhost" not in host:
                kb_rows.append([{"text": "📝 Barcha xizmatlar", "url": f"https://{host}/services"}])
            edit(chat_id, mid2, "👉 O‘zingizga kerakli tarmoqni tanlang:", keyboard(kb_rows))
        return

    if data.startswith("tanla1=") and joinchat(chat_id):
        n = data.split("=")[1]
        put_file("set/sub.json", json.dumps({"cate_id": n}))
        cates = database.fetch_all("SELECT * FROM `cates` WHERE `category_id` = ?", (n,))
        if not cates:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu tarmoq uchun xizmat turlari topilmadi!", "show_alert": True})
        else:
            seen = set()
            btns = []
            for s in cates:
                nm = enc("decode", s["name"])
                if nm not in seen:
                    seen.add(nm)
                    btns.append([{"text": nm, "callback_data": f"tanla2={s['cate_id']}"}])
            btns.append([{"text": "Orqaga", "callback_data": "absd"}])
            edit(chat_id, message_id, "👉 Kerakli xizmat turini tanlang:", keyboard(btns))
        return

    if data.startswith("tanla2=") and joinchat(chat_id):
        n = data.split("=")[1]
        srvs = database.fetch_all("SELECT * FROM `services` WHERE `category_id` = ? AND `service_status` = 'on'", (n,))
        if not srvs:
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Ushbu bo'lim uchun xizmatlar topilmadi!", "show_alert": True})
        else:
            btns = [
                [{"text": f"{enc('decode', s['service_name'])} {s['service_price']} - so‘m", "callback_data": f"ordered={s['service_id']}={n}"}]
                for s in srvs
            ]
            sub_info = json.loads(get_file("set/sub.json") or "{}")
            btns.append([{"text": "Orqaga", "callback_data": f"tanla1={sub_info.get('cate_id', '')}"}])
            edit(chat_id, message_id, "👉 O‘zingizga kerakli xizmatni tanlang:", keyboard(btns))
        return

    if data.startswith("ordered="):
        parts = data.split("=")
        n, n2 = parts[1], parts[2]
        s = database.fetch_one("SELECT * FROM `services` WHERE `service_id` = ?", (n,))
        if not s or not s.get("service_min") or not s.get("service_max"):
            bot("answerCallbackQuery", {"callback_query_id": qid, "text": "⚠️ Nimadir xato ketdi qaytadan urining.", "show_alert": True})
            return
        nam = enc("decode", s["service_name"])
        sid = s["service_id"]
        narx = s["service_price"]
        stype = s.get("service_type", "Default")
        spi = s["service_api"]
        api = s["api_service"]
        min_v = s["service_min"]
        max_v = s["service_max"]
        abs_desc = enc("decode", s.get("service_desc", "")) if s.get("service_desc") else ""
        if stype.lower() == "default":
            ab_block = f"🔽 Minimal buyurtma: {min_v} ta\n🔼 Maksimal buyurtma: {max_v} ta\n\n{abs_desc}"
        else:
            ab_block = abs_desc
        edit(
            chat_id,
            message_id,
            f"<b>{nam}</b>\n\n🔑 Xizmat IDsi: <code>{sid}</code>\n💵 Narxi (1000 ta) - {narx} so‘m\n\n{ab_block}",
            keyboard([
                [{"text": "✅ Buyurtma berish", "callback_data": f"order={spi}={min_v}={max_v}={narx}={stype}={api}={sid}"}],
                [{"text": "Orqaga", "callback_data": f"tanla2={n2}"}],
            ]),
        )
        return

    if data.startswith("order="):
        parts = data.split("=")
        oid, omin, omax, orate, otype, prov, serv = parts[1:8]
        del_msg(chat_id, message_id)
        if otype.lower() == "default":
            sms(chat_id, "⬇️ Kerakli buyurtma miqdorini kiriting:", ORDER_ORT_KB)
            put_file(f"user/{chat_id}.step", "order=default=sp1")
            put_file(f"user/{chat_id}.params", f"{oid}={omin}={omax}={orate}={prov}={serv}")
            put_file(f"user/{chat_id}.si", oid)
        elif otype == "Package":
            clean_rate = fmt_money(orate)
            sms(chat_id, "📎 Kerakli havolani kiriting (https://):", ORDER_ORT_KB)
            put_file(f"user/{chat_id}.step", f"order=package=sp2=1={clean_rate}")
            put_file(f"user/{chat_id}.params", f"{oid}={omin}={omax}={clean_rate}={prov}={serv}")
            put_file(f"user/{chat_id}.si", oid)
            put_file(f"user/{chat_id}.qu", "1")
        return

    s_parts = step.split("=")
    if len(s_parts) >= 3 and s_parts[0] == "order" and s_parts[1] == "default" and s_parts[2] == "sp1" and text and text.isdigit() and joinchat(cid):
        p = get_file(f"user/{cid}.params").split("=")
        qty = int(text)
        min_q, max_q, rate_q = int(float(p[1])), int(float(p[2])), float(p[3])
        narxi = round((rate_q / 1000.0) * qty, 4)
        narxi_str = fmt_money(narxi)
        if min_q <= qty <= max_q:
            rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (cid,)) or {}
            if float(rew.get("balance") or 0) >= narxi:
                sms(cid, f"✅ {text} ta saqlandi!\n\n📎 Kerakli havolani kiriting (https://):", ORDER_ORT_KB)
                put_file(f"user/{cid}.step", f"order=default=sp2={text}={narxi_str}")
                put_file(f"user/{cid}.qu", text)
            else:
                sms(cid, f"❌ Yetarli mablag‘ mavjud emas!\n💰 Buyurtma narxi: <b>{narxi_str} so‘m</b>\n\nBoshqa miqdor kiritib ko‘ring:", ORDER_ORT_KB)
        else:
            sms(cid, f"⚠️ Buyurtma miqdori noto‘g‘ri kiritilmoqda!\n\n⬇️ Minimal buyurtma: {min_q}\n⬆️ Maksimal buyurtma: {max_q}\n\nBoshqa miqdor kiriting:", ORDER_ORT_KB)
        return

    if len(s_parts) >= 5 and s_parts[0] == "order" and s_parts[1] in ("default", "package") and s_parts[2] == "sp2" and text and joinchat(cid):
        price_str = fmt_money(s_parts[4])
        pc = f"🔢 Buyurtma miqdori: <b>{s_parts[3]} ta</b>" if s_parts[1] == "default" else ""
        p_info = get_file(f"user/{cid}.params").split("=")
        srv_row = database.fetch_one("SELECT `service_name` FROM `services` WHERE `service_id` = ?", (p_info[5],)) if len(p_info) >= 6 else None
        srv_title = enc("decode", srv_row["service_name"]) if srv_row and srv_row.get("service_name") else f"Xizmat #{p_info[5] if len(p_info) >= 6 else ''}"
        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (cid,)) or {}
        if float(rew.get("balance") or 0) >= float(s_parts[4]):
            if "https://" in tx or "http://" in tx or "@" in text or "t.me/" in tx:
                sms(
                    cid,
                    f"➡️ <b>Ma'lumotlarni o‘qib chiqing:</b>\n\n"
                    f"📦 Buyurtma xizmati: <b>{srv_title}</b>\n"
                    f"💵 Buyurtma narxi: <b>{price_str} so‘m</b>\n"
                    f"📎 Buyurtma manzili: <code>{text}</code>\n"
                    f"{pc}\n\n"
                    f"⚠️ Ma'lumotlar to‘g‘ri bo‘lsa (<b>✅ Yuborish</b>) tugmasini bosing va sizning hisobingizdan "
                    f"<b>{price_str} so‘m</b> miqdorda pul yechib olinadi hamda buyurtma yuboriladi.\n"
                    f"💡 <i>Yoki «💾 Saqlab qo‘yish» tugmasini bosib buyurtmani keyinroq yuborish uchun Balans bo‘limiga saqlab qo‘yishingiz mumkin.</i>",
                    keyboard([
                        [{"text": "✅ Yuborish", "callback_data": f"checkorder={uuid.uuid4().hex}"}],
                        [
                            {"text": "💾 Saqlab qo‘yish", "callback_data": "saveorder"},
                            {"text": "❌ Bekor qilish", "callback_data": "cancelorder"},
                        ],
                    ]),
                )
                put_file(f"user/{cid}.step", f"order={s_parts[1]}=sp3={s_parts[3]}={price_str}={text}")
                put_file(f"user/{cid}.ur", text)
            else:
                sms(cid, "⚠️ Havola noto‘g‘ri yuborilmoqda!\nQaytadan harakat qiling (masalan: https://t.me/... yoki @username):", ORDER_ORT_KB)
        else:
            sms(cid, "❌ Yetarli mablag‘ mavjud emas\n\nHisobingizni to‘ldirib urinib ko‘ring.", ORT_KB)
        return

    if data == "cancelorder" and joinchat(chat_id):
        for ext in ("step", "params", "si", "qu", "ur"):
            unlink_file(f"user/{chat_id}.{ext}")
        del_msg(chat_id, message_id)
        bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "❌ Buyurtma bekor qilindi!"})
        sms(chat_id, "❌ <b>Buyurtma bekor qilindi!</b>\n🖥️ Asosiy menyudasiz.", m_kb)
        return

    sc = stepc.split("=")
    if data == "saveorder" and len(sc) >= 5 and sc[0] == "order" and sc[1] in ("default", "package") and sc[2] == "sp3" and joinchat(chat_id):
        sp = get_file(f"user/{chat_id}.params").split("=")
        si = get_file(f"user/{chat_id}.si").strip() or (sp[0] if len(sp) > 0 else "")
        ur_raw = get_file(f"user/{chat_id}.ur").strip() or (sc[5] if len(sc) > 5 else "")
        qu_raw = get_file(f"user/{chat_id}.qu").strip() or sc[3]
        cost_str = fmt_money(sc[4])
        prov_id = sp[4] if len(sp) > 4 else ""
        serv_id = sp[5] if len(sp) > 5 else ""
        srv_row = database.fetch_one("SELECT `service_name` FROM `services` WHERE `service_id` = ?", (serv_id,)) if serv_id else None
        srv_title = enc("decode", srv_row["service_name"]) if srv_row and srv_row.get("service_name") else f"Xizmat #{serv_id}"
        sav_time = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
        database.execute(
            """INSERT INTO `saved_orders`
            (`user_id`, `service_id`, `service_name`, `provider_id`, `api_service`, `quantity`, `link`, `price`, `order_type`, `created_at`)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (chat_id, serv_id, srv_title, prov_id, si, qu_raw, ur_raw, cost_str, sc[1], sav_time),
        )
        for ext in ("step", "params", "si", "qu", "ur"):
            unlink_file(f"user/{chat_id}.{ext}")
        bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "💾 Buyurtma saqlab qo‘yildi!"})
        edit(
            chat_id,
            message_id,
            f"💾 <b>Buyurtma muvaffaqiyatli saqlab qo‘yildi!</b>\n\n"
            f"📦 Xizmat: <b>{srv_title}</b>\n"
            f"🔢 Miqdor: <b>{qu_raw} ta</b> | 💵 Narx: <b>{cost_str} so‘m</b>\n"
            f"📎 Manzil: <code>{ur_raw}</code>\n\n"
            f"<i>Uni istalgan vaqtda <b>💳 Balans ➡️ 💾 Saqlanganlar</b> bo‘limidan ko‘rishingiz va bir bosishda yuborishingiz mumkin!</i>",
            keyboard([[{"text": "💾 Saqlangan buyurtmalarni ko‘rish", "callback_data": "menu=saved"}]]),
        )
        sms(chat_id, "🖥️ Asosiy menyudasiz", m_kb)
        return

    if data.startswith("checkorder=") and len(sc) >= 5 and sc[0] == "order" and sc[1] in ("default", "package") and sc[2] == "sp3" and joinchat(chat_id):
        rew = database.fetch_one("SELECT * FROM `users` WHERE `id` = ?", (chat_id,)) or {}
        cost = round(float(sc[4]), 4)
        if float(rew.get("balance") or 0) >= cost:
            sp = get_file(f"user/{chat_id}.params").split("=")
            m = database.fetch_one("SELECT * FROM `providers` WHERE `id` = ?", (sp[4],))
            if not m:
                return
            si = get_file(f"user/{chat_id}.si").strip()
            ur = urllib.parse.quote(get_file(f"user/{chat_id}.ur").strip())
            qu = get_file(f"user/{chat_id}.qu").strip() or sc[3]
            raw = http_get(f"{m['api_url']}?key={m['api_key']}&action=add&service={si}&link={ur}&quantity={qu}")
            try:
                j = json.loads(raw)
            except Exception:
                j = {}
            jid = j.get("order")
            if not jid:
                bot("answerCallbackQuery", {"callback_query_id": cqid, "text": "⚠️ Noma'lum xatolik yuz berdi\n\nKeyinroq urinib ko‘ring", "show_alert": True})
                sms(chat_id, "🖥️ Asosiy menyudasiz", MENU_USER_KB)
                for ext in ("step", "params", "si", "qu", "ur"):
                    unlink_file(f"user/{chat_id}.{ext}")
            else:
                or_id = database.count_rows("orders") + 1
                sav = datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S")
                serv_id = sp[5] if len(sp) > 5 else ""
                srv_row = database.fetch_one("SELECT `service_name` FROM `services` WHERE `service_id` = ?", (serv_id,)) if serv_id else None
                srv_title = enc("decode", srv_row["service_name"]) if srv_row and srv_row.get("service_name") else f"Xizmat #{serv_id}"
                database.execute(
                    """INSERT INTO `myorder`
                    (`order_id`, `user_id`, `retail`, `status`, `service`, `order_create`, `last_check`)
                    VALUES (?, ?, ?, 'Pending', ?, ?, ?)""",
                    (or_id, chat_id, fmt_money(cost), serv_id, sav, sav),
                )
                database.execute(
                    """INSERT INTO `orders`
                    (`api_order`, `order_id`, `provider`, `status`)
                    VALUES (?, ?, ?, 'Pending')""",
                    (str(jid), or_id, sp[4]),
                )
                order_tpl = enc("decode", setting.get("orders", ""))
                order_msg = format_order_confirmed_msg(order_tpl, or_id, jid, srv_title, qu, cost)
                sms(chat_id, order_msg, m_kb)
                new_bal = round(float(rew.get("balance") or 0) - cost, 4)
                database.execute("UPDATE `users` SET `balance` = ? WHERE `id` = ?", (fmt_money(new_bal), chat_id))
                for ext in ("step", "params", "si", "qu", "ur"):
                    unlink_file(f"user/{chat_id}.{ext}")
                del_msg(chat_id, message_id)
        return



def run_polling() -> None:
    """Telegram botni TURBO Long-Polling rejimida (tayyor SSL + Worker Pool bilan) ishga tushiradi."""
    start_http_server_background(handle_update)
    if not API_KEY or API_KEY in ("TOKEN", "TOKEN_SHU_YERGA_YOZILADI"):
        print("⚠️ DIQQAT: BOT_TOKEN o'rnatilmagan! ushbu faylning 42-qatoriga BOT_TOKEN ni kiriting.")
        return

    # 1. Tarmoq Keep-Alive havzasi va fon oqimlarini ishga tushiramiz
    start_network_workers()

    # 2. Oldindan 6 ta doimiy ishchi oqim (Worker Pool) tayyorlab qo'yamiz
    for _ in range(8):
        threading.Thread(target=_update_worker_loop, daemon=True).start()

    # 3. Webhookni o'chirib, bot ma'lumotini keshlaymiz
    bot("deleteWebhook")
    me_info = bot("getMe")
    if me_info.get("ok"):
        uname = me_info.get("result", {}).get("username", "")
        print(f"✅ Bot ulandi: @{uname}")
    else:
        print(f"❌ BOT_TOKEN xatoligi: {me_info}")

    # 4. Cron oqimini va saqlangan mijoz botlarini fonda ishga tushiramiz
    restore_all_active_hosted_bots()
    threading.Thread(target=_cron_worker, daemon=True).start()
    print("🚀 Telegram bot MODULLI TURBO rejimda ishga tushdi! (Javob tezligi ~0.08s - 0.15s)")

    offset = 0
    allowed = ["message", "edited_message", "callback_query", "my_chat_member"]
    while True:
        try:
            res = bot("getUpdates", {"offset": offset, "timeout": 20, "allowed_updates": allowed})
            if res.get("ok") and isinstance(res.get("result"), list):
                for upd in res["result"]:
                    offset = upd["update_id"] + 1
                    _UPDATE_QUEUE.put(upd)
            elif not res.get("ok"):
                desc = str(res.get("description", ""))
                if "Conflict" in desc:
                    print("⚠️ DIQQAT: Ushbu bot boshqa terminalda ham ishlab turibdi! Eski terminalni yoping.")
                time.sleep(1)
        except KeyboardInterrupt:
            print("Bot to'xtatildi.")
            break
        except Exception as exc:
            print(f"Polling xatoligi: {exc}")
            time.sleep(1)


if __name__ == "__main__":
    run_polling()
