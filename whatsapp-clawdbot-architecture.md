# WhatsApp ClawdBot Architecture

## Overview
A mini ClawdBot for WhatsApp that summarizes messages and sends scheduled messages using Claude AI, MCP (Model Context Protocol), and RAG (Retrieval-Augmented Generation).

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         User Interface                           │
│                    (WhatsApp Application)                        │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    WhatsApp Business API                         │
│                  (or WhatsApp Web Protocol)                      │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                     MCP WhatsApp Server                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐     │
│  │ Message      │  │ Send Message │  │ Schedule Manager  │     │
│  │ Retrieval    │  │ Tool         │  │ (Cron/APScheduler)│     │
│  └──────────────┘  └──────────────┘  └───────────────────┘     │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Agent Orchestrator                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Claude AI Agent (Anthropic API)                         │   │
│  │  - Message understanding                                 │   │
│  │  - Summarization logic                                   │   │
│  │  - Scheduling logic                                      │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       RAG System                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐     │
│  │ Vector DB    │  │ Embeddings   │  │ Message History   │     │
│  │ (ChromaDB/   │  │ (Voyage AI/  │  │ Indexer           │     │
│  │  Pinecone)   │  │  OpenAI)     │  │                   │     │
│  └──────────────┘  └──────────────┘  └───────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. WhatsApp Integration Layer
**Options:**
- **whatsapp-web.js**: Free, uses WhatsApp Web protocol (recommended for personal use)
- **WhatsApp Business API**: Official, requires approval, better for production
- **Baileys**: TypeScript/JavaScript library for WhatsApp

### 2. MCP WhatsApp Server
A custom MCP server that exposes WhatsApp functionality as tools.

**Core Tools:**
```json
{
  "tools": [
    {
      "name": "get_messages",
      "description": "Retrieve messages from a chat or group",
      "parameters": {
        "chat_id": "string",
        "limit": "number",
        "start_date": "string (optional)",
        "end_date": "string (optional)"
      }
    },
    {
      "name": "send_message",
      "description": "Send a message to a contact or group",
      "parameters": {
        "phone_number": "string",
        "message": "string",
        "reply_to": "string (optional)"
      }
    },
    {
      "name": "schedule_message",
      "description": "Schedule a message to be sent at a specific time",
      "parameters": {
        "phone_number": "string",
        "message": "string",
        "schedule_time": "ISO datetime string",
        "recurring": "boolean (optional)",
        "recurrence_pattern": "string (optional, e.g., 'daily', 'weekly')"
      }
    },
    {
      "name": "get_chat_list",
      "description": "Get list of all chats",
      "parameters": {}
    },
    {
      "name": "search_messages",
      "description": "Search for messages containing specific text",
      "parameters": {
        "query": "string",
        "chat_id": "string (optional)"
      }
    }
  ]
}
```

### 3. Claude AI Agent
The brain of the system that:
- Processes user commands
- Generates summaries
- Composes messages
- Decides when to use RAG

**Agent Capabilities:**
- Natural language understanding of commands like:
  - "Summarize today's messages from John"
  - "Send 'Happy Birthday' to +1234567890 tomorrow at 9 AM"
  - "What did the team discuss about the project last week?"
- Context-aware responses using RAG
- Smart message composition

### 4. RAG System
Stores and retrieves historical messages for context-aware responses.

**Components:**
- **Vector Database**: ChromaDB or Pinecone
- **Embedding Model**: Voyage AI or OpenAI embeddings
- **Indexing Strategy**: 
  - Index messages with metadata (sender, timestamp, chat_id)
  - Chunk long conversations
  - Update index in real-time or batch

**Retrieval Flow:**
```
User Query → Embed Query → Similarity Search → 
Retrieve Relevant Messages → Pass to Claude → Generate Response
```

### 5. Scheduler
Handles message scheduling using APScheduler or similar.

**Features:**
- One-time scheduled messages
- Recurring messages (daily, weekly, monthly)
- Timezone support
- Persistent storage of scheduled tasks

## Data Flow

### Message Summarization Flow
```
1. User sends: "Summarize messages from Sarah this week"
2. Agent parses command → Identifies: contact="Sarah", timeframe="this week"
3. MCP Server → get_messages(chat_id="Sarah", start_date="2025-02-06")
4. RAG System → Retrieve relevant context if needed
5. Claude processes messages → Generates summary
6. MCP Server → send_message(reply to user with summary)
```

### Scheduled Message Flow
```
1. User sends: "Send 'Meeting at 3 PM' to Tom tomorrow at 2 PM"
2. Agent parses command → Extracts: recipient, message, time
3. Scheduler → Creates task for tomorrow 2 PM
4. At scheduled time → MCP Server → send_message(phone="Tom", message="Meeting at 3 PM")
5. Optional: Confirm delivery to user
```

