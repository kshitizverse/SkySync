# SkySync - Telegram Cloud Storage Web Interface

## Quick Start Guide

### 1. Get Telegram API Credentials

To connect your Telegram account and access your files:

1. Go to [https://my.telegram.org/apps](https://my.telegram.org/apps)
2. Log in with your Telegram account
3. Fill in the application details:
   - App title: `SkySync`
   - Short name: `tdrive`
   - URL: `http://localhost:5000`
   - Platform: `Desktop`
4. Click "Create my application"
5. Copy your **API ID** and **API Hash**

### 2. Configure Environment Variables

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` and add your credentials:
```
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here
FLASK_ENV=development
ALLOW_DEMO_MODE=False
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Run the Server
```bash
python main.py
```

You should see:
```
============================================================
  SkySync - Telegram Cloud Storage
============================================================

✅ Server starting...
🌐 Open: http://127.0.0.1:5000
📱 Login with Telegram credentials
🔐 OTP is requested from Telegram for your phone number

```

### 5. Access the Web Interface
Open your browser and go to: **http://127.0.0.1:5000**

### 6. Login
- Enter your phone number (with country code, e.g., +919876543210)
- You'll receive a code in your Telegram app
- Enter the verifi code to access your files

## Features

✅ **Real Telegram Integration** - Access files from your Telegram Saved Messages
✅ **Upload Files** - Upload to your Telegram Saved Messages folder
✅ **Download Files** - Download files to your device
✅ **File Management** - Delete files from Telegram
✅ **Professional UI** - Beautiful dark mode interface
✅ **Category Filtering** - Filter by images, videos, documents, audio

## Demo Mode

Demo mode is optional. Set `ALLOW_DEMO_MODE=True` only if you intentionally want a local fallback for UI testing.

## Important Notes

- **Saved Messages**: Files are stored in your private "Saved Messages" folder on Telegram
- **Security**: Your API credentials are stored locally, never shared
- **No API Key**: This uses your personal Telegram account (not a bot token)
- **Private**: Only you can access your files through this interface

### 4. Login

**Real Telegram Login:**
- Use your actual Telegram phone number
- Verify using OTP from Telegram app
- Access your cloud storage through the web

### 5. Features

#### File Manager
- 📁 View folders and files
- 🔍 Search files by name
- 📊 Storage statistics
- 🏷️ Filter by category (Images, Videos, Documents, Audio)

#### File Operations
- ⬆️ Upload files (drag & drop supported)
- ⬇️ Download files
- 🗑️ Delete files
- ✏️ Rename files
- 🔗 Share links (feature coming soon)

#### User Experience
- 🎨 Dark theme with colorful folder gradients
- 📱 Responsive design (mobile, tablet, desktop)
- 🎯 Grid and list view modes
- 💾 Real-time storage bar

### 6. Project Structure

```
SkySync/
├── main.py                 # Flask server with API endpoints
├── templates/
│   ├── login.html         # Login form with Telegram auth
│   └── dashboard.html     # File manager interface
├── static/
│   ├── dashboard.css      # Styling (dark theme, colors)
│   └── dashboard.js       # Frontend logic
├── .env                   # (Your API credentials)
├── requirements.txt       # Python dependencies
└── README.md             # Full documentation
```

### 7. API Endpoints (for developers)

#### Authentication
- `POST /api/auth/send-code` - Send verification code
- `POST /api/auth/verify-code` - Verify OTP

#### Files
- `GET /api/files` - List files
- `POST /api/files/upload` - Upload file
- `GET /api/files/<id>/download` - Download file
- `DELETE /api/files/<id>/delete` - Delete file

### 8. Demo Data

The server comes with sample files for testing:
- 2 Folders (Documents, Photos)
- 3 Different file types (PDF, Images, Videos)

### 9. Troubleshooting

**Port Already in Use:**
```bash
# Change port in main.py (line ~130):
app.run(host='127.0.0.1', port=5001)  # Change 5000 to 5001
```

**Module Not Found:**
```bash
# Make sure all dependencies are installed:
pip install -r requirements.txt --upgrade
```

**Session Errors:**
```bash
# Clear session files and restart:
rm -rf flask_session/
python main.py
```

### 10. Next Steps

1. Add your Telegram API credentials to `.env`
2. Connect real Telegram account
3. Access actual cloud files
4. Set up file sync across devices

---

**Status:** Backend ✅ | UI/UX ✅ | Telegram Integration 🔄

For more details, see [README.md](README.md)
