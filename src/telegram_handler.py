"""
Telegram handler for file management.
Uses Telethon to interact with Telegram API with per-user session isolation.
"""
import os
import secrets
from telethon import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

SESSIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "telegram_sessions")


def _ensure_sessions_dir():
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    try:
        os.chmod(SESSIONS_DIR, 0o700)
    except (OSError, AttributeError):
        pass


def generate_session_path(telegram_user_id):
    """Generate a safe, non-identifying session file path for a Telegram user."""
    _ensure_sessions_dir()
    safe_name = f"user_{telegram_user_id}_{secrets.token_hex(8)}"
    return os.path.join(SESSIONS_DIR, f"{safe_name}.session")


def validate_session_path(session_path):
    """Ensure a session path is inside the sessions directory and not traversable."""
    if not session_path:
        return False
    real_sessions = os.path.realpath(SESSIONS_DIR)
    try:
        real_path = os.path.realpath(session_path)
    except (OSError, ValueError):
        return False
    return real_path.startswith(real_sessions + os.sep) or real_path == real_sessions


class TelegramHandler:
    def __init__(self, api_id, api_hash, session_name_or_path, target_chat=None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.target_chat = target_chat or os.getenv('TELEGRAM_TARGET_CHAT', 'me').strip()
        if os.path.isabs(session_name_or_path) and session_name_or_path.endswith('.session'):
            self.session_path = session_name_or_path
            self.session_name = session_name_or_path[:-8] if session_name_or_path.endswith('.session') else session_name_or_path
        else:
            self.session_name = session_name_or_path
            self.session_path = None
        self.client = None

    def _build_client(self):
        """Create a fresh client for the current request/event loop."""
        if self.session_path:
            base = self.session_path[:-8] if self.session_path.endswith('.session') else self.session_path
            return TelegramClient(base, self.api_id, self.api_hash)
        return TelegramClient(self.session_name, self.api_id, self.api_hash)

    async def _resolve_target_entity(self, client):
        """Resolve the configured Telegram storage destination."""
        target = self.target_chat or 'me'
        normalized = target.strip()
        lowered = normalized.lower()

        if lowered in {'me', 'saved', 'saved messages', 'saved_messages'}:
            return 'me'

        if normalized.lstrip('-').isdigit():
            return await client.get_entity(int(normalized))

        async for dialog in client.iter_dialogs():
            username = getattr(dialog.entity, 'username', '') or ''
            title = dialog.name or ''
            if username.lower() == lowered or title.lower() == lowered:
                return dialog.entity

        raise ValueError(
            f"Configured Telegram target '{target}' was not found. "
            "Set TELEGRAM_TARGET_CHAT to an exact chat title, username, or numeric chat id."
        )

    async def _run_with_client(self, operation):
        """Run a Telegram operation with a short-lived client."""
        client = self._build_client()
        try:
            await client.connect()
            if not await client.is_user_authorized():
                logger.warning("Telegram session is not authorized for %s", self.session_name)
                return None

            self.client = client
            return await operation(client)
        except Exception as e:
            logger.error("Telegram operation failed for %s: %s: %s", self.session_name, type(e).__name__, e)
            return None
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass
            self.client = None

    async def check_authorized(self):
        """Check if the stored session is still authorized."""
        client = self._build_client()
        try:
            await client.connect()
            return await client.is_user_authorized()
        except Exception:
            return False
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

    async def get_saved_messages(self, limit=100):
        """Get messages from the configured Telegram storage chat."""
        async def operation(client):
            files = []
            target_entity = await self._resolve_target_entity(client)

            history = await client(GetHistoryRequest(
                peer=target_entity,
                offset_id=0,
                offset_date=None,
                add_offset=0,
                limit=limit,
                max_id=0,
                min_id=0,
                hash=0
            ))

            for message in history.messages:
                file_info = self._extract_file_info(message)
                if file_info:
                    files.append(file_info)

            return files

        result = await self._run_with_client(operation)
        return result or []

    def _extract_file_info(self, message):
        """Extract file information from a message"""
        try:
            media = message.media
            if not media:
                return None

            file_info = {
                'id': message.id,
                'message_id': message.id,
                'name': 'Unknown',
                'type': 'document',
                'size': 0,
                'date': message.date.isoformat() if message.date else datetime.now().isoformat(),
                'mime_type': None,
                'caption': message.message or '',
            }

            media_class = media.__class__.__name__

            if media_class == 'MessageMediaDocument':
                doc = media.document
                file_info['size'] = doc.size if hasattr(doc, 'size') else 0
                file_info['mime_type'] = doc.mime_type if hasattr(doc, 'mime_type') else 'application/octet-stream'

                mime = file_info['mime_type'] or ''
                if 'image' in mime:
                    file_info['type'] = 'image'
                    file_info['name'] = self._get_filename(doc) or 'photo.jpg'
                elif 'video' in mime:
                    file_info['type'] = 'video'
                    file_info['name'] = self._get_filename(doc) or 'video.mp4'
                elif 'audio' in mime:
                    file_info['type'] = 'audio'
                    file_info['name'] = self._get_filename(doc) or 'audio.mp3'
                else:
                    file_info['type'] = 'document'
                    file_info['name'] = self._get_filename(doc) or 'document'

            elif media_class == 'MessageMediaPhoto':
                file_info['type'] = 'image'
                if hasattr(media, 'photo') and hasattr(media.photo, 'size'):
                    file_info['size'] = media.photo.size
                file_info['name'] = f"photo_{message.id}.jpg"

            elif media_class == 'MessageMediaVideo':
                file_info['type'] = 'video'
                if hasattr(media, 'video') and hasattr(media.video, 'size'):
                    file_info['size'] = media.video.size
                file_info['name'] = f"video_{message.id}.mp4"

            elif media_class == 'MessageMediaAudio':
                file_info['type'] = 'audio'
                if hasattr(media, 'audio') and hasattr(media.audio, 'size'):
                    file_info['size'] = media.audio.size
                file_info['name'] = f"audio_{message.id}.mp3"

            return file_info

        except Exception as e:
            logger.error("Error extracting file info: %s", e)
            return None

    def _get_filename(self, document):
        """Extract filename from document attributes"""
        try:
            for attr in document.attributes:
                if hasattr(attr, 'file_name'):
                    return attr.file_name
        except Exception:
            pass
        return None

    async def download_file(self, message_id, output_path):
        """Download a file from Telegram"""
        async def operation(client):
            target_entity = await self._resolve_target_entity(client)
            message = await client.get_messages(target_entity, ids=message_id)
            if not message:
                return False

            if isinstance(message, (list, tuple)):
                message = message[0] if message else None
            elif hasattr(message, "__iter__") and not hasattr(message, "media"):
                message = next(iter(message), None)

            if message and getattr(message, "media", None):
                await client.download_media(message, file=output_path)
                return True

            return False

        return bool(await self._run_with_client(operation))

    async def send_file(self, file_path, caption=""):
        """Upload file to the configured Telegram storage chat."""
        async def operation(client):
            target_entity = await self._resolve_target_entity(client)
            message = await client.send_file(target_entity, file=file_path, caption=caption)
            return {
                'message_id': message.id,
                'date': message.date.isoformat() if message.date else None,
            }

        return await self._run_with_client(operation)

    async def delete_message(self, message_id):
        """Delete a message from Telegram"""
        async def operation(client):
            target_entity = await self._resolve_target_entity(client)
            await client.delete_messages(target_entity, [message_id])
            return True

        return bool(await self._run_with_client(operation))


def create_telegram_handler_for_user(user):
    """Create a TelegramHandler using a user's stored session."""
    session_path = user.get("session_path")
    if not session_path or not os.path.exists(session_path):
        logger.warning("No valid session for user %s", user.get("id"))
        return None
    if not validate_session_path(session_path):
        logger.warning("Session path validation failed for user %s", user.get("id"))
        return None
    api_id = int(os.getenv('TELEGRAM_API_ID', '0'))
    api_hash = os.getenv('TELEGRAM_API_HASH', '').strip()
    if not api_id or not api_hash:
        logger.warning("Telegram API credentials not configured")
        return None
    try:
        return TelegramHandler(api_id, api_hash, session_path)
    except Exception as exc:
        logger.error("Failed to create Telegram handler: %s", exc)
        return None


def create_telegram_handler(phone_number):
    """Legacy factory: create handler by phone (for backward compatibility)."""
    if not phone_number:
        return None
    api_id = int(os.getenv('TELEGRAM_API_ID', '0'))
    api_hash = os.getenv('TELEGRAM_API_HASH', '').strip()
    if not api_id or not api_hash:
        logger.warning("Telegram API credentials not configured")
        return None
    try:
        return TelegramHandler(api_id, api_hash, f'session_{phone_number.replace("+", "")}')
    except Exception as exc:
        logger.error("Failed to create Telegram handler: %s", exc)
        return None
