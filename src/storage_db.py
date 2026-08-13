"""
SQLite persistence for local users and Telegram-backed file metadata.
"""
import hashlib
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from werkzeug.security import generate_password_hash


DB_PATH = os.getenv(
    "TDRIVE_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "tdrive.db"),
)


@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row):
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows):
    return [dict(r) for r in rows]


def utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE,
                password_hash TEXT,
                is_admin INTEGER NOT NULL DEFAULT 0,
                phone TEXT,
                name TEXT,
                created_at TEXT NOT NULL,
                telegram_user_id TEXT UNIQUE,
                telegram_first_name TEXT,
                telegram_last_name TEXT,
                telegram_username TEXT,
                session_path TEXT,
                account_status TEXT NOT NULL DEFAULT 'active',
                connected_at TEXT,
                last_login TEXT
            )
            """
        )
        existing_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "name" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN name TEXT")
        if "username" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
        if "password_reset_token" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN password_reset_token TEXT")
        if "password_reset_expires" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN password_reset_expires TEXT")
        if "telegram_user_id" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN telegram_user_id TEXT")
        if "telegram_first_name" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN telegram_first_name TEXT")
        if "telegram_last_name" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN telegram_last_name TEXT")
        if "telegram_username" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN telegram_username TEXT")
        if "session_path" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN session_path TEXT")
        if "account_status" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN account_status TEXT DEFAULT 'active'")
        if "connected_at" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN connected_at TEXT")
        if "last_login" not in existing_columns:
            conn.execute("ALTER TABLE users ADD COLUMN last_login TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                telegram_message_id INTEGER NOT NULL,
                filename TEXT NOT NULL,
                mime_type TEXT,
                size INTEGER NOT NULL DEFAULT 0,
                uploaded_at TEXT NOT NULL,
                is_favorite INTEGER NOT NULL DEFAULT 0,
                is_deleted INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        file_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(file_records)").fetchall()
        }
        if "is_favorite" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN is_favorite INTEGER NOT NULL DEFAULT 0")
        if "is_deleted" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
        if "deleted_at" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN deleted_at TEXT")
        if "folder_id" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN folder_id INTEGER DEFAULT NULL")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS folders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                parent_id INTEGER DEFAULT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(parent_id) REFERENCES folders(id)
            )
            """
        )
        folder_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(folders)").fetchall()
        }
        if "is_deleted" not in folder_cols:
            conn.execute("ALTER TABLE folders ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0")
        if "deleted_at" not in folder_cols:
            conn.execute("ALTER TABLE folders ADD COLUMN deleted_at TEXT")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS file_shares (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                owner_user_id INTEGER NOT NULL,
                share_token TEXT UNIQUE NOT NULL,
                can_view INTEGER NOT NULL DEFAULT 1,
                can_download INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY(file_id) REFERENCES file_records(id),
                FOREIGN KEY(owner_user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                detail TEXT,
                ip_address TEXT,
                user_agent TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS webdav_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT 'default',
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )

        for stmt in [
            "CREATE INDEX IF NOT EXISTS idx_files_user ON file_records(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_files_user_msg ON file_records(user_id, telegram_message_id)",
            "CREATE INDEX IF NOT EXISTS idx_files_user_deleted ON file_records(user_id, is_deleted)",
            "CREATE INDEX IF NOT EXISTS idx_files_user_fav ON file_records(user_id, is_favorite)",
            "CREATE INDEX IF NOT EXISTS idx_files_folder ON file_records(folder_id)",
            "CREATE INDEX IF NOT EXISTS idx_shares_token ON file_shares(share_token)",
            "CREATE INDEX IF NOT EXISTS idx_shares_file ON file_shares(file_id)",
            "CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_log(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_folders_user ON folders(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_folders_parent ON folders(parent_id)",
            "CREATE INDEX IF NOT EXISTS idx_webdav_tokens_user ON webdav_tokens(user_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username) WHERE username IS NOT NULL",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_telegram_id ON users(telegram_user_id) WHERE telegram_user_id IS NOT NULL",
            "CREATE INDEX IF NOT EXISTS idx_users_phone ON users(phone)",
        ]:
            conn.execute(stmt)


def log_activity(user_id, action, detail=None, ip_address=None, user_agent=None):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO activity_log (user_id, action, detail, ip_address, user_agent, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, action, detail, ip_address, user_agent, utcnow_iso()),
        )


def get_user_count():
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
        return row["count"]


def get_user_by_telegram_id(telegram_user_id):
    if not telegram_user_id:
        return None
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM users WHERE telegram_user_id = ?",
            (str(telegram_user_id),),
        ).fetchone())


