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
                folder_id INTEGER DEFAULT NULL,
                is_vaulted INTEGER NOT NULL DEFAULT 0,
                -- Encryption metadata
                enc_version TINYINT DEFAULT 0,
                dek_wrap_nonce BLOB,
                dek_wrap_cipher BLOB,
                dek_wrap_tag BLOB,
                file_enc_nonce BLOB,
                file_enc_tag BLOB,
                enc_flag INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        # Add columns if they don't exist (for backwards compatibility)
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
        if "is_vaulted" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN is_vaulted INTEGER NOT NULL DEFAULT 0")
        if "enc_version" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN enc_version TINYINT DEFAULT 0")
        if "dek_wrap_nonce" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN dek_wrap_nonce BLOB")
        if "dek_wrap_cipher" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN dek_wrap_cipher BLOB")
        if "dek_wrap_tag" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN dek_wrap_tag BLOB")
        if "file_enc_nonce" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN file_enc_nonce BLOB")
        if "file_enc_tag" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN file_enc_tag BLOB")
        if "enc_flag" not in file_cols:
            conn.execute("ALTER TABLE file_records ADD COLUMN enc_flag INTEGER NOT NULL DEFAULT 0")

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
        if "is_vaulted" not in folder_cols:
            conn.execute("ALTER TABLE folders ADD COLUMN is_vaulted INTEGER NOT NULL DEFAULT 0")

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
                password_hash TEXT,
                one_time INTEGER NOT NULL DEFAULT 0,
                download_limit INTEGER,
                download_count INTEGER NOT NULL DEFAULT 0,
                last_accessed_at TEXT,
                revoked_at TEXT,
                UNIQUE(share_token)
            )
            """
        )
        share_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(file_shares)").fetchall()
        }
        if "password_hash" not in share_cols:
            conn.execute("ALTER TABLE file_shares ADD COLUMN password_hash TEXT")
        if "one_time" not in share_cols:
            conn.execute("ALTER TABLE file_shares ADD COLUMN one_time INTEGER NOT NULL DEFAULT 0")
        if "download_limit" not in share_cols:
            conn.execute("ALTER TABLE file_shares ADD COLUMN download_limit INTEGER")
        if "download_count" not in share_cols:
            conn.execute("ALTER TABLE file_shares ADD COLUMN download_count INTEGER NOT NULL DEFAULT 0")
        if "last_accessed_at" not in share_cols:
            conn.execute("ALTER TABLE file_shares ADD COLUMN last_accessed_at TEXT")
        if "revoked_at" not in share_cols:
            conn.execute("ALTER TABLE file_shares ADD COLUMN revoked_at TEXT")
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

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS vault_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                pin_hash TEXT NOT NULL,
                vault_enabled INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                -- Encryption metadata
                enc_version TINYINT DEFAULT 1,
                kdf_algo VARCHAR(16) DEFAULT 'argon2id',
                kdf_salt BLOB,
                kdf_mem SMALLINT DEFAULT 64,
                kdf_iter SMALLINT DEFAULT 3,
                kdf_parallel SMALLINT DEFAULT 4,
                vmk_wrap_nonce BLOB,
                vmk_wrap_cipher BLOB,
                vmk_wrap_tag BLOB,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )
            """
        )
        # Add encryption columns if they don't exist (for backwards compatibility)
        vault_settings_cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(vault_settings)").fetchall()
        }
        if "enc_version" not in vault_settings_cols:
            conn.execute("ALTER TABLE vault_settings ADD COLUMN enc_version TINYINT DEFAULT 1")
        if "kdf_algo" not in vault_settings_cols:
            conn.execute("ALTER TABLE vault_settings ADD COLUMN kdf_algo VARCHAR(16) DEFAULT 'argon2id'")
        if "kdf_salt" not in vault_settings_cols:
            conn.execute("ALTER TABLE vault_settings ADD COLUMN kdf_salt BLOB")
        if "kdf_mem" not in vault_settings_cols:
            conn.execute("ALTER TABLE vault_settings ADD COLUMN kdf_mem SMALLINT DEFAULT 64")
        if "kdf_iter" not in vault_settings_cols:
            conn.execute("ALTER TABLE vault_settings ADD COLUMN kdf_iter SMALLINT DEFAULT 3")
        if "kdf_parallel" not in vault_settings_cols:
            conn.execute("ALTER TABLE vault_settings ADD COLUMN kdf_parallel SMALLINT DEFAULT 4")
        if "vmk_wrap_nonce" not in vault_settings_cols:
            conn.execute("ALTER TABLE vault_settings ADD COLUMN vmk_wrap_nonce BLOB")
        if "vmk_wrap_cipher" not in vault_settings_cols:
            conn.execute("ALTER TABLE vault_settings ADD COLUMN vmk_wrap_cipher BLOB")
        if "vmk_wrap_tag" not in vault_settings_cols:
            conn.execute("ALTER TABLE vault_settings ADD COLUMN vmk_wrap_tag BLOB")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS activity_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                resource_type TEXT,
                resource_id INTEGER,
                metadata TEXT,
                created_at TEXT NOT NULL,
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
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_settings_user ON vault_settings(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_activity_events_user ON activity_events(user_id)",
            "CREATE INDEX IF NOT EXISTS idx_activity_events_type ON activity_events(event_type)",
            "CREATE INDEX IF NOT EXISTS idx_activity_events_created ON activity_events(created_at)",
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


def create_share(file_id, owner_user_id, can_view=1, can_download=0, expires_at=None,
                 password_hash=None, one_time=0, download_limit=None):
    token = secrets.token_urlsafe(32)
    now = utcnow_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            """INSERT INTO file_shares
               (file_id, owner_user_id, share_token, can_view, can_download, expires_at,
                created_at, password_hash, one_time, download_limit)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_id, owner_user_id, token, int(can_view), int(can_download), expires_at,
             now, password_hash, int(one_time), download_limit),
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
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_shares SET is_active = 0, revoked_at = ? WHERE id = ? AND owner_user_id = ?",
            (now, share_id, owner_user_id),
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


def get_file_stats(user_id, exclude_vaulted=False):
    vault_filter = " AND is_vaulted = 0" if exclude_vaulted else ""
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) as total, COALESCE(SUM(size), 0) as total_size FROM file_records WHERE user_id = ? AND is_deleted = 0{vault_filter}",
            (user_id,),
        ).fetchone()
        cats = rows_to_dicts(conn.execute(
            f"""
            SELECT
                CASE
                    WHEN mime_type LIKE 'image/%' THEN 'images'
                    WHEN mime_type LIKE 'video/%' THEN 'videos'
                    WHEN mime_type LIKE 'audio/%' THEN 'audio'
                    ELSE 'documents'
                END as category,
                COUNT(*) as count
            FROM file_records WHERE user_id = ? AND is_deleted = 0{vault_filter}
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


def get_share_by_id(share_id, owner_user_id):
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM file_shares WHERE id = ? AND owner_user_id = ?",
            (share_id, owner_user_id),
        ).fetchone())


