"""
WebDAV provider that bridges WsgiDAV with SkySync's database and Telegram storage.

Every WebDAV request is associated with exactly one SkySync user via the
environ["wsgidav.auth.user"] key set by the domain controller.
"""
import io
import logging
import os
import tempfile
import time
from datetime import datetime, timezone

from wsgidav.dav_provider import DAVCollection, DAVNonCollection, DAVProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _user_id_from_environ(environ):
    return environ.get("wsgidav.auth.user", {}).get("id")


def _record_activity(user_id, event_type, resource_type=None, resource_id=None, metadata=None):
    """Best-effort activity logging — never raises."""
    try:
        from storage_db import record_activity as _rec
        _rec(user_id, event_type, resource_type=resource_type, resource_id=resource_id, metadata=metadata)
    except Exception:
        pass


def _parse_webdav_path(path):
    """Return (parent_path_parts, name) for a WebDAV path.

    path = "/Documents/College/assignment.pdf"
    ->  (["Documents", "College"], "assignment.pdf")

    path = "/Documents"
    ->  ([], "Documents")
    """
    path = path.strip("/")
    if not path:
        return [], ""
    parts = path.split("/")
    return parts[:-1], parts[-1]


def _normalize_path(path):
    """Normalise a WebDAV path: strip trailing slash, collapse doubles."""
    if not path:
        return "/"
    parts = [p for p in path.split("/") if p]
    return "/" + "/".join(parts)


def _safe_webdav_name(name):
    """Reject traversal attempts or absolute paths."""
    if not name:
        return False
    if ".." in name or name.startswith("/"):
        return False
    if "\x00" in name:
        return False
    return True


def _run_telegram_op(cached_entry, coro, timeout=300):
    """Run a Telegram coroutine on the user's persistent event loop.

    *cached_entry* is a ``_CachedHandler`` from the handler cache.
    Acquires the per-user lock so concurrent WebDAV requests for the same
    user are serialised.  Different users are NOT blocked.
    """
    from telegram_handler import run_telegram_op as _run_op
    return _run_op(cached_entry, coro, timeout=timeout)


# ---------------------------------------------------------------------------
# DAV resource classes
# ---------------------------------------------------------------------------

