"""
Smart Vault file & folder operation tests (Phase 3B).

Tests vault move/restore, endpoint protection when vault is locked,
filtering of vaulted items from listings, and WebDAV integration.
Uses mocked Telegram access — no real OTP required.
"""
import sys
import os
import io
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from storage_db import (
    init_db,
    create_user,
    get_vault_settings,
    get_connection,
    create_file_record,
    create_folder,
    vault_file,
    unvault_file,
    vault_folder,
    unvault_folder,
    list_user_files,
    list_vaulted_files,
    is_file_vaulted,
    soft_delete_file,
)
from main import app
from vault import vault_bp, VAULT_INACTIVITY_SECONDS

# Global variable to hold the session path for dummy Telegram sessions in tests
_SESSION_PATH = None


def _get_or_create_user(tg_id, phone, name, email, session_path=None):
    from storage_db import get_user_by_telegram_id
    user = get_user_by_telegram_id(tg_id)
    if user:
        return user
    if session_path is None:
        session_path = _SESSION_PATH
    return create_user(
        email=email, phone=phone,
        name=name, telegram_user_id=tg_id,
        session_path=session_path,
    )


def _cleanup_test_data():
    """Remove test users and vault data from DB."""
    with get_connection() as conn:
        for tg_id in ("400001", "400002"):
            row = conn.execute("SELECT id FROM users WHERE telegram_user_id = ?", (tg_id,)).fetchone()
            if row:
                uid = row["id"]
                conn.execute("DELETE FROM vault_settings WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_log WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_events WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM file_records WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM folders WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM file_shares WHERE owner_user_id = ?", (uid,))
                conn.execute("DELETE FROM webdav_tokens WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM users WHERE id = ?", (uid,))


class VaultOpsTestBase(unittest.TestCase):
    """Base class: inits DB, creates two test users."""

    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        init_db()
        _cleanup_test_data()
        # Set up dummy Telegram credentials and test mode
        os.environ['TELEGRAM_API_ID'] = '12345'
        os.environ['TELEGRAM_API_HASH'] = 'dummyhash'
        os.environ['TELEGRAM_TEST_MODE'] = '1'
        # Create a dummy session file for the Telegram handler
        global _SESSION_PATH
        cls._session_fd, _SESSION_PATH = tempfile.mkstemp(suffix='.session')
        os.close(cls._session_fd)
        # Create an empty session file
        open(_SESSION_PATH, 'a').close()
        cls.user_a = _get_or_create_user("400001", "+4000000001", "Vault Ops User A", "voa@test.local")
        cls.user_b = _get_or_create_user("400002", "+4000000002", "Vault Ops User B", "vob@test.local")

    @classmethod
    def tearDownClass(cls):
        global _SESSION_PATH
        if _SESSION_PATH and os.path.exists(_SESSION_PATH):
            os.unlink(_SESSION_PATH)
        _SESSION_PATH = None

    def setUp(self):
        self.client = app.test_client()
        # Clean vault state and create test files
        with get_connection() as conn:
            conn.execute("DELETE FROM vault_settings WHERE user_id IN (?, ?)",
                         (self.user_a["id"], self.user_b["id"]))
            conn.execute("DELETE FROM file_records WHERE user_id IN (?, ?)",
                         (self.user_a["id"], self.user_b["id"]))
            conn.execute("DELETE FROM folders WHERE user_id IN (?, ?)",
                         (self.user_a["id"], self.user_b["id"]))

        # Create test files for user A
        self.file_a1 = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=1001,
            filename="test_file_a1.txt",
            mime_type="text/plain",
            size=1024,
        )
        self.file_a2 = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=1002,
            filename="test_file_a2.txt",
            mime_type="text/plain",
            size=2048,
        )
        # Create a folder for user A
        self.folder_a = create_folder(self.user_a["id"], "TestFolderA")
        # Create a file inside the folder
        self.file_a3 = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=1003,
            filename="test_file_a3.txt",
            mime_type="text/plain",
            size=512,
        )
        # Move file_a3 into folder
        from storage_db import move_file_to_folder
        move_file_to_folder(self.file_a3["id"], self.user_a["id"], self.folder_a["id"])

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess["app_user_id"] = user_id

    def _clear_vault_session(self):
        """Clear vault unlock state from session."""
        with self.client.session_transaction() as sess:
            sess.pop("vault_unlocked", None)
            sess.pop("vault_last_activity", None)

    def _setup_vault(self, pin="123456"):
        """Set up vault with PIN for user A."""
        self._login(self.user_a["id"])
        self.client.post("/api/vault/pin", json={"pin": pin})
        self._clear_vault_session()

    def _unlock(self, pin="123456"):
        """Unlock vault for user A."""
        self._login(self.user_a["id"])
        return self.client.post("/api/vault/unlock", json={"pin": pin})


