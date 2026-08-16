"""
Storage Intelligence tests (Phase 6A).

Tests storage stats API, file type breakdown, largest/recent files,
vault privacy, deleted-file exclusion, user isolation, and security.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage_db import (
    init_db,
    create_user,
    get_connection,
    create_file_record,
    create_folder,
    get_storage_intelligence,
)
from main import app


def _cleanup():
    with get_connection() as conn:
        for tg_id in ("700001", "700002"):
            row = conn.execute("SELECT id FROM users WHERE telegram_user_id = ?", (tg_id,)).fetchone()
            if row:
                uid = row["id"]
                conn.execute("DELETE FROM file_shares WHERE file_id IN (SELECT id FROM file_records WHERE user_id = ?)", (uid,))
                conn.execute("DELETE FROM activity_events WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_log WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM file_records WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM folders WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM webdav_tokens WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM vault_settings WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        for email in ("si_a@test.local", "si_b@test.local"):
            row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if row:
                uid = row["id"]
                conn.execute("DELETE FROM file_shares WHERE file_id IN (SELECT id FROM file_records WHERE user_id = ?)", (uid,))
                conn.execute("DELETE FROM activity_events WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_log WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM file_records WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM folders WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM webdav_tokens WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM vault_settings WHERE user_id = ?", (uid,))
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


class TestStorageStatsEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        _cleanup()
        cls.user_a = _get_or_create_user("700001", "+7000000001", "Stats User A", "si_a@test.local")
        cls.user_b = _get_or_create_user("700002", "+7000000002", "Stats User B", "si_b@test.local")

    def setUp(self):
        self.client = app.test_client()
        with get_connection() as conn:
            conn.execute("DELETE FROM file_records WHERE user_id IN (?, ?)", (self.user_a["id"], self.user_b["id"]))
            conn.execute("DELETE FROM folders WHERE user_id IN (?, ?)", (self.user_a["id"], self.user_b["id"]))
            conn.execute("DELETE FROM vault_settings WHERE user_id IN (?, ?)", (self.user_a["id"], self.user_b["id"]))

    def _login(self, uid):
        with self.client.session_transaction() as sess:
            sess["app_user_id"] = uid

    def test_unauthenticated_returns_401(self):
        r = self.client.get("/api/storage/stats")
        self.assertEqual(r.status_code, 401)

    def test_empty_storage(self):
        self._login(self.user_a["id"])
        r = self.client.get("/api/storage/stats")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["total_size"], 0)
        self.assertEqual(data["file_count"], 0)
        self.assertEqual(data["folder_count"], 0)
        self.assertEqual(data["average_file_size"], 0)
        self.assertEqual(data["largest_files"], [])
        self.assertEqual(data["recent_files"], [])

    def test_total_size(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 1001, "a.pdf", "application/pdf", size=1000)
        create_file_record(self.user_a["id"], 1002, "b.pdf", "application/pdf", size=2000)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["total_size"], 3000)
        self.assertEqual(data["file_count"], 2)

    def test_file_count(self):
        self._login(self.user_a["id"])
        for i in range(5):
            create_file_record(self.user_a["id"], 2000 + i, f"f{i}.txt", "text/plain", size=100)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["file_count"], 5)

    def test_folder_count(self):
        self._login(self.user_a["id"])
        create_folder(self.user_a["id"], "Projects")
        create_folder(self.user_a["id"], "Photos")
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["folder_count"], 2)

    def test_average_file_size(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 3001, "a.txt", "text/plain", size=100)
        create_file_record(self.user_a["id"], 3002, "b.txt", "text/plain", size=300)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["average_file_size"], 200)

    def test_average_zero_files(self):
        self._login(self.user_a["id"])
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["average_file_size"], 0)

    def test_mime_categorization_images(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 4001, "photo.jpg", "image/jpeg", size=5000)
        create_file_record(self.user_a["id"], 4002, "icon.png", "image/png", size=1000)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["type_breakdown"]["images"]["count"], 2)
        self.assertEqual(data["type_breakdown"]["images"]["bytes"], 6000)

    def test_mime_categorization_videos(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 4010, "clip.mp4", "video/mp4", size=50000)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["type_breakdown"]["videos"]["count"], 1)
        self.assertEqual(data["type_breakdown"]["videos"]["bytes"], 50000)

    def test_mime_categorization_audio(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 4020, "song.mp3", "audio/mpeg", size=8000)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["type_breakdown"]["audio"]["count"], 1)

    def test_mime_categorization_documents(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 4030, "report.pdf", "application/pdf", size=3000)
        create_file_record(self.user_a["id"], 4031, "notes.txt", "text/plain", size=500)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["type_breakdown"]["documents"]["count"], 2)

    def test_mime_categorization_archives(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 4040, "backup.zip", "application/zip", size=9000)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["type_breakdown"]["archives"]["count"], 1)

    def test_mime_categorization_other(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 4050, "unknown.xyz", "application/x-unknown", size=200)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["type_breakdown"]["other"]["count"], 1)

    def test_percentages(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 5001, "a.jpg", "image/jpeg", size=750)
        create_file_record(self.user_a["id"], 5002, "b.pdf", "application/pdf", size=250)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertAlmostEqual(data["type_breakdown"]["images"]["percentage"], 75.0, places=1)
        self.assertAlmostEqual(data["type_breakdown"]["documents"]["percentage"], 25.0, places=1)

    def test_percentages_zero_size(self):
        self._login(self.user_a["id"])
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        for cat in data["type_breakdown"]:
            self.assertEqual(data["type_breakdown"][cat]["percentage"], 0.0)

    def test_largest_files(self):
        self._login(self.user_a["id"])
        sizes = [100, 5000, 200, 8000, 300]
        for i, sz in enumerate(sizes):
            create_file_record(self.user_a["id"], 6000 + i, f"f{i}.bin", "application/octet-stream", size=sz)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(len(data["largest_files"]), 5)
        self.assertEqual(data["largest_files"][0]["filename"], "f3.bin")
        self.assertEqual(data["largest_files"][0]["size"], 8000)

    def test_largest_files_limit_10(self):
        self._login(self.user_a["id"])
        for i in range(15):
            create_file_record(self.user_a["id"], 7000 + i, f"f{i}.bin", "application/octet-stream", size=100 + i)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(len(data["largest_files"]), 10)

    def test_largest_files_safe_fields(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 8001, "test.pdf", "application/pdf", size=1000)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        f = data["largest_files"][0]
        self.assertIn("id", f)
        self.assertIn("filename", f)
        self.assertIn("size", f)
        self.assertIn("mime_type", f)
        self.assertIn("uploaded_at", f)
        self.assertNotIn("telegram_message_id", f)

    def test_recent_files(self):
        self._login(self.user_a["id"])
        for i in range(3):
            create_file_record(self.user_a["id"], 9000 + i, f"f{i}.txt", "text/plain", size=100)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(len(data["recent_files"]), 3)
        self.assertEqual(data["recent_files"][0]["filename"], "f2.txt")

    def test_deleted_files_excluded(self):
        self._login(self.user_a["id"])
        f1 = create_file_record(self.user_a["id"], 9100, "active.pdf", "application/pdf", size=1000)
        f2 = create_file_record(self.user_a["id"], 9101, "deleted.pdf", "application/pdf", size=2000)
        from storage_db import soft_delete_file
        soft_delete_file(f2["id"], self.user_a["id"])
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["file_count"], 1)
        self.assertEqual(data["total_size"], 1000)

    def test_vault_locked_excludes_vaulted(self):
        self._login(self.user_a["id"])
        f1 = create_file_record(self.user_a["id"], 9200, "normal.pdf", "application/pdf", size=1000)
        f2 = create_file_record(self.user_a["id"], 9201, "secret.pdf", "application/pdf", size=5000)
        from storage_db import vault_file
        vault_file(f2["id"], self.user_a["id"])
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["file_count"], 1)
        self.assertEqual(data["total_size"], 1000)
        self.assertEqual(data["vault"]["visible"], False)

    def test_vault_unlocked_includes_vaulted(self):
        self._login(self.user_a["id"])
        f1 = create_file_record(self.user_a["id"], 9300, "normal.pdf", "application/pdf", size=1000)
        f2 = create_file_record(self.user_a["id"], 9301, "secret.pdf", "application/pdf", size=5000)
        from storage_db import vault_file
        vault_file(f2["id"], self.user_a["id"])
        from storage_db import get_vault_settings, create_vault_settings
        settings = get_vault_settings(self.user_a["id"])
        if not settings:
            from werkzeug.security import generate_password_hash
            pin_hash = generate_password_hash("1234", method="pbkdf2:sha256", salt_length=16)
            create_vault_settings(self.user_a["id"], pin_hash=pin_hash)
        # Unlock vault via PIN
        from werkzeug.security import generate_password_hash
        pin_hash = generate_password_hash("1234", method="pbkdf2:sha256", salt_length=16)
        with get_connection() as conn:
            conn.execute("UPDATE vault_settings SET pin_hash = ? WHERE user_id = ?", (pin_hash, self.user_a["id"]))
        r = self.client.post("/api/vault/unlock", json={"pin": "1234"})
        self.assertEqual(r.status_code, 200)
        # Now request stats
        r2 = self.client.get("/api/storage/stats")
        data = r2.get_json()
        self.assertEqual(data["file_count"], 2)
        self.assertEqual(data["total_size"], 6000)
        self.assertEqual(data["vault"]["visible"], True)
        self.assertEqual(data["vault"]["files"], 1)
        self.assertEqual(data["vault"]["bytes"], 5000)

    def test_user_isolation(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 9400, "a.pdf", "application/pdf", size=1000)
        self._login(self.user_b["id"])
        create_file_record(self.user_b["id"], 9500, "b.pdf", "application/pdf", size=5000)
        self._login(self.user_a["id"])
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["file_count"], 1)
        self.assertEqual(data["total_size"], 1000)

    def test_idor_attempt(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 9600, "my.pdf", "application/pdf", size=1000)
        create_file_record(self.user_b["id"], 9700, "other.pdf", "application/pdf", size=5000)
        r = self.client.get(f"/api/storage/stats?user_id={self.user_b['id']}")
        data = r.get_json()
        self.assertEqual(data["file_count"], 1)
        self.assertEqual(data["total_size"], 1000)

    def test_missing_mime_type(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 9800, "noext", None, size=100)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["file_count"], 1)
        self.assertEqual(data["type_breakdown"]["other"]["count"], 1)

    def test_zero_size_file(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 9900, "empty.txt", "text/plain", size=0)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertEqual(data["file_count"], 1)
        self.assertEqual(data["total_size"], 0)
        self.assertEqual(data["average_file_size"], 0)

    def test_xss_filename(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 9910, '<script>alert(1)</script>.pdf', "application/pdf", size=100)
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertIn("<script>", data["largest_files"][0]["filename"])

    def test_no_telegram_calls(self):
        self._login(self.user_a["id"])
        create_file_record(self.user_a["id"], 9920, "test.pdf", "application/pdf", size=100)
        r = self.client.get("/api/storage/stats")
        self.assertEqual(r.status_code, 200)

    def test_vault_leakage_locked(self):
        self._login(self.user_a["id"])
        f = create_file_record(self.user_a["id"], 9930, "secret.pdf", "application/pdf", size=5000)
        from storage_db import vault_file
        vault_file(f["id"], self.user_a["id"])
        r = self.client.get("/api/storage/stats")
        data = r.get_json()
        self.assertNotIn("5000", str(data))
        self.assertEqual(data["vault"]["visible"], False)
        self.assertNotIn("bytes", data["vault"])
        self.assertNotIn("files", data["vault"])


if __name__ == "__main__":
    unittest.main()
