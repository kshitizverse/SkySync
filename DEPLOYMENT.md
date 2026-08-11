# SkySync Deployment Guide

## 1. Local Production Test

```bash
cp .env.example .env
# Edit .env with real Telegram credentials

pip install -r requirements.txt
APP_ENV=production CORS_ORIGINS=http://localhost:8000 python main.py
# Visit http://localhost:8000/health
```

## 2. Environment Setup

Required variables (set in `.env`):

```bash
TELEGRAM_API_ID=<real_value>           # From my.telegram.org/apps
TELEGRAM_API_HASH=<real_value>         # From my.telegram.org/apps
TELEGRAM_STORAGE_PHONE=<phone>         # Phone for file storage
APP_ENV=production
CORS_ORIGINS=https://yourdomain.com
SECRET_KEY=<generate_with_python>
```

Generate SECRET_KEY:
```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 3. Redis Setup

Redis is required for multi-instance deployments. For single-instance, in-memory rate limiting is used with a startup warning.

### Docker Compose (included)
Redis starts automatically with `docker compose up`.

### Manual Redis
```bash
# Ubuntu/Debian
sudo apt install redis-server
sudo systemctl enable redis-server

# Set in .env
REDIS_URL=redis://localhost:6379/0
```

## 4. Database Persistence

SkySync uses SQLite (`tdrive.db`).

**Docker:** The `tdrive-data` volume mounts `/data` which contains the database.

**Manual:** Ensure `tdrive.db` is on persistent storage. The database path is controlled by `TDRIVE_DB_PATH` env var (defaults to project root).

**Limitations:** SQLite does not support concurrent writes from multiple processes. For multi-user production, consider migrating to PostgreSQL.

## 5. Telegram Session Persistence

Telethon stores session files as `user_<id>_<random>.session` in the `telegram_sessions/` directory.

**Docker:** Session files are stored in `/app/telegram_sessions` (persistent volume).

**Manual:** Ensure the `telegram_sessions/` directory is on persistent storage. Session files are:
- `user_<id>_<random>.session` - Authentication state
- `user_<id>_<random>.session-journal` - Transaction journal

**Never delete these files** unless you want to force re-authentication.

## 6. GitHub Repository Setup

```bash
git init
git status                    # Verify .env, *.session, *.db, *.log are NOT listed
git add .
git status                    # Confirm only source code is staged
git commit -m "Initial secure SkySync version"
git remote add origin <your-repo-url>
git push -u origin main
```

## 7. Recommended Architecture

```
Internet → Nginx (HTTPS) → Gunicorn (0.0.0.0:8000) → SQLite (/data/tdrive.db)
                                                       → Redis (rate limiting)
                                                       → Telegram API (file storage)
                                                       → Telegram Bot API (OTP delivery)
```

## 8. Deployment Commands

### Docker Compose (recommended)
```bash
docker compose up -d
docker compose logs -f app
```

### Manual with Gunicorn
```bash
pip install -r requirements.txt
APP_ENV=production gunicorn --config gunicorn.conf.py main:app
```

### Heroku
```bash
heroku create your-app-name
heroku config:set APP_ENV=production TELEGRAM_API_ID=xxx TELEGRAM_API_HASH=xxx
git push heroku main
```

## 9. Health Check

```bash
curl http://localhost:8000/health
# Returns: {"status": "healthy", "service": "SkySync", "version": "2.0.0"}
```

## 10. Custom Domain Setup

1. Point your domain to the server IP
2. Configure Nginx with TLS (Let's Encrypt)
3. Update `CORS_ORIGINS=https://yourdomain.com` in `.env`
4. Update `SESSION_COOKIE_SECURE=True` (set automatically in production)
5. Restart the application

## 11. CORS Configuration

Production requires explicit origins. Never use `*`.

```bash
# Single domain
CORS_ORIGINS=https://yourdomain.com

# Multiple domains
CORS_ORIGINS=https://app.example.com,https://admin.example.com
```

## 12. Post-Deployment Verification

```bash
# Health check
curl https://yourdomain.com/health

# Login page
curl -I https://yourdomain.com/login

# API test
curl https://yourdomain.com/api/files
# Should return 401 Unauthorized
```

## 13. Backup Strategy

### Database
```bash
# Backup
cp tdrive.db tdrive.db.backup.$(date +%Y%m%d)

# Or with SQLite
sqlite3 tdrive.db ".backup 'tdrive.db.backup'"
```

### Session Files
```bash
tar -czf sessions-backup-$(date +%Y%m%d).tar.gz telegram_sessions/*.session*
```

### Full Backup
```bash
tar -czf skysync-backup-$(date +%Y%m%d).tar.gz \
    tdrive.db \
    telegram_sessions/*.session* \
    uploads/ \
    .env
```

## 14. Rollback Strategy

1. Stop the current deployment
2. Restore database from backup
3. Restore session files from backup
4. Deploy the previous version
5. Restart

```bash
# Docker
docker compose down
# Restore volumes
docker compose up -d
```

## Environment Variables Reference

| Variable | Required | Description |
|----------|----------|-------------|
| TELEGRAM_API_ID | Yes | Telegram API ID |
| TELEGRAM_API_HASH | Yes | Telegram API hash |
| TELEGRAM_STORAGE_PHONE | Yes | Phone for file storage |
| APP_ENV | Yes | Set to "production" |
| CORS_ORIGINS | Yes | Your domain(s) |
| SECRET_KEY | Yes | Flask secret (auto-generated if not set) |
| REDIS_URL | Recommended | Redis URL for rate limiting |
| TELEGRAM_BOT_TOKEN | Recommended | Bot token for OTP delivery |
| TELEGRAM_BOT_CHAT_ID | Recommended | Bot chat ID for OTP |
| ADMIN_PHONE | Optional | Admin phone number |
| TELEGRAM_TARGET_CHAT | Optional | Storage chat (default: "me") |
| MAX_FILE_SIZE | Optional | Max upload bytes (default: 100MB) |
| FLASK_HOST | Optional | Bind host (default: 0.0.0.0) |
| FLASK_PORT | Optional | Bind port (default: 8000) |
| GUNICORN_WORKERS | Optional | Worker count (default: CPU*2+1) |
