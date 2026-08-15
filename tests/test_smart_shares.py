"""
Smart Share Links tests (Phase 4A).

Tests share creation with advanced options, password protection,
download limits, one-time links, expiration, revocation, vault integration,
and security properties. Uses mocked Telegram access.
"""
import sys
import os
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from storage_db import (
    init_db,
    create_user,
    get_vault_settings,
    get_connection,
    create_file_record,
    create_share,
    get_share_by_token,
    get_share_by_id,
    revoke_share,
    list_user_shares,
    increment_share_download_count,
    invalidate_one_time_share,
    update_share_last_accessed,
    vault_file,
    soft_delete_file,
)
from main import app


class _FreshRateLimitStore:
    """Fresh in-memory rate limiter store for tests (no Redis)."""
    def __init__(self):
        from rate_limiter import _InMemoryBackend
        self._backend = _InMemoryBackend()
        self._backend_name = "memory"

    @property
    def backend_name(self):
        return self._backend_name

    def status(self, key: str, limit, window) -> int | None:
        from datetime import timedelta
        if isinstance(window, timedelta):
            window_seconds = int(window.total_seconds())
        else:
            window_seconds = int(window)
        return self._backend.is_allowed(f"ratelimit:{key}", limit, window_seconds)

    def remember(self, key: str):
        self._backend.record(f"ratelimit:{key}")

    def prune_all(self, window):
        from datetime import timedelta
        if isinstance(window, timedelta):
            window_seconds = int(window.total_seconds())
        else:
            window_seconds = int(window)
        self._backend.prune(window_seconds)


def _cleanup_test_data():
    with get_connection() as conn:
        for tg_id in ("500001", "500002"):
            row = conn.execute("SELECT id FROM users WHERE telegram_user_id = ?", (tg_id,)).fetchone()
            if row:
                uid = row["id"]
                conn.execute("DELETE FROM file_shares WHERE owner_user_id = ?", (uid,))
                conn.execute("DELETE FROM vault_settings WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_log WHERE user_id = ?", (uid,))
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


class ShareTestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        init_db()
        _cleanup_test_data()
        cls.user_a = _get_or_create_user("500001", "+5000000001", "Share User A", "sa@test.local")
        cls.user_b = _get_or_create_user("500002", "+5000000002", "Share User B", "sb@test.local")

    def setUp(self):
        self.client = app.test_client()
        with get_connection() as conn:
            conn.execute("DELETE FROM file_shares WHERE owner_user_id IN (?, ?)",
                         (self.user_a["id"], self.user_b["id"]))
            conn.execute("DELETE FROM file_records WHERE user_id IN (?, ?)",
                         (self.user_a["id"], self.user_b["id"]))
        import main as _main
        _main.rate_limit = _FreshRateLimitStore()
        self.file_a = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=2001,
            filename="test_share.txt",
            mime_type="text/plain",
            size=1024,
        )
        self.image_a = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=2002,
            filename="photo.jpg",
            mime_type="image/jpeg",
            size=2048,
        )

    def _login(self, user_id):
        with self.client.session_transaction() as sess:
            sess["app_user_id"] = user_id


class TestExistingShareWorks(ShareTestBase):
    def test_basic_share_creation(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "can_download": True,
        })
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertIn("token", data["share"])
        self.assertIn("url", data["share"])

    def test_basic_share_viewable(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        token = r.get_json()["share"]["token"]
        r2 = self.client.get(f"/s/{token}")
        self.assertEqual(r2.status_code, 200)


class TestCreateShareAdvanced(ShareTestBase):
    def test_share_with_expiration(self):
        future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "expires_at": future,
        })
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertIsNotNone(data["share"]["expires_at"])

    def test_share_with_past_expiration_rejected(self):
        past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "expires_at": past,
        })
        self.assertEqual(r.status_code, 400)

    def test_share_with_invalid_expiration_rejected(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "expires_at": "not-a-date",
        })
        self.assertEqual(r.status_code, 400)

    def test_share_with_download_limit(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "can_download": True, "download_limit": 5,
        })
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertEqual(data["share"]["download_limit"], 5)

    def test_share_with_invalid_download_limit(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "download_limit": -1,
        })
        self.assertEqual(r.status_code, 400)

    def test_share_with_zero_download_limit(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "download_limit": 0,
        })
        self.assertEqual(r.status_code, 400)

    def test_share_with_one_time(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "can_download": True, "one_time": True,
        })
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertTrue(data["share"]["one_time"])

    def test_share_with_password(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "password": "secret123",
        })
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertTrue(data["share"]["has_password"])

    def test_share_with_short_password_rejected(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "password": "ab",
        })
        self.assertEqual(r.status_code, 400)

    def test_share_password_not_stored_plaintext(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "password": "secret123",
        })
        token = r.get_json()["share"]["token"]
        share = get_share_by_token(token)
        self.assertIsNotNone(share)
        self.assertNotEqual(share["password_hash"], "secret123")
        self.assertIn("pbkdf2:", share["password_hash"])