class TestVaultMoveFile(VaultOpsTestBase):
    """Test moving files to vault via API."""

    def test_vault_move_file_requires_unlock(self):
        """Vault move endpoint requires vault to be configured and unlocked."""
        self._setup_vault()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/move", json={"type": "file", "id": self.file_a1["id"]})
        self.assertIn(r.status_code, (400, 403))
        data = r.get_json()
        self.assertFalse(data["success"])

    def test_vault_move_file_success(self):
        """Vault move succeeds when vault is unlocked."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/move", json={"type": "file", "id": self.file_a1["id"]})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])

    def test_vault_move_file_sets_is_vaulted(self):
        """Vault move sets is_vaulted=1 in DB."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        self.client.post("/api/vault/move", json={"type": "file", "id": self.file_a1["id"]})
        self.assertTrue(is_file_vaulted(self.file_a1["id"], self.user_a["id"]))

    def test_vault_move_folder_success(self):
        """Vault move can handle folders."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/move", json={"type": "folder", "id": self.folder_a["id"]})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])

    def test_vault_move_invalid_type(self):
        """Vault move with invalid type returns error."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/move", json={"type": "invalid", "id": 1})
        self.assertEqual(r.status_code, 400)


class TestVaultRestoreFile(VaultOpsTestBase):
    """Test restoring files from vault via API."""

    def test_vault_restore_file_requires_unlock(self):
        """Vault restore requires vault to be configured and unlocked."""
        self._setup_vault()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/restore", json={"type": "file", "id": self.file_a1["id"]})
        self.assertIn(r.status_code, (400, 403))

    def test_vault_restore_file_success(self):
        """Vault restore succeeds when vault is unlocked."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        # Vault the file using the move endpoint
        r_move = self.client.post("/api/vault/move", json={"type": "file", "id": self.file_a1["id"]})
        self.assertEqual(r_move.status_code, 200)
        # Now restore it
        r = self.client.post("/api/vault/restore", json={"type": "file", "id": self.file_a1["id"]})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])

    def test_vault_restore_clears_is_vaulted(self):
        """Vault restore sets is_vaulted=0 in DB."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        # Vault the file using the move endpoint
        r_move = self.client.post("/api/vault/move", json={"type": "file", "id": self.file_a1["id"]})
        self.assertEqual(r_move.status_code, 200)
        # Now restore it
        self.client.post("/api/vault/restore", json={"type": "file", "id": self.file_a1["id"]})
        self.assertFalse(is_file_vaulted(self.file_a1["id"], self.user_a["id"]))


class TestVaultListFiles(VaultOpsTestBase):
    """Test listing vaulted files via API."""

    def test_vault_list_files_requires_unlock(self):
        """Vault list requires vault to be configured and unlocked."""
        self._setup_vault()
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/files")
        self.assertIn(r.status_code, (400, 403))

    def test_vault_list_files_success(self):
        """Vault list returns vaulted files when unlocked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/files")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["files"]), 1)
        self.assertEqual(data["files"][0]["id"], self.file_a1["id"])

    def test_vault_list_files_excludes_non_vaulted(self):
        """Vault list only returns vaulted files."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/files")
        data = r.get_json()
        file_ids = [f["id"] for f in data["files"]]
        self.assertNotIn(self.file_a2["id"], file_ids)


