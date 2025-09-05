# AI Agent Bootstrapper - Setup Guide

## ⚠️ IMPORTANT: Gemini API Key Required

The AI Agent Bootstrapper uses Google's Gemini API to power the AI conversations. **Without an API key, the AI will get stuck and won't be able to generate projects.**

## Quick Setup

### 1. Get a Gemini API Key (Required!)

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Sign in with your Google account
3. Click "Create API Key"
4. Copy the generated API key

### 2. Configure the API Key

```bash
# Navigate to the backend directory
cd backend

# Edit the .env file
# Add your API key to the GEMINI_API_KEY line:
GEMINI_API_KEY=your_actual_api_key_here
```

### 3. Restart the Application

After adding the API key, restart the backend server:

```bash
# Kill any existing servers
pkill -f uvicorn

# Start the backend
cd backend
source venv/bin/activate
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

## Troubleshooting

### AI Gets Stuck at "AI is thinking..."
- **Cause**: Missing Gemini API key
- **Solution**: Add your API key to `backend/.env` as shown above

### "Configuration Error" Message
- **Cause**: Invalid or missing API key
- **Solution**: Verify your API key is correct and properly set in the `.env` file

### Server Won't Start
- Check if port 8000 is already in use: `lsof -i :8000`
- Kill the process if needed: `kill -9 <PID>`

## What Happens After Setup

Once the API key is configured:

1. The AI will process your project requirements
2. It will automatically detect your system capabilities
3. Generate an execution plan for your project
4. **Automatically execute the plan** to create your project files
5. Your project will be ready to use!

## Current Status

✅ Fixed Issues:
- Project type validation (web application → fullstack)
- DateTime serialization
- Missing schema fields
- Automatic execution after planning

⚠️ Pending:
- Gemini API key configuration (user action required)

## Need Help?

If you continue to experience issues after adding the API key, check:
- The backend console for error messages
- That your API key has the correct permissions
- Your internet connection (API calls require network access)