class SkySyncFolder(DAVCollection):
    """Represents a folder (collection) in SkySync via WebDAV."""

    def __init__(self, path, environ, folder_record=None):
        super().__init__(path, environ)
        self._folder = folder_record  # dict from DB or None for root

    def get_display_name(self):
        if self._folder:
            return self._folder["name"]
        return "SkySync"

    def get_creation_date(self):
        if self._folder and self._folder.get("created_at"):
            try:
                dt = datetime.fromisoformat(self._folder["created_at"])
                return dt.timestamp()
            except (ValueError, TypeError):
                pass
        return time.time()

    def get_last_modified(self):
        return self.get_creation_date()

    def get_etag(self):
        if self._folder:
            return f'{self._folder["id"]}-{self._folder.get("created_at", "")}'
        return 'root'

    def get_content_type(self):
        return "httpd/unix-directory"

    def get_content_length(self):
        return None

    def get_member_names(self):
        user_id = _user_id_from_environ(self.environ)
        if not user_id:
            return []
        from storage_db import list_user_folders, list_user_files
        folder_id = self._folder["id"] if self._folder else None
        subfolders = list_user_folders(user_id, parent_id=folder_id)
        files = list_user_files(user_id)
        # Filter files belonging to this folder
        folder_files = [f for f in files if (f.get("folder_id") == folder_id) or (folder_id is None and not f.get("folder_id"))]
        names = [f["name"] for f in subfolders] + [f["filename"] for f in folder_files]
        return names

    def get_member(self, name):
        user_id = _user_id_from_environ(self.environ)
        if not user_id:
            return None
        from storage_db import list_user_folders, get_folder, get_user_file_record, get_file_record
        folder_id = self._folder["id"] if self._folder else None

        vault_unlocked = False
        try:
            from vault import vault_is_unlocked
            vault_unlocked = vault_is_unlocked(user_id)
        except Exception:
            pass

        subfolders = list_user_folders(user_id, parent_id=folder_id)
        for sf in subfolders:
            if sf["name"] == name:
                if sf.get("is_vaulted") and not vault_unlocked:
                    return None
                child_path = self.path.rstrip("/") + "/" + name
                return SkySyncFolder(child_path, self.environ, sf)
        files_all = list_user_files(user_id)
        for f in files_all:
            if f["filename"] == name and (f.get("folder_id") == folder_id or (folder_id is None and not f.get("folder_id"))):
                if f.get("is_vaulted") and not vault_unlocked:
                    return None
                child_path = self.path.rstrip("/") + "/" + name
                return SkySyncFile(child_path, self.environ, f)
        return None

    def get_member_list(self):
        user_id = _user_id_from_environ(self.environ)
        if not user_id:
            return []
        from storage_db import list_user_folders, list_user_files
        folder_id = self._folder["id"] if self._folder else None

        vault_unlocked = False
        try:
            from vault import vault_is_unlocked
            vault_unlocked = vault_is_unlocked(user_id)
        except Exception:
            pass

        subfolders = list_user_folders(user_id, parent_id=folder_id)
        files_all = list_user_files(user_id)
        folder_files = [f for f in files_all if (f.get("folder_id") == folder_id) or (folder_id is None and not f.get("folder_id"))]
        members = []
        for sf in subfolders:
            if sf.get("is_vaulted") and not vault_unlocked:
                continue
            child_path = self.path.rstrip("/") + "/" + sf["name"]
            members.append(SkySyncFolder(child_path, self.environ, sf))
        for f in folder_files:
            if f.get("is_vaulted") and not vault_unlocked:
                continue
            child_path = self.path.rstrip("/") + "/" + f["filename"]
            members.append(SkySyncFile(child_path, self.environ, f))
        return members

    def create_collection(self, name):
        if not _safe_webdav_name(name):
            from wsgidav.dav_provider import DAVError
            from wsgidav.util import get_dict_value
            raise DAVError(400, "Invalid folder name")
        user_id = _user_id_from_environ(self.environ)
        if not user_id:
            from wsgidav.dav_provider import DAVError
            raise DAVError(403, "Forbidden")
        from storage_db import create_folder, log_activity
        parent_id = self._folder["id"] if self._folder else None
        create_folder(user_id, name, parent_id=parent_id)
        log_activity(user_id, "webdav_create_folder", detail=name)
        _record_activity(user_id, "WEBDAV_FOLDER_CREATED", resource_type="folder", metadata={"name": name})
        child_path = self.path.rstrip("/") + "/" + name
        new_folder = {"id": None, "name": name, "parent_id": parent_id, "created_at": datetime.now(timezone.utc).isoformat()}
        return SkySyncFolder(child_path, self.environ, new_folder)

    def create_empty_resource(self, name):
        if not _safe_webdav_name(name):
            from wsgidav.dav_provider import DAVError
            raise DAVError(400, "Invalid file name")
        user_id = _user_id_from_environ(self.environ)
        if not user_id:
            from wsgidav.dav_provider import DAVError
            raise DAVError(403, "Forbidden")
        from storage_db import log_activity
        log_activity(user_id, "webdav_create_empty", detail=name)
        folder_id = self._folder["id"] if self._folder else None
        file_record = {"id": None, "filename": name, "folder_id": folder_id, "size": 0,
                        "mime_type": None, "uploaded_at": datetime.now(timezone.utc).isoformat()}
        child_path = self.path.rstrip("/") + "/" + name
        return SkySyncFile(child_path, self.environ, file_record)

    def delete(self):
        user_id = _user_id_from_environ(self.environ)
        if not user_id or not self._folder:
            from wsgidav.dav_provider import DAVError
            raise DAVError(403, "Cannot delete root")

        if self._folder.get("is_vaulted"):
            try:
                from vault import vault_is_unlocked
                if not vault_is_unlocked(user_id):
                    from wsgidav.dav_provider import DAVError
                    raise DAVError(403, "Vault is locked")
            except Exception:
                pass

        from storage_db import soft_delete_folder, log_activity
        try:
            soft_delete_folder(self._folder["id"], user_id)
            log_activity(user_id, "webdav_delete_folder", detail=self._folder["name"])
            _record_activity(user_id, "WEBDAV_DELETE", resource_type="folder", resource_id=self._folder["id"], metadata={"name": self._folder["name"]})
        except Exception as exc:
            logger.error("WebDAV folder delete failed: %s", exc)
            from wsgidav.dav_provider import DAVError
            raise DAVError(500, str(exc)) from exc

    def handle_move(self, dest_path):
        user_id = _user_id_from_environ(self.environ)
        if not user_id or not self._folder:
            from wsgidav.dav_provider import DAVError
            raise DAVError(403, "Cannot move root")

        if self._folder.get("is_vaulted"):
            try:
                from vault import vault_is_unlocked
                if not vault_is_unlocked(user_id):
                    from wsgidav.dav_provider import DAVError
                    raise DAVError(403, "Vault is locked")
            except Exception:
                pass

        _, new_name = _parse_webdav_path(dest_path)
        if not new_name or not _safe_webdav_name(new_name):
            from wsgidav.dav_provider import DAVError
            raise DAVError(400, "Invalid destination name")
        from storage_db import rename_folder, log_activity
        rename_folder(self._folder["id"], user_id, new_name)
        log_activity(user_id, "webdav_rename_folder", detail=f"{self._folder['name']} -> {new_name}")
        _record_activity(user_id, "WEBDAV_MOVE", resource_type="folder", resource_id=self._folder["id"], metadata={"old_name": self._folder["name"], "new_name": new_name})
        return True

    def copy_move_single(self, dest_path, *, is_move):
        if is_move:
            return self.handle_move(dest_path)
        else:
            from wsgidav.dav_provider import DAVError
            raise DAVError(405, "Copy not supported for folders")

    def support_recursive_move(self, dest_path):
        return True

    def move_recursive(self, dest_path):
        return self.handle_move(dest_path)

    def support_recursive_delete(self):
        return False

    def handle_delete(self):
        self.delete()
        return True