def increment_share_download_count(share_id):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_shares SET download_count = download_count + 1, last_accessed_at = ? WHERE id = ?",
            (now, share_id),
        )


def update_share_last_accessed(share_id):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_shares SET last_accessed_at = ? WHERE id = ?",
            (now, share_id),
        )


def invalidate_one_time_share(share_id):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_shares SET is_active = 0, revoked_at = ? WHERE id = ?",
            (now, share_id),
        )


def get_active_share_by_token(token):
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM file_shares WHERE share_token = ? AND is_active = 1",
            (token,),
        ).fetchone())


def revoke_all_shares_for_file(file_id, owner_user_id):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_shares SET is_active = 0, revoked_at = ? WHERE file_id = ? AND owner_user_id = ? AND is_active = 1",
            (now, file_id, owner_user_id),
        )


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


# ---------------------------------------------------------------------------
# Vault settings
# ---------------------------------------------------------------------------

def get_vault_settings(user_id):
    with get_connection() as conn:
        return row_to_dict(conn.execute(
            "SELECT * FROM vault_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone())


def create_vault_settings(user_id, pin_hash):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO vault_settings
               (user_id, pin_hash, vault_enabled, failed_attempts, created_at, updated_at)
               VALUES (?, ?, 1, 0, ?, ?)""",
            (user_id, pin_hash, now, now),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM vault_settings WHERE user_id = ?", (user_id,),
        ).fetchone())


def update_vault_pin(user_id, pin_hash):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE vault_settings SET pin_hash = ?, failed_attempts = 0, locked_until = NULL, updated_at = ? WHERE user_id = ?",
            (pin_hash, now, user_id),
        )


def increment_vault_failed_attempts(user_id):
    now = utcnow_iso()
    with get_connection() as conn:
        settings = conn.execute(
            "SELECT failed_attempts FROM vault_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not settings:
            return 0
        new_count = settings["failed_attempts"] + 1
        locked_until = None
        if new_count >= 5:
            progressive_seconds = min(300, 30 * (2 ** (new_count - 5)))
            from datetime import datetime as _dt, timezone as _tz
            lock_time = _dt.now(_tz.utc).isoformat()
            locked_until = lock_time
        conn.execute(
            "UPDATE vault_settings SET failed_attempts = ?, locked_until = COALESCE(?, locked_until), updated_at = ? WHERE user_id = ?",
            (new_count, locked_until, now, user_id),
        )
        return new_count


def reset_vault_failed_attempts(user_id):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE vault_settings SET failed_attempts = 0, locked_until = NULL, updated_at = ? WHERE user_id = ?",
            (now, user_id),
        )


def set_vault_locked_until(user_id, locked_until):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE vault_settings SET locked_until = ?, updated_at = ? WHERE user_id = ?",
            (locked_until, now, user_id),
        )


def disable_vault(user_id):
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE vault_settings SET vault_enabled = 0, updated_at = ? WHERE user_id = ?",
            (now, user_id),
        )


def update_vault_encryption(user_id, enc_version=None, kdf_algo=None, kdf_salt=None,
                            kdf_mem=None, kdf_iter=None, kdf_parallel=None,
                            vmk_wrap_nonce=None, vmk_wrap_cipher=None, vmk_wrap_tag=None):
    """Update the encryption metadata in vault_settings."""
    with get_connection() as conn:
        fields = []
        values = []
        if enc_version is not None:
            fields.append("enc_version = ?")
            values.append(enc_version)
        if kdf_algo is not None:
            fields.append("kdf_algo = ?")
            values.append(kdf_algo)
        if kdf_salt is not None:
            fields.append("kdf_salt = ?")
            values.append(kdf_salt)
        if kdf_mem is not None:
            fields.append("kdf_mem = ?")
            values.append(kdf_mem)
        if kdf_iter is not None:
            fields.append("kdf_iter = ?")
            values.append(kdf_iter)
        if kdf_parallel is not None:
            fields.append("kdf_parallel = ?")
            values.append(kdf_parallel)
        if vmk_wrap_nonce is not None:
            fields.append("vmk_wrap_nonce = ?")
            values.append(vmk_wrap_nonce)
        if vmk_wrap_cipher is not None:
            fields.append("vmk_wrap_cipher = ?")
            values.append(vmk_wrap_cipher)
        if vmk_wrap_tag is not None:
            fields.append("vmk_wrap_tag = ?")
            values.append(vmk_wrap_tag)
        if not fields:
            return
        values.append(utcnow_iso())  # updated_at
        values.append(user_id)
        stmt = f"UPDATE vault_settings SET {', '.join(fields)}, updated_at = ? WHERE user_id = ?"
        conn.execute(stmt, values)


def update_file_encryption(file_id, user_id, enc_version=None,
                           dek_wrap_nonce=None, dek_wrap_cipher=None, dek_wrap_tag=None,
                           file_enc_nonce=None, file_enc_tag=None, enc_flag=None):
    """Update the encryption metadata for a file record."""
    with get_connection() as conn:
        fields = []
        values = []
        if enc_version is not None:
            fields.append("enc_version = ?")
            values.append(enc_version)
        if dek_wrap_nonce is not None:
            fields.append("dek_wrap_nonce = ?")
            values.append(dek_wrap_nonce)
        if dek_wrap_cipher is not None:
            fields.append("dek_wrap_cipher = ?")
            values.append(dek_wrap_cipher)
        if dek_wrap_tag is not None:
            fields.append("dek_wrap_tag = ?")
            values.append(dek_wrap_tag)
        if file_enc_nonce is not None:
            fields.append("file_enc_nonce = ?")
            values.append(file_enc_nonce)
        if file_enc_tag is not None:
            fields.append("file_enc_tag = ?")
            values.append(file_enc_tag)
        if enc_flag is not None:
            fields.append("enc_flag = ?")
            values.append(enc_flag)
        if not fields:
            return
        values.append(file_id)
        values.append(user_id)
        stmt = f"UPDATE file_records SET {', '.join(fields)} WHERE id = ? AND user_id = ?"
        conn.execute(stmt, values)


# ---------------------------------------------------------------------------
# Vault file/folder operations
# ---------------------------------------------------------------------------

def vault_file(record_id, user_id):
    """Move a file into the Vault. Sets is_vaulted=1."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE file_records SET is_vaulted = 1 WHERE id = ? AND user_id = ? AND is_deleted = 0",
            (record_id, user_id),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE id = ? AND user_id = ?", (record_id, user_id),
        ).fetchone())


