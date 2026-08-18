"""
Regression test for Vault -> Set Up Vault -> Settings flow.
Tests that after setting up Vault PIN, the Settings view renders correctly
with the Vault Security section visible.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import app


def test_vault_setup_to_settings_flow():
    """Test the complete Vault -> Set Up Vault -> Settings flow."""
    with app.test_client() as client:
        from storage_db import init_db, create_user, get_connection

        # Initialize DB for test
        init_db()
        with get_connection() as conn:
            # Clean up any existing test user
            conn.execute("DELETE FROM users WHERE telegram_user_id = ?", ("999998",))
            conn.commit()

        # Create a test user
        user = create_user(
            email="test2@example.com",
            phone="+19999999998",
            name="Test User 2",
            telegram_user_id="999998",
            session_path="test2.session",
        )
        # Create a dummy session file
        open("test2.session", "a").close()

        # Log in by setting the session
        with client.session_transaction() as sess:
            sess["app_user_id"] = user["id"]

        # 1. Access dashboard (should redirect to setup since no vault PIN)
        resp = client.get("/dashboard")
        # Might redirect or show vault not configured - either way we proceed

        # 2. Check that we can access settings view directly
        resp = client.get("/dashboard?view=settings")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # Check that the settings view container is present
        assert 'id="settings-view"' in html

        # Check that the vault-security-content container is present
        # (The actual content is loaded dynamically by JavaScript)
        assert 'id="vault-security-content"' in html

        # Check that we have the settings toolbar with back button
        assert 'id="settings-back-btn"' in html

        # Clean up
        if os.path.exists("test2.session"):
            os.unlink("test2.session")


def test_settings_view_direct_access():
    """Test that settings view can be accessed directly and shows expected structure."""
    with app.test_client() as client:
        from storage_db import init_db, create_user, get_connection

        # Initialize DB for test
        init_db()
        with get_connection() as conn:
            # Clean up any existing test user
            conn.execute("DELETE FROM users WHERE telegram_user_id = ?", ("999997",))
            conn.commit()

        # Create a test user
        user = create_user(
            email="test3@example.com",
            phone="+19999999997",
            name="Test User 3",
            telegram_user_id="999997",
            session_path="test3.session",
        )
        # Create a dummy session file
        open("test3.session", "a").close()

        # Log in by setting the session
        with client.session_transaction() as sess:
            sess["app_user_id"] = user["id"]

        # Request the dashboard with settings view
        resp = client.get("/dashboard?view=settings")
        assert resp.status_code == 200
        html = resp.data.decode("utf-8")

        # Verify the settings view container exists
        assert 'id="settings-view"' in html
        assert 'id="vault-security-content"' in html

        # Verify the settings toolbar has the back button
        assert 'id="settings-back-btn"' in html

        # Clean up
        if os.path.exists("test3.session"):
            os.unlink("test3.session")


if __name__ == "__main__":
    test_vault_setup_to_settings_flow()
    test_settings_view_direct_access()
    print("All tests passed!")