class SkySyncFile(DAVNonCollection):
    """Represents a file (non-collection) in SkySync via WebDAV."""

    def __init__(self, path, environ, file_record=None):
        super().__init__(path, environ)
        self._record = file_record  # dict from DB or None

    def get_display_name(self):
        if self._record:
            return self._record.get("filename", "file")
        return "file"

    def get_creation_date(self):
        if self._record and self._record.get("uploaded_at"):
            try:
                dt = datetime.fromisoformat(self._record["uploaded_at"])
                return dt.timestamp()
            except (ValueError, TypeError):
                pass
        return time.time()

    def get_last_modified(self):
        return self.get_creation_date()

    def get_etag(self):
        if self._record:
            return f'{self._record.get("id", 0)}-{self._record.get("size", 0)}'
        return '0-0'

    def get_content_type(self):
        if self._record:
            return self._record.get("mime_type") or "application/octet-stream"
        return "application/octet-stream"

    def get_content_length(self):
        if self._record:
            return self._record.get("size", 0)
        return 0

    def support_etag(self):
        return True

    def support_ranges(self):
        return True

    def get_content(self):
        if not self._record or not self._record.get("telegram_message_id"):
            return io.BytesIO(b"")
        user_id = _user_id_from_environ(self.environ)
        if not user_id:
            return io.BytesIO(b"")

        if self._record.get("is_vaulted"):
            try:
                from vault import vault_is_unlocked
                if not vault_is_unlocked(user_id):
                    from wsgidav.dav_provider import DAVError
                    raise DAVError(403, "Vault is locked")
            except Exception:
                pass

        from storage_db import get_user_by_id
        from telegram_handler import create_telegram_handler_for_user
        user = get_user_by_id(user_id)
        if not user:
            return io.BytesIO(b"")
        cached = create_telegram_handler_for_user(user)
        if not cached:
            return io.BytesIO(b"")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".tmp")
        tmp_path = tmp.name
        tmp.close()
        try:
            success = _run_telegram_op(
                cached,
                cached.handler.download_file(self._record["telegram_message_id"], tmp_path),
            )
            if not success:
                return io.BytesIO(b"")
            with open(tmp_path, "rb") as f:
                data = f.read()
            _record_activity(user_id, "WEBDAV_DOWNLOAD", resource_type="file", resource_id=self._record.get("id"), metadata={"filename": self._record.get("filename")})
            return io.BytesIO(data)
        except Exception as exc:
            logger.error("WebDAV download failed: %s", exc)
            return io.BytesIO(b"")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def begin_write(self, *, content_type=None):
        user_id = _user_id_from_environ(self.environ)
        if self._record and self._record.get("is_vaulted"):
            try:
                from vault import vault_is_unlocked
                if not vault_is_unlocked(user_id):
                    from wsgidav.dav_provider import DAVError
                    raise DAVError(403, "Vault is locked")
            except Exception:
                pass
        self._tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".webdav_upload")
        self._content_type = content_type
        return self._tmp_file

    def end_write(self, *, with_errors=False):
        tmp_file = getattr(self, "_tmp_file", None)
        if not tmp_file or with_errors:
            if tmp_file:
                try:
                    tmp_file.close()
                    os.unlink(tmp_file.name)
                except OSError:
                    pass
            return
        tmp_path = tmp_file.name
        tmp_file.close()
        user_id = _user_id_from_environ(self.environ)
        if not user_id:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return
        from storage_db import get_user_by_id, create_file_record, move_file_to_folder, log_activity
        from telegram_handler import create_telegram_handler_for_user
        user = get_user_by_id(user_id)
        if not user:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return
        _cached = create_telegram_handler_for_user(user)
        logger.info("end_write: got cached handler=0x%x for user=%s", id(_cached) if _cached else 0, user_id)
        cached = _cached
        if not cached:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            return
        filename = self._record.get("filename", os.path.basename(tmp_path)) if self._record else os.path.basename(tmp_path)
        size = os.path.getsize(tmp_path)
        t_start = time.monotonic()
        try:
            logger.info("end_write: uploading for user=%s, file=%s (size=%d)", user_id, filename, size)
            result = _run_telegram_op(
                cached,
                cached.handler.send_file(tmp_path, caption=f"WebDAV upload: {filename}"),
            )
            elapsed = int((time.monotonic()-t_start)*1000)
            logger.info("end_write: completed in %dms, result=%s", elapsed, "ok" if result else "None")
        except Exception as exc:
            elapsed = int((time.monotonic()-t_start)*1000)
            logger.error("WebDAV upload failed: %s (%dms)", exc, elapsed)
            result = None
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        if not result:
            return
        record = create_file_record(
            user_id=user_id,
            telegram_message_id=result["message_id"],
            filename=filename,
            mime_type=self._content_type or "application/octet-stream",
            size=size,
        )
        folder_id = self._record.get("folder_id") if self._record else None
        if folder_id and record:
            move_file_to_folder(record["id"], user_id, folder_id)
        log_activity(user_id, "webdav_upload", detail=filename)
        _record_activity(user_id, "WEBDAV_UPLOAD", resource_type="file", resource_id=record["id"] if record else None, metadata={"filename": filename, "size": size})

    def delete(self):
        user_id = _user_id_from_environ(self.environ)
        if not user_id or not self._record or not self._record.get("id"):
            from wsgidav.dav_provider import DAVError
            raise DAVError(403, "Cannot delete")

        if self._record.get("is_vaulted"):
            try:
                from vault import vault_is_unlocked
                if not vault_is_unlocked(user_id):
                    from wsgidav.dav_provider import DAVError
                    raise DAVError(403, "Vault is locked")
            except Exception:
                pass

        from storage_db import soft_delete_file, log_activity
        soft_delete_file(self._record["id"], user_id)
        log_activity(user_id, "webdav_delete_file", detail=self._record.get("filename"))
        _record_activity(user_id, "WEBDAV_DELETE", resource_type="file", resource_id=self._record["id"], metadata={"filename": self._record.get("filename")})

    def handle_move(self, dest_path):
        user_id = _user_id_from_environ(self.environ)
        if not user_id or not self._record or not self._record.get("id"):
            from wsgidav.dav_provider import DAVError
            raise DAVError(403, "Cannot move")

        if self._record.get("is_vaulted"):
            try:
                from vault import vault_is_unlocked
                if not vault_is_unlocked(user_id):
                    from wsgidav.dav_provider import DAVError
                    raise DAVError(403, "Vault is locked")
            except Exception:
                pass

        _, new_name = _parse_webdav_path(dest_path)
        if not new_name or not _safe_webdav_name(new_name):
            from wsgidav.dav_provider import DAVError
            raise DAVError(400, "Invalid destination name")
        from storage_db import update_file_record_name, log_activity
        old_name = self._record.get("filename", "")
        update_file_record_name(self._record["id"], user_id, new_name)
        log_activity(user_id, "webdav_rename_file", detail=f"{old_name} -> {new_name}")
        _record_activity(user_id, "WEBDAV_MOVE", resource_type="file", resource_id=self._record["id"], metadata={"old_name": old_name, "new_name": new_name})
        return True

    def copy_move_single(self, dest_path, *, is_move):
        if is_move:
            return self.handle_move(dest_path)
        else:
            from wsgidav.dav_provider import DAVError
            raise DAVError(405, "Copy not supported")

    def support_recursive_move(self, dest_path):
        return True

    def move_recursive(self, dest_path):
        return self.handle_move(dest_path)

    def handle_delete(self):
        self.delete()
        return True


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class SkySyncDAVProvider(DAVProvider):
    """WebDAV provider backed by SkySync database + Telegram storage.

    The root ("/") is the authenticated user's storage root.
    """

    def __init__(self):
        super().__init__()

    def is_readonly(self):
        return False

    def get_resource_inst(self, path, environ):
        path = _normalize_path(path)
        user_id = _user_id_from_environ(environ)
        if not user_id:
            return None

        if path == "/":
            return SkySyncFolder("/", environ, None)

        parent_parts, name = _parse_webdav_path(path)
        if not name:
            return SkySyncFolder("/", environ, None)

        # Navigate the folder tree to find the parent, then look up name
        from storage_db import list_user_folders, list_user_files

        current_folder_id = None
        for part in parent_parts:
            subfolders = list_user_folders(user_id, parent_id=current_folder_id)
            found = False
            for sf in subfolders:
                if sf["name"] == part:
                    current_folder_id = sf["id"]
                    found = True
                    break
            if not found:
                return None

        # Look up the final name
        subfolders = list_user_folders(user_id, parent_id=current_folder_id)
        for sf in subfolders:
            if sf["name"] == name:
                return SkySyncFolder(path, environ, sf)

        files = list_user_files(user_id)
        for f in files:
            if f["filename"] == name and (f.get("folder_id") == current_folder_id or (current_folder_id is None and not f.get("folder_id"))):
                return SkySyncFile(path, environ, f)

        return None

    def exists(self, path, environ):
        return self.get_resource_inst(path, environ) is not None

    def is_collection(self, path, environ):
        resource = self.get_resource_inst(path, environ)
        if resource is None:
            return False
        return isinstance(resource, SkySyncFolder)