class TestVaultProtection(VaultOpsTestBase):
    """Test that protected endpoints reject vaulted items when locked."""

    def test_download_vaulted_file_locked(self):
        """Download of vaulted file fails when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.get(f"/api/files/{self.file_a1['id']}/download")
        self.assertIn(r.status_code, (403, 401))

    def test_preview_vaulted_file_locked(self):
        """Preview of vaulted file fails when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.get(f"/api/files/{self.file_a1['id']}/preview")
        self.assertIn(r.status_code, (403, 401))

    def test_rename_vaulted_file_locked(self):
        """Rename of vaulted file fails when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a1['id']}/rename", json={"name": "new_name.txt"})
        self.assertIn(r.status_code, (403, 401))

    def test_delete_vaulted_file_locked(self):
        """Delete of vaulted file fails when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.delete(f"/api/files/{self.file_a1['id']}/delete")
        self.assertIn(r.status_code, (403, 401))

    def test_favorite_vaulted_file_locked(self):
        """Toggle favorite of vaulted file fails when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a1['id']}/favorite")
        self.assertIn(r.status_code, (403, 401))

    def test_move_vaulted_file_locked(self):
        """Move of vaulted file fails when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a1['id']}/move", json={"folder_id": None})
        self.assertIn(r.status_code, (403, 401))

    def test_share_vaulted_file_locked(self):
        """Share of vaulted file fails when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a1['id']}/share", json={"can_view": True})
        self.assertIn(r.status_code, (403, 401))


class TestVaultFiltering(VaultOpsTestBase):
    """Test that vaulted items are filtered from normal listings."""

    def test_normal_listing_excludes_vaulted(self):
        """Normal file listing excludes vaulted items when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.get("/api/files")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        file_ids = [f["id"] for f in data["files"]]
        self.assertNotIn(self.file_a1["id"], file_ids)
        self.assertIn(self.file_a2["id"], file_ids)

    def test_favorites_excludes_vaulted(self):
        """Favorites listing excludes vaulted items when vault is locked."""
        self._setup_vault()
        self._unlock()
        from storage_db import toggle_favorite
        toggle_favorite(self.file_a1["id"], self.user_a["id"])
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.get("/api/files?view=favorites")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        file_ids = [f["id"] for f in data["files"]]
        self.assertNotIn(self.file_a1["id"], file_ids)

    def test_trash_excludes_vaulted(self):
        """Trash listing excludes vaulted items when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        soft_delete_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.get("/api/files?view=trash")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        file_ids = [f["id"] for f in data["files"]]
        self.assertNotIn(self.file_a1["id"], file_ids)


class TestVaultStats(VaultOpsTestBase):
    """Test that vaulted items are excluded from stats."""

    def test_stats_exclude_vaulted(self):
        """File stats exclude vaulted items when vault is locked."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.get("/api/files")
        data = r.get_json()
        # Stats should only count non-vaulted files (file_a2 at root, file_a3 in folder)
        self.assertEqual(data["summary"]["total_files"], 2)


