"""
Telegram authentication handler.
Handles login, OTP verification, 2FA, and persistent session creation.
"""
import asyncio
import os
import secrets
import shutil

from telethon import TelegramClient
from telethon.errors import (
    ApiIdInvalidError,
    FloodWaitError,
    PasswordHashInvalidError,
    PhoneCodeExpiredError,
    PhoneCodeHashEmptyError,
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    PhoneNumberUnoccupiedError,
    SessionPasswordNeededError,
)
from telethon.tl.types.auth import (
    SentCodeTypeApp,
    SentCodeTypeCall,
    SentCodeTypeEmailCode,
    SentCodeTypeFlashCall,
    SentCodeTypeMissedCall,
    SentCodeTypeSms,
)
import logging

logger = logging.getLogger(__name__)

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "telegram_sessions")


def _ensure_sessions_dir():
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    try:
        os.chmod(SESSIONS_DIR, 0o700)
    except (OSError, AttributeError):
        pass


class TelegramAuthHandler:
    """Handles Telegram authentication flow"""

    def __init__(self, api_id, api_hash, phone_number):
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone_number = phone_number
        self.client_hash = None
        phone_digits = "".join(ch for ch in phone_number if ch.isdigit())
        self.session_name = f'auth_session_{phone_digits}_{secrets.token_hex(8)}'
        self.client = None

    def _delivery_details(self, sent_code):
        """Describe how Telegram says the code will arrive."""
        sent_type = getattr(sent_code, "type", None)
        if isinstance(sent_type, SentCodeTypeApp):
            return {
                "channel": "telegram_app",
                "message": "Code sent to your Telegram app",
                "hint": "Open Telegram on a device already logged into this phone number and look for a login code from Telegram.",
            }
        if isinstance(sent_type, SentCodeTypeSms):
            return {
                "channel": "sms",
                "message": "Code sent by SMS",
                "hint": "Check the SMS inbox for this phone number.",
            }
        if isinstance(sent_type, SentCodeTypeCall):
            return {
                "channel": "call",
                "message": "Code will arrive by phone call",
                "hint": "Telegram will call this phone number with the login code.",
            }
        if isinstance(sent_type, SentCodeTypeFlashCall):
            return {
                "channel": "flash_call",
                "message": "Code will arrive by flash call",
                "hint": "Telegram may place a brief verification call to this number.",
            }
        if isinstance(sent_type, SentCodeTypeMissedCall):
            return {
                "channel": "missed_call",
                "message": "Code will arrive by missed call verification",
                "hint": "Telegram may verify using a missed call to this phone number.",
            }
        if isinstance(sent_type, SentCodeTypeEmailCode):
            return {
                "channel": "email",
                "message": "Code sent by Telegram email verification",
                "hint": "Check the recovery email linked to this Telegram account.",
            }
        return {
            "channel": "unknown",
            "message": "Code requested from Telegram",
            "hint": "Check Telegram for the verification code.",
        }

    def _build_client(self):
        """Create a client bound to the current auth session file."""
        return TelegramClient(self.session_name, self.api_id, self.api_hash)

    def _friendly_error(self, error):
        """Convert Telethon errors into user-facing auth messages."""
        if isinstance(error, ApiIdInvalidError):
            return "Telegram API credentials are invalid. Update TELEGRAM_API_ID and TELEGRAM_API_HASH."
        if isinstance(error, PhoneNumberInvalidError):
            return "Phone number is invalid. Use international format like +919876543210."
        if isinstance(error, PhoneNumberUnoccupiedError):
            return "This phone number is not registered on Telegram. Use the Telegram bot channel instead, or register the number in Telegram first."
        if isinstance(error, PhoneCodeInvalidError):
            return "The Telegram code is invalid. Please check the code in your Telegram app and try again."
        if isinstance(error, PhoneCodeExpiredError):
            return "The Telegram code expired. Request a new code and try again."
        if isinstance(error, PhoneCodeHashEmptyError):
            return "The Telegram code hash is missing. Request a new code and try again."
        if isinstance(error, PasswordHashInvalidError):
            return "The Telegram 2FA password is incorrect."
        if isinstance(error, FloodWaitError):
            return f"Too many attempts. Please wait {error.seconds} seconds before requesting another code."
        if isinstance(error, ConnectionError):
            return "Could not connect to Telegram. Check your internet connection and allow this app through the firewall."
        if isinstance(error, PermissionError):
            return "Telegram connection was blocked by the operating system or firewall."
        return str(error)

    def _error_payload(self, error):
        """Build a structured delivery/error dict with retry information."""
        message = self._friendly_error(error)
        payload = {
            "channel": "telegram_app",
            "message": message,
            "hint": "Telegram limits how often codes can be requested for a phone number. Wait for the cooldown or use the Telegram bot channel.",
        }
        if isinstance(error, FloodWaitError):
            payload["retry_after"] = getattr(error, "seconds", None)
        return payload

    async def _disconnect_client(self):
        """Close the active client safely and clear the reference."""
        client = self.client
        self.client = None
        if not client:
            return
        try:
            if client.is_connected():
                await client.disconnect()
        except Exception as exc:
            logger.warning(f"Error disconnecting Telegram client for {self.phone_number}: {exc}")
    
    async def request_login_code(self, force_sms=False):
        """Request login code from Telegram.

        Returns (True, delivery_dict) on success or (False, error_dict) on failure.
        The client stays connected on success so verify_code can reuse it.
        """
        try:
            logger.info("Initializing TelegramClient for phone_hash=%s", str(hash(str(self.phone_number)))[:8])
            self.client = self._build_client()
            logger.info("Connecting to Telegram...")
            await self.client.connect()
            logger.info("Connected. Sending code request...")

            # Request phone code
            result = await self.client.send_code_request(self.phone_number, force_sms=force_sms)

            # Store hash for verification
            self.client_hash = result.phone_code_hash
            delivery = self._delivery_details(result)

            logger.info("Login code sent to %s via %s", self.phone_number, delivery["channel"])
            # Client stays connected for verify_code to reuse
            return True, delivery

        except FloodWaitError as exc:
            logger.warning(
                "Flood wait %ss while requesting code for %s", exc.seconds, self.phone_number
            )
            return False, self._error_payload(exc)
        except Exception as e:
            logger.error("Error requesting code: %s: %s", type(e).__name__, e)
            return False, self._error_payload(e)
        finally:
            # Disconnect only on error (success keeps client alive for verify_code)
            if not self.client_hash:
                await self._disconnect_client()

    async def _ensure_client(self):
        """Create a fresh client for the current event loop.

        Telethon clients are bound to the event loop they were created on.
        Since run_async() creates a new event loop per HTTP request, we must
        always create a new client. The phone_code_hash (stored on self) survives
        across client instances.
        """
        # Disconnect old client if any
        if self.client:
            try:
                if self.client.is_connected():
                    await self.client.disconnect()
            except Exception:
                pass
        # Create a fresh client on the current event loop
        self.client = self._build_client()
        await self.client.connect()

    async def verify_code(self, code):
        """Verify the login code"""
        try:
            await self._ensure_client()

            # Sign in with code
            await self.client.sign_in(self.phone_number, code, phone_code_hash=self.client_hash)

            # Get user info
            me = await self.client.get_me()
            logger.info("User authenticated: %s (%s)", me.first_name, me.phone)

            # Keep client connected for file operations
            return True, {
                'user_id': me.id,
                'first_name': me.first_name,
                'last_name': me.last_name or '',
                'phone': me.phone,
                'username': me.username or ''
            }

        except SessionPasswordNeededError:
            logger.warning("2FA password required")
            return False, "2FA_REQUIRED"
        except Exception as e:
            logger.error("Error verifying code: %s", e)
            await self._disconnect_client()
            return False, self._friendly_error(e)

    async def verify_2fa_password(self, password):
        """Verify 2FA password"""
        try:
            await self._ensure_client()

            # Sign in with password
            await self.client.sign_in(password=password)

            # Get user info
            me = await self.client.get_me()
            logger.info("User authenticated with 2FA: %s", me.first_name)

            return True, {
                'user_id': me.id,
                'first_name': me.first_name,
                'last_name': me.last_name or '',
                'phone': me.phone,
                'username': me.username or ''
            }

        except Exception as e:
            logger.error("Error verifying 2FA: %s", e)
            await self._disconnect_client()
            return False, self._friendly_error(e)
    
    async def disconnect(self):
        """Disconnect client safely, handling event loop changes."""
        if not self.client:
            return
        try:
            if self.client.is_connected():
                await self.client.disconnect()
            logger.info("Disconnected from Telegram for %s", self.phone_number)
        except Exception:
            # Client may be on a different event loop; just clear the reference
            self.client = None

    def cleanup_session_files(self):
        """Remove temporary Telethon auth session files after a flow finishes."""
        for suffix in ("", "-journal"):
            path = f"{self.session_name}.session{suffix}"
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as exc:
                logger.warning("Could not remove temporary auth session %s: %s", path, exc)

    def create_persistent_session(self, telegram_user_id):
        """Move the temporary auth session to a persistent location.

        Returns the persistent session file path, or None on failure.
        """
        _ensure_sessions_dir()
        safe_name = f"user_{telegram_user_id}_{secrets.token_hex(8)}"
        persistent_path = os.path.join(SESSIONS_DIR, f"{safe_name}.session")
        temp_path = f"{self.session_name}.session"
        temp_journal = f"{self.session_name}.session-journal"

        if not os.path.exists(temp_path):
            logger.error("Temp session file not found: %s", temp_path)
            return None

        try:
            shutil.move(temp_path, persistent_path)
            for journal_suffix in ("-journal", "-wal", "-shm"):
                src = f"{self.session_name}.session{journal_suffix}"
                dst = f"{persistent_path}{journal_suffix}"
                if os.path.exists(src):
                    shutil.move(src, dst)
            try:
                os.chmod(persistent_path, 0o600)
            except (OSError, AttributeError):
                pass
            logger.info("Persistent session created for telegram_user_id=%s", telegram_user_id)
            return persistent_path
        except OSError as exc:
            logger.error("Failed to create persistent session: %s", exc)
            return None

    def get_session_path(self):
        """Get the path to the current temporary session file."""
        return f"{self.session_name}.session"