def get_user_by_phone(phone):
    if not phone:
        return None
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM users WHERE phone = ?",
            (phone,),
        ).fetchone())


def get_user_by_id(user_id):
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (user_id,),
        ).fetchone())


def create_user(email=None, password=None, phone=None, is_admin=False, name=None, username=None,
                telegram_user_id=None, telegram_first_name=None, telegram_last_name=None,
                telegram_username=None, session_path=None):
    created_at = utcnow_iso()
    password_hash = generate_password_hash(password) if password else None
    # Telegram users don't have email/password. The DB schema may enforce
    # NOT NULL on these columns, so provide placeholders when needed.
    if not email and telegram_user_id:
        email = f"tg_{telegram_user_id}@tdrive.local"
    if not password_hash and telegram_user_id:
        password_hash = "telegram_auth"
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO users (email, password_hash, is_admin, phone, name, created_at, username,
                telegram_user_id, telegram_first_name, telegram_last_name, telegram_username,
                session_path, connected_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (email, password_hash, int(is_admin), phone, name, created_at, username,
             str(telegram_user_id) if telegram_user_id else None,
             telegram_first_name, telegram_last_name, telegram_username,
             session_path, created_at if telegram_user_id else None),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone())


def find_or_create_telegram_user(telegram_user_id, phone, first_name, last_name, username, session_path):
    """Find existing user by Telegram ID or phone, or create a new one."""
    user = get_user_by_telegram_id(telegram_user_id)
    if not user:
        user = get_user_by_phone(phone)
    if user:
        update_user_telegram_info(user["id"], telegram_user_id, phone, first_name, last_name, username, session_path)
        return get_user_by_id(user["id"])
    is_first = get_user_count() == 0
    display_name = f"{first_name} {last_name}".strip() if first_name else None
    return create_user(
        phone=phone,
        is_admin=is_first,
        name=display_name,
        telegram_user_id=telegram_user_id,
        telegram_first_name=first_name,
        telegram_last_name=last_name,
        telegram_username=username,
        session_path=session_path,
    )


def update_user_telegram_info(user_id, telegram_user_id, phone, first_name, last_name, username, session_path):
    with get_connection() as conn:
        conn.execute(
            """UPDATE users SET telegram_user_id = ?, phone = ?,
                telegram_first_name = ?, telegram_last_name = ?, telegram_username = ?,
                session_path = ?, last_login = ?
                WHERE id = ?""",
            (str(telegram_user_id), phone, first_name, last_name, username,
             session_path, utcnow_iso(), user_id),
        )


def update_user_session_path(user_id, session_path):
    with get_connection() as conn:
        conn.execute("UPDATE users SET session_path = ? WHERE id = ?", (session_path, user_id))


def update_user_name(user_id, name):
    with get_connection() as conn:
        conn.execute("UPDATE users SET name = ? WHERE id = ?", (name, user_id))


def list_users():
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT id, email, username, is_admin, phone, name, created_at, telegram_user_id, account_status, connected_at, last_login FROM users ORDER BY created_at ASC"
        ).fetchall())


# ---------------------------------------------------------------------------
# Folder operations
# ---------------------------------------------------------------------------

def create_folder(user_id, name, parent_id=None):
    now = utcnow_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO folders (user_id, name, parent_id, created_at) VALUES (?, ?, ?, ?)",
            (user_id, name, parent_id, now),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM folders WHERE id = ?", (cursor.lastrowid,),
        ).fetchone())


def get_folder(folder_id, user_id):
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM folders WHERE id = ? AND user_id = ? AND is_deleted = 0",
            (folder_id, user_id),
        ).fetchone())


def rename_folder(folder_id, user_id, new_name):
    with get_connection() as conn:
        conn.execute(
            "UPDATE folders SET name = ? WHERE id = ? AND user_id = ? AND is_deleted = 0",
            (new_name, folder_id, user_id),
        )


def soft_delete_folder(folder_id, user_id):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE folders SET is_deleted = 1, deleted_at = ? WHERE id = ? AND user_id = ? AND is_deleted = 0",
            (now, folder_id, user_id),
        )
        conn.execute(
            "UPDATE file_records SET is_deleted = 1, deleted_at = ? WHERE folder_id = ? AND user_id = ? AND is_deleted = 0",
            (now, folder_id, user_id),
        )


def restore_folder(folder_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE folders SET is_deleted = 0, deleted_at = NULL WHERE id = ? AND user_id = ? AND is_deleted = 1",
            (folder_id, user_id),
        )
        conn.execute(
            "UPDATE file_records SET is_deleted = 0, deleted_at = NULL WHERE folder_id = ? AND user_id = ? AND is_deleted = 1",
            (folder_id, user_id),
        )


