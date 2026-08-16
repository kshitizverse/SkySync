"""
SkySync Flask server with Telegram-backed per-user storage.
"""
from datetime import datetime, timedelta, timezone
import asyncio
import json
import logging
import os
import secrets
import sys
import tempfile
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_cors import CORS
from flask_session import Session
from werkzeug.utils import secure_filename as werkzeug_secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.exceptions import HTTPException

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from storage_db import (  # noqa: E402
    count_folder_items,
    count_user_active_shares,
    create_file_record,
    create_folder,
    create_share,
    delete_user_account,
    find_or_create_telegram_user,
    get_file_record,
    get_file_stats,
    get_folder,
    get_folder_breadcrumb,
    get_share_by_id,
    get_share_by_token,
    get_storage_intelligence,
    get_user_by_id,
    get_user_by_telegram_id,
    get_user_file_record,
    increment_share_download_count,
    init_db,
    invalidate_one_time_share,
    list_trash_files,
    list_trash_folders,
    list_user_files,
    list_user_favorites,
    list_user_folders,
    list_user_shares,
    list_users,
    list_webdav_tokens,
    log_activity,
    record_activity,
    move_file_to_folder,
    permanent_delete_file,
    permanent_delete_folder,
    purge_expired_trash,
    rename_folder,
    restore_file,
    restore_folder,
    revoke_all_user_shares,
    revoke_all_webdav_tokens,
    revoke_share,
    revoke_all_shares_for_file,
    row_to_dict,
    soft_delete_file,
    soft_delete_folder,
    toggle_favorite,
    update_file_record_name,
    update_user_name,
    update_user_session_path,
    update_user_telegram_info,
    update_share_last_accessed,
)
from rate_limiter import RateLimitStore  # noqa: E402
from telegram_handler import create_telegram_handler_for_user, run_telegram_op  # noqa: E402
from telegram_auth import TelegramAuthHandler  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)
for noisy_logger in ("telethon", "asyncio", "aiohttp", "urllib3"):
    logging.getLogger(noisy_logger).setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


BASE_DIR = os.path.dirname(__file__)
TRASH_RETENTION_DAYS = int(os.getenv("TRASH_RETENTION_DAYS", "30"))


def _is_production():
    """Return True when APP_ENV is 'production'."""
    return os.getenv("APP_ENV", "").strip().lower() == "production"


def _is_debug_requested():
    """Return True when FLASK_DEBUG is explicitly enabled."""
    return os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}


def validate_environment():
    """Validate required environment variables at startup."""
    required = {
        "TELEGRAM_API_ID": "your_telegram_api_id",
        "TELEGRAM_API_HASH": "your_telegram_api_hash",
    }
    missing = []
    for var, placeholder in required.items():
        value = os.getenv(var, "").strip()
        if not value or value == placeholder:
            missing.append(var)
    if missing:
        print("\n" + "=" * 60)
        print("  STARTUP ERROR: Missing required configuration")
        print("=" * 60)
        print(f"\nThe following environment variables must be set in .env:")
        for var in missing:
            print(f"  - {var}")
        print("\nCopy .env.example to .env and fill in real values:")
        print("  cp .env.example .env")
        print("=" * 60 + "\n")
        sys.exit(1)

    if _is_production() and _is_debug_requested():
        logger.warning(
            "APP_ENV is 'production' but FLASK_DEBUG is enabled. "
            "Debug mode has been forced off for safety."
        )

    if _is_production():
        cors_raw = os.getenv("CORS_ORIGINS", "").strip()
        if not cors_raw or cors_raw == "*":
            print("\n" + "=" * 60)
            print("  STARTUP ERROR: CORS_ORIGINS not configured for production")
            print("=" * 60)
            print("\nIn production, CORS_ORIGINS must be set to your domain(s).")
            print("=" * 60 + "\n")
            sys.exit(1)

        redis_url = os.getenv("REDIS_URL", "").strip()
        if not redis_url:
            print("\n" + "=" * 60)
            print("  WARNING: REDIS_URL not set in production")
            print("=" * 60)
            print("\nRate limiting will use in-memory storage, which does NOT")
            print("persist across restarts or multiple worker processes.")
            print("=" * 60 + "\n")


def parse_cors_origins(raw: str) -> list[str]:
    """Parse comma-separated CORS origins into a clean list.

    Returns ['*'] for wildcard, or a list of specific origins.
    """
    raw = raw.strip()
    if not raw:
        return ["*"]
    if raw == "*":
        return ["*"]
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    return origins if origins else ["*"]


def load_or_create_secret_key():
    configured_secret = os.getenv("SECRET_KEY", "").strip()
    if configured_secret:
        return configured_secret
    secret_path = os.path.join(BASE_DIR, ".flask_secret")
    try:
        if os.path.exists(secret_path):
            with open(secret_path, "r", encoding="utf-8") as f:
                saved = f.read().strip()
                if saved:
                    return saved
        generated = secrets.token_urlsafe(48)
        with open(secret_path, "w", encoding="utf-8") as f:
            f.write(generated)
        return generated
    except OSError as exc:
        logger.warning("Could not persist Flask SECRET_KEY: %s", exc)
        return secrets.token_urlsafe(48)


app = Flask(__name__, template_folder="templates", static_folder="static")
cors_origins_raw = os.getenv("CORS_ORIGINS", "*").strip()
cors_origins_list = parse_cors_origins(cors_origins_raw)
cors_supports_credentials = cors_origins_list != ["*"]
CORS(app, resources={
    r"/api/*": {
        "origins": cors_origins_list,
        "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization", "X-Requested-With"],
        "supports_credentials": cors_supports_credentials,
        "max_age": 86400,
    }
})

app.config["SECRET_KEY"] = load_or_create_secret_key()
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = os.path.join(BASE_DIR, ".flask_session")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_NAME"] = "skysync_session"
is_production = _is_production()
app.config["SESSION_COOKIE_SECURE"] = is_production
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_FILE_SIZE", str(100 * 1024 * 1024)))
os.makedirs(app.config["SESSION_FILE_DIR"], exist_ok=True)
Session(app)

validate_environment()
init_db()
purge_expired_trash()


# ---------------------------------------------------------------------------
# WebDAV integration — mount at /webdav/
# ---------------------------------------------------------------------------

def _setup_webdav():
    """Configure and mount WsgiDAV as a WSGI sub-application."""
    try:
        from wsgidav.wsgidav_app import WsgiDAVApp
        from webdav_provider import SkySyncDAVProvider
        from webdav_auth import SkySyncDomainController

        dav_config = {
            "host": "0.0.0.0",
            "port": 0,
            "mount_path": "/webdav",
            "provider_mapping": {"/": SkySyncDAVProvider()},
            "http_authenticator": {
                "domain_controller": SkySyncDomainController,
                "accept_basic": True,
                "accept_digest": False,
                "default_to_digest": False,
            },
            "simple_dc": {"user_mapping": {"*": True}},
            "verbose": 1,
            "logging": {
                "enable": False,
            },
            "hotfixes": {
                "winxp_accept_root_share_login": True,
                "win_accept_anonymous_options": True,
            },
            "middleware_stack": [
                "wsgidav.error_printer.ErrorPrinter",
                "wsgidav.http_authenticator.HTTPAuthenticator",
                "wsgidav.request_resolver.RequestResolver",
            ],
        }

        webdav_app = WsgiDAVApp(dav_config)

        from wsgidav.request_server import RequestServer as _OrigReqServ

        # Monkey-patch WsgiDAV's _stream_data to fix a blocking-read bug.
        # The original loops on wsgi.input.read() until it returns b"" (EOF).
        # With HTTP keep-alive the socket never closes, so read() blocks
        # for 15-30 s even though the body is already buffered.  When
        # Content-Length is present we read exactly that many bytes and stop,
        # preserving streaming (no full-body RAM load for large files).
        def _fast_stream(self, environ, block_size):
            inp = environ.get("wsgi.input")
            if inp is None:
                return
            _cl = environ.get("CONTENT_LENGTH", "")
            try:
                _cl_int = int(_cl) if _cl else -1
            except (ValueError, TypeError):
                _cl_int = -1

            if _cl_int >= 0:
                total_read = 0
                while total_read < _cl_int:
                    buf = inp.read(min(block_size, _cl_int - total_read))
                    if buf == b"":
                        break
                    total_read += len(buf)
                    environ["wsgidav.some_input_read"] = 1
                    yield buf
                environ["wsgidav.all_input_read"] = 1
            else:
                while True:
                    buf = inp.read(block_size)
                    if buf == b"":
                        break
                    environ["wsgidav.some_input_read"] = 1
                    yield buf
                environ["wsgidav.all_input_read"] = 1

        _OrigReqServ._stream_data = _fast_stream

        class WebDAVMiddleware:
            """WSGI middleware that routes /webdav/* to WsgiDAV."""

            def __init__(self, wsgi_app, dav_app, prefix="/webdav"):
                self.wsgi_app = wsgi_app
                self.dav_app = dav_app
                self.prefix = prefix

            def __call__(self, environ, start_response):
                path = environ.get("PATH_INFO", "")
                method = environ.get("REQUEST_METHOD", "")
                if path == self.prefix or path.startswith(self.prefix + "/"):
                    environ["SCRIPT_NAME"] = self.prefix
                    environ["PATH_INFO"] = path[len(self.prefix):]
                    _r = self.dav_app(environ, start_response)
                    return _r
                return self.wsgi_app(environ, start_response)

        app.wsgi_app = WebDAVMiddleware(app.wsgi_app, webdav_app, "/webdav")
        logger.info("WebDAV endpoint mounted at /webdav/")
    except ImportError:
        logger.warning("wsgidav not installed — WebDAV endpoint disabled")
    except Exception as exc:
        logger.error("Failed to mount WebDAV: %s", exc)


