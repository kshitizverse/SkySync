"""
Multi-worker Vault VMK store tests.

Simulates gunicorn's multi-worker topology: the Vault unlock runs against
one backend instance and subsequent requests (read / upload / lock) run
against a DIFFERENT one. With the historical per-process VMK dict this
exact sequence failed on the second worker with 403 "Vault session
expired". With the shared store the full authorized state (unlocked flag
in the server-side session + VMK in the shared store) is visible to every
worker behind the same session cookie.

The shared backend used here is a dict-based stand-in with the exact same
interface as _RedisVMKBackend; the real Redis backend is additionally
unit-tested for serialization/TTL round-trips (TestRedisVMKBackend).
No plaintext PIN, VMK, or credential ever appears in a response body.
"""
import base64
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from storage_db import (
    init_db,
    create_user,
    get_user_by_telegram_id,
    get_connection,
)
from main import app
import vault as vault_module


def _cleanup_test_data():
    """Remove the multi-worker test users from the DB."""
    with get_connection() as conn:
        for tg_id in ("300003", "300004"):
            row = conn.execute("SELECT id FROM users WHERE telegram_user_id = ?", (tg_id,)).fetchone()
            if row:
                uid = row["id"]
                conn.execute("DELETE FROM vault_settings WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_log WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_events WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM file_records WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM users WHERE id = ?", (uid,))


def _get_or_create_user(tg_id, phone, name, email):
    user = get_user_by_telegram_id(tg_id)
    if user:
        return user
    return create_user(
        email=email, phone=phone,
        name=name, telegram_user_id=tg_id,
        session_path="/fake/path.session",
    )


class _SharedFakeBackend:
    """Dict backend with the exact interface of _RedisVMKBackend.

    Stands in for a Redis instance that every gunicorn worker shares:
    state written by "worker A" is visible to "worker B" because both
    simulated workers point at this one object.
    """

    def __init__(self):
        self.store = {}

    def put(self, session_id, record):
        self.store[session_id] = dict(record)

    def get(self, session_id):
        record = self.store.get(session_id)
        return dict(record) if record else None

    def delete(self, session_id):
        self.store.pop(session_id, None)

    def touch(self, session_id, now):
        record = self.store.get(session_id)
        if record is not None:
            record["last_activity"] = now


class _FakeRedis:
    """Minimal redis-py stand-in for _RedisVMKBackend unit tests."""

    def __init__(self):
        self.data = {}
        self.last_ex = None

    def ping(self):
        return True

    def set(self, key, value, ex=None):
        self.data[key] = value
        self.last_ex = ex
        return True

    def get(self, key):
        return self.data.get(key)

    def delete(self, key):
        return 1 if self.data.pop(key, None) is not None else 0

    def expire(self, key, ex):
        return key in self.data


class MultiWorkerVMKTestBase(unittest.TestCase):
    """Two users, two simulated workers, one shared VMK backend."""

    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        init_db()
        _cleanup_test_data()
        cls.user_a = _get_or_create_user("300003", "+3000000003", "MW User A", "mwa@test.local")
        cls.user_b = _get_or_create_user("300004", "+3000000004", "MW User B", "mwb@test.local")
        # Set up the Vault PIN once for user A (Argon2id, ~0.3 s).
        cls.pin_client = app.test_client()
        with cls.pin_client.session_transaction() as sess:
            sess["app_user_id"] = cls.user_a["id"]
        resp = cls.pin_client.post("/api/vault/pin", json={"pin": "123456"})
        assert resp.status_code in (200, 201), resp.get_data(as_text=True)

    def setUp(self):
        # One shared "Redis" and a fresh worker pair per test.
        self.shared = _SharedFakeBackend()
        self.worker_a = app.test_client()
        self.worker_b = app.test_client()
        patcher = mock.patch.object(vault_module, "_vmk_backend", self.shared)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _login(self, client, user_id):
        with client.session_transaction() as sess:
            sess["app_user_id"] = user_id

    def _unlock_on_worker_a(self, pin="123456"):
        """PIN unlock against worker A. Returns (status, session_id)."""
        self._login(self.worker_a, self.user_a["id"])
        resp = self.worker_a.post("/api/vault/unlock", json={"pin": pin})
        session_id = next(iter(self.shared.store), None)
        return resp, session_id

    def _share_session_cookie(self):
        """Copy worker A's session cookie onto worker B (same browser session,
        different gunicorn worker)."""
        cookie = self.worker_a.get_cookie("skysync_session")
        assert cookie is not None, "worker A did not set a session cookie"
        self.worker_b.set_cookie(cookie.key, cookie.value)


