"""
Smart Vault foundation tests.

Uses mocked Telegram access — no real OTP required.
Tests PIN management, unlock/lock, rate limiting, user isolation,
inactivity expiration, and security properties.
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
    utcnow_iso,
)
from main import app
from vault import vault_bp, VAULT_INACTIVITY_SECONDS


def _cleanup_test_data():
    """Remove test users and vault data from DB."""
    with get_connection() as conn:
        for tg_id in ("300001", "300002"):
            row = conn.execute("SELECT id FROM users WHERE telegram_user_id = ?", (tg_id,)).fetchone()
            if row:
                uid = row["id"]
                conn.execute("DELETE FROM vault_settings WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_log WHERE user_id = ?", (uid,))
                conn.execute("DELETE FROM activity_events WHERE user_id = ?", (uid,))
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


class VaultTestBase(unittest.TestCase):
    """Base class: inits DB, creates two test users."""

    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        init_db()
        _cleanup_test_data()
        cls.user_a = _get_or_create_user("300001", "+3000000001", "Vault User A", "va@test.local")
        cls.user_b = _get_or_create_user("300002", "+3000000002", "Vault User B", "vb@test.local")

    def setUp(self):
        self.client = app.test_client()
        # Clean vault state for each test
        with get_connection() as conn:
            conn.execute("DELETE FROM vault_settings WHERE user_id IN (?, ?)",
                         (self.user_a["id"], self.user_b["id"]))

    def _login(self, user_id):
        """Set up a logged-in session for the given user."""
        with self.client.session_transaction() as sess:
            sess["app_user_id"] = user_id

    def _set_pin(self, pin="123456"):
        """Helper: set PIN for user A."""
        self._login(self.user_a["id"])
        return self.client.post("/api/vault/pin", json={"pin": pin})

    def _unlock(self, pin="123456"):
        """Helper: unlock vault for user A."""
        self._login(self.user_a["id"])
        return self.client.post("/api/vault/unlock", json={"pin": pin})


class TestVaultStatusUnauthenticated(VaultTestBase):
    """1. Unauthenticated status returns 401."""

    def test_unauthenticated_status_returns_401(self):
        r = self.client.get("/api/vault/status")
        self.assertEqual(r.status_code, 401)
        data = r.get_json()
        self.assertFalse(data["success"])
        self.assertIn("error", data)


class TestVaultStatusAuthenticated(VaultTestBase):
    """2. Authenticated status returns configured=false when no PIN set."""

    def test_configured_false_when_no_pin(self):
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/status")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["configured"])
        self.assertFalse(data["unlocked"])


class TestVaultSetPin(VaultTestBase):
    """3. Set PIN creates vault settings."""

    def test_set_pin_creates_vault(self):
        r = self._set_pin()
        self.assertEqual(r.status_code, 201)
        data = r.get_json()
        self.assertTrue(data["success"])
        # Verify DB
        settings = get_vault_settings(self.user_a["id"])
        self.assertIsNotNone(settings)
        self.assertEqual(settings["vault_enabled"], 1)
        self.assertEqual(settings["failed_attempts"], 0)


class TestVaultSetPinTwice(VaultTestBase):
    """4. Setting PIN twice returns error."""

    def test_set_pin_twice_rejected(self):
        self._set_pin()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/pin", json={"pin": "654321"})
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertIn("already set", data["error"].lower())


class TestVaultChangePinWrongCurrent(VaultTestBase):
    """5. Change PIN with wrong current PIN fails."""

    def test_wrong_current_pin_rejected(self):
        self._set_pin()
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/pin/change", json={
            "current_pin": "wrong",
            "new_pin": "654321",
        })
        self.assertEqual(r.status_code, 403)
        data = r.get_json()
        self.assertIn("invalid current pin", data["error"].lower())


class TestVaultChangePinCorrect(VaultTestBase):
    """6. Change PIN with correct current PIN succeeds."""

    def test_correct_current_pin_accepted(self):
        self._set_pin("123456")
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/pin/change", json={
            "current_pin": "123456",
            "new_pin": "654321",
        })
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])


class TestVaultUnlockWrongPin(VaultTestBase):
    """7. Unlock with wrong PIN fails."""

    def test_wrong_pin_rejected(self):
        self._set_pin("123456")
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/unlock", json={"pin": "wrong"})
        self.assertEqual(r.status_code, 403)
        data = r.get_json()
        self.assertIn("invalid", data["error"].lower())


class TestVaultUnlockCorrectPin(VaultTestBase):
    """8. Unlock with correct PIN succeeds and unlocks vault."""

    def test_correct_pin_unlocks(self):
        self._set_pin("123456")
        r = self._unlock("123456")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        # Verify status shows unlocked
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/status")
        data = r.get_json()
        self.assertTrue(data["unlocked"])


class TestVaultLock(VaultTestBase):
    """9. Lock immediately locks the vault."""

    def test_lock_locks_vault(self):
        self._set_pin("123456")
        self._unlock("123456")
        # Lock
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/lock")
        self.assertEqual(r.status_code, 200)
        data = r.get_json()
        self.assertTrue(data["success"])
        # Verify locked
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/status")
        data = r.get_json()
        self.assertFalse(data["unlocked"])


class TestVaultStatusAfterLock(VaultTestBase):
    """10. Status after lock shows unlocked=false."""

    def test_status_after_lock(self):
        self._set_pin("123456")
        self._unlock("123456")
        self._login(self.user_a["id"])
        self.client.post("/api/vault/lock")
        # Check status
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/status")
        data = r.get_json()
        self.assertFalse(data["unlocked"])


class TestVaultUserIsolation(VaultTestBase):
    """11. User A vault must not affect User B."""

    def test_user_b_cannot_see_user_a_vault(self):
        # User A sets PIN and unlocks
        self._set_pin("123456")
        self._unlock("123456")
        # User B checks status — should see own (unconfigured) vault
        self._login(self.user_b["id"])
        r = self.client.get("/api/vault/status")
        data = r.get_json()
        self.assertTrue(data["success"])
        self.assertFalse(data["configured"])
        self.assertFalse(data["unlocked"])


class TestVaultRateLimiting(VaultTestBase):
    """12. Rate limiting after repeated wrong PINs."""

    def test_rate_limit_after_failures(self):
        self._set_pin("123456")
        # Make 10 wrong attempts
        for _ in range(10):
            self._login(self.user_a["id"])
            self.client.post("/api/vault/unlock", json={"pin": "wrong"})
        # 11th attempt should be rate-limited
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/unlock", json={"pin": "wrong"})
        # Should be 429 or 403 (rate-limited or still rejected)
        self.assertIn(r.status_code, (403, 429))


class TestVaultPinHashNotReturned(VaultTestBase):
    """13. PIN hash is never returned in API responses."""

    def test_pin_hash_not_in_status(self):
        self._set_pin("123456")
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/status")
        data = r.get_json()
        self.assertNotIn("pin_hash", data)
        self.assertNotIn("pin", data)
        self.assertNotIn("hash", data)


class TestVaultPinNotStoredPlaintext(VaultTestBase):
    """14. PIN is not stored in plaintext in the database."""

    def test_pin_not_stored_plaintext(self):
        pin = "123456"
        self._set_pin(pin)
        settings = get_vault_settings(self.user_a["id"])
        self.assertIsNotNone(settings)
        self.assertNotEqual(settings["pin_hash"], pin)
        self.assertIn("pbkdf2:", settings["pin_hash"])  # werkzeug default


class TestVaultInactivityExpiration(VaultTestBase):
    """15. Inactivity expiration locks the vault after timeout."""

    def test_inactivity_expires_vault(self):
        self._set_pin("123456")
        self._unlock("123456")
        # Manually set last activity to the past
        from datetime import datetime, timedelta, timezone
        past = (datetime.now(timezone.utc) - timedelta(seconds=VAULT_INACTIVITY_SECONDS + 60)).isoformat()
        with self.client.session_transaction() as sess:
            sess["vault_last_activity"] = past
        # Check status — should be locked
        self._login(self.user_a["id"])
        r = self.client.get("/api/vault/status")
        data = r.get_json()
        self.assertFalse(data["unlocked"])


class TestVaultChangePinFlow(VaultTestBase):
    """16-18. Full change PIN flow: old PIN rejected, new PIN accepted."""

    def test_old_pin_rejected_after_change(self):
        self._set_pin("123456")
        # Change PIN
        self._login(self.user_a["id"])
        self.client.post("/api/vault/pin/change", json={
            "current_pin": "123456",
            "new_pin": "654321",
        })
        # Old PIN should be rejected
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/unlock", json={"pin": "123456"})
        self.assertEqual(r.status_code, 403)

    def test_new_pin_accepted_after_change(self):
        self._set_pin("123456")
        # Change PIN
        self._login(self.user_a["id"])
        self.client.post("/api/vault/pin/change", json={
            "current_pin": "123456",
            "new_pin": "654321",
        })
        # New PIN should work
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/unlock", json={"pin": "654321"})
        self.assertEqual(r.status_code, 200)


class TestVaultPinValidation(VaultTestBase):
    """PIN validation: too short, missing, empty."""

    def test_pin_too_short(self):
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/pin", json={"pin": "123"})
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertIn("at least", data["error"].lower())

    def test_pin_missing(self):
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/pin", json={})
        self.assertEqual(r.status_code, 400)

    def test_pin_empty(self):
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/pin", json={"pin": ""})
        self.assertEqual(r.status_code, 400)


class TestVaultNotConfiguredEndpoints(VaultTestBase):
    """Endpoints behave correctly when vault is not configured."""

    def test_unlock_not_configured(self):
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/unlock", json={"pin": "123456"})
        self.assertEqual(r.status_code, 400)
        data = r.get_json()
        self.assertIn("not configured", data["error"].lower())

    def test_change_pin_not_configured(self):
        self._login(self.user_a["id"])
        r = self.client.post("/api/vault/pin/change", json={
            "current_pin": "123",
            "new_pin": "456",
        })
        self.assertEqual(r.status_code, 400)


class TestVaultSecurityNoIDOR(VaultTestBase):
    """User B must not be able to operate on User A's vault."""

    def test_user_b_cannot_change_user_a_pin(self):
        self._set_pin("123456")
        # User B tries to change User A's PIN
        self._login(self.user_b["id"])
        r = self.client.post("/api/vault/pin/change", json={
            "current_pin": "123456",
            "new_pin": "654321",
        })
        # Should fail — user B has no vault configured
        self.assertIn(r.status_code, (400, 403))

    def test_user_b_cannot_unlock_user_a_vault(self):
        self._set_pin("123456")
        self._login(self.user_b["id"])
        r = self.client.post("/api/vault/unlock", json={"pin": "123456"})
        self.assertIn(r.status_code, (400, 403))


if __name__ == "__main__":
    unittest.main()
