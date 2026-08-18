"""
Regression test for Settings view rendering, specifically for the
Vault -> Set Up Vault -> Settings flow.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import app


def test_settings_view_structure():
    """Test that the settings view exists in the dashboard HTML and has the expected structure."""
    with app.test_client() as client:
        # Get the dashboard page (requires login, so we need to log in first)
        # For simplicity, we'll test the template context by checking that the
        # settings-view element is present in the base template.
        # Since the dashboard route requires authentication, we'll log in a test user.
        # However, note that the settings view is part of the dashboard template
        # and does not depend on the user's vault state for its presence.
        # We can test by checking the raw template, but let's use a test client
        # with a mocked session.

        # Instead, we can test that the settings-view element is in the HTML
        # when we request the dashboard page (after logging in).
        # We'll create a test user and log in.

        from storage_db import init_db, create_user, get_connection

        # Initialize DB for test
        init_db()
        with get_connection() as conn:
            # Clean up any existing test user
            conn.execute("DELETE FROM users WHERE telegram_user_id = ?", ("999999",))
            conn.commit()

        # Create a test user
        user = create_user(
            email="test@example.com",
            phone="+19999999999",
            name="Test User",
            telegram_user_id="999999",
            session_path="test.session",
        )
        # Create a dummy session file
        open("test.session", "a").close()

        # Log in by setting the session
        with client.session_transaction() as sess:
            sess["app_user_id"] = user["id"]

        # Now request the dashboard
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # Check that the settings-view element is present
        assert 'id="settings-view"' in html

        # Check that the vault-security-content div is present inside the settings-view
        assert 'id="vault-security-content"' in html

        # Clean up the dummy session file
        if os.path.exists("test.session"):
            os.unlink("test.session")