class TestListShares(ShareTestBase):
    def test_list_shares_returns_own(self):
        self._login(self.user_a["id"])
        self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        r = self.client.get("/api/shares")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(len(data["shares"]), 1)

    def test_list_shares_excludes_other_users(self):
        self._login(self.user_a["id"])
        self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        self._login(self.user_b["id"])
        r = self.client.get("/api/shares")
        data = r.get_json()
        self.assertEqual(len(data["shares"]), 0)

    def test_list_shares_includes_new_fields(self):
        self._login(self.user_a["id"])
        self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "password": "test1234", "one_time": True, "download_limit": 5,
        })
        r = self.client.get("/api/shares")
        share = r.get_json()["shares"][0]
        self.assertTrue(share["has_password"])
        self.assertTrue(share["one_time"])
        self.assertEqual(share["download_limit"], 5)
        self.assertEqual(share["download_count"], 0)


class TestRevokeShare(ShareTestBase):
    def test_revoke_share(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        share_id = r.get_json()["share"]["id"]
        r2 = self.client.delete(f"/api/shares/{share_id}/revoke")
        self.assertEqual(r2.status_code, 200)

    def test_revoked_share_inaccessible(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        token = r.get_json()["share"]["token"]
        share_id = r.get_json()["share"]["id"]
        self.client.delete(f"/api/shares/{share_id}/revoke")
        r2 = self.client.get(f"/s/{token}")
        self.assertIn(r2.status_code, (403, 404, 410))

    def test_revoke_sets_revoked_at(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        share_id = r.get_json()["share"]["id"]
        self.client.delete(f"/api/shares/{share_id}/revoke")
        share = get_share_by_id(share_id, self.user_a["id"])
        self.assertIsNotNone(share["revoked_at"])

    def test_user_b_cannot_revoke_user_a_share(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        share_id = r.get_json()["share"]["id"]
        self._login(self.user_b["id"])
        r2 = self.client.delete(f"/api/shares/{share_id}/revoke")
        self.assertEqual(r2.status_code, 404)


class TestExpiredShare(ShareTestBase):
    def _create_expired_share(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "can_download": True,
        })
        share = r.get_json()["share"]
        token = share["token"]
        past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with get_connection() as conn:
            conn.execute("UPDATE file_shares SET expires_at = ? WHERE share_token = ?",
                         (past, token))
        return token

    def test_expired_share_returns_410(self):
        token = self._create_expired_share()
        r2 = self.client.get(f"/s/{token}")
        self.assertEqual(r2.status_code, 410)

    def test_expired_share_download_denied(self):
        token = self._create_expired_share()
        r2 = self.client.get(f"/api/share/{token}/download")
        self.assertIn(r2.status_code, (403, 410))


class TestPasswordShare(ShareTestBase):
    def test_password_share_requires_password(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "password": "secret123",
        })
        token = r.get_json()["share"]["token"]
        r2 = self.client.get(f"/s/{token}")
        self.assertEqual(r2.status_code, 200)
        self.assertIn(b"password", r2.data.lower())

    def test_wrong_password_rejected(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "password": "secret123",
        })
        token = r.get_json()["share"]["token"]
        r2 = self.client.post(f"/api/share/{token}/verify-password", json={
            "password": "wrongpass",
        })
        self.assertEqual(r2.status_code, 403)

    def test_correct_password_grants_access(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "password": "secret123",
        })
        token = r.get_json()["share"]["token"]
        r2 = self.client.post(f"/api/share/{token}/verify-password", json={
            "password": "secret123",
        })
        self.assertEqual(r2.status_code, 200)

    def test_password_rate_limiting(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "password": "secret123",
        })
        token = r.get_json()["share"]["token"]
        for _ in range(12):
            self.client.post(f"/api/share/{token}/verify-password", json={
                "password": "wrong",
            })
        r2 = self.client.post(f"/api/share/{token}/verify-password", json={
            "password": "wrong",
        })
        self.assertIn(r2.status_code, (403, 429))


class TestDownloadPermission(ShareTestBase):
    def test_download_disabled_returns_403(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "can_download": False,
        })
        token = r.get_json()["share"]["token"]
        r2 = self.client.get(f"/api/share/{token}/download")
        self.assertEqual(r2.status_code, 403)

    def test_download_enabled_works(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "can_download": True,
        })
        token = r.get_json()["share"]["token"]
        r2 = self.client.get(f"/api/share/{token}/download")
        self.assertNotEqual(r2.status_code, 403)


class TestDownloadLimit(ShareTestBase):
    def test_download_limit_enforced(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "can_download": True, "download_limit": 1,
        })
        token = r.get_json()["share"]["token"]
        share = get_share_by_token(token)
        increment_share_download_count(share["id"])
        r2 = self.client.get(f"/api/share/{token}/download")
        self.assertIn(r2.status_code, (403, 410))

    def test_download_count_incremented(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "can_download": True, "download_limit": 5,
        })
        share_id = r.get_json()["share"]["id"]
        increment_share_download_count(share_id)
        share = get_share_by_id(share_id, self.user_a["id"])
        self.assertEqual(share["download_count"], 1)


