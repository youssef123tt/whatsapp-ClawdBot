# WhatsApp ClawdBot 🤖

An intelligent WhatsApp assistant powered by Claude AI that can summarize messages, send scheduled messages, and answer questions about your chat history.

## Features

- 📝 **Message Summarization**: Automatically summarize conversations from specific contacts or groups
- ⏰ **Message Scheduling**: Schedule one-time or recurring messages
- 🔍 **Smart Search**: Search and retrieve information from chat history using RAG
- 🤖 **Natural Language Interface**: Interact with your WhatsApp messages using natural language
- 💬 **Context-Aware Responses**: Uses RAG to provide contextually relevant answers

## Architecture

```
WhatsApp ← → MCP Server ← → Claude Agent
                ↓              ↓
           Scheduler      RAG System
```

### Components

1. **MCP WhatsApp Server**: Exposes WhatsApp functionality as MCP tools
2. **Claude Agent**: Processes requests and generates responses using Claude
3. **RAG System**: Stores and retrieves message context using ChromaDB
4. **Scheduler**: Manages scheduled and recurring messages

## Prerequisites

- Python 3.10 or higher
- Node.js 18 or higher
- Anthropic API key
- (Optional) Voyage AI API key for better embeddings

## Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd whatsapp-clawdbot
```

### 2. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 3. Install Node.js Dependencies

```bash
npm install
```

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and add your API keys:

```env
ANTHROPIC_API_KEY=your_key_here
ADMIN_PHONE_NUMBERS=+1234567890  # Your phone number
```

### 5. First Run - QR Code Authentication

```bash
python main.py
```

On first run, you'll see a QR code in the terminal. Scan it with WhatsApp to authenticate.

## Usage

### Basic Commands

Once running, you can message yourself (or the bot number) with commands:

**Summarization:**
```
"Summarize messages from John today"
"What did the team discuss in the group chat this week?"
"Summarize the last 50 messages in Sales group"
```

**Send Messages:**
```
"Send 'Hello there!' to +1234567890"
"Message Sarah with 'Thanks for your help!'"
```

**Schedule Messages:**
```
"Send 'Good morning' to +9876543210 tomorrow at 8 AM"
"Remind me to call John every day at 5 PM"
"Send 'Happy Birthday!' to +1234567890 on March 15 at 9 AM"
```

**Search & Questions:**
```
"Search for messages about 'project deadline'"
"What did Sarah say about the meeting?"
"Find messages from last week about budget"
```

**Bot Commands:**
- `/help` - Show help message
- `/stats` - Show bot statistics
- `/clear` - Clear conversation history
- `/schedule` - List scheduled messages

### Examples

```
You: Summarize today's messages from the Team group

Bot: Here's a summary of today's messages from Team group:

📊 Project Status (8 messages)
- Sarah reported completing the frontend redesign
- John mentioned backend API is 90% done
- Team agreed to push deployment to Friday

⚠️ Issues (3 messages)
- Database migration needs review
- QA found 2 critical bugs

📅 Next Steps
- Code review scheduled for tomorrow at 2 PM
- Deploy to staging on Thursday
```

```
You: Send "Don't forget about our meeting tomorrow!" to +1234567890 today at 6 PM

Bot: ✅ Message scheduled!
Recipient: +1234567890
Message: "Don't forget about our meeting tomorrow!"
Scheduled for: Today at 6:00 PM
```

## Advanced Configuration

### Using Voyage AI Embeddings

For better search results, configure Voyage AI:

```env
VOYAGE_API_KEY=your_voyage_key
RAG_EMBEDDING_MODEL=voyage-2
```

### Message Indexing

To index existing messages for RAG:

```python
# In main.py
bot = WhatsAppClawdBot(enable_rag=True)
await bot.run_message_indexing()
```

This will index up to 100 messages from each of your recent 50 chats.

### Recurring Message Patterns

Supported patterns for scheduled messages:

- `daily` - Every day at the same time
- `weekly` - Every week on the same day
- `monthly` - Every month on the same date
- `every_N_hours` - Every N hours
- `every_N_minutes` - Every N minutes

## Docker Deployment

### Build and Run

```bash
docker-compose up -d
```

### View Logs

```bash
docker-compose logs -f
```

### Stop

```bash
docker-compose down
```

## Architecture Details

### MCP Server Tools

The MCP server exposes these tools to Claude:

1. `get_messages` - Retrieve messages from a chat
2. `send_message` - Send a message
3. `schedule_message` - Schedule a message
4. `get_chat_list` - List all chats
5. `search_messages` - Search messages
6. `get_contact_info` - Get contact information

### RAG System

- **Vector Database**: ChromaDB
- **Embeddings**: Voyage AI or ChromaDB default
- **Index Strategy**: Real-time indexing of incoming messages
- **Retrieval**: Top-K similarity search with metadata filtering

### Scheduler

- **Backend**: APScheduler with SQLAlchemy
- **Persistence**: SQLite database
- **Features**: One-time and recurring messages, timezone support

## Security Considerations

1. **API Keys**: Never commit `.env` file
2. **Admin Numbers**: Whitelist authorized phone numbers
3. **Rate Limiting**: WhatsApp has rate limits - be mindful
4. **Data Privacy**: Messages are stored locally

## Troubleshooting

### QR Code Not Showing

```bash
# Make sure you're running in a terminal that supports QR codes
# Try reducing terminal font size if QR is cut off
```

### WhatsApp Disconnects

```bash
# Delete session folder and re-authenticate
rm -rf session/
python main.py
```

### ChromaDB Errors

```bash
# Clear and rebuild vector database
rm -rf chroma_db/
# Re-run message indexing
```

### Scheduled Messages Not Sending

```bash
# Check scheduler database
sqlite3 scheduler.db
SELECT * FROM apscheduler_jobs;
```

## Development

### Project Structure

```
whatsapp-clawdbot/
├── mcp_server/
│   ├── whatsapp_server.py    # MCP server implementation
│   ├── whatsapp_client.py    # WhatsApp client wrapper
│   └── whatsapp_bridge.js    # Node.js bridge for whatsapp-web.js
├── agent/
│   └── claude_agent.py       # Claude AI agent
├── rag/
│   └── message_rag.py        # RAG system
├── scheduler/
│   └── task_scheduler.py    # Task scheduler
├── main.py                   # Main application
├── requirements.txt          # Python dependencies
├── package.json             # Node.js dependencies
└── Dockerfile               # Docker configuration
```

### Adding Custom Tools

Add new tools to `mcp_server/whatsapp_server.py`:

```python
Tool(
    name="your_tool_name",
    description="What your tool does",
    inputSchema={...}
)
```

## Limitations

- WhatsApp Web session may need periodic re-authentication
- Rate limits apply to message sending
- Large groups may have message retrieval limits
- Voice messages and media are not transcribed (yet)

## Future Enhancements

- [ ] Voice message transcription (Whisper API)
- [ ] Image analysis (Claude Vision)
- [ ] Group analytics
- [ ] Multi-language support
- [ ] Custom message templates
- [ ] WhatsApp Business API support

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

MIT

## Disclaimer

This project is not affiliated with WhatsApp or Meta. Use responsibly and in accordance with WhatsApp's Terms of Service.