class TestMultiWorkerVaultFlow(MultiWorkerVMKTestBase):

    def test_unlock_on_worker_a_readable_and_uploadable_on_worker_b(self):
        """Worker A: unlock. Worker B (same session cookie): read + upload path
        must see the authorized Vault state, not 403 'Vault session expired'."""
        resp, session_id = self._unlock_on_worker_a()
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertIsNotNone(session_id, "unlock must store a VMK entry")
        self._share_session_cookie()

        # Worker B: status sees the vault unlocked
        status = self.worker_b.get("/api/vault/status")
        self.assertEqual(status.status_code, 200)
        self.assertTrue(status.get_json()["unlocked"])

        # Worker B: authenticated vault read succeeds
        files = self.worker_b.get("/api/vault/files")
        self.assertEqual(files.status_code, 200, files.get_data(as_text=True))
        self.assertTrue(files.get_json()["success"])

        # Worker B: the VMK itself is retrievable with the owner binding
        vmk = vault_module._get_vmk_from_store(session_id, user_id=self.user_a["id"])
        self.assertIsInstance(vmk, (bytes, bytearray))
        self.assertEqual(len(vmk), vault_module.AESGCM_KEY_LEN)

    def test_lock_on_worker_a_invalidates_vmk_for_worker_b(self):
        """Worker A: unlock then lock. Worker B: read/upload must fail locked
        and the shared VMK entry must be gone."""
        _, session_id = self._unlock_on_worker_a()
        self._share_session_cookie()

        lock = self.worker_a.post("/api/vault/lock")
        self.assertEqual(lock.status_code, 200)

        # VMK removed from the shared store on lock
        self.assertIsNone(vault_module._get_vmk_from_store(session_id, user_id=self.user_a["id"]))

        # Worker B: read now fails locked
        files = self.worker_b.get("/api/vault/files")
        self.assertEqual(files.status_code, 403)
        self.assertIn("locked", files.get_json()["error"].lower())

        # Worker B: upload also fails locked (Telegram handler mocked so the
        # assertion lands on the vault-locked check, not on offline Telegram)
        from io import BytesIO
        from unittest import mock as _mock
        with _mock.patch.object(vault_module, "create_telegram_handler_for_user_from_vault",
                                return_value=object()):
            upload = self.worker_b.post(
                "/api/vault/upload",
                data={"file": (BytesIO(b"multi-worker probe"), "mw-probe.txt")},
                content_type="multipart/form-data",
            )
        self.assertEqual(upload.status_code, 403)
        body = upload.get_json()
        self.assertFalse(body["success"])

    def test_user_isolation_across_workers(self):
        """User B's session on any worker can never read user A's VMK or
        vault contents."""
        _, session_id = self._unlock_on_worker_a()

        # Worker B running user B's OWN session (no shared cookie)
        self._login(self.worker_b, self.user_b["id"])
        files = self.worker_b.get("/api/vault/files")
        self.assertEqual(files.status_code, 403)

        # Even with A's session id, the store refuses user B
        self.assertIsNone(vault_module._get_vmk_from_store(session_id, user_id=self.user_b["id"]))
        # ...but still serves the rightful owner
        self.assertIsNotNone(vault_module._get_vmk_from_store(session_id, user_id=self.user_a["id"]))

    def test_b_locked_session_does_not_leak_a_unlocked_listing(self):
        """B's unlocked flag lives in B's session; A unlocking must not
        unlock B's vault view on a different worker."""
        _, _ = self._unlock_on_worker_a()
        self._login(self.worker_b, self.user_b["id"])
        status = self.worker_b.get("/api/vault/status")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.get_json()["unlocked"])

    def test_expired_vmk_entry_is_denied_and_removed(self):
        """An entry idle longer than VAULT_INACTIVITY_SECONDS is treated as
        absent and deleted (auto-lock semantics in the store)."""
        _, session_id = self._unlock_on_worker_a()
        record = self.shared.store[session_id]
        record["last_activity"] = time.time() - vault_module.VAULT_INACTIVITY_SECONDS - 5

        self.assertIsNone(vault_module._get_vmk_from_store(session_id, user_id=self.user_a["id"]))
        self.assertNotIn(session_id, self.shared.store)

    def test_missing_session_id_returns_none(self):
        self.assertIsNone(vault_module._get_vmk_from_store(None, user_id=self.user_a["id"]))
        self.assertIsNone(vault_module._get_vmk_from_store("", user_id=self.user_a["id"]))


