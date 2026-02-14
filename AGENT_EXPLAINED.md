# How the WhatsApp Agent Works — From First Principles

## Architecture Overview

The bot is a **4-layer architecture** where each layer has one job:

```
WhatsApp (real world)
    ↕  JSON over stdin/stdout
Node.js Bridge (whatsapp_bridge.js)
    ↕  async events/commands
WhatsApp Client (whatsapp_client.py)
    ↕  method calls
Main Orchestrator (main.py)
    ↕  process_message() + tool callbacks
Gemini Agent (gemini_agent.py)  ←→  RAG (message_rag.py)
```

---

## Layer 1: The Node.js Bridge (`whatsapp_bridge.js`)

A **child process** spawned by Python. It runs `whatsapp-web.js` (a library that controls a real WhatsApp Web session) and communicates with Python via **JSON lines over stdin/stdout**.

- **Incoming messages** → the bridge emits a JSON event on stdout:
  ```json
  {"event": "message_received", "data": {"id": "msg123", "from": "201281835346@c.us", "body": "Hello!", "timestamp": 1707955200, "fromMe": false}}
  ```
- **Outgoing commands** → Python writes JSON to the bridge's stdin:
  ```json
  {"request_id": "uuid-abc", "command": "send_message", "params": {"phone_number": "201281835346", "message": "Hi there!"}}
  ```
  The bridge responds with:
  ```json
  {"request_id": "uuid-abc", "success": true, "data": {"id": "msg456", "from": "me", "chat_id": "201281835346@c.us"}}
  ```

---

## Layer 2: WhatsApp Client (`whatsapp_client.py`)

Wraps the raw JSON protocol into Python async methods. Key mechanism:

- **`_read_stdout()`** — a persistent background loop reading every JSON line from the bridge. It does two things:
  1. If the JSON has `"request_id"` → it's a response to a command we sent. It resolves the matching `asyncio.Future`.
  2. If the JSON has `"event"` → it's an incoming WhatsApp event. It calls `self.event_handler(event_type, data)`.

- **`_send_command()`** — creates a `Future`, writes the command JSON to stdin, and `await`s the future with a 30s timeout. This is how every action (send, get_chats, get_messages) works.

---

## Layer 3: Main Orchestrator (`main.py` — `WhatsAppClawdBot`)

The **brain wiring**. During `initialize()`:

1. Sets itself as the event handler: `self.wa_client.set_event_handler(self._on_whatsapp_event)`
2. Registers **7 tool handlers** with the Gemini agent:
   ```python
   self.agent.set_tool_handlers({
       "send_message":         self._tool_send_message,
       "schedule_message":     self._tool_schedule_message,
       "search_messages":      self._tool_search_messages,
       "summarize_chat":       self._tool_summarize_chat,
       "list_scheduled_tasks": self._tool_list_scheduled_tasks,
       "cancel_scheduled_task":self._tool_cancel_scheduled_task,
       "get_chats":            self._tool_get_chats,
   })
   ```

When a message arrives, `handle_incoming_message()` runs this pipeline:

```
1. Loop prevention  →  ignore if from_me AND has [BOT] signature
2. Authorization    →  check sender against ADMIN_PHONE_NUMBERS or from_me
3. Command check    →  if starts with /, handle directly (bypass agent)
4. RAG indexing     →  store message in ChromaDB
5. RAG retrieval    →  find similar past messages
6. Agent call       →  agent.process_message(content, sender, rag_context)
7. Send response    →  append [BOT] signature and send back
```

---

## Layer 4: Gemini Agent (`gemini_agent.py`)

This is where the AI reasoning happens.

### Context Construction

The context sent to Gemini for ANY message is built from **3 sources**:

**Source 1 — System Prompt** (set once at session creation):
```python
history = [
    {"role": "user", "parts": [system_instructions]},   # The rules
    {"role": "model", "parts": ["Understood! I'm your WhatsApp assistant..."]}
]
```
This tells Gemini what tools it has and how to behave (e.g., "call `get_chats` first when user mentions a name").

**Source 2 — Conversation History** (persistent per user):
Every previous user message and model response for this `user_id` is in `chat.history`. This gives the model conversational memory. It's trimmed to stay under 30 turns / 16,000 tokens.

**Source 3 — RAG Context** (appended to the user message):
If similar past messages exist in ChromaDB, they're appended:
```python
user_message = f"{user_message}\n\nRelevant context from past messages:\n{context_text}"
```
Where `context_text` looks like:
```
[2026-02-10T14:30:00] 201281835346@c.us: Let's meet at 5pm tomorrow
[2026-02-09T09:15:00] 201281835346@c.us: The project deadline is Friday
```

### Tool Declarations

The model is initialized with `TOOL_DECLARATIONS` — OpenAPI-style schemas that tell Gemini what functions it can call:
```python
self.model = GenerativeModel(
    "gemini-2.5-flash",
    tools=[{"function_declarations": TOOL_DECLARATIONS}],
)
```

---

## Concrete Examples

### Example 1: Simple Chat (No Tools)

User sends: *"What's the weather like?"*

