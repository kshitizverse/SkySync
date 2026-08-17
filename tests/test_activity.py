"""
Activity Timeline tests (Phase 5A).

Tests record_activity, get_user_activity, _sanitize_metadata,
event type validation, user isolation, and the GET /api/user/activity endpoint.
"""
import sys
import os
import json
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(1, os.path.join(os.path.dirname(__file__), ".."))

from storage_db import (
    init_db,
    create_user,
    get_connection,
    create_file_record,
    create_folder,
    record_activity,
    get_user_activity,
    _sanitize_metadata,
    _VALID_EVENT_TYPES,
    _SENSITIVE_KEYS,
)
from main import app


def _cleanup():
    with get_connection() as conn:
        for tg_id in ("600001", "600002"):
            row = conn.execute("SELECT id FROM users WHERE telegram_user_id = ?", (tg_id,)).fetchone()
            if row:
                uid = row["id"]
                conn.execute("DELETE FROM activity_events WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_log WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM file_records WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM folders WHERE user_id = ?", (uid,))
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


class TestSanitizeMetadata(unittest.TestCase):
    def test_strips_sensitive_keys(self):
        meta = {"filename": "doc.pdf", "password": "secret123", "token": "abc"}
        result = json.loads(_sanitize_metadata(meta))
        self.assertIn("filename", result)
        self.assertNotIn("password", result)
        self.assertNotIn("token", result)

    def test_strips_hash_variants(self):
        meta = {"pin_hash": "x", "share_password_hash": "y", "api_key": "z"}
        result = _sanitize_metadata(meta)
        self.assertIsNone(result)

    def test_returns_none_for_empty(self):
        self.assertIsNone(_sanitize_metadata(None))
        self.assertIsNone(_sanitize_metadata({}))
        self.assertIsNone(_sanitize_metadata("not a dict"))

    def test_preserves_safe_keys(self):
        meta = {"filename": "test.txt", "size": 1024, "old_name": "a.txt", "new_name": "b.txt"}
        result = json.loads(_sanitize_metadata(meta))
        self.assertEqual(result["filename"], "test.txt")
        self.assertEqual(result["size"], 1024)


class TestRecordActivity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        _cleanup()
        cls.user_a = _get_or_create_user("600001", "+6000000001", "Activity User A", "aa@test.local")
        cls.user_b = _get_or_create_user("600002", "+6000000002", "Activity User B", "ab@test.local")

    def setUp(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM activity_events WHERE user_id IN (?, ?)",
                         (self.user_a["id"], self.user_b["id"]))

    def test_records_valid_event(self):
        record_activity(self.user_a["id"], "FILE_UPLOADED", resource_type="file", resource_id=1,
                        metadata={"filename": "test.pdf"})
        events = get_user_activity(self.user_a["id"])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "FILE_UPLOADED")
        self.assertEqual(events[0]["resource_type"], "file")
        self.assertEqual(events[0]["resource_id"], 1)

    def test_ignores_invalid_event_type(self):
        record_activity(self.user_a["id"], "INVALID_EVENT")
        events = get_user_activity(self.user_a["id"])
        self.assertEqual(len(events), 0)

    def test_never_raises_on_db_error(self):
        record_activity(999999, "FILE_UPLOADED")
        events = get_user_activity(999999)
        self.assertEqual(len(events), 0)

    def test_metadata_sanitized_on_record(self):
        record_activity(self.user_a["id"], "SHARE_CREATED", resource_type="file",
                        metadata={"filename": "x.pdf", "password": "secret"})
        events = get_user_activity(self.user_a["id"])
        self.assertEqual(len(events), 1)
        meta = json.loads(events[0]["metadata"])
        self.assertIn("filename", meta)
        self.assertNotIn("password", meta)

    def test_all_valid_event_types_accepted(self):
        for et in _VALID_EVENT_TYPES:
            record_activity(self.user_a["id"], et, resource_type="file", resource_id=0)
        events = get_user_activity(self.user_a["id"])
        recorded_types = {e["event_type"] for e in events}
        self.assertEqual(recorded_types, _VALID_EVENT_TYPES)