def unvault_file(record_id, user_id):
    """Restore a file from Vault. Sets is_vaulted=0, restores to parent or root."""
    with get_connection() as conn:
        file_row = conn.execute(
            "SELECT folder_id FROM file_records WHERE id = ? AND user_id = ? AND is_deleted = 0",
            (record_id, user_id),
        ).fetchone()
        if not file_row:
            return None
        # If parent folder is vaulted, restore to root
        parent_id = file_row["folder_id"]
        if parent_id is not None:
            folder_row = conn.execute(
                "SELECT is_vaulted FROM folders WHERE id = ? AND user_id = ?",
                (parent_id, user_id),
            ).fetchone()
            if folder_row and folder_row["is_vaulted"]:
                parent_id = None  # restore to root
        conn.execute(
            "UPDATE file_records SET is_vaulted = 0, folder_id = ? WHERE id = ? AND user_id = ?",
            (parent_id, record_id, user_id),
        )
        return row_to_dict(conn.execute(
            "SELECT * FROM file_records WHERE id = ? AND user_id = ?", (record_id, user_id),
        ).fetchone())


def vault_folder(folder_id, user_id):
    """Move a folder and all descendants into the Vault."""
    with get_connection() as conn:
        # Collect all descendant folder IDs (BFS)
        to_vault = [folder_id]
        queue = [folder_id]
        while queue:
            current = queue.pop(0)
            children = conn.execute(
                "SELECT id FROM folders WHERE parent_id = ? AND user_id = ? AND is_deleted = 0",
                (current, user_id),
            ).fetchall()
            for child in children:
                to_vault.append(child["id"])
                queue.append(child["id"])
        # Vault all folders
        placeholders = ",".join("?" * len(to_vault))
        conn.execute(
            f"UPDATE folders SET is_vaulted = 1 WHERE id IN ({placeholders}) AND user_id = ?",
            (*to_vault, user_id),
        )
        # Vault all files in all these folders
        conn.execute(
            f"UPDATE file_records SET is_vaulted = 1 WHERE folder_id IN ({placeholders}) AND user_id = ? AND is_deleted = 0",
            (*to_vault, user_id),
        )
        return to_vault