def permanent_delete_folder(folder_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM file_records WHERE folder_id = ? AND user_id = ? AND is_deleted = 1",
            (folder_id, user_id),
        )
        conn.execute(
            "DELETE FROM folders WHERE id = ? AND user_id = ? AND is_deleted = 1",
            (folder_id, user_id),
        )


def list_user_folders(user_id, parent_id=None):
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT * FROM folders WHERE user_id = ? AND is_deleted = 0 AND parent_id IS ? ORDER BY name",
            (user_id, parent_id),
        ).fetchall())


def count_folder_items(user_id, folder_id):
    with get_connection() as conn:
        files = conn.execute(
            "SELECT COUNT(*) as cnt FROM file_records WHERE user_id = ? AND folder_id = ? AND is_deleted = 0",
            (user_id, folder_id),
        ).fetchone()["cnt"]
        subfolders = conn.execute(
            "SELECT COUNT(*) as cnt FROM folders WHERE user_id = ? AND parent_id = ? AND is_deleted = 0",
            (user_id, folder_id),
        ).fetchone()["cnt"]
        return files + subfolders


def list_trash_folders(user_id):
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT * FROM folders WHERE user_id = ? AND is_deleted = 1 ORDER BY deleted_at DESC",
            (user_id,),
        ).fetchall())


def move_file_to_folder(file_id, user_id, folder_id):
    with get_connection() as conn:
        if folder_id is not None:
            folder = conn.execute(
                "SELECT id FROM folders WHERE id = ? AND user_id = ? AND is_deleted = 0",
                (folder_id, user_id),
            ).fetchone()
            if not folder:
                return False
        conn.execute(
            "UPDATE file_records SET folder_id = ? WHERE id = ? AND user_id = ?",
            (folder_id, file_id, user_id),
        )
        return True


def get_folder_breadcrumb(folder_id, user_id):
    path = []
    current_id = folder_id
    with get_connection() as conn:
        while current_id is not None:
            folder = conn.execute(
                "SELECT id, name, parent_id FROM folders WHERE id = ? AND user_id = ?",
                (current_id, user_id),
            ).fetchone()
            if not folder:
                break
            path.append({"id": folder["id"], "name": folder["name"]})
            current_id = folder["parent_id"]
    path.reverse()
    return path


def create_file_record(user_id, telegram_message_id, filename, mime_type, size):
    uploaded_at = utcnow_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO file_records (user_id, telegram_message_id, filename, mime_type, size, uploaded_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, telegram_message_id, filename, mime_type, size, uploaded_at),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE id = ?", (cursor.lastrowid,),
        ).fetchone())


def update_file_record_name(record_id, user_id, filename):
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_records SET filename = ? WHERE id = ? AND user_id = ? AND is_deleted = 0",
            (filename, record_id, user_id),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE id = ? AND user_id = ?", (record_id, user_id),
        ).fetchone())


def toggle_favorite(record_id, user_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_favorite FROM file_records WHERE id = ? AND user_id = ? AND is_deleted = 0",
            (record_id, user_id),
        ).fetchone()
        if not row:
            return None
        new_val = 0 if row["is_favorite"] else 1
        conn.execute(
            "UPDATE file_records SET is_favorite = ? WHERE id = ? AND user_id = ?",
            (new_val, record_id, user_id),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE id = ? AND user_id = ?", (record_id, user_id),
        ).fetchone())


def soft_delete_file(record_id, user_id):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_records SET is_deleted = 1, deleted_at = ? WHERE id = ? AND user_id = ? AND is_deleted = 0",
            (now, record_id, user_id),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE id = ? AND user_id = ?", (record_id, user_id),
        ).fetchone())


def restore_file(record_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_records SET is_deleted = 0, deleted_at = NULL WHERE id = ? AND user_id = ? AND is_deleted = 1",
            (record_id, user_id),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE id = ? AND user_id = ?", (record_id, user_id),
        ).fetchone())


def permanent_delete_file(record_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM file_records WHERE id = ? AND user_id = ? AND is_deleted = 1",
            (record_id, user_id),
        )


def purge_expired_trash():
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM file_records WHERE is_deleted = 1 AND deleted_at IS NOT NULL AND deleted_at < strftime('%Y-%m-%dT%H:%M:%S', 'now', '-30 days')"
        )


def list_user_files(user_id, include_deleted=False):
    with get_connection() as conn:
        where = "WHERE user_id = ?" if include_deleted else "WHERE user_id = ? AND is_deleted = 0"
        return rows_to_dicts(conn.execute(
            f"SELECT * FROM file_records {where} ORDER BY uploaded_at DESC",
            (user_id,),
        ).fetchall())