```
1. Bridge emits: {"event": "message_received", "data": {"body": "What's the weather like?", ...}}
2. WhatsAppClient calls event_handler → main._on_whatsapp_event()
3. handle_incoming_message():
   - Not from_me, sender is authorized ✓
   - Not a /command
   - RAG indexes: "What's the weather like?" → ChromaDB
   - RAG retrieves similar past messages (probably nothing relevant)
   - agent.process_message("What's the weather like?", sender, context=None)
4. GeminiAgent:
   - Gets/creates chat session for this user
   - Trims history if needed
   - Sends to Gemini: "What's the weather like?"
   - Gemini responds with TEXT (no function_call) → "I don't have weather info..."
   - Returns text
5. main sends: "I don't have weather info...\n\n[BOT]" → back to user
```

### Example 2: Sending a Message by Name (Multi-Tool Chain)

User sends: *"Send hello to mum"*

```
1. message arrives → same pipeline → reaches agent.process_message()
2. GeminiAgent sends to Gemini: "Send hello to mum"
3. Gemini's FIRST response is a function_call (not text):
   function_call: get_chats(limit=20)  ← model knows it needs the chat ID

4. Agentic tool loop (round 1):
   - Extract function_call: name="get_chats", args={"limit": 20}
   - Execute: self._tool_handlers["get_chats"](limit=20)
     → calls main._tool_get_chats()
     → calls wa_client.get_chats()
     → sends {"command": "get_chats"} to bridge
     → bridge returns list of chats
     → returns: {"chats": [{"id": "201234567890@c.us", "name": "Mum", ...}, ...]}
   
   - Feed result back to Gemini as FunctionResponse

5. Gemini's SECOND response is another function_call:
   function_call: send_message(phone_number="201234567890@c.us", message="Hello! 👋")
   
6. Agentic tool loop (round 2):
   - Execute: self._tool_handlers["send_message"](...)
     → calls wa_client.send_message()
     → bridge sends the actual WhatsApp message
     → returns: {"status": "sent", "to": "201234567890@c.us"}
   
   - Feed result back to Gemini

7. Gemini's THIRD response is TEXT:
   "Done! I've sent 'Hello! 👋' to Mum."
   
8. return that text → main appends [BOT] → sends to user
```

The key insight: **the model autonomously decided to chain 2 tool calls** — first `get_chats` to look up the name, then `send_message` with the resolved ID. This is the "agentic loop" (max 5 rounds).

### Example 3: Scheduling via Natural Language

User sends: *"Remind me to call the doctor every day at 9am"*

```
1. → agent.process_message("Remind me to call the doctor every day at 9am", ...)
2. Gemini responds with: schedule_message(
       phone_number=<sender's number>,
       message="📞 Don't forget to call the doctor!",
       time="09:00",
       pattern="daily"
   )
3. Tool handler _tool_schedule_message():
   - Parses "09:00" → hour=9, minute=0
   - Creates schedule_time in Africa/Cairo timezone
   - Calls scheduler.schedule_message() → APScheduler creates a cron job
   - Returns {"status": "scheduled", "task_id": "abc123", ...}
4. Fed back to Gemini → responds: "All set! I'll remind you daily at 9:00 AM."
```

### Example 4: Chat Summary with RAG Context

User sends: *"What were we talking about last week with Ahmed?"*

```
1. RAG retrieval: ChromaDB searches for messages similar to the query
   → Finds 5 past messages from Ahmed's chat:
     "[2026-02-07] Ahmed: The deadline is next Friday"
     "[2026-02-06] Ahmed: Can you review the PR?"

2. agent.process_message() receives:
   "What were we talking about last week with Ahmed?
   
   Relevant context from past messages:
   [2026-02-07T10:30:00] 201234567890@c.us: The deadline is next Friday
   [2026-02-06T14:15:00] 201234567890@c.us: Can you review the PR?"

3. Gemini can now answer directly from the RAG context:
   "Based on your recent messages, you and Ahmed were discussing..."
   
   OR Gemini might decide to use summarize_chat() for a deeper look.
```

---

## Loop Prevention Mechanism

Every bot response includes `[BOT]` at the end. When the bot sends a message, WhatsApp echoes it back as a `from_me=True` event. The handler catches this:

```python
if from_me:
    if self.BOT_SIGNATURE in content:  # "[BOT]" found
        return  # Ignore it, don't feed it to the agent again
```

Without this, the bot would reply to its own messages infinitely.

---

## Summary: What Happens for Every Message

| Step | Component | What Happens |
|------|-----------|-------------|
| 1 | `whatsapp_bridge.js` | Receives WA message, emits JSON event on stdout |
| 2 | `WhatsAppClient._read_stdout` | Reads JSON, calls `event_handler()` |
| 3 | `main._on_whatsapp_event` | Parses timestamp, calls `handle_incoming_message()` |
| 4 | `main.handle_incoming_message` | Loop prevention → auth → command check |
| 5 | `MessageRAG.index_message` | Stores message as vector in ChromaDB |
| 6 | `MessageRAG.get_context_for_query` | Retrieves similar past messages |
| 7 | `GeminiAgent.process_message` | Sends user msg + RAG context to Gemini |
| 8 | Gemini API | Returns text OR function_call |
| 9 | `GeminiAgent._execute_tool` | If function_call → runs handler → feeds result back |
| 10 | (repeat 8-9) | Until Gemini returns text (max 5 rounds) |
| 11 | `main` | Appends `[BOT]`, sends response via WhatsAppClient |
| 12 | `WhatsAppClient.send_message` | Writes JSON command to bridge stdin |
| 13 | `whatsapp_bridge.js` | Sends actual WhatsApp message |