def unvault_folder(folder_id, user_id):
    """Restore a folder and all descendants from Vault."""
    with get_connection() as conn:
        # Collect all descendant folder IDs (BFS)
        to_unvault = [folder_id]
        queue = [folder_id]
        while queue:
            current = queue.pop(0)
            children = conn.execute(
                "SELECT id FROM folders WHERE parent_id = ? AND user_id = ? AND is_deleted = 0",
                (current, user_id),
            ).fetchall()
            for child in children:
                to_unvault.append(child["id"])
                queue.append(child["id"])
        # Unvault all folders
        placeholders = ",".join("?" * len(to_unvault))
        conn.execute(
            f"UPDATE folders SET is_vaulted = 0 WHERE id IN ({placeholders}) AND user_id = ?",
            (*to_unvault, user_id),
        )
        # Unvault all files in all these folders
        conn.execute(
            f"UPDATE file_records SET is_vaulted = 0 WHERE folder_id IN ({placeholders}) AND user_id = ? AND is_deleted = 0",
            (*to_unvault, user_id),
        )
        return to_unvault


def list_vaulted_files(user_id):
    """List all vaulted (non-deleted) files for a user."""
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT * FROM file_records WHERE user_id = ? AND is_deleted = 0 AND is_vaulted = 1 ORDER BY uploaded_at DESC",
            (user_id,),
        ).fetchall())