class TestGetUserActivity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        _cleanup()
        cls.user_a = _get_or_create_user("600001", "+6000000001", "Activity User A", "aa@test.local")
        cls.user_b = _get_or_create_user("600002", "+6000000002", "Activity User B", "ab@test.local")

    def setUp(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM activity_events WHERE user_id IN (?, ?)",
                         (self.user_a["id"], self.user_b["id"]))

    def _seed_events(self, user_id, count=10):
        for i in range(count):
            record_activity(user_id, "FILE_UPLOADED", resource_type="file", resource_id=i,
                            metadata={"filename": f"f{i}.txt"})

    def test_limit_caps_at_100(self):
        self._seed_events(self.user_a["id"], 110)
        events = get_user_activity(self.user_a["id"], limit=200)
        self.assertEqual(len(events), 100)

    def test_limit_zero_returns_empty(self):
        self._seed_events(self.user_a["id"])
        events = get_user_activity(self.user_a["id"], limit=0)
        self.assertEqual(len(events), 0)

    def test_offset_works(self):
        self._seed_events(self.user_a["id"], 5)
        events = get_user_activity(self.user_a["id"], limit=2, offset=3)
        self.assertEqual(len(events), 2)

    def test_event_type_filter(self):
        record_activity(self.user_a["id"], "FILE_UPLOADED", resource_type="file")
        record_activity(self.user_a["id"], "FILE_DELETED", resource_type="file")
        events = get_user_activity(self.user_a["id"], event_type="FILE_UPLOADED")
        self.assertTrue(all(e["event_type"] == "FILE_UPLOADED" for e in events))

    def test_resource_type_filter(self):
        record_activity(self.user_a["id"], "FILE_UPLOADED", resource_type="file")
        record_activity(self.user_a["id"], "FOLDER_CREATED", resource_type="folder")
        events = get_user_activity(self.user_a["id"], resource_type="folder")
        self.assertTrue(all(e["resource_type"] == "folder" for e in events))


class TestUserIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        _cleanup()
        cls.user_a = _get_or_create_user("600001", "+6000000001", "Activity User A", "aa@test.local")
        cls.user_b = _get_or_create_user("600002", "+6000000002", "Activity User B", "ab@test.local")

    def setUp(self):
        with get_connection() as conn:
            conn.execute("DELETE FROM activity_events WHERE user_id IN (?, ?)",
                         (self.user_a["id"], self.user_b["id"]))

    def test_user_a_cannot_see_user_b_events(self):
        record_activity(self.user_a["id"], "FILE_UPLOADED", resource_type="file", metadata={"filename": "a.txt"})
        record_activity(self.user_b["id"], "FILE_UPLOADED", resource_type="file", metadata={"filename": "b.txt"})
        events_a = get_user_activity(self.user_a["id"])
        events_b = get_user_activity(self.user_b["id"])
        self.assertEqual(len(events_a), 1)
        self.assertEqual(len(events_b), 1)
        self.assertIn("a.txt", events_a[0]["metadata"])
        self.assertIn("b.txt", events_b[0]["metadata"])