_setup_webdav()

from vault import vault_bp
app.register_blueprint(vault_bp)


def cleanup_old_previews():
    try:
        preview_dir = os.path.join(BASE_DIR, "previews")
        if not os.path.isdir(preview_dir):
            return
        cutoff = time.time() - 86400
        for name in os.listdir(preview_dir):
            path = os.path.join(preview_dir, name)
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
    except OSError as exc:
        logger.warning("Could not clean old previews: %s", exc)


cleanup_old_previews()

rate_limit = RateLimitStore()
app.config["RATE_LIMIT_STORE"] = rate_limit

UPLOAD_RATE_WINDOW = timedelta(minutes=1)
UPLOAD_MAX_PER_WINDOW = 20
LOGIN_RATE_WINDOW = timedelta(minutes=15)
LOGIN_MAX_ATTEMPTS = 10
TELEGRAM_CODE_RATE_WINDOW = timedelta(minutes=5)
TELEGRAM_CODE_MAX_PER_WINDOW = 5
SHARE_CREATE_RATE_WINDOW = timedelta(minutes=5)
SHARE_CREATE_MAX_PER_WINDOW = 20
SHARE_PASSWORD_RATE_WINDOW = timedelta(minutes=5)
SHARE_PASSWORD_MAX_ATTEMPTS = 10


def utcnow():
    return datetime.now(timezone.utc)


def request_payload():
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form.to_dict() if request.form else {}


def client_ip():
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    return request.remote_addr or "unknown"


def sanitize_filename(name):
    cleaned = werkzeug_secure_filename(name)
    if not cleaned:
        cleaned = "upload"
    if len(cleaned) > 200:
        ext = os.path.splitext(cleaned)[1]
        cleaned = cleaned[:200 - len(ext)] + ext
    return cleaned


def _format_size(size_bytes):
    if not size_bytes:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}" if unit == "B" else f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


@app.errorhandler(HTTPException)
def json_http_error(error):
    if not request.path.startswith("/api/"):
        return error
    status = error.code
    code_name = error.name.upper().replace(" ", "_") if hasattr(error, 'name') else f"HTTP_{status}"
    safe_messages = {
        400: "Bad request",
        401: "Authentication required",
        403: "Access denied",
        404: "Resource not found",
        405: "Method not allowed",
        409: "Conflict",
        413: "File too large",
        422: "Unprocessable request",
        429: "Too many requests",
    }
    message = safe_messages.get(status, error.description or error.name)
    if status == 405:
        allowed = sorted(getattr(error, "valid_methods", set()) or set())
        allowed = [m for m in allowed if m != "OPTIONS"]
        message = f"Method not allowed. Allowed: {', '.join(allowed)}." if allowed else "Method not allowed"
    return jsonify({
        "success": False,
        "error": message,
        "code": code_name,
        "status": status,
    }), status


@app.errorhandler(Exception)
def json_unhandled_error(error):
    if isinstance(error, HTTPException):
        return json_http_error(error)
    logger.exception("Unhandled server error")
    if not request.path.startswith("/api/"):
        raise error
    return jsonify({"success": False, "error": "Internal server error", "code": "INTERNAL_ERROR", "status": 500}), 500


@app.before_request
def before_request():
    if request.path.startswith("/api/"):
        logger.info("REQUEST: %s %s", request.method, request.path)


@app.after_request
def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), payment=(), usb=()"
    if _is_production():
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    elif not request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    csp_parts = [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
        "img-src 'self' data: blob:",
        "font-src 'self' https://cdnjs.cloudflare.com",
        "connect-src 'self'",
        "frame-ancestors 'none'",
        "base-uri 'self'",
        "form-action 'self'",
    ]
    response.headers["Content-Security-Policy"] = "; ".join(csp_parts)
    return response


def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            try:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        asyncio.set_event_loop(None)
        loop.close()


def get_telegram_credentials():
    api_id = int(os.getenv("TELEGRAM_API_ID", "0"))
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    return api_id, api_hash


def telegram_ready():
    api_id, api_hash = get_telegram_credentials()
    return bool(api_id and api_hash)


def get_storage_chat():
    return os.getenv("TELEGRAM_TARGET_CHAT", "me").strip()


def normalize_phone_number(phone):
    raw = (phone or "").strip()
    if not raw:
        return ""
    if not raw.startswith("+"):
        digits = "".join(ch for ch in raw if ch.isdigit())
        return f"+{digits}" if digits else ""
    digits = "".join(ch for ch in raw[1:] if ch.isdigit())
    return f"+{digits}" if digits else raw


def current_user():
    user_id = session.get("app_user_id")
    if not user_id:
        return None
    return get_user_by_id(user_id)


def require_auth():
    user = current_user()
    if not user:
        return None
    return user


def is_admin_user():
    user = current_user()
    return bool(user and user["is_admin"])


def complete_local_login(user, auth_mode="telegram"):
    session.clear()
    session["user_id"] = f"user_{user['id']}"
    session["app_user_id"] = user["id"]
    name = (user["name"] or "").strip()
    if not name:
        name = (user.get("telegram_first_name") or "").strip() or f"User {user['id']}"
    session["user_name"] = name
    session["name"] = name
    session["email"] = user.get("email") or ""
    session["is_admin"] = bool(user["is_admin"])
    session["phone"] = user["phone"]
    session["auth_mode"] = auth_mode
    session["telegram_connected"] = bool(user.get("session_path"))
    session["telegram_user_id"] = user.get("telegram_user_id")
    session["login_time"] = datetime.now(timezone.utc).isoformat()


