# Quick Start Guide

## 5-Minute Setup

### Step 1: Install Dependencies

```bash
# Python dependencies
pip install -r requirements.txt

# Node.js dependencies
npm install
```

### Step 2: Configure

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your Anthropic API key
nano .env
```

Minimum required configuration in `.env`:
```env
ANTHROPIC_API_KEY=sk-ant-xxxxx
ADMIN_PHONE_NUMBERS=+1234567890
```

### Step 3: Run

```bash
python main.py
```

### Step 4: Authenticate

1. A QR code will appear in your terminal
2. Open WhatsApp on your phone
3. Go to Settings → Linked Devices → Link a Device
4. Scan the QR code

### Step 5: Test

Send yourself a message:
```
/help
```

You should receive a help message from the bot!

## Next Steps

### Try Summarization

Send a message to yourself:
```
Summarize my recent messages
```

### Schedule a Message

```
Send "Hello World" to +1234567890 in 5 minutes
```

### Index Existing Messages (Optional)

For better context-aware responses, index your existing messages:

```python
# Edit main.py and uncomment:
# await bot.run_message_indexing()
```

Then run:
```bash
python main.py
```

This will index your recent messages for RAG-powered search.

## Common Issues

### "QR Code Not Displaying"
- Make sure your terminal supports Unicode
- Try making your terminal window larger
- Check terminal font size

### "Module Not Found"
```bash
pip install -r requirements.txt
npm install
```

### "API Key Error"
- Verify your `.env` file has correct API key
- Check key starts with `sk-ant-`

### "Permission Denied"
```bash
chmod +x main.py
```

## Docker Quick Start

```bash
# Build and run with Docker
docker-compose up -d

# View logs
docker-compose logs -f

# First time: Scan QR code from logs
# Look for QR code in the output

# Stop
docker-compose down
```

## What to Try

1. **Message Summarization**
   - "Summarize messages from [contact name] today"
   - "What did we discuss in [group name] this week?"

2. **Smart Search**
   - "Search for messages about [topic]"
   - "What did [person] say about [subject]?"

3. **Scheduled Messages**
   - "Send 'Good morning' to [number] tomorrow at 8 AM"
   - "Remind [person] about meeting every day at 5 PM"

4. **General Queries**
   - "Who messaged me most today?"
   - "What are my unread messages?"

Enjoy your WhatsApp ClawdBot! 🤖