def list_user_favorites(user_id):
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT * FROM file_records WHERE user_id = ? AND is_deleted = 0 AND is_favorite = 1 ORDER BY uploaded_at DESC",
            (user_id,),
        ).fetchall())


def list_trash_files(user_id):
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT * FROM file_records WHERE user_id = ? AND is_deleted = 1 ORDER BY deleted_at DESC",
            (user_id,),
        ).fetchall())


def get_file_record(record_id):
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE id = ?", (record_id,),
        ).fetchone())


def get_user_file_record(record_id, user_id):
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE id = ? AND user_id = ?",
            (record_id, user_id),
        ).fetchone())


def get_user_file_by_message_id(user_id, telegram_message_id):
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE user_id = ? AND telegram_message_id = ?",
            (user_id, telegram_message_id),
        ).fetchone())


def create_share(file_id, owner_user_id, can_view=1, can_download=0, expires_at=None):
    token = secrets.token_urlsafe(32)
    now = utcnow_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            "INSERT INTO file_shares (file_id, owner_user_id, share_token, can_view, can_download, expires_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, owner_user_id, token, int(can_view), int(can_download), expires_at, now),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM file_shares WHERE id = ?", (cursor.lastrowid,),
        ).fetchone())


def get_share_by_token(token):
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM file_shares WHERE share_token = ? AND is_active = 1",
            (token,),
        ).fetchone())


def revoke_share(share_id, owner_user_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_shares SET is_active = 0 WHERE id = ? AND owner_user_id = ?",
            (share_id, owner_user_id),
        )


def list_user_shares(user_id):
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            """
            SELECT s.*, f.filename, f.mime_type, f.size
            FROM file_shares s JOIN file_records f ON s.file_id = f.id
            WHERE s.owner_user_id = ? AND s.is_active = 1
            ORDER BY s.created_at DESC
            """,
            (user_id,),
        ).fetchall())


def get_file_stats(user_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as total, COALESCE(SUM(size), 0) as total_size FROM file_records WHERE user_id = ? AND is_deleted = 0",
            (user_id,),
        ).fetchone()
        cats = rows_to_dicts(conn.execute(
            """
            SELECT
                CASE
                    WHEN mime_type LIKE 'image/%' THEN 'images'
                    WHEN mime_type LIKE 'video/%' THEN 'videos'
                    WHEN mime_type LIKE 'audio/%' THEN 'audio'
                    ELSE 'documents'
                END as category,
                COUNT(*) as count
            FROM file_records WHERE user_id = ? AND is_deleted = 0
            GROUP BY category
            """,
            (user_id,),
        ).fetchall())
        cat_map = {c["category"]: c["count"] for c in cats}
        return {
            "total_files": row["total"],
            "total_size": row["total_size"],
            "images": cat_map.get("images", 0),
            "videos": cat_map.get("videos", 0),
            "audio": cat_map.get("audio", 0),
            "documents": cat_map.get("documents", 0),
        }


def delete_user_account(user_id):
    with get_connection() as conn:
        conn.execute("UPDATE file_shares SET is_active = 0 WHERE owner_user_id = ?", (user_id,))
        conn.execute("DELETE FROM activity_log WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM file_records WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM webdav_tokens WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def revoke_all_user_shares(user_id):
    with get_connection() as conn:
        conn.execute("UPDATE file_shares SET is_active = 0 WHERE owner_user_id = ?", (user_id,))


def count_user_active_shares(user_id):
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM file_shares WHERE owner_user_id = ? AND is_active = 1",
            (user_id,),
        ).fetchone()
        return row["cnt"]


# ---------------------------------------------------------------------------
# WebDAV token operations
# ---------------------------------------------------------------------------

def _hash_webdav_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_webdav_token(user_id, label="default"):
    token = secrets.token_urlsafe(32)
    token_hash = _hash_webdav_token(token)
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO webdav_tokens (user_id, token_hash, label, created_at) VALUES (?, ?, ?, ?)",
            (user_id, token_hash, label, now),
        )
    return token


def verify_webdav_token(token):
    token_hash = _hash_webdav_token(token)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM webdav_tokens WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if not row:
            return None
        user = get_user_by_id(row["user_id"])
        if not user or user.get("account_status") != "active":
            return None
        conn.execute(
            "UPDATE webdav_tokens SET last_used_at = ? WHERE id = ?",
            (utcnow_iso(), row["id"]),
        )
        return user


def list_webdav_tokens(user_id):
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT id, label, created_at, last_used_at FROM webdav_tokens WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        ).fetchall())


def revoke_webdav_token(token_id, user_id):
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM webdav_tokens WHERE id = ? AND user_id = ?",
            (token_id, user_id),
        )


def revoke_all_webdav_tokens(user_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM webdav_tokens WHERE user_id = ?", (user_id,))