class TestActivityEndpoint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        _cleanup()
        cls.user_a = _get_or_create_user("600001", "+6000000001", "Activity User A", "aa@test.local")

    def setUp(self):
        self.client = app.test_client()
        with get_connection() as conn:
            conn.execute("DELETE FROM activity_events WHERE user_id = ?", (self.user_a["id"],))

    def _login(self, uid):
        with self.client.session_transaction() as sess:
            sess["app_user_id"] = uid

    def test_unauthenticated_returns_401(self):
        r = self.client.get("/api/user/activity")
        self.assertEqual(r.status_code, 401)

    def test_returns_activities(self):
        record_activity(self.user_a["id"], "FILE_UPLOADED", resource_type="file")
        self._login(self.user_a["id"])
        r = self.client.get("/api/user/activity")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["activities"]), 1)
        self.assertEqual(data["activities"][0]["event_type"], "FILE_UPLOADED")

    def test_limit_and_offset_params(self):
        for i in range(10):
            record_activity(self.user_a["id"], "FILE_UPLOADED", resource_type="file")
        self._login(self.user_a["id"])
        r = self.client.get("/api/user/activity?limit=3&offset=5")
        data = r.get_json()
        self.assertEqual(len(data["activities"]), 3)

    def test_event_type_filter_endpoint(self):
        record_activity(self.user_a["id"], "FILE_UPLOADED", resource_type="file")
        record_activity(self.user_a["id"], "FILE_DELETED", resource_type="file")
        self._login(self.user_a["id"])
        r = self.client.get("/api/user/activity?event_type=FILE_UPLOADED")
        data = r.get_json()
        self.assertTrue(all(e["event_type"] == "FILE_UPLOADED" for e in data["activities"]))

    def test_user_isolation_endpoint(self):
        other = _get_or_create_user("600002", "+6000000002", "Other", "other@test.local")
        record_activity(other["id"], "FILE_UPLOADED", resource_type="file", metadata={"filename": "other.txt"})
        self._login(self.user_a["id"])
        r = self.client.get("/api/user/activity")
        data = r.get_json()
        self.assertEqual(len(data["activities"]), 0)

    def test_limit_validated(self):
        self._login(self.user_a["id"])
        r = self.client.get("/api/user/activity?limit=-5")
        data = r.get_json()
        self.assertTrue(data["success"])


class TestLoggingFailureIsolation(unittest.TestCase):
    def test_record_activity_never_raises(self):
        record_activity(999999, "FILE_UPLOADED", resource_type="file")
        record_activity(999999, "INVALID_TYPE", resource_type="file")
        record_activity(999999, "FILE_UPLOADED", metadata={"password": "x", "token": "y"})


class TestSensitiveMetadataStripping(unittest.TestCase):
    def test_all_sensitive_keys_stripped(self):
        meta = {}
        for key in _SENSITIVE_KEYS:
            meta[key] = "secret_value"
        meta["filename"] = "safe.txt"
        result = json.loads(_sanitize_metadata(meta))
        self.assertEqual(len(result), 1)
        self.assertEqual(result["filename"], "safe.txt")

    def test_case_insensitive_stripping(self):
        meta = {"PASSWORD": "x", "Token": "y", "Api_Key": "z"}
        result = _sanitize_metadata(meta)
        self.assertIsNone(result)


class TestBulkOperations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db()
        _cleanup()
        cls.user_a = _get_or_create_user("600001", "+6000000001", "Activity User A", "aa@test.local")

    def setUp(self):
        self.client = app.test_client()
        with get_connection() as conn:
            conn.execute("DELETE FROM activity_events WHERE user_id = ?", (self.user_a["id"],))
            conn.execute("DELETE FROM file_records WHERE user_id = ?", (self.user_a["id"],))

    def _login(self, uid):
        with self.client.session_transaction() as sess:
            sess["app_user_id"] = uid

    def test_bulk_delete_records_events(self):
        self._login(self.user_a["id"])
        files = []
        for i in range(3):
            f = create_file_record(self.user_a["id"], telegram_message_id=9000 + i,
                                   filename=f"bulk{i}.txt", mime_type="text/plain", size=100)
            files.append(f)
        r = self.client.post("/api/files/bulk-delete", json={"file_ids": [f["id"] for f in files]})
        self.assertEqual(r.status_code, 200)
        events = get_user_activity(self.user_a["id"], event_type="FILE_DELETED")
        self.assertEqual(len(events), 3)

    def test_bulk_restore_records_events(self):
        self._login(self.user_a["id"])
        files = []
        for i in range(3):
            f = create_file_record(self.user_a["id"], telegram_message_id=9100 + i,
                                   filename=f"restore{i}.txt", mime_type="text/plain", size=100)
            from storage_db import soft_delete_file
            soft_delete_file(f["id"], self.user_a["id"])
            files.append(f)
        r = self.client.post("/api/files/bulk-restore", json={"file_ids": [f["id"] for f in files]})
        self.assertEqual(r.status_code, 200)
        events = get_user_activity(self.user_a["id"], event_type="FILE_RESTORED")
        self.assertEqual(len(events), 3)


if __name__ == "__main__":
    unittest.main()