def file_type_from_mime(mime_type):
    mime = (mime_type or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime:
        return "document"
    return "others"


def file_record_to_api(record):
    return {
        "id": record["id"],
        "message_id": record.get("telegram_message_id"),
        "name": record["filename"],
        "type": file_type_from_mime(record.get("mime_type")),
        "size": record.get("size", 0),
        "date": record.get("uploaded_at"),
        "mime_type": record.get("mime_type"),
        "is_favorite": bool(record.get("is_favorite", 0)),
        "is_deleted": bool(record.get("is_deleted", 0)),
        "deleted_at": record.get("deleted_at"),
        "folder_id": record.get("folder_id"),
    }


@app.route("/health")
def health_check():
    return jsonify({"status": "healthy", "service": "SkySync", "version": "2.0.0"}), 200


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login")
def login():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if not session.get("app_user_id"):
        return redirect(url_for("login"))
    return render_template("dashboard.html")


@app.route("/logout")
def logout():
    user = current_user()
    if user:
        log_activity(user["id"], "logout", ip_address=client_ip(), user_agent=request.headers.get("User-Agent", ""))
    session.clear()
    return redirect(url_for("login"))


@app.route("/s/<token>")
def share_view(token):
    share = get_share_by_token(token)
    if not share:
        return render_template("share.html", error="Share link is invalid or has been revoked", file=None, can_download=False, preview_url="", download_url="", requires_password=False, share_token=token, share_info=None), 404

    if share.get("revoked_at"):
        return render_template("share.html", error="Share link has been revoked", file=None, can_download=False, preview_url="", download_url="", requires_password=False, share_token=token, share_info=None), 410

    if share["expires_at"]:
        try:
            exp = datetime.fromisoformat(share["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if utcnow() > exp:
                return render_template("share.html", error="Share link has expired", file=None, can_download=False, preview_url="", download_url="", requires_password=False, share_token=token, share_info=None), 410
        except (ValueError, TypeError):
            pass

    record = get_file_record(share["file_id"])
    if not record:
        return render_template("share.html", error="Shared file no longer exists", file=None, can_download=False, preview_url="", download_url="", requires_password=False, share_token=token, share_info=None), 404

    if record.get("is_deleted"):
        return render_template("share.html", error="Shared file has been deleted", file=None, can_download=False, preview_url="", download_url="", requires_password=False, share_token=token, share_info=None), 404

    if record.get("is_vaulted"):
        return render_template("share.html", error="This file is no longer available", file=None, can_download=False, preview_url="", download_url="", requires_password=False, share_token=token, share_info=None), 403

    if share.get("one_time") and share.get("download_count", 0) > 0:
        return render_template("share.html", error="This one-time link has already been used", file=None, can_download=False, preview_url="", download_url="", requires_password=False, share_token=token, share_info=None), 410

    if share.get("password_hash"):
        session_key = f"share_pwd_{share['id']}"
        if not session.get(session_key):
            return render_template("share.html", error=None, file=None, can_download=False, preview_url="", download_url="", requires_password=True, share_token=token, share_info={
                "filename": record["filename"],
                "has_password": True,
            }), 200

    can_download = bool(share["can_download"])
    if share.get("download_limit") is not None and share.get("download_count", 0) >= share["download_limit"]:
        can_download = False

    mime = (record.get("mime_type") or "").lower()
    file_type = file_type_from_mime(mime)
    is_previewable = file_type in ("image", "video", "audio")
    size_str = _format_size(record.get("size", 0))

    file_data = {
        "name": record["filename"],
        "type": file_type,
        "size": size_str,
        "mime": mime,
        "is_previewable": is_previewable,
    }

    download_url = url_for("shared_download", token=token)
    preview_url = url_for("shared_preview", token=token) if is_previewable else ""

    expires_display = None
    if share["expires_at"]:
        try:
            exp = datetime.fromisoformat(share["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            delta = exp - utcnow()
            if delta.days > 0:
                expires_display = f"{delta.days} day{'s' if delta.days != 1 else ''}"
            else:
                hours = max(1, delta.seconds // 3600)
                expires_display = f"{hours} hour{'s' if hours != 1 else ''}"
        except (ValueError, TypeError):
            pass

    share_info = {
        "download_count": share.get("download_count", 0),
        "download_limit": share.get("download_limit"),
        "expires_display": expires_display,
        "has_password": bool(share.get("password_hash")),
        "one_time": bool(share.get("one_time")),
    }

    return render_template("share.html",
        file=file_data,
        error=None,
        can_download=can_download,
        download_url=download_url,
        preview_url=preview_url,
        requires_password=False,
        share_token=token,
        share_info=share_info,
    )


# ---------------------------------------------------------------------------
# Auth API — Telegram OTP Authentication
# ---------------------------------------------------------------------------
# Persistent Telegram auth state — survives server restarts
# ---------------------------------------------------------------------------

AUTH_STATE_FILE = os.path.join(os.path.dirname(__file__), ".auth_state.json")
TELEGRAM_AUTH_STATE_TTL = timedelta(minutes=10)
_telegram_auth_states = {}


def _save_auth_states():
    """Persist serializable auth state to disk."""
    serializable = {}
    for key, state in _telegram_auth_states.items():
        serializable[key] = {
            "phone": state["phone"],
            "client_hash": state["client_hash"],
            "session_name": state.get("session_name", ""),
            "step": state.get("step", "code_sent"),
            "created_at": state["created_at"].isoformat(),
        }
    try:
        with open(AUTH_STATE_FILE, "w") as f:
            json.dump(serializable, f)
    except OSError as exc:
        logger.warning("Could not persist auth states: %s", exc)


def _load_auth_states():
    """Load persisted auth states from disk and reconstruct handlers."""
    if not os.path.exists(AUTH_STATE_FILE):
        return
    try:
        with open(AUTH_STATE_FILE, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load auth states: %s", exc)
        return

    api_id, api_hash = get_telegram_credentials()
    if not api_id or not api_hash:
        return

    now = utcnow()
    for key, saved in data.items():
        created_at = datetime.fromisoformat(saved["created_at"])
        if (now - created_at).total_seconds() > TELEGRAM_AUTH_STATE_TTL.total_seconds():
            continue
        from telegram_auth import TelegramAuthHandler
        handler = TelegramAuthHandler(api_id, api_hash, saved["phone"])
        handler.client_hash = saved["client_hash"]
        handler.session_name = saved.get("session_name", handler.session_name)
        _telegram_auth_states[key] = {
            "phone": saved["phone"],
            "handler": handler,
            "client_hash": saved["client_hash"],
            "delivery": {"channel": "telegram_app", "message": "Code sent", "hint": "Check Telegram."},
            "created_at": created_at,
            "step": saved.get("step", "code_sent"),
        }
    logger.info("Restored %d auth state(s) from disk", len(_telegram_auth_states))


def cleanup_expired_auth_states():
    now = utcnow()
    expired = [k for k, v in _telegram_auth_states.items()
               if (now - v["created_at"]).total_seconds() > TELEGRAM_AUTH_STATE_TTL.total_seconds()]
    for k in expired:
        try:
            handler = _telegram_auth_states[k].get("handler")
            if handler:
                run_async(handler.disconnect())
                handler.cleanup_session_files()
        except Exception:
            pass
        del _telegram_auth_states[k]
    if expired:
        _save_auth_states()


@app.route("/api/auth/status", methods=["GET"])
def auth_status():
    cleanup_expired_auth_states()
    return jsonify({
        "success": True,
        "telegram_configured": telegram_ready(),
    }), 200


@app.route("/api/auth/send-code", methods=["POST"])
def send_telegram_code():
    ip = client_ip()
    retry_after = rate_limit.status(f"tg_code:{ip}", TELEGRAM_CODE_MAX_PER_WINDOW, TELEGRAM_CODE_RATE_WINDOW)
    if retry_after:
        return jsonify({"success": False, "error": "Too many code requests. Please wait.", "retry_after": retry_after}), 429

    data = request_payload()
    phone = normalize_phone_number(data.get("phone") or "")
    if not phone or len(phone) < 10:
        return jsonify({"success": False, "error": "Enter a valid phone number in international format (e.g. +1234567890)"}), 400

    api_id, api_hash = get_telegram_credentials()
    if not api_id or not api_hash:
        return jsonify({"success": False, "error": "Telegram API is not configured on this server"}), 503

    handler = TelegramAuthHandler(api_id, api_hash, phone)
    success, result = run_async(handler.request_login_code())

    if not success:
        return jsonify({"success": False, "error": result.get("message", "Failed to send code"), "retry_after": result.get("retry_after")}), 400

    state_key = secrets.token_urlsafe(32)
    _telegram_auth_states[state_key] = {
        "phone": phone,
        "handler": handler,
        "client_hash": handler.client_hash,
        "session_name": handler.session_name,
        "delivery": result,
        "created_at": utcnow(),
        "step": "code_sent",
    }
    _save_auth_states()

    rate_limit.remember(f"tg_code:{ip}")
    return jsonify({
        "success": True,
        "state_key": state_key,
        "delivery": result,
    }), 200


@app.route("/api/auth/verify-code", methods=["POST"])
def verify_telegram_code():
    ip = client_ip()
    retry_after = rate_limit.status(f"tg_verify:{ip}", LOGIN_MAX_ATTEMPTS, LOGIN_RATE_WINDOW)
    if retry_after:
        return jsonify({"success": False, "error": "Too many verification attempts. Please wait.", "retry_after": retry_after}), 429

    data = request_payload()
    state_key = (data.get("state_key") or "").strip()
    code = (data.get("code") or "").strip()

    if not state_key or state_key not in _telegram_auth_states:
        return jsonify({"success": False, "error": "Session expired. Request a new code."}), 400
    if not code:
        return jsonify({"success": False, "error": "Enter the verification code"}), 400

    rate_limit.remember(f"tg_verify:{ip}")

    state = _telegram_auth_states[state_key]
    handler = state["handler"]

    success, result = run_async(handler.verify_code(code))

    if success:
        telegram_user_id = result["user_id"]
        phone = result.get("phone") or state["phone"]
        first_name = result.get("first_name", "")
        last_name = result.get("last_name", "")
        username = result.get("username", "")

        # Disconnect the Telethon client BEFORE moving the session file,
        # otherwise the .session file is locked on Windows.
        try:
            run_async(handler.disconnect())
        except Exception:
            pass
        session_path = handler.create_persistent_session(telegram_user_id)
        user = find_or_create_telegram_user(
            telegram_user_id=telegram_user_id,
            phone=phone,
            first_name=first_name,
            last_name=last_name,
            username=username,
            session_path=session_path,
        )
        complete_local_login(user, auth_mode="telegram")
        log_activity(user["id"], "login", detail="Telegram OTP login", ip_address=client_ip(), user_agent=request.headers.get("User-Agent", ""))

        del _telegram_auth_states[state_key]
        _save_auth_states()
        return jsonify({
            "success": True,
            "message": "Login successful",
            "user": {"id": user["id"], "name": user.get("name"), "phone": phone},
        }), 200

    if result == "2FA_REQUIRED":
        state["step"] = "2fa_required"
        _save_auth_states()
        return jsonify({"success": True, "requires_2fa": True, "message": "Two-factor authentication required"}), 200

    return jsonify({"success": False, "error": result}), 400


@app.route("/api/auth/verify-2fa", methods=["POST"])
def verify_telegram_2fa():
    ip = client_ip()
    retry_after = rate_limit.status(f"tg_verify:{ip}", LOGIN_MAX_ATTEMPTS, LOGIN_RATE_WINDOW)
    if retry_after:
        return jsonify({"success": False, "error": "Too many verification attempts. Please wait.", "retry_after": retry_after}), 429

    data = request_payload()
    state_key = (data.get("state_key") or "").strip()
    password = (data.get("password") or "").strip()

    if not state_key or state_key not in _telegram_auth_states:
        return jsonify({"success": False, "error": "Session expired. Start the login process again."}), 400
    if not password:
        return jsonify({"success": False, "error": "Enter your Telegram 2FA password"}), 400

    rate_limit.remember(f"tg_verify:{ip}")

    state = _telegram_auth_states[state_key]
    if state.get("step") != "2fa_required":
        return jsonify({"success": False, "error": "Invalid authentication state"}), 400

    handler = state["handler"]
    success, result = run_async(handler.verify_2fa_password(password))

    if success:
        telegram_user_id = result["user_id"]
        phone = result.get("phone") or state["phone"]
        first_name = result.get("first_name", "")
        last_name = result.get("last_name", "")
        username = result.get("username", "")

        # Disconnect the Telethon client BEFORE moving the session file,
        # otherwise the .session file is locked on Windows.
        try:
            run_async(handler.disconnect())
        except Exception:
            pass
        session_path = handler.create_persistent_session(telegram_user_id)
        user = find_or_create_telegram_user(
            telegram_user_id=telegram_user_id,
            phone=phone,
            first_name=first_name,
            last_name=last_name,
            username=username,
            session_path=session_path,
        )
        complete_local_login(user, auth_mode="telegram")
        log_activity(user["id"], "login", detail="Telegram 2FA login", ip_address=client_ip(), user_agent=request.headers.get("User-Agent", ""))

        del _telegram_auth_states[state_key]
        _save_auth_states()
        return jsonify({
            "success": True,
            "message": "Login successful",
            "user": {"id": user["id"], "name": user.get("name"), "phone": phone},
        }), 200

    return jsonify({"success": False, "error": result}), 400


@app.route("/api/auth/disconnect-telegram", methods=["POST"])
def disconnect_telegram():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    session_path = user.get("session_path")
    if session_path and os.path.exists(session_path):
        try:
            os.remove(session_path)
            for suffix in ("-journal", "-wal", "-shm"):
                p = f"{session_path}{suffix}"
                if os.path.exists(p):
                    os.remove(p)
        except OSError as exc:
            logger.warning("Failed to remove session file: %s", exc)

    update_user_session_path(user["id"], None)
    session["telegram_connected"] = False
    log_activity(user["id"], "telegram_disconnect", detail="Telegram account disconnected", ip_address=client_ip())
    return jsonify({"success": True, "message": "Telegram account disconnected"}), 200


# ---------------------------------------------------------------------------
# Admin API
# ---------------------------------------------------------------------------

@app.route("/api/admin/users", methods=["GET"])
def admin_list_users():
    if not is_admin_user():
        return jsonify({"success": False, "error": "Admin access required"}), 403
    users = [
        {
            "id": row["id"],
            "telegram_user_id": row.get("telegram_user_id"),
            "is_admin": bool(row["is_admin"]),
            "phone": row["phone"],
            "name": row.get("name"),
            "account_status": row.get("account_status", "active"),
            "connected_at": row.get("connected_at"),
            "last_login": row.get("last_login"),
            "created_at": row["created_at"],
        }
        for row in list_users()
    ]
    return jsonify({"success": True, "users": users}), 200


# ---------------------------------------------------------------------------
# Files API
# ---------------------------------------------------------------------------

@app.route("/api/files", methods=["GET"])
def get_files():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    view = request.args.get("view", "files")
    folder_id = request.args.get("folder_id")
    if folder_id:
        try:
            folder_id = int(folder_id)
        except (ValueError, TypeError):
            folder_id = None

    if view == "trash":
        records = list_trash_files(user["id"])
        folders = list_trash_folders(user["id"])
    elif view == "favorites":
        records = list_user_favorites(user["id"])
        folders = []
    else:
        records = list_user_files(user["id"])
        if folder_id:
            records = [r for r in records if dict(r).get("folder_id") == folder_id]
            folders = list_user_folders(user["id"], parent_id=folder_id)
        else:
            records = [r for r in records if not dict(r).get("folder_id")]
            folders = list_user_folders(user["id"], parent_id=None)

    # Filter out vaulted items from normal/favorites/trash views
    from vault import vault_is_unlocked
    vault_open = vault_is_unlocked(user["id"])
    if not vault_open:
        records = [r for r in records if not dict(r).get("is_vaulted")]
        folders = [f for f in folders if not dict(f).get("is_vaulted")]

    files = [file_record_to_api(r) for r in records]

    for folder in folders:
        folder["item_count"] = count_folder_items(user["id"], folder["id"])

    # Pagination
    total_files = len(files)
    total_folders = len(folders)
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    per_page = min(per_page, 200)
    total_pages = max(1, (total_files + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    files = files[start:end]

    stats = get_file_stats(user["id"], exclude_vaulted=not vault_open)
    return jsonify({
        "success": True,
        "files": files,
        "folders": folders,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total_files": total_files,
            "total_pages": total_pages,
        },
        "summary": {
            "total_files": stats["total_files"],
            "total_size": stats["total_size"],
            "categories": {
                "images": stats["images"],
                "videos": stats["videos"],
                "documents": stats["documents"],
                "audio": stats["audio"],
                "others": stats["total_files"] - stats["images"] - stats["videos"] - stats["documents"] - stats["audio"],
            },
        },
    }), 200


@app.route("/api/files/upload", methods=["POST"])
def upload_file():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    ip_key = f"upload:{client_ip()}"
    retry_after = rate_limit.status(ip_key, UPLOAD_MAX_PER_WINDOW, UPLOAD_RATE_WINDOW)
    if retry_after:
        return jsonify({"success": False, "error": "Upload rate limit. Please wait.", "retry_after": retry_after}), 429

    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"success": False, "error": "No file selected"}), 400

    safe_name = sanitize_filename(file.filename)
    cached = create_telegram_handler_for_user(user)
    if not cached:
        return jsonify({"success": False, "error": "Telegram storage is not configured"}), 503

    os.makedirs("uploads", exist_ok=True)
    extension = os.path.splitext(safe_name)[1]
    temp_file = tempfile.NamedTemporaryFile(delete=False, dir="uploads", suffix=extension)
    temp_path = temp_file.name
    temp_file.close()
    file.save(temp_path)

    try:
        file_size = os.path.getsize(temp_path)
        max_size = app.config.get("MAX_CONTENT_LENGTH", 100 * 1024 * 1024)
        if file_size > max_size:
            return jsonify({"success": False, "error": f"File exceeds the {max_size // (1024*1024)} MB upload limit"}), 413

        upload_result = run_telegram_op(cached, cached.handler.send_file(temp_path, caption=f"Uploaded by {user['email']}"))
        if not upload_result or not upload_result.get("message_id"):
            return jsonify({"success": False, "error": "Telegram upload failed"}), 500

        record = create_file_record(
            user_id=user["id"],
            telegram_message_id=upload_result["message_id"],
            filename=safe_name,
            mime_type=file.mimetype,
            size=file_size,
        )
        folder_id = request.form.get("folder_id") or request.args.get("folder_id")
        if folder_id:
            try:
                move_file_to_folder(record["id"], user["id"], int(folder_id))
                record = get_user_file_record(record["id"], user["id"])
            except (ValueError, TypeError):
                pass
        rate_limit.remember(ip_key)
        log_activity(user["id"], "upload", detail=safe_name, ip_address=client_ip())
        record_activity(
            user["id"], "FILE_UPLOADED", resource_type="file", resource_id=record["id"],
            metadata={"filename": safe_name, "size": file_size, "mime_type": file.mimetype},
        )
        return jsonify({
            "success": True,
            "message": f"File {safe_name} uploaded successfully",
            "file": file_record_to_api(record),
        }), 201
    except Exception as exc:
        logger.error("Upload failed: %s", exc)
        return jsonify({"success": False, "error": "Upload failed"}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@app.route("/api/files/<int:file_id>/download", methods=["GET"])
def download_file(file_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    record = get_user_file_record(file_id, user["id"])
    if not record or record.get("is_deleted"):
        return jsonify({"success": False, "error": "File not found"}), 404

    if record.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    cached = create_telegram_handler_for_user(user)
    if not cached:
        return jsonify({"success": False, "error": "Telegram storage is not configured"}), 503

    os.makedirs("downloads", exist_ok=True)
    safe_name = sanitize_filename(record["filename"]) or f"file_{file_id}"
    output_path = os.path.join("downloads", f"{file_id}_{safe_name}")
    try:
        success = run_telegram_op(cached, cached.handler.download_file(record["telegram_message_id"], output_path))
        if not success or not os.path.exists(output_path):
            return jsonify({"success": False, "error": "Download failed"}), 500
        log_activity(user["id"], "download", detail=record["filename"], ip_address=client_ip())
        record_activity(
            user["id"], "FILE_DOWNLOADED", resource_type="file", resource_id=file_id,
            metadata={"filename": record["filename"], "size": record.get("size")},
        )
        return send_file(output_path, as_attachment=True, download_name=record["filename"])
    finally:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass


@app.route("/api/files/<int:file_id>/preview", methods=["GET"])
def preview_file(file_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    record = get_user_file_record(file_id, user["id"])
    if not record or record.get("is_deleted"):
        return jsonify({"success": False, "error": "File not found"}), 404

    if record.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    mime_type = (record.get("mime_type") or "").lower()
    if not (mime_type.startswith("image/") or mime_type.startswith("video/") or mime_type.startswith("audio/")):
        return jsonify({"success": False, "error": "Preview not available for this file type"}), 400

    cached = create_telegram_handler_for_user(user)
    if not cached:
        return jsonify({"success": False, "error": "Telegram storage is not configured"}), 503

    os.makedirs("previews", exist_ok=True)
    safe_name = sanitize_filename(record["filename"]) or f"preview_{file_id}"
    preview_path = os.path.join("previews", f"{file_id}_{safe_name}")
    if not os.path.exists(preview_path) or os.path.getsize(preview_path) == 0:
        success = run_telegram_op(cached, cached.handler.download_file(record["telegram_message_id"], preview_path))
        if not success or not os.path.exists(preview_path):
            return jsonify({"success": False, "error": "Preview download failed"}), 500

    record_activity(
        user["id"], "FILE_PREVIEWED", resource_type="file", resource_id=file_id,
        metadata={"filename": record["filename"]},
    )
    return send_file(
        preview_path,
        mimetype=record.get("mime_type") or None,
        as_attachment=False,
        download_name=record["filename"],
    )


@app.route("/api/files/<int:file_id>/delete", methods=["DELETE"])
def delete_file(file_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    record = get_user_file_record(file_id, user["id"])
    if not record or record.get("is_deleted"):
        return jsonify({"success": False, "error": "File not found"}), 404

    if record.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    soft_delete_file(file_id, user["id"])
    log_activity(user["id"], "trash", detail=record["filename"], ip_address=client_ip())
    record_activity(
        user["id"], "FILE_DELETED", resource_type="file", resource_id=file_id,
        metadata={"filename": record["filename"]},
    )
    return jsonify({"success": True, "message": "File moved to trash"}), 200


@app.route("/api/files/<int:file_id>/rename", methods=["POST"])
def rename_file(file_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    record = get_user_file_record(file_id, user["id"])
    if not record or record.get("is_deleted"):
        return jsonify({"success": False, "error": "File not found"}), 404

    if record.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    data = request.json or {}
    new_name = sanitize_filename((data.get("name") or "").strip())
    if not new_name:
        return jsonify({"success": False, "error": "Enter a valid file name"}), 400

    updated = update_file_record_name(file_id, user["id"], new_name)
    if not updated:
        return jsonify({"success": False, "error": "Rename failed"}), 500

    log_activity(user["id"], "rename", detail=f"{record['filename']} -> {new_name}", ip_address=client_ip())
    record_activity(
        user["id"], "FILE_RENAMED", resource_type="file", resource_id=file_id,
        metadata={"old_name": record["filename"], "new_name": new_name},
    )
    return jsonify({
        "success": True,
        "message": "File renamed successfully",
        "file": file_record_to_api(updated),
    }), 200


@app.route("/api/files/<int:file_id>/favorite", methods=["POST"])
def toggle_file_favorite(file_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    record = get_user_file_record(file_id, user["id"])
    if not record or record.get("is_deleted"):
        return jsonify({"success": False, "error": "File not found"}), 404

    if record.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    updated = toggle_favorite(file_id, user["id"])
    if not updated:
        return jsonify({"success": False, "error": "Failed to toggle favorite"}), 500

    is_fav = bool(updated.get("is_favorite", 0))
    record_activity(
        user["id"], "FILE_FAVORITED" if is_fav else "FILE_UNFAVORITED",
        resource_type="file", resource_id=file_id,
        metadata={"filename": record["filename"]},
    )
    return jsonify({
        "success": True,
        "is_favorite": is_fav,
        "message": "Favorite updated",
    }), 200


@app.route("/api/files/<int:file_id>/restore", methods=["POST"])
def restore_file_endpoint(file_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    record = restore_file(file_id, user["id"])
    if not record:
        return jsonify({"success": False, "error": "File not found in trash"}), 404

    log_activity(user["id"], "restore", detail=record.get("filename"), ip_address=client_ip())
    record_activity(
        user["id"], "FILE_RESTORED", resource_type="file", resource_id=file_id,
        metadata={"filename": record.get("filename")},
    )
    return jsonify({"success": True, "message": "File restored", "file": file_record_to_api(record)}), 200


@app.route("/api/files/<int:file_id>/permanent-delete", methods=["DELETE"])
def permanent_delete_file_endpoint(file_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    record = get_user_file_record(file_id, user["id"])
    if not record or not record.get("is_deleted"):
        return jsonify({"success": False, "error": "File not found in trash"}), 404

    if record.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    cached = create_telegram_handler_for_user(user)
    if cached:
        try:
            run_telegram_op(cached, cached.handler.delete_message(record["telegram_message_id"]))
        except Exception as exc:
            logger.warning("Telegram delete failed for file %s: %s", file_id, exc)

    permanent_delete_file(file_id, user["id"])
    log_activity(user["id"], "permanent_delete", detail=record.get("filename"), ip_address=client_ip())
    record_activity(
        user["id"], "FILE_PERMANENTLY_DELETED", resource_type="file", resource_id=file_id,
        metadata={"filename": record.get("filename")},
    )
    return jsonify({"success": True, "message": "File permanently deleted"}), 200


@app.route("/api/files/bulk-delete", methods=["POST"])
def bulk_delete_files():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.json or {}
    file_ids = data.get("file_ids", [])
    if not file_ids or not isinstance(file_ids, list):
        return jsonify({"success": False, "error": "No file IDs provided"}), 400
    if len(file_ids) > 100:
        return jsonify({"success": False, "error": "Too many files. Maximum 100 per batch."}), 400

    from vault import vault_is_unlocked
    vault_open = vault_is_unlocked(user["id"])
    deleted = 0
    for fid in file_ids[:100]:
        try:
            fid_int = int(fid)
        except (ValueError, TypeError):
            continue
        record = get_user_file_record(fid_int, user["id"])
        if record and not record.get("is_deleted"):
            if record.get("is_vaulted") and not vault_open:
                continue
            soft_delete_file(fid_int, user["id"])
            record_activity(
                user["id"], "FILE_DELETED", resource_type="file", resource_id=fid_int,
                metadata={"filename": record["filename"]},
            )
            deleted += 1

    return jsonify({"success": True, "message": f"{deleted} file(s) moved to trash", "deleted": deleted}), 200


@app.route("/api/files/bulk-restore", methods=["POST"])
def bulk_restore_files():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request.json or {}
    file_ids = data.get("file_ids", [])
    if not file_ids or not isinstance(file_ids, list):
        return jsonify({"success": False, "error": "No file IDs provided"}), 400

    restored = 0
    for fid in file_ids[:100]:
        try:
            fid_int = int(fid)
        except (ValueError, TypeError):
            continue
        record = restore_file(fid_int, user["id"])
        if record:
            record_activity(
                user["id"], "FILE_RESTORED", resource_type="file", resource_id=fid_int,
                metadata={"filename": record.get("filename")},
            )
            restored += 1

    return jsonify({"success": True, "message": f"{restored} file(s) restored", "restored": restored}), 200


# ---------------------------------------------------------------------------
# Sharing API
# ---------------------------------------------------------------------------

@app.route("/api/files/<int:file_id>/share", methods=["POST"])
def create_file_share(file_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    ip_key = f"share_create:{client_ip()}"
    retry_after = rate_limit.status(ip_key, SHARE_CREATE_MAX_PER_WINDOW, SHARE_CREATE_RATE_WINDOW)
    if retry_after:
        return jsonify({"success": False, "error": "Too many share requests. Please wait.", "retry_after": retry_after}), 429

    record = get_user_file_record(file_id, user["id"])
    if not record or record.get("is_deleted"):
        return jsonify({"success": False, "error": "File not found"}), 404

    if record.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    data = request.json or {}
    can_view = data.get("can_view", True)
    can_download = data.get("can_download", False)
    expires_at = data.get("expires_at")
    password = data.get("password")
    one_time = data.get("one_time", False)
    download_limit = data.get("download_limit")

    if expires_at:
        try:
            exp_dt = datetime.fromisoformat(expires_at)
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if exp_dt <= utcnow():
                return jsonify({"success": False, "error": "Expiration must be in the future"}), 400
            expires_at = exp_dt.isoformat()
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid expiration timestamp"}), 400

    password_hash = None
    if password:
        if not isinstance(password, str) or len(password) < 4:
            return jsonify({"success": False, "error": "Password must be at least 4 characters"}), 400
        if len(password) > 128:
            return jsonify({"success": False, "error": "Password must be at most 128 characters"}), 400
        password_hash = generate_password_hash(password, method="pbkdf2:sha256", salt_length=16)

    if one_time:
        one_time = 1
    else:
        one_time = 0

    if download_limit is not None:
        try:
            download_limit = int(download_limit)
            if download_limit < 1:
                return jsonify({"success": False, "error": "Download limit must be a positive integer"}), 400
            if download_limit > 10000:
                return jsonify({"success": False, "error": "Download limit is too high"}), 400
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid download limit"}), 400
    else:
        download_limit = None

    share = create_share(
        file_id, user["id"],
        can_view=int(can_view),
        can_download=int(can_download),
        expires_at=expires_at,
        password_hash=password_hash,
        one_time=one_time,
        download_limit=download_limit,
    )
    rate_limit.remember(ip_key)
    log_activity(user["id"], "share", detail=f"Shared {record['filename']}", ip_address=client_ip())
    record_activity(
        user["id"], "SHARE_CREATED", resource_type="file", resource_id=file_id,
        metadata={"filename": record["filename"], "share_token": share["share_token"]},
    )

    share_url = url_for("share_view", token=share["share_token"], _external=True)
    return jsonify({
        "success": True,
        "message": "Share link created",
        "share": {
            "id": share["id"],
            "token": share["share_token"],
            "url": share_url,
            "can_view": bool(share["can_view"]),
            "can_download": bool(share["can_download"]),
            "expires_at": share["expires_at"],
            "has_password": password_hash is not None,
            "one_time": bool(share["one_time"]),
            "download_limit": share["download_limit"],
            "download_count": share["download_count"],
        },
    }), 201


@app.route("/api/shares", methods=["GET"])
def list_shares():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    shares = list_user_shares(user["id"])
    return jsonify({
        "success": True,
        "shares": [
            {
                "id": s["id"],
                "token": s["share_token"],
                "filename": s["filename"],
                "can_view": bool(s["can_view"]),
                "can_download": bool(s["can_download"]),
                "expires_at": s["expires_at"],
                "created_at": s["created_at"],
                "has_password": bool(s.get("password_hash")),
                "one_time": bool(s.get("one_time", 0)),
                "download_limit": s.get("download_limit"),
                "download_count": s.get("download_count", 0),
                "last_accessed_at": s.get("last_accessed_at"),
                "revoked_at": s.get("revoked_at"),
                "url": url_for("share_view", token=s["share_token"], _external=True),
            }
            for s in shares
        ],
    }), 200


@app.route("/api/shares/<int:share_id>/revoke", methods=["DELETE"])
def revoke_share_endpoint(share_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    share = get_share_by_id(share_id, user["id"])
    if not share:
        return jsonify({"success": False, "error": "Share not found"}), 404

    revoke_share(share_id, user["id"])
    log_activity(user["id"], "share_revoke", detail=f"Revoked share {share_id}", ip_address=client_ip())
    record_activity(
        user["id"], "SHARE_REVOKED", resource_type="file", resource_id=share["file_id"],
        metadata={"share_id": share_id},
    )
    return jsonify({"success": True, "message": "Share link revoked"}), 200


@app.route("/api/share/<token>/verify-password", methods=["POST"])
def verify_share_password(token):
    share = get_share_by_token(token)
    if not share:
        return jsonify({"success": False, "error": "Share link is invalid"}), 404

    if not share.get("password_hash"):
        return jsonify({"success": False, "error": "This share does not require a password"}), 400

    ip_key = f"share_pwd:{client_ip()}:{share['id']}"
    retry_after = rate_limit.status(ip_key, SHARE_PASSWORD_MAX_ATTEMPTS, SHARE_PASSWORD_RATE_WINDOW)
    if retry_after:
        return jsonify({"success": False, "error": "Too many password attempts. Please wait.", "retry_after": retry_after}), 429

    data = request.json or {}
    password = data.get("password", "")

    if not password or not isinstance(password, str):
        return jsonify({"success": False, "error": "Password is required"}), 400

    if not check_password_hash(share["password_hash"], password):
        rate_limit.remember(ip_key)
        return jsonify({"success": False, "error": "Invalid password"}), 403

    session_key = f"share_pwd_{share['id']}"
    session[session_key] = True
    rate_limit.remember(f"share_pwd_ok:{client_ip()}:{share['id']}")
    return jsonify({"success": True, "message": "Password verified"}), 200


@app.route("/api/share/<token>/download", methods=["GET"])
def shared_download(token):
    share = get_share_by_token(token)
    if not share:
        return jsonify({"success": False, "error": "Access denied"}), 403

    if share.get("revoked_at"):
        return jsonify({"success": False, "error": "Share link has been revoked"}), 403

    if share["expires_at"]:
        try:
            exp = datetime.fromisoformat(share["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if utcnow() > exp:
                return jsonify({"success": False, "error": "Share link has expired"}), 410
        except (ValueError, TypeError):
            pass

    record = get_file_record(share["file_id"])
    if not record:
        return jsonify({"success": False, "error": "File not found"}), 404

    if record.get("is_deleted"):
        return jsonify({"success": False, "error": "File has been deleted"}), 404

    if record.get("is_vaulted"):
        return jsonify({"success": False, "error": "Access denied"}), 403

    if not share["can_download"]:
        return jsonify({"success": False, "error": "Download not allowed for this share"}), 403

    if share.get("password_hash"):
        session_key = f"share_pwd_{share['id']}"
        if not session.get(session_key):
            return jsonify({"success": False, "error": "Password required"}), 403

    if share.get("download_limit") is not None and share.get("download_count", 0) >= share["download_limit"]:
        return jsonify({"success": False, "error": "Download limit reached"}), 403

    if share.get("one_time") and share.get("download_count", 0) > 0:
        return jsonify({"success": False, "error": "This one-time link has already been used"}), 410

    owner = get_user_by_id(record["user_id"])
    cached = create_telegram_handler_for_user(owner) if owner else None
    if not cached:
        return jsonify({"success": False, "error": "Telegram storage is not configured"}), 503

    os.makedirs("downloads", exist_ok=True)
    safe_name = sanitize_filename(record["filename"]) or f"file_{record['id']}"
    output_path = os.path.join("downloads", f"share_{safe_name}")
    try:
        success = run_telegram_op(cached, cached.handler.download_file(record["telegram_message_id"], output_path))
        if not success or not os.path.exists(output_path):
            return jsonify({"success": False, "error": "Download failed"}), 500

        increment_share_download_count(share["id"])

        if share.get("one_time"):
            invalidate_one_time_share(share["id"])

        record_activity(
            share["owner_user_id"], "SHARE_ACCESSED", resource_type="file", resource_id=record["id"],
            metadata={"filename": record["filename"], "share_token": share["share_token"]},
        )
        return send_file(output_path, as_attachment=True, download_name=record["filename"])
    except Exception as exc:
        logger.error("Shared download error: %s", exc)
        return jsonify({"success": False, "error": "Download failed"}), 500
    finally:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass


@app.route("/api/share/<token>/preview", methods=["GET"])
def shared_preview(token):
    share = get_share_by_token(token)
    if not share:
        return jsonify({"success": False, "error": "Access denied"}), 403

    if share.get("revoked_at"):
        return jsonify({"success": False, "error": "Share link has been revoked"}), 403

    if share["expires_at"]:
        try:
            exp = datetime.fromisoformat(share["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            if utcnow() > exp:
                return jsonify({"success": False, "error": "Share link has expired"}), 410
        except (ValueError, TypeError):
            pass

    record = get_file_record(share["file_id"])
    if not record:
        return jsonify({"success": False, "error": "File not found"}), 404

    if record.get("is_deleted"):
        return jsonify({"success": False, "error": "File has been deleted"}), 404

    if record.get("is_vaulted"):
        return jsonify({"success": False, "error": "Access denied"}), 403

    if not share["can_view"]:
        return jsonify({"success": False, "error": "Preview not allowed for this share"}), 403

    if share.get("password_hash"):
        session_key = f"share_pwd_{share['id']}"
        if not session.get(session_key):
            return jsonify({"success": False, "error": "Password required"}), 403

    if share.get("one_time") and share.get("download_count", 0) > 0:
        return jsonify({"success": False, "error": "This one-time link has already been used"}), 410

    mime_type = (record.get("mime_type") or "").lower()
    if not (mime_type.startswith("image/") or mime_type.startswith("video/") or mime_type.startswith("audio/")):
        return jsonify({"success": False, "error": "Preview not available"}), 400

    owner = get_user_by_id(record["user_id"])
    cached = create_telegram_handler_for_user(owner) if owner else None
    if not cached:
        return jsonify({"success": False, "error": "Telegram storage is not configured"}), 503

    os.makedirs("previews", exist_ok=True)
    safe_name = sanitize_filename(record["filename"]) or f"preview_{record['id']}"
    preview_path = os.path.join("previews", f"share_{safe_name}")
    if not os.path.exists(preview_path) or os.path.getsize(preview_path) == 0:
        success = run_telegram_op(cached, cached.handler.download_file(record["telegram_message_id"], preview_path))
        if not success or not os.path.exists(preview_path):
            return jsonify({"success": False, "error": "Preview download failed"}), 500

    update_share_last_accessed(share["id"])

    if share.get("one_time"):
        invalidate_one_time_share(share["id"])

    return send_file(preview_path, mimetype=record.get("mime_type") or None, as_attachment=False)


# ---------------------------------------------------------------------------
# User profile API
# ---------------------------------------------------------------------------

@app.route("/api/user/profile", methods=["GET"])
def get_profile():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    name = (session.get("name") or "").strip()
    if not name:
        name = (user["name"] or "").strip()
    from vault import vault_is_unlocked
    stats = get_file_stats(user["id"], exclude_vaulted=not vault_is_unlocked(user["id"]))
    token_count = len(list_webdav_tokens(user["id"]))
    return jsonify({
        "success": True,
        "user": {
            "id": session.get("user_id"),
            "db_user_id": user["id"],
            "name": name,
            "phone": session.get("phone"),
            "telegram_user_id": session.get("telegram_user_id"),
            "login_time": session.get("login_time"),
            "is_admin": bool(session.get("is_admin")),
            "auth_mode": session.get("auth_mode"),
            "telegram_connected": session.get("telegram_connected"),
            "storage_target": get_storage_chat(),
            "stats": stats,
            "webdav_token_count": token_count,
            "webdav_url": request.host_url.rstrip("/") + "/webdav/",
        },
    }), 200


@app.route("/api/user/profile", methods=["POST"])
def update_profile():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request_payload()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Please enter your name"}), 400
    if len(name) > 80:
        return jsonify({"success": False, "error": "Name must be 80 characters or fewer"}), 400

    update_user_name(user["id"], name)
    user = current_user()
    session["name"] = name
    session["user_name"] = name

    log_activity(user["id"], "profile_update", detail="Display name updated", ip_address=client_ip())
    return jsonify({
        "success": True,
        "message": "Profile updated",
        "user": {
            "id": session.get("user_id"),
            "name": name,
            "email": session.get("email"),
            "phone": session.get("phone"),
            "login_time": session.get("login_time"),
            "is_admin": bool(session.get("is_admin")),
            "auth_mode": session.get("auth_mode"),
            "storage_target": get_storage_chat(),
        },
    }), 200


@app.route("/api/user/activity", methods=["GET"])
def get_activity():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    limit = request.args.get("limit", 50, type=int)
    offset = request.args.get("offset", 0, type=int)
    event_type = request.args.get("event_type")
    resource_type = request.args.get("resource_type")

    from storage_db import get_user_activity
    activities = get_user_activity(
        user["id"], limit=limit, offset=offset,
        event_type=event_type, resource_type=resource_type,
    )

    return jsonify({"success": True, "activities": activities, "total": len(activities)}), 200


# ---------------------------------------------------------------------------
# Storage Intelligence (Phase 6A)
# ---------------------------------------------------------------------------

@app.route("/api/storage/stats", methods=["GET"])
def storage_stats():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    from vault import vault_is_unlocked
    vault_open = vault_is_unlocked(user["id"])

    stats = get_storage_intelligence(user["id"], vault_unlocked=vault_open)
    return jsonify({"success": True, **stats}), 200


# ---------------------------------------------------------------------------
# WebDAV Token Management API
# ---------------------------------------------------------------------------

@app.route("/api/webdav/tokens", methods=["GET"])
def list_webdav_tokens_endpoint():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    from storage_db import list_webdav_tokens
    tokens = list_webdav_tokens(user["id"])
    return jsonify({"success": True, "tokens": tokens}), 200


@app.route("/api/webdav/tokens", methods=["POST"])
def create_webdav_token_endpoint():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    data = request_payload()
    label = (data.get("label") or "default").strip()
    if len(label) > 100:
        return jsonify({"success": False, "error": "Label too long"}), 400
    from storage_db import create_webdav_token
    token = create_webdav_token(user["id"], label=label)
    log_activity(user["id"], "webdav_token_create", detail=label, ip_address=client_ip())
    return jsonify({"success": True, "token": token, "label": label,
                     "message": "Save this token now — it will not be shown again."}), 201


@app.route("/api/webdav/tokens/<int:token_id>", methods=["DELETE"])
def revoke_webdav_token_endpoint(token_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    from storage_db import revoke_webdav_token
    revoke_webdav_token(token_id, user["id"])
    log_activity(user["id"], "webdav_token_revoke", detail=str(token_id), ip_address=client_ip())
    return jsonify({"success": True, "message": "Token revoked"}), 200


@app.route("/api/user/delete-account", methods=["POST"])
def delete_account():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    data = request_payload()
    confirm = data.get("confirm_delete") or ""

    if confirm != "DELETE_MY_ACCOUNT":
        return jsonify({"success": False, "error": "Type DELETE_MY_ACCOUNT to confirm"}), 400

    log_activity(user["id"], "account_deleted", detail="Account permanently deleted", ip_address=client_ip(), user_agent=request.headers.get("User-Agent", ""))
    revoke_all_user_shares(user["id"])
    delete_user_account(user["id"])
    session.clear()
    return jsonify({"success": True, "message": "Account deleted successfully"}), 200


# ---------------------------------------------------------------------------
# Folder API
# ---------------------------------------------------------------------------

@app.route("/api/folders", methods=["GET"])
def list_folders():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    parent_id = request.args.get("parent_id")
    if parent_id:
        try:
            parent_id = int(parent_id)
        except (ValueError, TypeError):
            parent_id = None
    folders = list_user_folders(user["id"], parent_id=parent_id)

    from vault import vault_is_unlocked
    vault_open = vault_is_unlocked(user["id"])
    if not vault_open:
        folders = [f for f in folders if not f.get("is_vaulted")]

    for folder in folders:
        folder["item_count"] = count_folder_items(user["id"], folder["id"])
    return jsonify({"success": True, "folders": folders}), 200


@app.route("/api/folders", methods=["POST"])
def create_folder_endpoint():
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    data = request_payload()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"success": False, "error": "Folder name is required"}), 400
    if len(name) > 200:
        return jsonify({"success": False, "error": "Folder name too long"}), 400
    parent_id = data.get("parent_id")
    if parent_id is not None:
        try:
            parent_id = int(parent_id)
        except (ValueError, TypeError):
            parent_id = None
    folder = create_folder(user["id"], name, parent_id=parent_id)
    log_activity(user["id"], "folder_create", detail=f"Created folder: {name}", ip_address=client_ip())
    record_activity(
        user["id"], "FOLDER_CREATED", resource_type="folder", resource_id=folder["id"],
        metadata={"name": name},
    )
    return jsonify({"success": True, "folder": folder}), 201


@app.route("/api/folders/<int:folder_id>/rename", methods=["POST"])
def rename_folder_endpoint(folder_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    folder = get_folder(folder_id, user["id"])
    if not folder:
        return jsonify({"success": False, "error": "Folder not found"}), 404

    if folder.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    data = request_payload()
    new_name = (data.get("name") or "").strip()
    if not new_name:
        return jsonify({"success": False, "error": "Folder name is required"}), 400
    rename_folder(folder_id, user["id"], new_name)
    log_activity(user["id"], "folder_rename", detail=f"Renamed folder {folder_id} to {new_name}", ip_address=client_ip())
    record_activity(
        user["id"], "FOLDER_RENAMED", resource_type="folder", resource_id=folder_id,
        metadata={"old_name": folder["name"], "new_name": new_name},
    )
    return jsonify({"success": True, "message": "Folder renamed"}), 200


@app.route("/api/folders/<int:folder_id>/delete", methods=["DELETE"])
def delete_folder_endpoint(folder_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    folder = get_folder(folder_id, user["id"])
    if not folder:
        return jsonify({"success": False, "error": "Folder not found"}), 404

    if folder.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    soft_delete_folder(folder_id, user["id"])
    log_activity(user["id"], "folder_delete", detail=f"Deleted folder: {folder['name']}", ip_address=client_ip())
    record_activity(
        user["id"], "FOLDER_DELETED", resource_type="folder", resource_id=folder_id,
        metadata={"name": folder["name"]},
    )
    return jsonify({"success": True, "message": "Folder moved to trash"}), 200


@app.route("/api/folders/<int:folder_id>/restore", methods=["POST"])
def restore_folder_endpoint(folder_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    restore_folder(folder_id, user["id"])
    log_activity(user["id"], "folder_restore", detail=f"Restored folder {folder_id}", ip_address=client_ip())
    record_activity(
        user["id"], "FOLDER_RESTORED", resource_type="folder", resource_id=folder_id,
    )
    return jsonify({"success": True, "message": "Folder restored"}), 200


@app.route("/api/folders/<int:folder_id>/permanent-delete", methods=["DELETE"])
def permanent_delete_folder_endpoint(folder_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    folder = get_folder(folder_id, user["id"])
    if folder and folder.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    permanent_delete_folder(folder_id, user["id"])
    log_activity(user["id"], "folder_permanent_delete", detail=f"Permanently deleted folder {folder_id}", ip_address=client_ip())
    record_activity(
        user["id"], "FOLDER_PERMANENTLY_DELETED", resource_type="folder", resource_id=folder_id,
        metadata={"name": folder["name"] if folder else None},
    )
    return jsonify({"success": True, "message": "Folder permanently deleted"}), 200


@app.route("/api/folders/<int:folder_id>/breadcrumb", methods=["GET"])
def folder_breadcrumb(folder_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    breadcrumb = get_folder_breadcrumb(folder_id, user["id"])
    return jsonify({"success": True, "breadcrumb": breadcrumb}), 200


@app.route("/api/files/<int:file_id>/move", methods=["POST"])
def move_file_endpoint(file_id):
    user = require_auth()
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401
    file = get_user_file_record(file_id, user["id"])
    if not file:
        return jsonify({"success": False, "error": "File not found"}), 404

    if file.get("is_vaulted"):
        from vault import vault_is_unlocked
        if not vault_is_unlocked(user["id"]):
            return jsonify({"success": False, "error": "Vault is locked"}), 403

    data = request_payload()
    folder_id = data.get("folder_id")
    if folder_id is not None:
        try:
            folder_id = int(folder_id)
        except (ValueError, TypeError):
            return jsonify({"success": False, "error": "Invalid folder ID"}), 400
    success = move_file_to_folder(file_id, user["id"], folder_id)
    if not success:
        return jsonify({"success": False, "error": "Folder not found"}), 404
    log_activity(user["id"], "file_move", detail=f"Moved file {file_id} to folder {folder_id}", ip_address=client_ip())
    record_activity(
        user["id"], "FILE_MOVED", resource_type="file", resource_id=file_id,
        metadata={"filename": file["filename"], "folder_id": folder_id},
    )
    return jsonify({"success": True, "message": "File moved"}), 200


# ---------------------------------------------------------------------------
# Legal pages
# ---------------------------------------------------------------------------

@app.route("/privacy")
def privacy_page():
    return render_template("legal.html", title="Privacy Policy", page="privacy")

@app.route("/terms")
def terms_page():
    return render_template("legal.html", title="Terms of Service", page="terms")

@app.route("/support")
def support_page():
    return render_template("legal.html", title="Support", page="support")


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(_error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Resource not found", "code": "NOT_FOUND", "status": 404}), 404
    return redirect(url_for("login"))


@app.errorhandler(413)
def file_too_large(_error):
    max_bytes = app.config.get("MAX_CONTENT_LENGTH") or 0
    max_mb = round(max_bytes / (1024 * 1024), 1) if max_bytes else 0
    return jsonify({"success": False, "error": f"File exceeds the {max_mb} MB upload limit", "code": "FILE_TOO_LARGE"}), 413


@app.errorhandler(500)
def server_error(_error):
    return jsonify({"success": False, "error": "Server error", "code": "INTERNAL_ERROR"}), 500


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug_requested = _is_debug_requested()
    production = _is_production()

    if production and debug_requested:
        print("\n[WARNING] APP_ENV=production but FLASK_DEBUG=True.")
        print("          Debug mode forced OFF for production safety.\n")
        debug_enabled = False
    elif production:
        debug_enabled = False
    else:
        debug_enabled = debug_requested

    print("\n" + "=" * 60)
    print("  SkySync - Telegram Cloud Storage")
    print("=" * 60)
    env_label = "PRODUCTION" if production else "DEVELOPMENT"
    debug_label = "ON" if debug_enabled else "OFF"
    print(f"\n[OK] Server starting...  env={env_label}  debug={debug_label}")
    print(f"[*] Open: http://{host}:{port}")
    print("[*] Telegram per-user authentication + storage enabled\n")

    _load_auth_states()
    app.run(host=host, port=port, debug=debug_enabled, use_reloader=False)