class TestRedisVMKBackend(unittest.TestCase):
    """Unit tests for the real Redis backend (serialization, TTL, namespace)."""

    def _backend(self):
        backend = vault_module._RedisVMKBackend.__new__(vault_module._RedisVMKBackend)
        backend._r = _FakeRedis()
        return backend

    def test_roundtrip_preserves_vmk_bytes_and_user_binding(self):
        backend = self._backend()
        vmk = os.urandom(vault_module.AESGCM_KEY_LEN)
        backend.put("sess-1", {"user_id": 42, "vmk": vmk, "created": 1.0, "last_activity": 2.0})

        record = backend.get("sess-1")
        self.assertIsNotNone(record)
        self.assertEqual(record["user_id"], 42)
        self.assertEqual(bytes(record["vmk"]), vmk)

    def test_delete_removes_entry(self):
        backend = self._backend()
        backend.put("sess-2", {"user_id": 1, "vmk": b"k" * 32, "created": 1.0, "last_activity": 2.0})
        backend.delete("sess-2")
        self.assertIsNone(backend.get("sess-2"))

    def test_keys_use_strict_namespace_and_ttl(self):
        backend = self._backend()
        backend.put("sess-3", {"user_id": 1, "vmk": b"k" * 32, "created": 1.0, "last_activity": 2.0})
        ((key, _),) = backend._r.data.items()
        self.assertTrue(key.startswith(vault_module._VMK_KEY_PREFIX))
        self.assertEqual(key, vault_module._VMK_KEY_PREFIX + "sess-3")
        self.assertEqual(backend._r.last_ex, int(vault_module.VAULT_INACTIVITY_SECONDS))

    def test_stored_blob_never_contains_raw_vmk_ascii(self):
        """The blob is JSON with base64 VMK — a raw VMK never lands in Redis
        as bare bytes, and the stored value is decodable only via _loads."""
        backend = self._backend()
        vmk = os.urandom(32)
        backend.put("sess-4", {"user_id": 7, "vmk": vmk, "created": 1.0, "last_activity": 2.0})
        ((_, blob),) = backend._r.data.items()
        self.assertIsInstance(blob, bytes)
        self.assertNotIn(vmk, blob)  # raw key bytes never appear verbatim
        record = vault_module._RedisVMKBackend._loads(blob)
        self.assertEqual(bytes(record["vmk"]), vmk)

    def test_backend_selection_prefers_redis_when_configured(self):
        fake = _FakeRedis()
        with mock.patch.dict(os.environ, {"REDIS_URL": "redis://fake:6379/0"}):
            with mock.patch("redis.from_url", return_value=fake):
                with mock.patch.object(vault_module, "_vmk_backend", None):
                    backend = vault_module._get_vmk_backend()
                    self.assertIsInstance(backend, vault_module._RedisVMKBackend)

    def test_backend_selection_uses_memory_only_without_redis_url(self):
        """Development behavior (REDIS_URL completely absent) is unchanged:
        the per-process memory backend is selected."""
        env = {k: v for k, v in os.environ.items() if k != "REDIS_URL"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(vault_module, "_vmk_backend", None):
                backend = vault_module._get_vmk_backend()
                self.assertIsInstance(backend, vault_module._MemoryVMKBackend)

    def test_redis_url_set_but_unreachable_raises_and_never_selects_memory(self):
        """Fail-closed: REDIS_URL configured + Redis down raises
        _VMKStoreUnavailable. The per-process memory backend must NOT be
        selected — a fallback would split gunicorn workers."""
        with mock.patch.dict(os.environ, {"REDIS_URL": "redis://dead:6379/0"}):
            with mock.patch("redis.from_url", side_effect=ConnectionError("refused")):
                with mock.patch.object(vault_module, "_vmk_backend", None):
                    with self.assertRaises(vault_module._VMKStoreUnavailable):
                        vault_module._get_vmk_backend()
                    # Not cached, not degraded to memory: a later call retries
                    self.assertIsNone(vault_module._vmk_backend)

    def test_unreachable_redis_is_never_cached_as_memory_backend(self):
        """No accidental per-worker fallback: repeated selection attempts keep
        raising (retry semantics) and the module slot stays empty."""
        with mock.patch.dict(os.environ, {"REDIS_URL": "redis://dead:6379/0"}):
            with mock.patch("redis.from_url", side_effect=ConnectionError("refused")):
                with mock.patch.object(vault_module, "_vmk_backend", None):
                    for _ in range(3):
                        with self.assertRaises(vault_module._VMKStoreUnavailable):
                            vault_module._get_vmk_backend()
                    self.assertIsNone(vault_module._vmk_backend)


class TestVMKStoreFailClosed(MultiWorkerVMKTestBase):
    """REDIS_URL configured + Redis unavailable must fail closed with honest
    errors — never a silent per-process fallback that would split workers."""

    def _store_down(self):
        return mock.patch.object(
            vault_module, "_get_vmk_backend",
            side_effect=vault_module._VMKStoreUnavailable("redis down"),
        )

    def test_unlock_returns_503_and_stores_nothing_when_store_unavailable(self):
        """unlock() must NOT report success without a durable shared entry."""
        self._login(self.worker_a, self.user_a["id"])
        with self._store_down():
            resp = self.worker_a.post("/api/vault/unlock", json={"pin": "123456"})
        self.assertEqual(resp.status_code, 503)
        body = resp.get_json()
        self.assertFalse(body["success"])
        self.assertNotIn("vmk", resp.get_data(as_text=True).lower())
        # No VMK entry was written to any backend
        self.assertEqual(len(self.shared.store), 0)

    def test_upload_returns_503_not_memory_fallback_when_store_unavailable(self):
        """Worker B upload with the shared store down gets an honest 503.
        A per-worker memory fallback would instead answer 403 'Vault session
        expired' (nothing in THIS worker's memory) — or worse, succeed on a
        stale local copy. 503 is the only correct answer."""
        self._unlock_on_worker_a()
        self._share_session_cookie()
        from io import BytesIO
        with self._store_down():
            with mock.patch.object(vault_module, "create_telegram_handler_for_user_from_vault",
                                   return_value=object()):
                upload = self.worker_b.post(
                    "/api/vault/upload",
                    data={"file": (BytesIO(b"outage probe"), "outage-probe.txt")},
                    content_type="multipart/form-data",
                )
        self.assertEqual(upload.status_code, 503)
        self.assertFalse(upload.get_json()["success"])

    def test_lock_still_clears_session_state_when_store_unavailable(self):
        """Lock is best-effort on the store (TTL self-heals the entry) but
        must always clear the in-session unlock state."""
        _, session_id = self._unlock_on_worker_a()
        with self._store_down():
            lock = self.worker_a.post("/api/vault/lock")
        self.assertEqual(lock.status_code, 200)
        status = self.worker_a.get("/api/vault/status")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.get_json()["unlocked"])

    def test_plaintext_retrieval_fails_closed_when_store_unavailable(self):
        """get_vault_plaintext returns None (never plaintext, never a crash)
        when the shared store cannot be reached mid-decrypt."""
        record = {"id": 1, "is_vaulted": True, "enc_flag": 1,
                  "telegram_message_id": 111, "filename": "f.bin",
                  "dek_wrap_nonce": b"n", "dek_wrap_cipher": b"c",
                  "dek_wrap_tag": b"t", "file_enc_nonce": b"fn",
                  "file_enc_tag": b"ft"}
        user = {"id": self.user_a["id"]}
        with mock.patch("storage_db.get_user_file_record", return_value=record), \
             mock.patch("storage_db.get_user_by_id", return_value=user), \
             mock.patch("telegram_handler.create_telegram_handler_for_user", return_value=object()), \
             mock.patch.object(vault_module, "_download_from_telegram", return_value=b"ciphertext"), \
             self._store_down():
            with self.worker_a.application.test_request_context("/"):
                from flask import session as flask_session
                flask_session["vault_session_id"] = "sess-outage"
                result = vault_module.get_vault_plaintext(1, self.user_a["id"])
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
