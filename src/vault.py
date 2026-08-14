"""
Smart Vault — security foundation for SkySync.

Provides server-side PIN management, unlock/lock state, rate limiting,
and auto-lock on inactivity.  Vault state is stored exclusively in the
server-side Flask session; the client never controls unlock state.

Endpoints
---------
POST /api/vault/pin          — set PIN (first time)
POST /api/vault/pin/change   — change PIN (requires current PIN)
POST /api/vault/unlock       — unlock with PIN
POST /api/vault/lock         — lock immediately
GET  /api/vault/status       — safe status info
POST /api/vault/move         — move file/folder to Vault
POST /api/vault/restore      — restore file/folder from Vault
GET  /api/vault/files        — list vaulted files (unlocked only)
GET  /api/vault/folders      — list vaulted folders (unlocked only)
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from storage_db import (
    create_vault_settings,
    get_vault_settings,
    increment_vault_failed_attempts,
    reset_vault_failed_attempts,
    update_vault_pin,
    utcnow_iso,
)

logger = logging.getLogger(__name__)

vault_bp = Blueprint("vault", __name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PIN_MIN_LENGTH = 6
PIN_MAX_LENGTH = 128
VAULT_INACTIVITY_SECONDS = 300  # 5 minutes — configurable via env

# ---------------------------------------------------------------------------
# Server-side vault session helpers
# ---------------------------------------------------------------------------

_VAULT_UNLOCKED_KEY = "vault_unlocked"
_VAULT_ACTIVITY_KEY = "vault_last_activity"


def vault_unlock(user_id):
    """Mark the Vault as unlocked for the current session."""
    session[_VAULT_UNLOCKED_KEY] = True
    session[_VAULT_ACTIVITY_KEY] = utcnow_iso()
    session.permanent = True


def vault_lock():
    """Immediately lock the Vault for the current session."""
    session.pop(_VAULT_UNLOCKED_KEY, None)
    session.pop(_VAULT_ACTIVITY_KEY, None)


def vault_is_unlocked(user_id):
    """Check whether the Vault is currently unlocked AND not expired."""
    if not session.get(_VAULT_UNLOCKED_KEY):
        return False
    last_activity = session.get(_VAULT_ACTIVITY_KEY)
    if not last_activity:
        return False
    try:
        last_dt = datetime.fromisoformat(last_activity)
        now = datetime.now(timezone.utc)
        if now - last_dt > timedelta(seconds=VAULT_INACTIVITY_SECONDS):
            vault_lock()
            return False
    except (ValueError, TypeError):
        vault_lock()
        return False
    # Refresh activity timestamp on successful check
    session[_VAULT_ACTIVITY_KEY] = utcnow_iso()
    return True


# ---------------------------------------------------------------------------
# Authorization helpers (reusable across future vault endpoints)
# ---------------------------------------------------------------------------

def require_authenticated_user():
    """Return the authenticated user dict or None.

    Checks Flask session for a valid ``app_user_id`` and looks up the
    corresponding user row.
    """
    from storage_db import get_user_by_id
    user_id = session.get("app_user_id")
    if not user_id:
        return None
    return get_user_by_id(user_id)


def require_vault_unlocked():
    """Enforce full vault authorization.

    Returns ``(user, error_response)`` — ``user`` is the authenticated
    user dict on success; ``error_response`` is a ``(body, status)`` tuple
    on failure.

    Checks in order:
    1. SkySync login
    2. Vault is configured
    3. Vault is currently unlocked
    4. Inactivity timeout has not expired
    5. Refreshes activity timestamp
    """
    user = require_authenticated_user()
    if not user:
        return None, (jsonify({"success": False, "error": "Authentication required"}), 401)

    settings = get_vault_settings(user["id"])
    if not settings:
        return None, (jsonify({"success": False, "error": "Vault is not configured"}), 403)

    if not settings["vault_enabled"]:
        return None, (jsonify({"success": False, "error": "Vault is disabled"}), 403)

    if not vault_is_unlocked(user["id"]):
        return None, (jsonify({"success": False, "error": "Vault is locked"}), 403)

    return user, None


# ---------------------------------------------------------------------------
# PIN validation
# ---------------------------------------------------------------------------

def _validate_pin(pin):
    """Return an error string if PIN is invalid, else None."""
    if not pin or not isinstance(pin, str):
        return "PIN is required"
    if len(pin) < PIN_MIN_LENGTH:
        return f"PIN must be at least {PIN_MIN_LENGTH} characters"
    if len(pin) > PIN_MAX_LENGTH:
        return f"PIN must be at most {PIN_MAX_LENGTH} characters"
    return None


def _hash_pin(pin):
    return generate_password_hash(pin, method="pbkdf2:sha256", salt_length=16)


def _check_pin(pin, pin_hash):
    return check_password_hash(pin_hash, pin)


# ---------------------------------------------------------------------------
# Rate limiting helpers
# ---------------------------------------------------------------------------

def _get_rate_limit_store():
    """Return the global RateLimitStore instance from the app."""
    return current_app.config.get("RATE_LIMIT_STORE")


def _check_vault_rate_limit(user_id):
    """Return (retry_seconds, error_response) or (None, None) if allowed."""
    store = _get_rate_limit_store()
    if not store:
        return None, None
    settings = get_vault_settings(user_id)
    if not settings:
        return None, None

    # Check database-level lockout
    if settings.get("locked_until"):
        try:
            lock_dt = datetime.fromisoformat(settings["locked_until"])
            now = datetime.now(timezone.utc)
            if now < lock_dt:
                retry_secs = int((lock_dt - now).total_seconds()) + 1
                return retry_secs, (
                    jsonify({"success": False, "error": "Too many PIN attempts. Please try again later."}),
                    429,
                )
            # Lockout expired — reset in DB
            reset_vault_failed_attempts(user_id)
        except (ValueError, TypeError):
            reset_vault_failed_attempts(user_id)

    return None, None


def _record_vault_failure(user_id):
    """Increment failure count; lock if threshold exceeded."""
    count = increment_vault_failed_attempts(user_id)
    return count


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@vault_bp.route("/api/vault/pin", methods=["POST"])
def set_pin():
    """Set the Vault PIN for the first time."""
    user = require_authenticated_user()
    if not user:
        return jsonify({"success": False, "error": "Authentication required"}), 401

    existing = get_vault_settings(user["id"])
    if existing:
        return jsonify({"success": False, "error": "PIN already set. Use /api/vault/pin/change instead."}), 400

    data = request.get_json(silent=True) or {}
    pin = data.get("pin", "")
    err = _validate_pin(pin)
    if err:
        return jsonify({"success": False, "error": err}), 400

    pin_hash = _hash_pin(pin)
    create_vault_settings(user["id"], pin_hash)
    log_activity(user["id"], "vault_pin_set", ip_address=_client_ip())
    return jsonify({"success": True, "message": "Vault PIN created"}), 201


@vault_bp.route("/api/vault/pin/change", methods=["POST"])
def change_pin():
    """Change the Vault PIN (requires current PIN)."""
    user = require_authenticated_user()
    if not user:
        return jsonify({"success": False, "error": "Authentication required"}), 401

    settings = get_vault_settings(user["id"])
    if not settings:
        return jsonify({"success": False, "error": "Vault is not configured"}), 400

    data = request.get_json(silent=True) or {}
    current_pin = data.get("current_pin", "")
    new_pin = data.get("new_pin", "")

    # Verify current PIN
    if not _check_pin(current_pin, settings["pin_hash"]):
        # Rate-limit PIN verification attempts
        store = _get_rate_limit_store()
        if store:
            from datetime import timedelta as _td
            retry = store.status(f"vault_pin:{user['id']}", 10, _td(minutes=15))
            if retry:
                return jsonify({"success": False, "error": "Too many PIN attempts. Please try again later."}), 429
            store.remember(f"vault_pin:{user['id']}")
        return jsonify({"success": False, "error": "Invalid current PIN"}), 403

    # Validate new PIN
    err = _validate_pin(new_pin)
    if err:
        return jsonify({"success": False, "error": err}), 400

    if current_pin == new_pin:
        return jsonify({"success": False, "error": "New PIN must be different from current PIN"}), 400

    new_hash = _hash_pin(new_pin)
    update_vault_pin(user["id"], new_hash)
    # Reset rate limit on success
    store = _get_rate_limit_store()
    if store:
        store.remember(f"vault_pin_ok:{user['id']}")
    log_activity(user["id"], "vault_pin_changed", ip_address=_client_ip())
    return jsonify({"success": True, "message": "Vault PIN changed"}), 200


@vault_bp.route("/api/vault/unlock", methods=["POST"])
def unlock():
    """Unlock the Vault with a PIN."""
    user = require_authenticated_user()
    if not user:
        return jsonify({"success": False, "error": "Authentication required"}), 401

    settings = get_vault_settings(user["id"])
    if not settings:
        return jsonify({"success": False, "error": "Vault is not configured"}), 400

    # Check rate limiting
    retry, err_resp = _check_vault_rate_limit(user["id"])
    if err_resp:
        return err_resp

    data = request.get_json(silent=True) or {}
    pin = data.get("pin", "")

    if not _check_pin(pin, settings["pin_hash"]):
        _record_vault_failure(user["id"])
        log_activity(user["id"], "vault_unlock_failed", ip_address=_client_ip())
        return jsonify({"success": False, "error": "Invalid Vault PIN"}), 403

    # Success — reset failures, unlock session
    reset_vault_failed_attempts(user["id"])
    vault_unlock(user["id"])
    log_activity(user["id"], "vault_unlocked", ip_address=_client_ip())
    return jsonify({"success": True, "message": "Vault unlocked"}), 200


@vault_bp.route("/api/vault/lock", methods=["POST"])
def lock():
    """Immediately lock the Vault for the current session."""
    user = require_authenticated_user()
    if not user:
        return jsonify({"success": False, "error": "Authentication required"}), 401

    vault_lock()
    log_activity(user["id"], "vault_locked", ip_address=_client_ip())
    return jsonify({"success": True, "message": "Vault locked"}), 200


@vault_bp.route("/api/vault/status", methods=["GET"])
def status():
    """Return safe vault status (no internal details)."""
    user = require_authenticated_user()
    if not user:
        return jsonify({"success": False, "error": "Authentication required"}), 401

    settings = get_vault_settings(user["id"])
    configured = settings is not None and settings["vault_enabled"] == 1
    unlocked = vault_is_unlocked(user["id"]) if configured else False

    return jsonify({
        "success": True,
        "configured": configured,
        "unlocked": unlocked,
    }), 200


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _client_ip():
    return request.remote_addr


def log_activity(user_id, action, detail=None, ip_address=None):
    """Thin wrapper — import from storage_db if available, else no-op."""
    try:
        from storage_db import log_activity as _log
        _log(user_id, action, detail=detail, ip_address=ip_address)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Vault file/folder operations
# ---------------------------------------------------------------------------

@vault_bp.route("/api/vault/move", methods=["POST"])
def vault_move():
    """Move a file or folder into the Vault.

    Request: {"type": "file"|"folder", "id": <int>}
    Requires: authenticated + vault unlocked.
    """
    user, err = require_vault_unlocked()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    res_type = data.get("type", "")
    res_id = data.get("id")

    if res_type not in ("file", "folder") or not isinstance(res_id, int):
        return jsonify({"success": False, "error": "Invalid request: type must be 'file' or 'folder', id must be integer"}), 400

    if res_type == "file":
        from storage_db import get_user_file_record, vault_file
        record = get_user_file_record(res_id, user["id"])
        if not record:
            return jsonify({"success": False, "error": "File not found"}), 404
        if record.get("is_vaulted"):
            return jsonify({"success": False, "error": "File is already in Vault"}), 400
        vault_file(res_id, user["id"])
        # Revoke any active shares for this file
        from storage_db import get_connection
        with get_connection() as conn:
            conn.execute(
                "UPDATE file_shares SET is_active = 0 WHERE file_id = ? AND owner_user_id = ?",
                (res_id, user["id"]),
            )
        log_activity(user["id"], "vault_file_moved", detail=record["filename"], ip_address=_client_ip())
        return jsonify({"success": True, "message": "File moved to Vault"}), 200

    else:  # folder
        from storage_db import get_folder, vault_folder
        folder = get_folder(res_id, user["id"])
        if not folder:
            return jsonify({"success": False, "error": "Folder not found"}), 404
        if folder.get("is_vaulted"):
            return jsonify({"success": False, "error": "Folder is already in Vault"}), 400
        vault_folder(res_id, user["id"])
        log_activity(user["id"], "vault_folder_moved", detail=folder["name"], ip_address=_client_ip())
        return jsonify({"success": True, "message": "Folder moved to Vault"}), 200


@vault_bp.route("/api/vault/restore", methods=["POST"])
def vault_restore():
    """Restore a file or folder from the Vault.

    Request: {"type": "file"|"folder", "id": <int>}
    Requires: authenticated + vault unlocked.
    """
    user, err = require_vault_unlocked()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    res_type = data.get("type", "")
    res_id = data.get("id")

    if res_type not in ("file", "folder") or not isinstance(res_id, int):
        return jsonify({"success": False, "error": "Invalid request: type must be 'file' or 'folder', id must be integer"}), 400

    if res_type == "file":
        from storage_db import get_user_file_record, unvault_file
        record = get_user_file_record(res_id, user["id"])
        if not record:
            return jsonify({"success": False, "error": "File not found"}), 404
        if not record.get("is_vaulted"):
            return jsonify({"success": False, "error": "File is not in Vault"}), 400
        unvault_file(res_id, user["id"])
        log_activity(user["id"], "vault_file_restored", detail=record["filename"], ip_address=_client_ip())
        return jsonify({"success": True, "message": "File restored from Vault"}), 200

    else:  # folder
        from storage_db import get_folder, unvault_folder
        folder = get_folder(res_id, user["id"])
        if not folder:
            return jsonify({"success": False, "error": "Folder not found"}), 404
        if not folder.get("is_vaulted"):
            return jsonify({"success": False, "error": "Folder is not in Vault"}), 400
        unvault_folder(res_id, user["id"])
        log_activity(user["id"], "vault_folder_restored", detail=folder["name"], ip_address=_client_ip())
        return jsonify({"success": True, "message": "Folder restored from Vault"}), 200


@vault_bp.route("/api/vault/files", methods=["GET"])
def vault_list_files():
    """List vaulted files. Requires vault unlocked."""
    user, err = require_vault_unlocked()
    if err:
        return err

    from storage_db import list_vaulted_files
    files = list_vaulted_files(user["id"])
    return jsonify({"success": True, "files": files}), 200


@vault_bp.route("/api/vault/folders", methods=["GET"])
def vault_list_folders():
    """List vaulted root-level folders. Requires vault unlocked."""
    user, err = require_vault_unlocked()
    if err:
        return err

    from storage_db import list_vaulted_folders
    parent_id = request.args.get("parent_id", None, type=int)
    folders = list_vaulted_folders(user["id"], parent_id=parent_id)
    return jsonify({"success": True, "folders": folders}), 200