### RAG-Enhanced Query Flow
```
1. User asks: "What did we decide about the budget?"
2. Query → Embed using embeddings API
3. Vector DB → Similarity search for relevant messages
4. Top K messages → Pass to Claude as context
5. Claude → Generate answer based on retrieved messages
6. Send response to user
```

## Technology Stack

### Backend
- **Language**: Python 3.10+
- **Framework**: FastAPI or Flask
- **WhatsApp Library**: whatsapp-web.js (Node.js) or Baileys
- **MCP**: Anthropic MCP SDK

### AI & ML
- **LLM**: Claude (via Anthropic API)
- **Embeddings**: Voyage AI or OpenAI
- **Vector DB**: ChromaDB (local) or Pinecone (cloud)

### Scheduling
- **APScheduler**: For task scheduling
- **Redis**: For job queue (optional)

### Storage
- **SQLite/PostgreSQL**: For message history, user preferences, scheduled tasks
- **ChromaDB**: For vector embeddings

### Infrastructure
- **Docker**: For containerization
- **Environment Variables**: For API keys and config

## Security Considerations

1. **Authentication**: 
   - Store WhatsApp session securely
   - Encrypt API keys
   - Use environment variables

2. **Data Privacy**:
   - Encrypt messages at rest
   - Implement data retention policy
   - GDPR compliance for EU users

3. **Rate Limiting**:
   - Respect WhatsApp's rate limits
   - Implement exponential backoff

4. **Access Control**:
   - Whitelist authorized phone numbers
   - Admin commands require verification

## Configuration

```yaml
# config.yaml
whatsapp:
  mode: "web"  # or "business-api"
  session_path: "./session"
  
anthropic:
  api_key: "${ANTHROPIC_API_KEY}"
  model: "claude-sonnet-4-20250514"
  max_tokens: 4000

rag:
  vector_db: "chromadb"
  embedding_model: "voyage-2"
  chunk_size: 1000
  top_k: 5

scheduler:
  timezone: "UTC"
  persistence: true
  database_url: "sqlite:///scheduler.db"

features:
  enable_summarization: true
  enable_scheduling: true
  enable_rag: true
  max_summary_messages: 100
```

## Environment Variables

```bash
ANTHROPIC_API_KEY=your_anthropic_key
VOYAGE_API_KEY=your_voyage_key  # or OPENAI_API_KEY
WHATSAPP_SESSION_PATH=./whatsapp_session
DATABASE_URL=sqlite:///clawdbot.db
REDIS_URL=redis://localhost:6379  # optional
ADMIN_PHONE_NUMBERS=+1234567890,+0987654321
```

## Implementation Phases

### Phase 1: Basic Setup (Week 1)
- Set up WhatsApp connection (whatsapp-web.js)
- Create basic MCP server with send/receive tools
- Implement simple Claude integration
- Test basic message sending/receiving

### Phase 2: Summarization (Week 2)
- Implement message retrieval with filters
- Add Claude-powered summarization
- Create summary templates for different scenarios
- Add date/time filtering

### Phase 3: Scheduling (Week 3)
- Implement APScheduler integration
- Create schedule_message tool
- Add persistent task storage
- Implement recurring message support
- Build timezone handling

### Phase 4: RAG Integration (Week 4)
- Set up ChromaDB or Pinecone
- Implement message indexing pipeline
- Add embedding generation
- Create retrieval logic
- Integrate with Claude agent

### Phase 5: Polish & Deploy (Week 5)
- Add error handling and logging
- Implement rate limiting
- Create configuration management
- Write documentation
- Deploy with Docker

## Commands Examples

```
User Commands:
1. "Summarize messages from John today"
2. "Send 'Hello' to +1234567890 at 5 PM tomorrow"
3. "What did Sarah say about the meeting?"
4. "Send 'Good morning' to +9876543210 every day at 8 AM"
5. "Show me all messages about 'project deadline'"
6. "Summarize the last 50 messages in the Team group"
```

## Monitoring & Logging

```python
# Log structure
{
  "timestamp": "2025-02-12T10:30:00Z",
  "event_type": "message_sent|message_received|summary_generated|scheduled_task",
  "user": "+1234567890",
  "status": "success|failure",
  "details": {...}
}
```

## Future Enhancements

1. **Multi-language support**: Detect and respond in user's language
2. **Voice message transcription**: Using Whisper API
3. **Media handling**: Summarize images, PDFs shared in chat
4. **Group analytics**: Participation metrics, sentiment analysis
5. **Smart replies**: Suggest responses based on context
6. **Custom templates**: User-defined message templates
7. **Backup & export**: Export chat history in various formats