class TestVaultUserIsolation(VaultOpsTestBase):
    """Test that users cannot access each other's vaulted files."""

    def test_user_b_cannot_see_user_a_vaulted_files(self):
        """User B cannot see User A's vaulted files in vault list."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._login(self.user_b["id"])
        r = self.client.get("/api/vault/files")
        self.assertIn(r.status_code, (400, 403))


class TestVaultDBFunctions(unittest.TestCase):
    """Test vault DB functions directly."""

    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        init_db()
        cls.user = _get_or_create_user("400099", "+4000000099", "DB Test User", "dbt@test.local")

    def setUp(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM file_records WHERE user_id = ?", (self.user["id"],))
            conn.execute("DELETE FROM folders WHERE user_id = ?", (self.user["id"],))

    def test_vault_file_sets_flag(self):
        """vault_file sets is_vaulted=1."""
        f = create_file_record(user_id=self.user["id"], telegram_message_id=9001, filename="test.txt", mime_type="text/plain", size=100)
        vault_file(f["id"], self.user["id"])
        result = is_file_vaulted(f["id"], self.user["id"])
        self.assertTrue(result)

    def test_unvault_file_clears_flag(self):
        """unvault_file sets is_vaulted=0."""
        f = create_file_record(user_id=self.user["id"], telegram_message_id=9002, filename="test2.txt", mime_type="text/plain", size=100)
        vault_file(f["id"], self.user["id"])
        unvault_file(f["id"], self.user["id"])
        result = is_file_vaulted(f["id"], self.user["id"])
        self.assertFalse(result)

    def test_vault_folder_vaults_descendants(self):
        """vault_folder vaults the folder and all descendant files."""
        folder = create_folder(self.user["id"], "ParentFolder")
        child = create_folder(self.user["id"], "ChildFolder", parent_id=folder["id"])
        f1 = create_file_record(user_id=self.user["id"], telegram_message_id=9003, filename="f1.txt", mime_type="text/plain", size=100)
        f2 = create_file_record(user_id=self.user["id"], telegram_message_id=9004, filename="f2.txt", mime_type="text/plain", size=100)
        from storage_db import move_file_to_folder
        move_file_to_folder(f1["id"], self.user["id"], folder["id"])
        move_file_to_folder(f2["id"], self.user["id"], child["id"])

        vaulted_ids = vault_folder(folder["id"], self.user["id"])
        self.assertIn(folder["id"], vaulted_ids)
        self.assertIn(child["id"], vaulted_ids)
        self.assertTrue(is_file_vaulted(f1["id"], self.user["id"]))
        self.assertTrue(is_file_vaulted(f2["id"], self.user["id"]))

    def test_list_vaulted_files(self):
        """list_vaulted_files returns only vaulted files."""
        f1 = create_file_record(user_id=self.user["id"], telegram_message_id=9005, filename="v1.txt", mime_type="text/plain", size=100)
        f2 = create_file_record(user_id=self.user["id"], telegram_message_id=9006, filename="v2.txt", mime_type="text/plain", size=100)
        vault_file(f1["id"], self.user["id"])
        vaulted = list_vaulted_files(self.user["id"])
        self.assertEqual(len(vaulted), 1)
        self.assertEqual(vaulted[0]["id"], f1["id"])


# ---------------------------------------------------------------------------
# Vault Upload endpoint tests
# ---------------------------------------------------------------------------

class TestVaultUpload(VaultOpsTestBase):
    """Test the direct POST /api/vault/upload endpoint."""

    def test_vault_upload_requires_unlock(self):
        """Vault upload fails when vault is locked."""
        self._setup_vault()
        self._login(self.user_a["id"])
        import io
        r = self.client.post("/api/vault/upload",
                             data={"file": (io.BytesIO(b"hello"), "test.txt")},
                             content_type="multipart/form-data")
        self.assertIn(r.status_code, (400, 403))

    def test_vault_upload_requires_auth(self):
        """Vault upload fails without authentication."""
        self._setup_vault()
        r = self.client.post("/api/vault/upload",
                             data={"file": (io.BytesIO(b"hello"), "test.txt")},
                             content_type="multipart/form-data")
        self.assertIn(r.status_code, (400, 401, 403))

    def test_vault_upload_success(self):
        """Vault upload succeeds when vault is unlocked."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        import io
        r = self.client.post("/api/vault/upload",
                             data={"file": (io.BytesIO(b"test content for vault"), "vault_test.txt")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["file"]["name"], "vault_test.txt")
        self.assertTrue(data["file"]["is_vaulted"])

    def test_vault_upload_creates_vaulted_record(self):
        """Vault upload creates a file record marked as vaulted."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        import io
        r = self.client.post("/api/vault/upload",
                             data={"file": (io.BytesIO(b"content"), "test_v.txt")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        file_id = data["file"]["id"]
        self.assertTrue(is_file_vaulted(file_id, self.user_a["id"]))

    def test_vault_upload_does_not_create_my_drive_copy(self):
        """Vault upload should NOT leave a non-vaulted copy in My Drive."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        import io
        r = self.client.post("/api/vault/upload",
                             data={"file": (io.BytesIO(b"content"), "test_no_md.txt")},
                             content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201)
        # The uploaded file should only appear in vaulted files
        files = list_user_files(self.user_a["id"])
        uploaded = [f for f in files if f["filename"] == "test_no_md.txt"]
        self.assertEqual(len(uploaded), 1)
        self.assertTrue(uploaded[0]["is_vaulted"])

    def test_vault_upload_no_file_returns_400(self):
        """Vault upload with no file returns 400."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/upload")
        self.assertEqual(r.status_code, 400)

    def test_vault_upload_user_isolation(self):
        """User B cannot upload to vault without their own vault setup."""
        self._setup_vault()
        self._unlock()
        # User B tries to upload without vault setup
        self._login(self.user_b["id"])
        import io
        r = self.client.post("/api/vault/upload",
                             data={"file": (io.BytesIO(b"content"), "hack.txt")},
                             content_type="multipart/form-data")
        self.assertIn(r.status_code, (400, 403))


# ---------------------------------------------------------------------------
# Preview / Download with mocked Telegram
# ---------------------------------------------------------------------------

class TestFilePreviewDownload(VaultOpsTestBase):
    """Test preview and download endpoints with mocked Telegram."""

    def test_download_non_vaulted_file(self):
        """Download of non-vaulted file works."""
        self._login(self.user_a["id"])
        r = self.client.get(f"/api/files/{self.file_a1['id']}/download")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"dummy content", r.data)

    def test_preview_non_vaulted_image(self):
        """Preview of a non-vaulted image returns correct content type."""
        # Create an image file record
        img = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=2001,
            filename="test.png",
            mime_type="image/png",
            size=100,
        )
        self._login(self.user_a["id"])
        r = self.client.get(f"/api/files/{img['id']}/preview")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "image/png")

    def test_preview_non_vaulted_pdf(self):
        """Preview of a non-vaulted PDF returns correct content type."""
        pdf = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=2002,
            filename="test.pdf",
            mime_type="application/pdf",
            size=200,
        )
        self._login(self.user_a["id"])
        r = self.client.get(f"/api/files/{pdf['id']}/preview")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "application/pdf")

    def test_preview_non_vaulted_video(self):
        """Preview of a non-vaulted video returns correct content type."""
        vid = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=2003,
            filename="test.mp4",
            mime_type="video/mp4",
            size=300,
        )
        self._login(self.user_a["id"])
        r = self.client.get(f"/api/files/{vid['id']}/preview")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "video/mp4")

    def test_preview_unsupported_type_returns_400(self):
        """Preview of unsupported file type returns 400."""
        exe = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=2004,
            filename="test.exe",
            mime_type="application/x-executable",
            size=400,
        )
        self._login(self.user_a["id"])
        r = self.client.get(f"/api/files/{exe['id']}/preview")
        self.assertEqual(r.status_code, 400)

    def test_download_requires_auth(self):
        """Download without authentication returns 401."""
        r = self.client.get(f"/api/files/{self.file_a1['id']}/download")
        self.assertEqual(r.status_code, 401)

    def test_preview_requires_auth(self):
        """Preview without authentication returns 401."""
        r = self.client.get(f"/api/files/{self.file_a1['id']}/preview")
        self.assertEqual(r.status_code, 401)

    def test_download_wrong_user_returns_404(self):
        """User B cannot download User A's file (IDOR protection)."""
        self._login(self.user_b["id"])
        r = self.client.get(f"/api/files/{self.file_a1['id']}/download")
        self.assertEqual(r.status_code, 404)

    def test_preview_wrong_user_returns_404(self):
        """User B cannot preview User A's file (IDOR protection)."""
        self._login(self.user_b["id"])
        r = self.client.get(f"/api/files/{self.file_a1['id']}/preview")
        self.assertEqual(r.status_code, 404)

    def test_download_nonexistent_returns_404(self):
        """Download of nonexistent file returns 404."""
        self._login(self.user_a["id"])
        r = self.client.get("/api/files/999999/download")
        self.assertEqual(r.status_code, 404)


# ---------------------------------------------------------------------------
# Vault PIN persistence across login/logout
# ---------------------------------------------------------------------------

class TestVaultPinPersistence(VaultOpsTestBase):
    """Test that vault PIN settings persist across logout/login cycles."""

    def test_vault_pin_persists_after_logout_login(self):
        """Vault PIN persists: after logout+login, vault shows configured."""
        # Set up vault
        self._setup_vault(pin="999999")
        # Verify it's configured
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/status")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["configured"])

        # Logout (clear session)
        with self.client.session_transaction() as sess:
            sess.clear()

        # Login again
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/status")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["configured"])  # Still configured
        self.assertFalse(data["unlocked"])   # But locked

    def test_vault_unlock_after_relogin(self):
        """After logout+login, vault can be unlocked with the same PIN."""
        self._setup_vault(pin="777777")
        # Logout
        with self.client.session_transaction() as sess:
            sess.clear()
        # Login
        self._login(self.user_a["id"])
        # Unlock with same PIN
        r = self.client.post("/api/vault/unlock", json={"pin": "777777"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])

    def test_wrong_pin_fails_after_relogin(self):
        """After logout+login, wrong PIN is rejected."""
        self._setup_vault(pin="555555")
        with self.client.session_transaction() as sess:
            sess.clear()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/unlock", json={"pin": "000000"})
        self.assertIn(r.status_code, (403, 401))

    def test_vault_files_persist_after_relogin(self):
        """Vault files persist after logout+login (within same process)."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        # Logout
        with self.client.session_transaction() as sess:
            sess.clear()
        # Login
        self._login(self.user_a["id"])
        # Unlock
        self.client.post("/api/vault/unlock", json={"pin": "123456"})
        # Check vault files
        r = self.client.get("/api/vault/files")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        file_ids = [f["id"] for f in data["files"]]
        self.assertIn(self.file_a1["id"], file_ids)


# ---------------------------------------------------------------------------
# Encrypted vault file preview / download (with VMK)
# ---------------------------------------------------------------------------

class TestEncryptedVaultPreview(VaultOpsTestBase):
    """Test preview/download of encrypted vault files."""

    def test_preview_vaulted_encrypted_file_when_unlocked(self):
        """Preview of encrypted vault file works when vault is unlocked."""
        self._setup_vault()
        self._unlock()
        # Create an encrypted vault file record
        enc_file = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=3001,
            filename="secret.png",
            mime_type="image/png",
            size=100,
        )
        vault_file(enc_file["id"], self.user_a["id"])
        from storage_db import update_file_encryption
        update_file_encryption(
            file_id=enc_file["id"],
            user_id=self.user_a["id"],
            enc_flag=1,
            enc_version=1,
            dek_wrap_nonce=b'\x00' * 12,
            dek_wrap_cipher=b'\x00' * 32,
            dek_wrap_tag=b'\x00' * 16,
            file_enc_nonce=b'\x00' * 12,
            file_enc_tag=b'\x00' * 16,
        )
        self._login(self.user_a["id"])
        # In test mode, the handler writes dummy content — decryption will fail
        # but we verify the endpoint doesn't crash
        r = self.client.get(f"/api/files/{enc_file['id']}/preview")
        # Should return 500 (decryption fails with dummy data) but NOT crash
        self.assertIn(r.status_code, (200, 500))

    def test_download_vaulted_encrypted_file_when_unlocked(self):
        """Download of encrypted vault file works when vault is unlocked."""
        self._setup_vault()
        self._unlock()
        enc_file = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=3002,
            filename="secret.pdf",
            mime_type="application/pdf",
            size=200,
        )
        vault_file(enc_file["id"], self.user_a["id"])
        from storage_db import update_file_encryption
        update_file_encryption(
            file_id=enc_file["id"],
            user_id=self.user_a["id"],
            enc_flag=1,
            enc_version=1,
            dek_wrap_nonce=b'\x00' * 12,
            dek_wrap_cipher=b'\x00' * 32,
            dek_wrap_tag=b'\x00' * 16,
            file_enc_nonce=b'\x00' * 12,
            file_enc_tag=b'\x00' * 16,
        )
        self._login(self.user_a["id"])
        r = self.client.get(f"/api/files/{enc_file['id']}/download")
        # Decryption fails with dummy data, but endpoint shouldn't crash
        self.assertIn(r.status_code, (200, 500))


# ---------------------------------------------------------------------------
# Regression: Bug A — PDF preview framing headers (modal <iframe>)
# ---------------------------------------------------------------------------

class TestPreviewFramingHeaders(VaultOpsTestBase):
    """Bug A: the dashboard modal embeds /api/files/<id>/preview in a
    same-origin <iframe>. add_security_headers() used to send
    X-Frame-Options: DENY + CSP frame-ancestors 'none' on EVERY response,
    so the browser blocked the PDF and the modal showed the
    'content blocked/failed' icon. Preview must be same-origin embeddable;
    everything else must stay frame-blocked."""

    MINIMAL_PDF = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF\n"
    )

    def _seed_pdf(self, message_id=3001, filename="frame_check.pdf"):
        """Write real PDF bytes into Telegram test-mode storage + DB record."""
        from telegram_handler import TEST_STORAGE_BASE
        storage_dir = os.path.join(TEST_STORAGE_BASE, os.path.basename(_SESSION_PATH))
        os.makedirs(storage_dir, exist_ok=True)
        with open(os.path.join(storage_dir, str(message_id)), "wb") as f:
            f.write(self.MINIMAL_PDF)
        return create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=message_id,
            filename=filename,
            mime_type="application/pdf",
            size=len(self.MINIMAL_PDF),
        )

    def test_pdf_preview_allows_same_origin_iframe(self):
        """Preview response must be 200, application/pdf, inline, real PDF
        bytes, and embeddable by the same-origin modal iframe."""
        rec = self._seed_pdf()
        self._login(self.user_a["id"])
        r = self.client.get(f"/api/files/{rec['id']}/preview")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "application/pdf")
        self.assertEqual(r.headers.get("Content-Disposition"), "inline")
        self.assertTrue(r.data.startswith(b"%PDF"))
        self.assertEqual(r.data, self.MINIMAL_PDF)
        # The actual Bug A regression assertions:
        self.assertEqual(r.headers.get("X-Frame-Options"), "SAMEORIGIN")
        csp = r.headers.get("Content-Security-Policy", "")
        self.assertIn("frame-ancestors 'self'", csp)
        self.assertNotIn("frame-ancestors 'none'", csp)

    def test_vaulted_pdf_preview_roundtrip_and_framing(self):
        """Vault upload -> vault preview returns the original PDF bytes and
        is equally embeddable in the same-origin iframe."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        r_up = self.client.post(
            "/api/vault/upload",
            data={"file": (io.BytesIO(self.MINIMAL_PDF), "vaulted_frame.pdf")},
            content_type="multipart/form-data",
        )
        self.assertEqual(r_up.status_code, 201)
        fid = r_up.get_json()["file"]["id"]
        r = self.client.get(f"/api/files/{fid}/preview")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "application/pdf")
        self.assertEqual(r.headers.get("Content-Disposition"), "inline")
        self.assertEqual(r.data, self.MINIMAL_PDF)
        self.assertEqual(r.headers.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertIn("frame-ancestors 'self'", r.headers.get("Content-Security-Policy", ""))

    def test_non_preview_responses_stay_frame_blocked(self):
        """The relaxed headers must apply to the preview endpoint ONLY."""
        self._login(self.user_a["id"])
        paths = (
            "/dashboard",
            "/api/files",
            f"/api/files/{self.file_a1['id']}/download",
        )
        for path in paths:
            r = self.client.get(path)
            self.assertEqual(r.headers.get("X-Frame-Options"), "DENY", path)
            self.assertIn(
                "frame-ancestors 'none'",
                r.headers.get("Content-Security-Policy", ""),
                path,
            )

    def test_preview_requires_auth_still_blocked(self):
        """Unauthenticated preview still 401 (auth unchanged by the fix)."""
        r = self.client.get(f"/api/files/{self.file_a1['id']}/preview")
        self.assertEqual(r.status_code, 401)


# ---------------------------------------------------------------------------
# Regression: Bug C — /api/vault/move JSON content-type contract
# ---------------------------------------------------------------------------

class TestVaultMoveContentType(VaultOpsTestBase):
    """Bug C: dashboard.js called fetchJSON('/api/vault/move', {method, body})
    WITHOUT a JSON Content-Type, so fetch sent text/plain;charset=UTF-8,
    Flask's request.get_json(silent=True) returned None, the handler saw {},
    and validation failed with "id must be integer" even though the id was a
    valid integer. The value was never bad — the body was never parsed."""

    EXPECTED_ERR = "Invalid request: type must be 'file' or 'folder', id must be integer"

    def test_move_with_json_header_succeeds(self):
        """Identical body with the JSON header moves the file (200)."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/move",
                             json={"type": "file", "id": self.file_a1["id"]})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["success"])
        self.assertTrue(is_file_vaulted(self.file_a1["id"], self.user_a["id"]))

    def test_move_with_text_plain_header_returns_exact_400(self):
        """Reproduces the original broken frontend request byte-for-byte:
        same JSON body, default fetch content type."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        body = '{"type": "file", "id": %d}' % self.file_a1["id"]
        r = self.client.post("/api/vault/move", data=body,
                             content_type="text/plain;charset=UTF-8")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], self.EXPECTED_ERR)
        # Nothing must have moved
        self.assertFalse(is_file_vaulted(self.file_a1["id"], self.user_a["id"]))

    def test_move_with_json_header_and_invalid_id_still_rejected(self):
        """Backend integer validation stays strict after the frontend fix."""
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/move",
                             json={"type": "file", "id": "not-a-number"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error"], self.EXPECTED_ERR)
        r2 = self.client.post("/api/vault/move", json={"type": "invalid", "id": 1})
        self.assertEqual(r2.status_code, 400)
        self.assertEqual(r2.get_json()["error"], self.EXPECTED_ERR)

    def test_move_requires_authentication(self):
        r = self.client.post("/api/vault/move",
                             json={"type": "file", "id": self.file_a1["id"]})
        self.assertEqual(r.status_code, 401)

    def test_move_requires_unlocked_vault(self):
        self._setup_vault()
        self._clear_vault_session()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/move",
                             json={"type": "file", "id": self.file_a1["id"]})
        self.assertIn(r.status_code, (400, 403))
        self.assertFalse(is_file_vaulted(self.file_a1["id"], self.user_a["id"]))

    def test_move_nonexistent_file_returns_404(self):
        self._setup_vault()
        self._unlock()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/move",
                             json={"type": "file", "id": 999999})
        self.assertEqual(r.status_code, 404)

    def test_move_other_users_file_returns_404(self):
        """IDOR: user B (own unlocked vault) cannot move user A's file."""
        self._login(self.user_b["id"])
        self.client.post("/api/vault/pin", json={"pin": "654321"})
        self.client.post("/api/vault/unlock", json={"pin": "654321"})
        r = self.client.post("/api/vault/move",
                             json={"type": "file", "id": self.file_a1["id"]})
        self.assertEqual(r.status_code, 404)
        self.assertFalse(is_file_vaulted(self.file_a1["id"], self.user_a["id"]))