def list_vaulted_root_files(user_id):
    """List vaulted files at root level (not in any folder)."""
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT * FROM file_records WHERE user_id = ? AND is_deleted = 0 AND is_vaulted = 1 AND folder_id IS NULL ORDER BY uploaded_at DESC",
            (user_id,),
        ).fetchall())


def list_vaulted_folders(user_id, parent_id=None):
    """List vaulted folders at a given parent level."""
    with get_connection() as conn:
        return rows_to_dicts(conn.execute(
            "SELECT * FROM folders WHERE user_id = ? AND is_deleted = 0 AND is_vaulted = 1 AND parent_id IS ? ORDER BY name",
            (user_id, parent_id),
        ).fetchall())


def is_file_vaulted(record_id, user_id):
    """Check if a file is vaulted."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT is_vaulted FROM file_records WHERE id = ? AND user_id = ? AND is_deleted = 0",
            (record_id, user_id),
        ).fetchone()
        return bool(row and row["is_vaulted"])


def is_folder_vaulted(folder_id, user_id):
    """Check if a folder is vaulted (or has a vaulted ancestor)."""
    with get_connection() as conn:
        current_id = folder_id
        while current_id is not None:
            row = conn.execute(
                "SELECT is_vaulted, parent_id FROM folders WHERE id = ? AND user_id = ?",
                (current_id, user_id),
            ).fetchone()
            if not row:
                return False
            if row["is_vaulted"]:
                return True
            current_id = row["parent_id"]
        return False


def get_vault_stats(user_id):
    """Get vault file/folder counts."""
    with get_connection() as conn:
        file_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM file_records WHERE user_id = ? AND is_deleted = 0 AND is_vaulted = 1",
            (user_id,),
        ).fetchone()["cnt"]
        folder_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM folders WHERE user_id = ? AND is_deleted = 0 AND is_vaulted = 1",
            (user_id,),
        ).fetchone()["cnt"]
        return {"files": file_count, "folders": folder_count}


# ---------------------------------------------------------------------------
# Storage Intelligence (Phase 6A)
# ---------------------------------------------------------------------------

_MIME_CATEGORIES = {
    "images": ("image/%",),
    "videos": ("video/%",),
    "audio": ("audio/%",),
    "documents": (
        "application/pdf", "application/msword",
        "application/vnd.openxmlformats-officedocument%",
        "application/vnd.ms-%", "text/%",
        "application/json", "application/xml",
    ),
    "archives": (
        "application/zip", "application/x-rar%", "application/x-7z%",
        "application/x-tar", "application/gzip",
    ),
}


def _mime_like_clause(column, patterns):
    """Build SQL OR LIKE clause for MIME type matching."""
    parts = []
    for p in patterns:
        parts.append(f"{column} LIKE ?")
    return " OR ".join(parts), list(patterns)


def get_storage_intelligence(user_id, vault_unlocked=False):
    """Return comprehensive storage statistics for a single user.

    Excludes deleted files. Excludes vaulted files unless vault_unlocked.
    """
    vault_filter = "" if vault_unlocked else " AND is_vaulted = 0"
    with get_connection() as conn:
        # Basic totals
        totals = conn.execute(
            f"SELECT COUNT(*) as cnt, COALESCE(SUM(size), 0) as total_size FROM file_records WHERE user_id = ? AND is_deleted = 0{vault_filter}",
            (user_id,),
        ).fetchone()
        file_count = totals["cnt"]
        total_size = totals["total_size"]

        # Folder count (vault filter applied)
        folder_count = conn.execute(
            f"SELECT COUNT(*) as cnt FROM folders WHERE user_id = ? AND is_deleted = 0{vault_filter}",
            (user_id,),
        ).fetchone()["cnt"]

        # Average file size
        avg_size = total_size // file_count if file_count else 0

        # File type breakdown (count + bytes per category)
        type_breakdown = {}
        for cat, patterns in _MIME_CATEGORIES.items():
            where_clause, params = _mime_like_clause("mime_type", patterns)
            row = conn.execute(
                f"SELECT COUNT(*) as cnt, COALESCE(SUM(size), 0) as total_bytes FROM file_records WHERE user_id = ? AND is_deleted = 0{vault_filter} AND ({where_clause})",
                [user_id] + params,
            ).fetchone()
            type_breakdown[cat] = {"count": row["cnt"], "bytes": row["total_bytes"]}

        # "other" = files not matching any category
        all_cat_patterns = []
        for patterns in _MIME_CATEGORIES.values():
            all_cat_patterns.extend(patterns)
        other_where, other_params = _mime_like_clause("mime_type", all_cat_patterns)
        other_row = conn.execute(
            f"SELECT COUNT(*) as cnt, COALESCE(SUM(size), 0) as total_bytes FROM file_records WHERE user_id = ? AND is_deleted = 0{vault_filter} AND (mime_type IS NULL OR NOT ({other_where}))",
            [user_id] + other_params,
        ).fetchone()
        type_breakdown["other"] = {"count": other_row["cnt"], "bytes": other_row["total_bytes"]}

        # Percentages
        for cat in type_breakdown:
            if total_size > 0:
                type_breakdown[cat]["percentage"] = round(type_breakdown[cat]["bytes"] / total_size * 100, 1)
            else:
                type_breakdown[cat]["percentage"] = 0.0

        # Largest files (top 10) — safe fields only
        largest_files = rows_to_dicts(conn.execute(
            f"SELECT id, filename, size, mime_type, uploaded_at, folder_id FROM file_records WHERE user_id = ? AND is_deleted = 0{vault_filter} ORDER BY size DESC LIMIT 10",
            (user_id,),
        ).fetchall())

        # Recent files (top 10) — safe fields only
        recent_files = rows_to_dicts(conn.execute(
            f"SELECT id, filename, size, mime_type, uploaded_at, folder_id FROM file_records WHERE user_id = ? AND is_deleted = 0{vault_filter} ORDER BY uploaded_at DESC LIMIT 10",
            (user_id,),
        ).fetchall())

        # Vault stats
        vault = {"visible": vault_unlocked}
        if vault_unlocked:
            v_files = conn.execute(
                "SELECT COUNT(*) as cnt, COALESCE(SUM(size), 0) as total_bytes FROM file_records WHERE user_id = ? AND is_deleted = 0 AND is_vaulted = 1",
                (user_id,),
            ).fetchone()
            v_folders = conn.execute(
                "SELECT COUNT(*) as cnt FROM folders WHERE user_id = ? AND is_deleted = 0 AND is_vaulted = 1",
                (user_id,),
            ).fetchone()
            vault["bytes"] = v_files["total_bytes"]
            vault["files"] = v_files["cnt"]
            vault["folders"] = v_folders["cnt"]

        return {
            "total_size": total_size,
            "file_count": file_count,
            "folder_count": folder_count,
            "average_file_size": avg_size,
            "type_breakdown": type_breakdown,
            "largest_files": largest_files,
            "recent_files": recent_files,
            "vault": vault,
        }


# ---------------------------------------------------------------------------
# Activity Events (Phase 5A)
# ---------------------------------------------------------------------------

_VALID_EVENT_TYPES = frozenset({
    "FILE_UPLOADED",
    "FILE_DOWNLOADED",
    "FILE_PREVIEWED",
    "FILE_RENAMED",
    "FILE_FAVORITED",
    "FILE_UNFAVORITED",
    "FILE_MOVED",
    "FILE_DELETED",
    "FILE_RESTORED",
    "FILE_PERMANENTLY_DELETED",
    "FOLDER_CREATED",
    "FOLDER_RENAMED",
    "FOLDER_MOVED",
    "FOLDER_DELETED",
    "FOLDER_RESTORED",
    "FOLDER_PERMANENTLY_DELETED",
    "VAULT_UNLOCKED",
    "VAULT_LOCKED",
    "FILE_MOVED_TO_VAULT",
    "FILE_RESTORED_FROM_VAULT",
    "FOLDER_MOVED_TO_VAULT",
    "FOLDER_RESTORED_FROM_VAULT",
    "SHARE_CREATED",
    "SHARE_ACCESSED",
    "SHARE_REVOKED",
    "WEBDAV_UPLOAD",
    "WEBDAV_DOWNLOAD",
    "WEBDAV_MOVE",
    "WEBDAV_DELETE",
    "WEBDAV_FOLDER_CREATED",
})

_SENSITIVE_KEYS = frozenset({
    "password", "password_hash", "pin", "pin_hash", "token",
    "token_hash", "secret", "api_key", "api_hash", "otp",
    "code", "session", "session_path", "auth_state",
    "share_token", "share_password", "share_password_hash",
})


def _sanitize_metadata(metadata):
    """Remove sensitive keys from metadata dict. Returns JSON string or None."""
    if not metadata or not isinstance(metadata, dict):
        return None
    safe = {}
    for k, v in metadata.items():
        kl = k.lower().replace("-", "_").replace(" ", "_")
        if any(s in kl for s in _SENSITIVE_KEYS):
            continue
        if isinstance(v, (str, int, float, bool)):
            safe[k] = v
        elif v is None:
            safe[k] = None
    if not safe:
        return None
    import json as _json
    try:
        return _json.dumps(safe, ensure_ascii=False)
    except (TypeError, ValueError):
        return None


def record_activity(user_id, event_type, resource_type=None, resource_id=None, metadata=None):
    """Record an activity event. Best-effort — never raises."""
    if event_type not in _VALID_EVENT_TYPES:
        return
    try:
        now = utcnow_iso()
        meta_json = _sanitize_metadata(metadata)
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO activity_events
                   (user_id, event_type, resource_type, resource_id, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, event_type, resource_type, resource_id, meta_json, now),
            )
    except Exception:
        pass


def get_user_activity(user_id, limit=50, offset=0, event_type=None, resource_type=None):
    """Retrieve activity events for a user. Returns list of dicts."""
    limit = min(max(int(limit), 0), 100)
    offset = max(int(offset), 0)
    with get_connection() as conn:
        query = "SELECT * FROM activity_events WHERE user_id = ?"
        params = [user_id]
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if resource_type:
            query += " AND resource_type = ?"
            params.append(resource_type)
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()
        return rows_to_dicts(rows)