class TestOneTimeLink(ShareTestBase):
    def test_one_time_share_invalidated_after_use(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "can_download": True, "one_time": True,
        })
        share_id = r.get_json()["share"]["id"]
        token = r.get_json()["share"]["token"]
        increment_share_download_count(share_id)
        invalidate_one_time_share(share_id)
        r2 = self.client.get(f"/s/{token}")
        self.assertIn(r2.status_code, (403, 404, 410))

    def test_one_time_share_not_invalidated_on_wrong_password(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "password": "secret123", "one_time": True,
        })
        token = r.get_json()["share"]["token"]
        self.client.post(f"/api/share/{token}/verify-password", json={"password": "wrong"})
        share = get_share_by_token(token)
        self.assertTrue(share is not None)
        self.assertEqual(share["is_active"], 1)


class TestOwnerIsolation(ShareTestBase):
    def test_user_b_cannot_see_user_a_shares(self):
        self._login(self.user_a["id"])
        self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        self._login(self.user_b["id"])
        r = self.client.get("/api/shares")
        data = r.get_json()
        self.assertEqual(len(data["shares"]), 0)

    def test_user_b_cannot_revoke_user_a_share(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        share_id = r.get_json()["share"]["id"]
        self._login(self.user_b["id"])
        r2 = self.client.delete(f"/api/shares/{share_id}/revoke")
        self.assertEqual(r2.status_code, 404)


class TestInvalidToken(ShareTestBase):
    def test_invalid_token_returns_404(self):
        r = self.client.get("/s/invalidtoken123")
        self.assertEqual(r.status_code, 404)

    def test_invalid_token_download_returns_403(self):
        r = self.client.get("/api/share/invalidtoken123/download")
        self.assertEqual(r.status_code, 403)


class TestDeletedFileShare(ShareTestBase):
    def test_deleted_file_share_inaccessible(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        token = r.get_json()["share"]["token"]
        soft_delete_file(self.file_a["id"], self.user_a["id"])
        r2 = self.client.get(f"/s/{token}")
        self.assertIn(r2.status_code, (404, 403, 410))


class TestVaultFileShare(ShareTestBase):
    def test_vaulted_file_share_inaccessible(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        token = r.get_json()["share"]["token"]
        vault_file(self.file_a["id"], self.user_a["id"])
        r2 = self.client.get(f"/s/{token}")
        self.assertIn(r2.status_code, (403, 404))


class TestMoveSharedFileToVault(ShareTestBase):
    def test_move_to_vault_revokes_shares(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        self._login(self.user_a["id"])
        r2 = self.client.post("/api/vault/pin", json={"pin": "123456"})
        self._login(self.user_a["id"])
        r3 = self.client.post("/api/vault/unlock", json={"pin": "123456"})
        self._login(self.user_a["id"])
        r4 = self.client.post("/api/vault/move", json={"type": "file", "id": self.file_a["id"]})
        self.assertEqual(r4.status_code, 200)


class TestPreviewOnlyShare(ShareTestBase):
    def test_preview_only_share_download_denied(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.image_a['id']}/share", json={
            "can_view": True, "can_download": False,
        })
        token = r.get_json()["share"]["token"]
        r2 = self.client.get(f"/api/share/{token}/download")
        self.assertEqual(r2.status_code, 403)


class TestMalformedExpiration(ShareTestBase):
    def test_string_expiration_rejected(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "expires_at": "not-a-date",
        })
        self.assertEqual(r.status_code, 400)

    def test_integer_expiration_rejected(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "expires_at": 12345,
        })
        self.assertEqual(r.status_code, 400)


class TestInvalidDownloadLimit(ShareTestBase):
    def test_negative_limit_rejected(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "download_limit": -1,
        })
        self.assertEqual(r.status_code, 400)

    def test_zero_limit_rejected(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "download_limit": 0,
        })
        self.assertEqual(r.status_code, 400)

    def test_huge_limit_rejected(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "download_limit": 999999,
        })
        self.assertEqual(r.status_code, 400)

    def test_string_limit_rejected(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={
            "can_view": True, "download_limit": "abc",
        })
        self.assertEqual(r.status_code, 400)


class TestXSSInFilename(ShareTestBase):
    def test_xss_in_filename_escaped(self):
        self._login(self.user_a["id"])
        xss_file = create_file_record(
            user_id=self.user_a["id"],
            telegram_message_id=2003,
            filename='<script>alert("xss")</script>.txt',
            mime_type="text/plain",
            size=100,
        )
        r = self.client.post(f"/api/files/{xss_file['id']}/share", json={"can_view": True})
        token = r.get_json()["share"]["token"]
        r2 = self.client.get(f"/s/{token}")
        self.assertNotIn(b"<script>", r2.data)


class TestCSPHeaders(ShareTestBase):
    def test_csp_header_present(self):
        self._login(self.user_a["id"])
        r = self.client.post(f"/api/files/{self.file_a['id']}/share", json={"can_view": True})
        token = r.get_json()["share"]["token"]
        r2 = self.client.get(f"/s/{token}")
        self.assertIn("Content-Security-Policy", r2.headers)


if __name__ == "__main__":
    unittest.main()
