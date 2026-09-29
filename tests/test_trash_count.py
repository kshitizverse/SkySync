"""
Trash count consistency tests.

After a successful single-file delete, the API must report the authoritative
server-side trash size (trash_count) so the client can update its sidebar
badge immediately, without first opening the Trash view. The count must match
what the server would list under view=trash.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from storage_db import (
    init_db,
    create_user,
    get_connection,
    create_file_record,
    soft_delete_file,
    list_trash_files,
)
from main import app


def _cleanup_test_data():
    with get_connection() as conn:
        for tg_id in ("600001",):
            row = conn.execute("SELECT id FROM users WHERE telegram_user_id = ?", (tg_id,)).fetchone()
            if row:
                uid = row["id"]
                conn.execute("DELETE FROM file_shares WHERE owner_user_id = ?", (uid,))
                conn.execute("DELETE FROM vault_settings WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_log WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_events WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM file_records WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM folders WHERE user_id = ?", (uid,))
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


class TrashCountTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        init_db()
        _cleanup_test_data()
        os.environ['TELEGRAM_API_ID'] = '12345'
        os.environ['TELEGRAM_API_HASH'] = 'dummyhash'
        os.environ['TELEGRAM_TEST_MODE'] = '1'
        cls.user = _get_or_create_user("600001", "+6000000001", "Trash User A", "trash@test.local")

    def setUp(self):
        self.client = app.test_client()
        with get_connection() as conn:
            conn.execute("DELETE FROM file_records WHERE user_id = ?", (self.user["id"],))
        self.f1 = create_file_record(
            user_id=self.user["id"], telegram_message_id=6001,
            filename="trash_me_1.txt", mime_type="text/plain", size=10,
        )
        self.f2 = create_file_record(
            user_id=self.user["id"], telegram_message_id=6002,
            filename="trash_me_2.txt", mime_type="text/plain", size=20,
        )

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess["app_user_id"] = user_id


class TestDeleteReportsTrashCount(TrashCountTestBase):
    def test_delete_response_includes_trash_count(self):
        self._login(self.user["id"])
        r = self.client.delete(f"/api/files/{self.f1['id']}/delete")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data.get("trash_count"), 1)

        r2 = self.client.delete(f"/api/files/{self.f2['id']}/delete")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.get_json().get("trash_count"), 2)

    def test_trash_count_matches_view_trash_listing(self):
        self._login(self.user["id"])
        self.client.delete(f"/api/files/{self.f1['id']}/delete")
        reported = self.client.delete(f"/api/files/{self.f2['id']}/delete").get_json()["trash_count"]
        r = self.client.get("/api/files?view=trash")
        self.assertEqual(r.status_code, 200)
        listed = len(r.get_json()["files"])
        self.assertEqual(reported, listed)

    def test_restore_decrements_trash_count_context(self):
        # Restore path stays intact: after restoring, view=trash is empty again.
        self._login(self.user["id"])
        self.client.delete(f"/api/files/{self.f1['id']}/delete")
        self.client.delete(f"/api/files/{self.f2['id']}/delete")
        r = self.client.post(f"/api/files/{self.f1['id']}/restore")
        self.assertEqual(r.status_code, 200)
        r2 = self.client.get("/api/files?view=trash")
        self.assertEqual(len(r2.get_json()["files"]), 1)

    def test_delete_twice_returns_404(self):
        # Already-deleted files are not re-trashed; no phantom count growth.
        self._login(self.user["id"])
        self.client.delete(f"/api/files/{self.f1['id']}/delete")
        r = self.client.delete(f"/api/files/{self.f1['id']}/delete")
        self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
