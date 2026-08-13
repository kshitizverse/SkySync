"""
Custom WsgiDAV domain controller for SkySync.

Validates WebDAV Basic Auth credentials against per-user tokens stored
in the database.  Tokens are SHA-256 hashed before storage.
"""
import logging

from wsgidav.dc.base_dc import BaseDomainController

logger = logging.getLogger(__name__)


class SkySyncDomainController(BaseDomainController):
    """Authenticate WebDAV requests using SkySync WebDAV tokens.

    WebDAV clients authenticate with:
        Username = <sky-sync-user-id>   (integer)
        Password = <webdav-token>       (plaintext token, never stored)
    """

    def __init__(self, wsgidav_app, config):
        super().__init__(wsgidav_app, config)

    def __str__(self):
        return "SkySyncDomainController"

    def get_domain_realm(self, path_info, environ):
        return "SkySync"

    def require_authentication(self, realm, environ):
        return True

    def basic_auth_user(self, realm, user_name, password, environ):
        """Validate Basic Auth credentials against SkySync WebDAV tokens.

        user_name  = SkySync user id (string integer)
        password   = plaintext WebDAV token
        Returns    = True if valid, False otherwise
        """
        if not user_name or not password:
            return False

        # Prevent abuse: user_name must be a numeric user ID
        try:
            user_id = int(user_name)
        except (ValueError, TypeError):
            logger.warning("WebDAV auth: invalid user_name format: %r", user_name)
            return False

        from storage_db import verify_webdav_token
        user = verify_webdav_token(password)
        if user is None:
            logger.warning("WebDAV auth: invalid token for user %s", user_name)
            return False

        if user["id"] != user_id:
            logger.warning("WebDAV auth: token user mismatch (token user=%s, requested=%s)", user["id"], user_name)
            return False

        if user.get("account_status") != "active":
            logger.warning("WebDAV auth: inactive account %s", user_id)
            return False

        # Set the authenticated user in environ for the provider
        environ["wsgidav.auth.user"] = user
        environ["wsgidav.auth.roles"] = []
        return True

    def supports_http_digest_auth(self):
        return False

    def digest_auth_user(self, realm, user_name, environ):
        return False