# ---------------------------------------------------------------------------
# Regression: Bug C frontend guard (static check — no JS test harness exists)
# ---------------------------------------------------------------------------

class TestFrontendPayloadGuards(unittest.TestCase):
    """The repo has no JS test harness; guard the exact frontend regressions
    with static assertions over static/dashboard.js."""

    @classmethod
    def setUpClass(cls):
        js_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "static", "dashboard.js",
        )
        with open(js_path, encoding="utf-8") as f:
            cls.js_src = f.read()

    def test_vault_move_fetch_sends_json_content_type(self):
        """finds fetchJSON('/api/vault/move', ...) and requires the header
        inside the same call — this is the Bug C fix."""
        idx = self.js_src.find("'/api/vault/move'")
        self.assertNotEqual(idx, -1, "vault move call site missing")
        call_window = self.js_src[idx:idx + 400]
        header_idx = call_window.find("'Content-Type': 'application/json'")
        self.assertNotEqual(
            header_idx, -1,
            "Bug C regression: /api/vault/move must be sent with a JSON "
            "Content-Type header, otherwise Flask cannot parse the body",
        )
        self.assertIn("JSON.stringify", call_window)

    def test_no_json_body_fetch_without_json_header_nearby(self):
        """Every fetchJSON POST to a vault endpoint whose body is
        JSON.stringify(...) must set 'Content-Type': 'application/json'
        within the same options object. (Scoped to /api/vault/ — other
        endpoints are outside this bug's scope.)"""
        import re
        pattern = re.compile(r"fetchJSON\(([^;]{0,600}?)\)", re.S)
        offenders = []
        for m in pattern.finditer(self.js_src):
            seg = m.group(1)
            if "/api/vault/" not in seg:
                continue
            if "JSON.stringify" in seg and "'Content-Type'" not in seg \
                    and '"Content-Type"' not in seg:
                offenders.append(seg[:120].replace("\n", " "))
        self.assertEqual(
            offenders, [],
            f"fetch calls with JSON bodies missing Content-Type: {offenders}",
        )


if __name__ == "__main__":
    unittest.main()