# SkySync Setup & Configuration Guide

## Getting Started with Telegram Integration

This guide will walk you through setting up SkySync with real Telegram file access.

## Step 1: Create Telegram API Application

### Required
- A Telegram account
- No phone verification needed (Telegram already has it)

### Steps

1. **Visit Telegram Apps**
   - Go to: https://my.telegram.org/apps
   - Sign in with your Telegram account phone number

2. **Create Application**
   - Click "Create a new application"
   - Fill in the form:
     - **App title**: SkySync
     - **Short name**: tdrive (no spaces or special characters)
     - **URL**: http://localhost:5000 (for local testing)
     - **Select Platform**: Desktop
     - **Description**: Personal Cloud Storage Manager

3. **Get Credentials**
   - Copy your **API ID** (a number)
   - Copy your **API Hash** (a long alphanumeric string)
   - Keep these safe and secret!

## Step 2: Configure SkySync

### Create .env File

1. **In the SkySync folder**, create a file named `.env`

2. **Add Configuration**
   ```
   # Telegram API Credentials from my.telegram.org
   TELEGRAM_API_ID=YOUR_API_ID_HERE
   TELEGRAM_API_HASH=YOUR_API_HASH_HERE
   
   # Flask settings
   FLASK_ENV=development
   FLASK_DEBUG=True
   
   # File limits
   MAX_FILE_SIZE=104857600
   UPLOAD_FOLDER=./uploads
   ```

3. **Replace placeholders**
   - Replace `YOUR_API_ID_HERE` with your actual API ID
   - Replace `YOUR_API_HASH_HERE` with your actual API Hash

### Example Configuration
```
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=abcd1234efgh5678ijkl9012mnop3456
FLASK_ENV=development
FLASK_DEBUG=True
```

## Step 3: Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- Flask - Web server framework
- Telethon - Telegram client library
- Flask-CORS - Cross-origin request handling
- Flask-Session - Session management
- And other required packages

## Step 4: Run SkySync

```bash
python main.py
```

### Expected Output
```
============================================================
  SkySync - Telegram Cloud Storage
============================================================

✅ Server starting...
🌐 Open: http://127.0.0.1:5000
📱 Login with Telegram credentials
⚠️  Demo mode: Use any 5-digit code for verification

 * Running on http://127.0.0.1:5000
Press CTRL+C to quit
```

## Step 5: First Login

1. **Open Browser**
   - Visit: http://127.0.0.1:5000

2. **Enter Phone Number**
   - Format: **+countrcode phonenumber**
   - Examples:
     - India: +91 98765 43210
     - USA: +1 234 567 8900
     - UK: +44 20 7946 0958

3. **Receive Code**
   - Check your Telegram app
   - You'll get a notification with a 5-digit code

4. **Enter Code**
   - Copy the code from Telegram
   - Paste it in the verification field
   - Click "Verify"

5. **Access Files**
   - You should now see your Telegram files
   - All files in your Saved Messages will appear here

## 📁 Understanding Telegram Storage

### What is "Saved Messages"?
- A private folder accessible only through your account
- Equivalent to a personal vault in Telegram
- No one else can access it

### What Gets Stored?
- Any files you forward to "Saved Messages" in Telegram
- Documents, images, videos, audio, or any media
- Text messages with media attachments

### How to Add Files to Telegram
In Telegram app:
1. Find any file/image/video
2. Right-click or long-press
3. Select "Save to Saved Messages"
4. Refresh SkySync to see the new file

## 🔧 Configuration Options

### Environment Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `TELEGRAM_API_ID` | int | required | Your Telegram API ID |
| `TELEGRAM_API_HASH` | string | required | Your Telegram API Hash |
| `FLASK_ENV` | string | development | Environment type |
| `FLASK_DEBUG` | bool | True | Enable debug mode |
| `MAX_FILE_SIZE` | int | 100MB | Max upload size |
| `UPLOAD_FOLDER` | path | ./uploads | Temp upload folder |

## 🚀 Usage Tips

### Uploading Files
1. Click "Upload" button or drag files into the upload area
2. Files are uploaded to your Telegram Saved Messages
3. They appear in your SkySync within seconds

### Finding Files
- Use the **Search** box to find files by name
- Use **Category Filters** to view specific file types:
  - Images
  - Videos
  - Documents
  - Audio
  - Others

### Managing Files
- **Download**: Right-click or click to download to your computer
- **Delete**: Remove files you no longer need
- **Organize**: Use Telegram's web interface or other clients

## ⚠️ Important Notes

### Security
- ✅ Your credentials are stored locally in `.env`
- ✅ Never share your `.env` file
- ✅ Never commit `.env` to git repository
- ✅ All communication is encrypted

### Demo Mode
- If credentials are missing, SkySync runs in demo mode
- Shows sample files for UI testing
- Full functionality available once you add credentials

### Browser Compatibility
- ✅ Chrome/Edge 90+
- ✅ Firefox 88+
- ✅ Safari 14+
- ✅ Mobile browsers (iOS/Android)

### File Limits
- Maximum file size: 100MB (configurable)
- Maximum files per session: 1000
- Recommended timeout: 30 minutes idle

## 🐛 Troubleshooting

### "Phone number invalid"
```
Error: Phone must start with +
```
**Solution**: Enter phone with '+' and country code
- ✅ Correct: +919876543210
- ❌ Wrong: 919876543210

### "Verification code expired"
```
Error: Verification code expired
```
**Solution**: Code is valid for 15 minutes. Get a new one.

### "Telegram credentials not configured"
```
Warning: Telegram credentials not configured. Using demo mode.
```
**Solution**: Fill in `.env` file with API ID and Hash

### "File upload timeout"
- Check internet connection
- Try smaller files first
- Increase browser timeout settings

### No files appearing
1. Check if logged in (see phone number in header)
2. Verify Saved Messages in Telegram has files
3. Refresh the browser page
4. Try clearing browser cache

## 🔄 Reconnecting/Logging In Again

### To switch accounts
1. Click **Logout** button in header
2. You'll be taken back to login page
3. Enter different phone number
4. Verify with new Telegram account

### To clear session
```bash
# Stop the server (Ctrl+C)
# Delete flask_session folder
# Restart the server
python main.py
```

## 📞 Getting Help

### Check Logs
- Server logs show in terminal
- Browser console (F12 Developer Tools)
- Check `uploads/` and `downloads/` folders

### Verify Setup
1. Open http://127.0.0.1:5000 in browser
2. Check if server is running (not getting connection refused)
3. Verify `.env` file exists in project root
4. Check if Python packages are installed (`pip list`)

### Common Issues Checklist

- [ ] `.env` file created with correct credentials
- [ ] API ID and Hash from my.telegram.org
- [ ] `pip install -r requirements.txt` completed
- [ ] Server running without errors
- [ ] Browser can reach http://127.0.0.1:5000
- [ ] Using phone number with country code (+)

## 🎓 Next Steps

1. Upload some files to Telegram Saved Messages
2. Test the upload feature in SkySync
3. Try different view modes (grid/list)
4. Explore filter options
5. Invite others to fork the project!

## 📚 Learn More

- **Telegram API Docs**: https://core.telegram.org/api
- **Telethon Docs**: https://docs.telethon.dev/
- **Flask Docs**: https://flask.palletsprojects.com/

---

**Happy cloud storage managing! ☁️**
