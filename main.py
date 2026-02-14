"""
WhatsApp ClawdBot Main Application
Orchestrates all components
"""

import asyncio
import os
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from gemini_agent import GeminiAgent
from message_rag import MessageRAG
from task_scheduler import TaskScheduler
from whatsapp_client import WhatsAppClient

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WhatsAppClawdBot:
    """
    Main WhatsApp ClawdBot application
    Integrates Claude agent, RAG, scheduler, and WhatsApp
    """
    
    def __init__(
        self,
        session_path: str = "./session",
        enable_rag: bool = True,
        enable_scheduler: bool = True
    ):
        # Initialize components
        self.wa_client = WhatsAppClient(session_path)
        self.agent = GeminiAgent()
        
        # Optional components
        self.rag = MessageRAG() if enable_rag else None
        self.scheduler = TaskScheduler() if enable_scheduler else None
        
        self.enable_rag = enable_rag
        self.enable_scheduler = enable_scheduler
        
        # Admin phone numbers (authorized users)
        self.admin_numbers = self._load_admin_numbers()
        
        # Running flag
        self.running = False
        
        # Sleep mode
        self.sleep_mode = False
        self.sleep_notified: set = set()  # senders already told "I'm sleeping"
    
    def _load_admin_numbers(self) -> set:
        """Load authorized admin phone numbers from environment"""
        admin_str = os.getenv("ADMIN_PHONE_NUMBERS", "")
        if admin_str:
            return set(admin_str.split(","))
        return set()
            
    def _track_sent_message(self, message_id: str):
        """Track ID of sent message to prevent loops"""
        if not hasattr(self, "sent_message_ids"):
            self.sent_message_ids = set()
        self.sent_message_ids.add(message_id)
        
        # Cleanup old IDs (simple approach: keep last 100)
        if len(self.sent_message_ids) > 100:
            self.sent_message_ids = set(list(self.sent_message_ids)[-50:])
    
    async def initialize(self):
        """Initialize all components"""
        logger.info("Initializing WhatsApp ClawdBot...")
        
        # Initialize WhatsApp client
        self.wa_client.set_event_handler(self._on_whatsapp_event)
        await self.wa_client.initialize()
        logger.info("WhatsApp client initialized")
        
        # Initialize scheduler
        if self.scheduler:
            # Set the send message callback
            self.scheduler.set_send_callback(self._send_message_callback)
            await self.scheduler.start()
            logger.info("Scheduler initialized")
        
        # Register tool handlers with the Gemini agent
        self.agent.set_tool_handlers({
            "send_message": self._tool_send_message,
            "schedule_message": self._tool_schedule_message,
            "search_messages": self._tool_search_messages,
            "summarize_chat": self._tool_summarize_chat,
            "list_scheduled_tasks": self._tool_list_scheduled_tasks,
            "cancel_scheduled_task": self._tool_cancel_scheduled_task,
            "get_chats":             self._tool_get_chats,
            "toggle_sleep_mode":     self._tool_toggle_sleep_mode,
        })
        logger.info("Agent tool handlers registered")
        
        logger.info("WhatsApp ClawdBot ready!")
    
    async def _on_whatsapp_event(self, event_type: str, data: Dict[str, Any]):
        """Handle incoming WhatsApp events"""
        if event_type == "message_received":
            # Normalize timestamp
            ts = data.get("timestamp")
            if isinstance(ts, (int, float)):
                timestamp = datetime.fromtimestamp(ts)
            elif isinstance(ts, str):
                try:
                    timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except:
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()

            await self.handle_incoming_message(
                message_id=data.get("id"),
                sender=data.get("from"),
                chat_id=data.get("from"), # Use sender as chat_id for now
                content=data.get("body"),
                timestamp=timestamp,
                from_me=data.get("fromMe", False)
            )

    async def _send_message_callback(
        self,
        phone_number: str,
        message: str
    ):
        """Callback for scheduler to send messages"""
        await self.wa_client.send_message(
            phone_number=phone_number,
            message=message
        )
    
    
    async def _index_chat(self, target_number: str, msg_count: int) -> int:
        """Fetch messages from a chat and index them into RAG. Returns count of indexed messages."""
        chat_id = target_number if "@" in target_number else f"{target_number.replace('+', '')}@c.us"
        
        logger.info(f"Indexing up to {msg_count} messages from {chat_id}...")
        
        messages = await self.wa_client.get_messages(chat_id, limit=msg_count)
        
        indexed_count = 0
        for msg in messages:
            if msg.body:
                await self.rag.index_message(
                    message_id=msg.id,
                    content=msg.body,
                    sender=msg.from_number,
                    chat_id=chat_id,
                    timestamp=msg.timestamp
                )
                indexed_count += 1
        
        logger.info(f"Indexed {indexed_count} messages from {chat_id}")
        return indexed_count

    # Signature to append to bot messages to prevent loops
    BOT_SIGNATURE = "[BOT]"

    async def handle_incoming_message(
        self,
        message_id: str,
        sender: str,
        chat_id: str,
        content: str,
        timestamp: datetime,
        from_me: bool = False
    ):
        """
        Handle incoming WhatsApp message
        
        Args:
            message_id: Unique message ID
            sender: Sender phone number
            chat_id: Chat ID
            content: Message content
            timestamp: Message timestamp
            from_me: Whether the message was sent by this client
        """
        try:
            # Prevent infinite loops:
            if from_me:
                # Debug logging to see why loop prevention might fail
                logger.info(f"Self-message detected. Content: {repr(content)}")
                
                # 1. Signature Check (Most Robust)
                if self.BOT_SIGNATURE in content:
                    logger.info(f"Ignoring own output message (signature detected): {message_id}")
                    return

                # 2. Tracked ID Check (Fallback)
                if hasattr(self, "sent_message_ids") and message_id in self.sent_message_ids:
                    logger.info(f"Ignoring own output message (ID tracked): {message_id}")
                    return
                
                # If it's a self-message WITHOUT the signature, we treat it as a user command (Note to Self)
                logger.info("Processing 'Note to Self' command...")
            
            # Log the raw sender for debugging
            # Log the raw sender for debugging
            logger.info(f"Received message from: {sender}")
            
            # Normalize sender (remove @c.us or @g.us)
            normalized_sender = sender.split("@")[0] if sender else ""
            if normalized_sender.startswith("+"):
                normalized_sender = normalized_sender[1:]
                
            # Check if sender is authorized
            # We check against the raw sender, the normalized sender, and version with +
            is_authorized = False
            
            # 1. Authorize if it's a self-message (Note to Self)
            if from_me:
                is_authorized = True
                logger.info(f"Processing self-message from {sender}")
            
            # 2. Authorize if in admin list
            elif self.admin_numbers:
                for admin_num in self.admin_numbers:
                    clean_admin = admin_num.replace("+", "").strip()
                    if sender == admin_num or normalized_sender == clean_admin:
                        is_authorized = True
                        break
            
            if not is_authorized:
                logger.warning(f"Unauthorized message from {sender} (Normalized: {normalized_sender})")
                return
            
            # Loop Prevention done at top
            
            logger.info(f"Processing message from {sender}: {content[:50]}...")
            
            # Sleep mode: auto-reply once, then ignore
            if self.sleep_mode and not from_me:
                if sender in self.sleep_notified:
                    logger.info(f"Sleep mode: ignoring repeat message from {sender}")
                    return
                # First message from this person — send one-time reply
                self.sleep_notified.add(sender)
                await self.wa_client.send_message(
                    sender,
                    "I'm sleeping right now 😴 I'll get back to you when I wake up! [BOT]"
                )
                logger.info(f"Sleep mode: notified {sender}, will ignore further messages")
                return
            
            # Handle commands (case-insensitive)
            content_lower = content.lower()
            
            if content_lower.startswith("/help"):
                help_msg = self._get_help_message()
                await self.wa_client.send_message(sender, f"{help_msg} [BOT]")
                return
                
            if content_lower.startswith("/clear"):
                self.agent.clear_history(sender)
                await self.wa_client.send_message(sender, "Conversation history cleared. [BOT]")
                return

            if content_lower.startswith("/send"):
                # Format: /send <number> <message>
                try:
                    parts = content.split(" ", 2)
                    if len(parts) < 3:
                        await self.wa_client.send_message(sender, "Usage: /send <number> <message>\nExample: /send 201281835346 Good morning! [BOT]")
                        return
                    
                    target_number = parts[1]
                    message_to_send = parts[2]
                    
                    # Don't append @c.us here — the bridge's sendMessage() already
                    # strips non-numeric chars (like +) and appends @c.us automatically.
                    logger.info(f"Sending message to {target_number}: {message_to_send[:50]}...")
                    
                    await self.wa_client.send_message(target_number, message_to_send)
                    await self.wa_client.send_message(sender, f"✅ Message sent to {parts[1]}! [BOT]")
                except Exception as e:
                    logger.error(f"Error sending message: {e}")
                    await self.wa_client.send_message(sender, f"Failed to send message: {str(e)} [BOT]")
                return

            if content_lower.startswith("/schedule"):
                # Format: /schedule <number> <pattern> <HH:MM> <message>
                # Patterns: daily, weekly, monthly, every_2_hours, every_30_minutes, once
                try:
                    parts = content.split(None, 4)
                    if len(parts) < 5:
                        await self.wa_client.send_message(sender, (
                            "Usage: /schedule <number> <pattern> <HH:MM> <message>\n\n"
                            "Patterns:\n"
                            "• daily — every day at the given time\n"
                            "• weekly — every week (same day) at the given time\n"
                            "• monthly — every month (same date) at the given time\n"
                            "• every_2_hours — every 2 hours\n"
                            "• every_30_minutes — every 30 minutes\n"
                            "• once — one-time message\n\n"
                            "Examples:\n"
                            "/schedule 201281835346 daily 08:00 Good morning! ☀️\n"
                            "/schedule 393203696230 weekly 09:00 Weekly check-in!\n"
                            "/schedule 201281835346 once 14:30 Don't forget the meeting! [BOT]"
                        ))
                        return
                    
                    target_number = parts[1]
                    pattern = parts[2].lower()
                    time_str = parts[3]
                    scheduled_message = parts[4]
                    
                    # Parse the time
                    try:
                        hour, minute = map(int, time_str.split(":"))
                    except ValueError:
                        await self.wa_client.send_message(sender, "Invalid time format. Use HH:MM (e.g. 08:00, 14:30) [BOT]")
                        return
                    
                    # Create schedule time (today at the specified time, or tomorrow if already passed)
                    from zoneinfo import ZoneInfo
                    tz = ZoneInfo("Africa/Cairo")
                    now = datetime.now(tz)
                    schedule_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if schedule_time <= now and pattern == "once":
                        schedule_time += timedelta(days=1)
                    
                    # Determine if recurring
                    is_recurring = pattern != "once"
                    recurrence_pattern = pattern if is_recurring else None
                    
                    task_id = await self.scheduler.schedule_message(
                        phone_number=target_number,
                        message=scheduled_message,
                        schedule_time=schedule_time,
                        recurring=is_recurring,
                        recurrence_pattern=recurrence_pattern
                    )
                    
                    if is_recurring:
                        desc = f"*{pattern}* at {time_str}"
                    else:
                        desc = f"once at {time_str} on {schedule_time.strftime('%Y-%m-%d')}"
                    
                    await self.wa_client.send_message(sender, (
                        f"✅ Scheduled!\n"
                        f"To: {target_number}\n"
                        f"When: {desc}\n"
                        f"Message: {scheduled_message}\n"
                        f"Task ID: {task_id}\n\n"
                        f"Use /tasks to see all scheduled messages.\n"
                        f"Use /unschedule {task_id} to cancel. [BOT]"
                    ))
                    
                except Exception as e:
                    logger.error(f"Error scheduling: {e}")
                    await self.wa_client.send_message(sender, f"Failed to schedule: {str(e)} [BOT]")
                return

            if content_lower.startswith("/unschedule"):
                try:
                    parts = content.split()
                    if len(parts) < 2:
                        await self.wa_client.send_message(sender, "Usage: /unschedule <task_id>\nUse /tasks to see all task IDs. [BOT]")
                        return
                    
                    task_id = parts[1]
                    success = self.scheduler.cancel_task(task_id)
                    
                    if success:
                        await self.wa_client.send_message(sender, f"✅ Cancelled task: {task_id} [BOT]")
                    else:
                        await self.wa_client.send_message(sender, f"❌ Task not found: {task_id} [BOT]")
                except Exception as e:
                    await self.wa_client.send_message(sender, f"Failed: {str(e)} [BOT]")
                return

            if content_lower.startswith("/tasks"):
                try:
                    tasks = self.scheduler.list_tasks()
                    
                    if not tasks:
                        await self.wa_client.send_message(sender, "No scheduled tasks. Use /schedule to create one. [BOT]")
                        return
                    
                    formatted = f"📋 *Scheduled Tasks* ({len(tasks)}):\n\n"
                    for t in tasks:
                        formatted += f"*ID:* {t['id']}\n"
                        formatted += f"  To: {t['phone_number']}\n"
                        formatted += f"  Next: {t['next_run']}\n"
                        formatted += f"  Pattern: {t['trigger']}\n"
                        msg_preview = (t['message'] or '')[:50]
                        formatted += f"  Msg: {msg_preview}\n\n"
                    
                    formatted += "Use /unschedule <task_id> to cancel. [BOT]"
                    await self.wa_client.send_message(sender, formatted)
                except Exception as e:
                    await self.wa_client.send_message(sender, f"Failed: {str(e)} [BOT]")
                return

            if content_lower.startswith("/summarize"):
                # Format: /summarize <number> [count]
                try:
                    parts = content.split()
                    if len(parts) < 2:
                        await self.wa_client.send_message(sender, "Usage: /summarize <number> [count]\nExample: /summarize 201281835346 20\nDefault count is 20 messages. [BOT]")
                        return
                    
                    target_number = parts[1]
                    msg_count = int(parts[2]) if len(parts) > 2 else 20
                    
                    # Format the chat_id for the bridge
                    chat_id = target_number if "@" in target_number else f"{target_number.replace('+', '')}@c.us"
                    
                    logger.info(f"Fetching {msg_count} messages from {chat_id} for summarization...")
                    await self.wa_client.send_message(sender, f"⏳ Fetching last {msg_count} messages from {target_number}... [BOT]")
                    
                    # Fetch messages from the chat
                    messages = await self.wa_client.get_messages(chat_id, limit=msg_count)
                    
                    if not messages:
                        await self.wa_client.send_message(sender, f"No messages found in chat with {target_number}. [BOT]")
                        return
                    
                    # Convert Message objects to dicts for the summarizer
                    message_dicts = [
                        {
                            "timestamp": msg.timestamp.isoformat() if msg.timestamp else "Unknown",
                            "from": msg.from_number,
                            "body": msg.body
                        }
                        for msg in messages
                        if msg.body  # Skip empty messages (media, etc.)
                    ]
                    
                    logger.info(f"Summarizing {len(message_dicts)} messages...")
                    summary = await self.agent.summarize_messages(message_dicts)
                    
                    await self.wa_client.send_message(sender, f"📋 *Summary of chat with {target_number}* ({len(message_dicts)} messages):\n\n{summary}\n\n[BOT]")
                    
                except ValueError:
                    await self.wa_client.send_message(sender, "Invalid count. Usage: /summarize <number> [count] [BOT]")
                except Exception as e:
                    logger.error(f"Error summarizing chat: {e}")
                    await self.wa_client.send_message(sender, f"Failed to summarize: {str(e)} [BOT]")
                return

            if content_lower.startswith("/search"):
                # Format: /search <query>
                # Searches RAG-indexed messages by semantic similarity
                try:
                    query = content[len("/search"):].strip()
                    if not query:
                        await self.wa_client.send_message(sender, "Usage: /search <query>\nExample: /search meeting tomorrow\n\nSearches through indexed messages by topic. [BOT]")
                        return
                    
                    if not self.rag:
                        await self.wa_client.send_message(sender, "RAG is not enabled. [BOT]")
                        return
                    
                    logger.info(f"RAG search for: {query}")
                    results = await self.rag.search_messages(query=query, n_results=5)
                    
                    if not results:
                        await self.wa_client.send_message(sender, f"No results found for: {query}\n\nTip: Use /index <number> to load past messages into the search index first. [BOT]")
                        return
                    
                    stats = self.rag.get_stats()
                    await self.wa_client.send_message(sender, f"🔍 *Found {len(results)} results for:* {query}\n_({stats.get('total_messages', '?')} messages indexed)_ [BOT]")
                    
                    # Send each result as a quoted reply to the original message
                    for i, msg in enumerate(results, 1):
                        meta = msg["metadata"]
                        score = round((1 - msg["distance"]) * 100, 1)
                        msg_id = msg["id"]
                        
                        result_text = f"*Result {i}* — _{score}% match_\nFrom: {meta.get('sender', '?')}\nDate: {meta.get('timestamp', '?')}\nChat: {meta.get('chat_id', '?')} [BOT]"
                        
                        # Try to quote the original message
                        try:
                            await self.wa_client.send_message(sender, result_text, reply_to=msg_id)
                        except Exception:
                            # Quoting failed (maybe cross-chat) — send with text preview instead
                            preview = msg['content'][:300]
                            result_text = f"*Result {i}* — _{score}% match_\nFrom: {meta.get('sender', '?')}\nDate: {meta.get('timestamp', '?')}\nChat: {meta.get('chat_id', '?')}\n\n💬 {preview} [BOT]"
                            await self.wa_client.send_message(sender, result_text)
                    
                except Exception as e:
                    logger.error(f"Error searching: {e}")
                    await self.wa_client.send_message(sender, f"Search failed: {str(e)} [BOT]")
                return

            if content_lower.startswith("/indexall"):
                # Format: /indexall <num1> <num2> ... [count]
                # Last arg is count if it's a pure number, otherwise treated as a chat number
                try:
                    parts = content.split()
                    if len(parts) < 2:
                        await self.wa_client.send_message(sender, "Usage: /indexall <number1> <number2> ... [count]\nExample: /indexall 201281835346 201003986947 100\nDefault count is 50 per chat. Use 'all' for full history. [BOT]")
                        return
                    
                    if not self.rag:
                        await self.wa_client.send_message(sender, "RAG is not enabled. [BOT]")
                        return
                    
                    args = parts[1:]
                    
                    # Check if last arg is a count or 'all'
                    msg_count = 50  # default
                    fetch_all = False
                    if args[-1].lower() == "all":
                        fetch_all = True
                        numbers = args[:-1]
                    elif args[-1].isdigit() and len(args) > 1:
                        msg_count = int(args[-1])
                        numbers = args[:-1]
                    else:
                        numbers = args
                    
                    if not numbers:
                        await self.wa_client.send_message(sender, "Please provide at least one chat number. [BOT]")
                        return
                    
                    count_label = "ALL" if fetch_all else str(msg_count)
                    await self.wa_client.send_message(sender, f"⏳ Indexing {count_label} messages from {len(numbers)} chats... [BOT]")
                    
                    total_indexed = 0
                    for number in numbers:
                        indexed = await self._index_chat(number, 99999 if fetch_all else msg_count)
                        total_indexed += indexed
                    
                    stats = self.rag.get_stats()
                    await self.wa_client.send_message(sender, f"✅ Done! Indexed {total_indexed} messages from {len(numbers)} chats.\nTotal in index: {stats.get('total_messages', '?')}\n\n[BOT]")
                    
                except Exception as e:
                    logger.error(f"Error in indexall: {e}")
                    await self.wa_client.send_message(sender, f"Failed: {str(e)} [BOT]")
                return

            if content_lower.startswith("/index"):
                # Format: /index <number> [count|all]
                try:
                    parts = content.split()
                    if len(parts) < 2:
                        await self.wa_client.send_message(sender, "Usage: /index <number> [count|all]\nExamples:\n  /index 201281835346 50\n  /index 201281835346 all\nDefault: 50 messages. [BOT]")
                        return
                    
                    if not self.rag:
                        await self.wa_client.send_message(sender, "RAG is not enabled. [BOT]")
                        return
                    
                    target_number = parts[1]
                    
                    # Parse count — isolate int() so ValueError only catches bad input
                    if len(parts) > 2 and parts[2].lower() == "all":
                        msg_count = 99999
                        count_label = "ALL"
                    elif len(parts) > 2:
                        try:
                            msg_count = int(parts[2])
                        except ValueError:
                            await self.wa_client.send_message(sender, "Invalid count. Usage: /index <number> [count|all] [BOT]")
                            return
                        count_label = str(msg_count)
                    else:
                        msg_count = 50
                        count_label = "50"
                    
                    await self.wa_client.send_message(sender, f"⏳ Fetching and indexing {count_label} messages from {target_number}... [BOT]")
                    
                    indexed_count = await self._index_chat(target_number, msg_count)
                    
                    stats = self.rag.get_stats()
                    await self.wa_client.send_message(sender, f"✅ Indexed {indexed_count} messages from {target_number}!\nTotal in index: {stats.get('total_messages', '?')}\n\nUse /search to find messages.\n\n[BOT]")
                    
                except Exception as e:
                    logger.error(f"Error indexing: {e}")
                    await self.wa_client.send_message(sender, f"Failed to index: {str(e)} [BOT]")
                return
            
            # --- RAG and Agent Logic ---
            # Index message in RAG if enabled
            if self.rag:
                await self.rag.index_message(
                    message_id=message_id,
                    content=content,
                    sender=sender,
                    chat_id=chat_id,
                    timestamp=timestamp
                )
            
            # Process with gemini agent
            # (RAG context is NOT force-fed here — the agent will call
            #  the search_messages tool on its own when it needs history)
            response = await self.agent.process_message(
                user_message=content,
                user_id=sender,
            )
            
            # Send response
            if response:
                # Append signature
                full_response = f"{response}\n\n{self.BOT_SIGNATURE}"
                
                result = await self.wa_client.send_message(
                    phone_number=sender,
                    message=full_response
                )
                self._track_sent_message(result.id)
                logger.info(f"Sent response to {sender}")
            
        except Exception as e:
            logger.error(f"Error handling message: {e}")
            
            # Send error message to user
            try:
                await self.wa_client.send_message(
                    phone_number=sender,
                    message="Sorry, I encountered an error processing your message. Please try again. [BOT]"
                )
            except:
                pass
    
    # ------------------------------------------------------------------
    # Tool handler methods (called by GeminiAgent when it uses tools)
    # ------------------------------------------------------------------

    async def _tool_send_message(self, phone_number: str, message: str) -> dict:
        """Tool handler: send a WhatsApp message."""
        try:
            await self.wa_client.send_message(phone_number, message)
            return {"status": "sent", "to": phone_number, "message": message}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_schedule_message(
        self, phone_number: str, message: str, time: str, pattern: str
    ) -> dict:
        """Tool handler: schedule a WhatsApp message."""
        try:
            if not self.scheduler:
                return {"error": "Scheduler is not enabled"}

            # Parse HH:MM
            hour, minute = map(int, time.split(":"))

            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Africa/Cairo")
            now = datetime.now(tz)
            schedule_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if schedule_time <= now and pattern == "once":
                schedule_time += timedelta(days=1)

            is_recurring = pattern != "once"
            recurrence_pattern = pattern if is_recurring else None

            task_id = await self.scheduler.schedule_message(
                phone_number=phone_number,
                message=message,
                schedule_time=schedule_time,
                recurring=is_recurring,
                recurrence_pattern=recurrence_pattern,
            )

            return {
                "status": "scheduled",
                "task_id": task_id,
                "to": phone_number,
                "pattern": pattern,
                "time": time,
                "message": message,
            }
        except Exception as e:
            return {"error": str(e)}

    async def _tool_search_messages(self, query: str) -> dict:
        """Tool handler: semantic search across indexed messages."""
        try:
            if not self.rag:
                return {"error": "RAG is not enabled"}

            results = await self.rag.search_messages(query=query, n_results=5)

            if not results:
                return {"results": [], "message": f"No results found for: {query}"}

            formatted = []
            for msg in results:
                meta = msg["metadata"]
                score = round((1 - msg["distance"]) * 100, 1)
                formatted.append({
                    "content": msg["content"][:300],
                    "sender": meta.get("sender", "?"),
                    "timestamp": meta.get("timestamp", "?"),
                    "match_score": f"{score}%",
                })

            return {"results": formatted, "total_indexed": self.rag.get_stats().get("total_messages", "?")}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_summarize_chat(
        self, phone_number: str, count: int = 50,
        start_date: str = None, end_date: str = None
    ) -> dict:
        """Tool handler: fetch messages from a chat and summarize them."""
        try:
            chat_id = phone_number if "@" in phone_number else f"{phone_number.replace('+', '')}@c.us"
            messages = await self.wa_client.get_messages(
                chat_id, limit=count,
                start_date=start_date, end_date=end_date
            )

            if not messages:
                period = ""
                if start_date and end_date:
                    period = f" between {start_date} and {end_date}"
                elif start_date:
                    period = f" from {start_date} onwards"
                elif end_date:
                    period = f" up to {end_date}"
                return {"error": f"No messages found in chat with {phone_number}{period}"}

            message_dicts = [
                {
                    "timestamp": msg.timestamp.isoformat() if msg.timestamp else "Unknown",
                    "from": msg.from_number,
                    "body": msg.body,
                }
                for msg in messages
                if msg.body
            ]

            summary = await self.agent.summarize_messages(message_dicts)
            period_desc = ""
            if start_date or end_date:
                period_desc = f" ({start_date or '...'} to {end_date or 'now'})"
            return {"summary": summary, "message_count": len(message_dicts), "period": period_desc}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_list_scheduled_tasks(self) -> dict:
        """Tool handler: list all scheduled tasks."""
        try:
            if not self.scheduler:
                return {"error": "Scheduler is not enabled"}

            tasks = self.scheduler.list_tasks()
            if not tasks:
                return {"tasks": [], "message": "No scheduled tasks"}

            formatted = []
            for t in tasks:
                formatted.append({
                    "id": t["id"],
                    "to": t["phone_number"],
                    "next_run": t["next_run"],
                    "pattern": t["trigger"],
                    "message_preview": (t["message"] or "")[:50],
                })
            return {"tasks": formatted}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_cancel_scheduled_task(self, task_id: str) -> dict:
        """Tool handler: cancel a scheduled task by ID."""
        try:
            if not self.scheduler:
                return {"error": "Scheduler is not enabled"}

            success = self.scheduler.cancel_task(task_id)
            if success:
                return {"status": "cancelled", "task_id": task_id}
            else:
                return {"error": f"Task not found: {task_id}"}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_get_chats(self, limit: int = 20) -> dict:
        """Tool handler: get list of recent chats (groups + individuals)."""
        try:
            chats = await self.wa_client.get_chats(limit=limit)

            if not chats:
                return {"chats": [], "message": "No chats found"}

            formatted = []
            for c in chats:
                formatted.append({
                    "id": c.id,
                    "name": c.name,
                    "type": "group" if c.is_group else "individual",
                    "unread": c.unread_count,
                })
            return {"chats": formatted}
        except Exception as e:
            return {"error": str(e)}

    async def _tool_toggle_sleep_mode(self, enabled: bool) -> dict:
        """Tool handler: toggle sleep mode on or off."""
        self.sleep_mode = enabled
        if enabled:
            self.sleep_notified.clear()  # reset so everyone gets one notification
            logger.info("Sleep mode ENABLED")
            return {"status": "sleep_mode_on", "message": "Sleep mode activated. I'll auto-reply to anyone who messages and then ignore them."}
        else:
            notified_count = len(self.sleep_notified)
            self.sleep_notified.clear()
            logger.info("Sleep mode DISABLED")
            return {"status": "sleep_mode_off", "message": f"Sleep mode deactivated. {notified_count} people were notified while you slept."}

    async def process_command(
        self,
        command: str,
        sender: str
    ) -> Optional[str]:
        """
        Process special commands
        
        Args:
            command: Command text
            sender: Sender phone number
        
        Returns:
            Response message
        """
        command = command.lower().strip()
        
        if command == "/help":
            return self._get_help_message()
        
        elif command == "/stats":
            return await self._get_stats()
        
        elif command == "/clear":
            self.agent.clear_history(sender)
            return "Conversation history cleared!"
        
        elif command.startswith("/schedule"):
            # List scheduled tasks
            if not self.scheduler:
                return "Scheduler is not enabled"
            
            tasks = self.scheduler.list_tasks()
            if not tasks:
                return "No scheduled messages"
            
            response = "📅 Scheduled Messages:\n\n"
            for task in tasks:
                response += f"• {task['phone_number']}\n"
                response += f"  Next: {task['next_run']}\n"
                response += f"  Message: {task['message'][:50]}...\n\n"
            
            return response
        
        return None
    
    def _get_help_message(self) -> str:
        """Get help message"""
        return """🤖 *WhatsApp ClawdBot Help*

💬 *Natural Language (Agent Mode):*
Just talk to me naturally and I'll use my tools automatically!

📤 Send: "Send hello to 201281835346"
📝 Summarize: "Summarize my chat with Ahmed"
⏰ Schedule: "Send good morning to Ahmed daily at 8am"
🔍 Search: "Find messages about the project"
📋 Tasks: "What messages are scheduled?"
❌ Cancel: "Cancel task msg_abc123"

⌨️ *Slash Commands (Direct):*
/send <number> <message>
/schedule <number> <pattern> <HH:MM> <message>
/summarize <number> [count]
/search <query>
/tasks — list scheduled tasks
/unschedule <task_id>
/index <number> [count|all]
/indexall <num1> <num2> ... [count]
/clear — clear conversation history
/help — show this help
/stats — show bot stats
"""
    
    async def _get_stats(self) -> str:
        """Get bot statistics"""
        stats = ["📊 WhatsApp ClawdBot Statistics\n"]
        
        # RAG stats
        if self.rag:
            rag_stats = self.rag.get_stats()
            stats.append(f"📚 Indexed messages: {rag_stats.get('total_messages', 0)}")
        
        # Scheduler stats
        if self.scheduler:
            tasks = self.scheduler.list_tasks()
            stats.append(f"⏰ Scheduled tasks: {len(tasks)}")
        
        # Admin stats
        stats.append(f"👥 Authorized users: {len(self.admin_numbers)}")
        
        return "\n".join(stats)
    
    async def run_message_indexing(self):
        """
        Background task to index existing messages
        Run this once to populate the RAG database
        """
        if not self.rag:
            logger.warning("RAG not enabled, skipping indexing")
            return
        
        logger.info("Starting message indexing...")
        
        try:
            # Get all chats
            chats = await self.wa_client.get_chats(limit=50)
            
            total_indexed = 0
            for chat in chats:
                logger.info(f"Indexing chat: {chat.name}")
                
                # Get messages from chat
                messages = await self.wa_client.get_messages(
                    chat_id=chat.id,
                    limit=100
                )
                
                # Prepare for batch indexing
                msg_batch = [
                    {
                        "id": msg.id,
                        "content": msg.body,
                        "sender": msg.from_number,
                        "chat_id": msg.chat_id,
                        "timestamp": msg.timestamp
                    }
                    for msg in messages
                    if msg.body  # Only text messages
                ]
                
                # Index batch
                await self.rag.index_messages_batch(msg_batch)
                total_indexed += len(msg_batch)
                
                # Small delay to avoid rate limits
                await asyncio.sleep(1)
            
            logger.info(f"Indexing complete! Total messages indexed: {total_indexed}")
            
        except Exception as e:
            logger.error(f"Error during indexing: {e}")
    
    async def run(self):
        """Main run loop"""
        await self.initialize()
        self.running = True
        
        logger.info("WhatsApp ClawdBot is running. Press Ctrl+C to stop.")
        
        # In a real implementation, you would listen for incoming messages
        # This is a simplified example
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            await self.shutdown()
    
    async def shutdown(self):
        """Shutdown the bot"""
        self.running = False
        
        if self.scheduler:
            await self.scheduler.shutdown()
        
        await self.wa_client.close()
        
        logger.info("WhatsApp ClawdBot shutdown complete")


async def main():
    """Main entry point"""
    # Create bot instance
    bot = WhatsAppClawdBot(
        enable_rag=True,
        enable_scheduler=True
    )
    
    # Optional: Run message indexing first
    # await bot.run_message_indexing()
    
    # Run the bot
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
