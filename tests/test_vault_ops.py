"""
Smart Vault file & folder operation tests (Phase 3B).

Tests vault move/restore, endpoint protection when vault is locked,
filtering of vaulted items from listings, and WebDAV integration.
Uses mocked Telegram access — no real OTP required.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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


def _cleanup_test_data():
    """Remove test users and vault data from DB."""
    with get_connection() as conn:
        for tg_id in ("400001", "400002"):
            row = conn.execute("SELECT id FROM users WHERE telegram_user_id = ?", (tg_id,)).fetchone()
            if row:
                uid = row["id"]
                conn.execute("DELETE FROM vault_settings WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_log WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM file_records WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM folders WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM file_shares WHERE owner_user_id = ?", (uid,))
                conn.execute("DELETE FROM webdav_tokens WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM users WHERE id = ?", (uid,))


def _get_or_create_user(tg_id, phone, name, email):
    from storage_db import get_user_by_telegram_id
    user = get_user_by_telegram_id(tg_id)
    if user:
        return user
    return create_user(
        email=email, phone=phone,
        name=name, telegram_user_id=tg_id,
        session_path="/fake/path.session",
    )


class VaultOpsTestBase(unittest.TestCase):
    """Base class: inits DB, creates two test users."""

    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        init_db()
        _cleanup_test_data()
        cls.user_a = _get_or_create_user("400001", "+4000000001", "Vault Ops User A", "voa@test.local")
        cls.user_b = _get_or_create_user("400002", "+4000000002", "Vault Ops User B", "vob@test.local")

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
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/restore", json={"type": "file", "id": self.file_a1["id"]})
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])

    def test_vault_restore_clears_is_vaulted(self):
        """Vault restore sets is_vaulted=0 in DB."""
        self._setup_vault()
        self._unlock()
        vault_file(self.file_a1["id"], self.user_a["id"])
        self._login(self.user_a["id"])
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


if __name__ == "__main__":
    unittest.main()
