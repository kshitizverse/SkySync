# SkySync - Telegram Cloud Storage Web Interface

A modern web-based file manager for accessing your Telegram cloud storage. Upload, download, and manage files through a beautiful, responsive web interface instead of using Telegram directly.

## 🌟 Features

### 🎨 User Interface
- **Professional Design**: Modern dark theme with purple gradients
- **Responsive Layout**: Works perfectly on desktop, tablet, and mobile
- **Dual View Modes**: Grid and list view options
- **Colorful Folders**: Unique gradient colors for easy folder identification
- **Real-time Stats**: View storage usage, file count, and folder details

### 📁 File Management (Telegram Integrated)
- **Upload to Telegram**: Upload files directly to Saved Messages
- **Download from Telegram**: Download files from your Telegram storage
- **Delete Files**: Remove files from Telegram
- **Smart Search**: Find files by name across all categories
- **Category Filtering**: View images, videos, documents, audio, and more

### 🔐 Security & Authentication
- **Telegram OTP Login**: Secure authentication via Telegram
- **Session Management**: Encrypted session handling
- **No Bot Tokens**: Uses your personal account (not a bot)
- **Privacy-First**: Files stored in your private Saved Messages folder

### 📊 Advanced Features
- **Storage Visualization**: See storage usage with progress bars
- **File Statistics**: Track total files, folders, and storage space
- **Drag-and-Drop Upload**: Upload multiple files at once
- **Context Menu**: Right-click options for file operations
- **Keyboard Shortcuts**: Efficient file management

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Active Telegram account
- Telegram API credentials (get from [my.telegram.org](https://my.telegram.org/apps))

### Installation

1. **Clone or Download**
```bash
# Download the project files
cd SkySync
```

2. **Install Dependencies**
```bash
pip install -r requirements.txt
```

3. **Get Telegram Credentials**
   - Visit [https://my.telegram.org/apps](https://my.telegram.org/apps)
   - Log in with your Telegram account
   - Create an application and get API ID & API Hash

4. **Configure Environment**
```bash
# Copy example config
cp .env.example .env

# Edit .env with your credentials
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here
```

5. **Run Server**
```bash
python main.py
```

6. **Access**
   - Open: http://127.0.0.1:5000
   - Enter phone number (with country code)
   - Verify with code from Telegram

## 📖 Usage Guide

### Login
1. Enter your phone number with country code (e.g., +919876543210)
2. Telegram will send you a code
3. Enter the 5-digit code to verify

### Upload Files
- **Drag & Drop**: Drag files into the upload area
- **Click to Browse**: Click upload button and select files
- Files are uploaded to your Telegram Saved Messages

### Download Files
- Right-click any file and select "Download"
- Or click the file and use the download option

### Manage Files
- **Delete**: Remove files you no longer need
- **Rename**: Change file names
- **Search**: Find files by typing in the search box
- **Filter**: Click category filters on the left

### View Modes
- **Grid View**: Thumbnail-based view (default)
- **List View**: Detailed list with file sizes

## 🔧 Configuration

### Environment Variables (.env)
```
# Telegram API Credentials (get from my.telegram.org)
TELEGRAM_API_ID=your_api_id_here
TELEGRAM_API_HASH=your_api_hash_here

# Flask Configuration
FLASK_ENV=development
FLASK_DEBUG=True

# File Limits
MAX_FILE_SIZE=104857600  # 100MB in bytes
```

### Demo Mode
If you don't have Telegram credentials, the app runs in demo mode with sample files for testing the UI.

## 📁 Project Structure
```
SkySync/
├── main.py                 # Flask server & API endpoints
├── requirements.txt        # Python dependencies
├── .env.example           # Configuration template
├── src/
│   └── telegram_handler.py # Telegram client logic
├── templates/
│   ├── login.html         # Login page
│   └── dashboard.html     # File manager interface
├── static/
│   ├── dashboard.js       # File manager functionality
│   └── dashboard.css      # Professional styling
└── flask_session/         # Session storage
```

## 🔌 API Endpoints

### Authentication
- `POST /api/auth/send-code` - Request verification code
- `POST /api/auth/verify-code` - Verify OTP

### File Management
- `GET /api/files` - List all files
- `POST /api/files/upload` - Upload file
- `GET /api/files/<id>/download` - Download file
- `DELETE /api/files/<id>/delete` - Delete file

### User
- `GET /api/user/profile` - Get user profile

## 🛡️ Security Notes

1. **Local Storage**: API credentials stored locally in .env file
2. **Session Encryption**: Flask session data encrypted
3. **CORS Protected**: API endpoints protected with CORS headers
4. **No Cloud Sync**: Data remains in your Telegram account

## 🐛 Troubleshooting

### "Telegram credentials not configured"
- Create .env file from .env.example
- Add your API ID and API Hash
- Restart the server

### "Connection timeout"
- Check internet connection
- Verify Telegram API credentials are correct
- Try again after a few moments

### Files not appearing
- In demo mode, sample files are shown
- With real credentials, check your Telegram Saved Messages
- Verify the phone number used for login

## 📝 Notes

- **Saved Messages**: Your personal Telegram folder accessible only to you
- **Encryption**: Files are encrypted in transit and at rest by Telegram
- **No Ads**: Client-side rendered, no tracking
- **Offline Mode**: Works offline with cached files

## 🤝 Contributing

Feel free to fork and contribute improvements!

## 📄 License

MIT License - Feel free to use, modify, and distribute.

## ⚠️ Disclaimer

This is an unofficial Telegram client. Use at your own risk. Respect Telegram's Terms of Service.
```

**Note:** Your API_ID must be a valid 7-digit Telegram API ID. Get one from https://my.telegram.org/apps

### Step 3: Run the Server
```bash
python main.py
```

## Usage

### Demo Mode (No Credentials Needed)
1. Open http://127.0.0.1:5000
2. Phone Number: `+918249747196` (or any number starting with +)
3. Verification Code: Any 5-digit number (e.g., `12345`)
4. See the file manager with sample data

### Real Telegram Mode (Requires Credentials)
1. Get Telegram API credentials from https://my.telegram.org/apps
2. Add credentials to `.env` file
3. Login with your actual phone number
4. Verify with OTP from Telegram
5. Access your actual cloud files

## API Endpoints

### Authentication
- `POST /api/auth/send-code`
  - Body: `{"phone": "+1234567890"}`
  - Response: `{"success": true, "verification_id": "..."}`

- `POST /api/auth/verify-code`
  - Body: `{"code": "12345"}`
  - Response: `{"success": true, "user_id": "...", "message": "Verified successfully"}`

### Files
- `GET /api/files` - List all files
  - Response: `{"success": true, "files": [...]}`

- `POST /api/files/upload` - Upload file
  - Body: FormData with file
  - Response: `{"success": true, "filename": "...", "size": 12345}`

- `GET /api/files/<id>/download` - Download file
  - Response: File download

- `DELETE /api/files/<id>/delete` - Delete file
  - Response: `{"success": true, "message": "File deleted"}`

- `GET /api/user/profile` - Get user profile
  - Response: `{"success": true, "user": {...}}`

## Project Structure

```
SkySync/
├── main.py                  # Flask server & API endpoints
├── templates/
│   ├── login.html          # Login form (200+ lines)
│   └── dashboard.html      # File manager UI (150+ lines)
├── static/
│   ├── dashboard.css       # Styling (1000+ lines, dark theme)
│   └── dashboard.js        # Frontend logic (400+ lines)
├── src/                    # (Optional Telegram integration)
│   ├── sync_manager.py
│   ├── telegram_client.py
│   └── virtual_drive.py
├── .env                    # Configuration (git ignored)
├── .env.example            # Example configuration
├── requirements.txt        # Python dependencies
├── QUICKSTART.md          # Quick start guide
└── README.md              # This file
```

## Technology Stack

### Backend
- **Flask 3.0.0**: Web framework
- **Flask-CORS 4.0.0**: Cross-origin support
- **Flask-Session 0.5.0**: Server-side sessions
- **Telethon 1.42.0**: Telegram API client
- **Pydantic 2.5.2**: Data validation

### Frontend
- **HTML5**: Semantic markup
- **CSS3**: Dark theme styling with gradients
- **JavaScript (ES6+)**: File operations, search, filtering
- **Responsive Design**: Mobile-first approach

## CSS Theme Colors

The interface uses a professional dark theme with these primary colors:

- **Primary**: `#667eea` (Purple-blue)
- **Secondary**: `#764ba2` (Dark purple)
- **Accent Red**: `#ff6b6b`
- **Accent Green**: `#43e97b`
- **Accent Cyan**: `#4facfe`
- **Accent Orange**: `#fa709a`

## JavaScript Functions

### File Operations
- `loadFiles()` - Fetch files from API
- `renderFiles()` - Display files on page
- `filterByCategory()` - Filter by file type
- `handleFileUpload()` - Upload via API
- `downloadFile()` - Download file
- `deleteFile()` - Delete file
- `renameFile()` - Rename file
- `shareFile()` - Generate share link

### UI Handlers
- `showContextMenu()` - Right-click options
- `selectFile()` - Select file for operations
- `updateStats()` - Recalculate statistics
- `handleDrop()` - Drag-and-drop upload
- `handleLogout()` - Logout user

## Environment Variables

```
TELEGRAM_API_ID=7123456          # Your Telegram API ID (7 digits)
TELEGRAM_API_HASH=abc123...      # Your Telegram API hash
TELEGRAM_PHONE=+1234567890       # Your Telegram phone number
DRIVE_LETTER=Z                   # (Optional) Virtual drive letter
SYNC_INTERVAL=5                  # Sync frequency in seconds
LOG_LEVEL=INFO                   # Logging level
```

## Troubleshooting

### Port Already in Use
If port 5000 is in use, edit `main.py`:
```python
app.run(host='127.0.0.1', port=5001)  # Change to 5001
```

### Module Not Found (ImportError)
```bash
pip install -r requirements.txt --upgrade
```

### Session Issues
```bash
# Clear session files and restart
rm -rf flask_session/
python main.py
```

### Invalid API_ID
Telegram API IDs must be 7 digits. If you get a `struct.error`, your API_ID is invalid:
1. Go to https://my.telegram.org/apps
2. Create or edit your app
3. Copy the correct API_ID (should be ≤ 7 digits)
4. Update `.env` file

### Telethon Connection Error
```bash
# Make sure you have valid credentials
# Try demo mode first to test UI without Telegram
```

## Demo Files

For testing without Telegram credentials, the server includes 10 sample files:
- 3 Folders: Documents, Photos, Videos
- 3 Images: vacation.jpg, screenshot.png, photo.jpg
- 2 Videos: movie.mp4, tutorial.mp4
- 2 Documents: report.pdf, report.docx
- 1 Archive: archive.zip

## Security Notes

1. **Don't commit `.env`** - It contains sensitive data
2. **Use HTTPS in production** - Don't expose login over HTTP
3. **Validate API responses** - Check success flag
4. **Rate limit** - Implement rate limiting for production
5. **Secure sessions** - Use strong SECRET_KEY
6. **CORS origin** - Restrict to your domain in production

## Performance Tips

1. **Caching**: Add Redis for session storage (large deployments)
2. **Pagination**: Implement file list pagination (1000+ files)
3. **Compression**: Enable gzip compression in production
4. **CDN**: Serve static files through CDN
5. **Database**: Use PostgreSQL for persistent storage

## Future Enhancements

- [ ] Real Telegram API integration
- [ ] File sharing with links
- [ ] User authentication database
- [ ] File versioning/history
- [ ] Collaborative folders
- [ ] Advanced search filters
- [ ] File preview (images, videos, documents)
- [ ] Sync across devices
- [ ] Desktop client
- [ ] Mobile app

## Contributing

To contribute:
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is provided as-is for educational use.

## Support

For issues or questions:
1. Check QUICKSTART.md
2. Review the API endpoints
3. Check console logs in browser (F12)
4. Check server logs in terminal

---

**Version:** 1.0.0  
**Status:** Beta  
**Last Updated:** 2026-03-15

Built with ❤️ for better Telegram file management
