"""
Gemini Agent Orchestrator
Main agent that processes WhatsApp messages and commands using Google's Gemini
Supports function calling (tool use) for WhatsApp actions
"""

import os
import json
import logging
import asyncio
import re
from typing import Optional, List, Dict, Any, Callable, Awaitable
import google.generativeai as genai
from google.generativeai import GenerativeModel
from google.generativeai.types import content_types
from google.api_core import retry
from google.api_core.exceptions import ResourceExhausted

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool declarations (OpenAPI-style schemas for Gemini function calling)
# ---------------------------------------------------------------------------

TOOL_DECLARATIONS = [
    {
        "name": "send_message",
        "description": (
            "Send a WhatsApp message to a phone number or group chat. "
            "Use this when the user asks you to send, forward, or deliver a message to someone or a group. "
            "For groups, use the chat ID from get_chats (ends with @g.us). "
            "For individuals, use digits only with country code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": "Recipient phone number (digits with country code, e.g. '201281835346') or group chat ID (e.g. '120363012345@g.us'). Use get_chats to find group IDs by name.",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to send.",
                },
            },
            "required": ["phone_number", "message"],
        },
    },
    {
        "name": "schedule_message",
        "description": (
            "Schedule a WhatsApp message to be sent at a specific time, either once or on a recurring basis. "
            "Use this when the user asks to schedule, remind, or send a message at a future time."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": "Recipient phone number (digits only, with country code).",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to schedule.",
                },
                "time": {
                    "type": "string",
                    "description": "Time to send in HH:MM 24-hour format (e.g. '08:00', '14:30').",
                },
                "pattern": {
                    "type": "string",
                    "enum": ["once", "daily", "weekly", "monthly", "every_2_hours", "every_30_minutes"],
                    "description": "Schedule pattern. Use 'once' for one-time messages.",
                },
            },
            "required": ["phone_number", "message", "time", "pattern"],
        },
    },
    {
        "name": "search_messages",
        "description": (
            "Search through previously indexed WhatsApp messages by semantic similarity. "
            "Use this when the user asks to find, look up, or search for specific messages or topics."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query describing what messages to find.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "summarize_chat",
        "description": (
            "Fetch messages from a WhatsApp chat and generate a summary. "
            "Use this when the user asks to summarize a conversation or chat history. "
            "Supports date ranges to summarize old or recent messages."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone_number": {
                    "type": "string",
                    "description": "Phone number or chat ID of the chat to summarize.",
                },
                "count": {
                    "type": "integer",
                    "description": "Max number of messages to summarize. Default is 50.",
                },
                "start_date": {
                    "type": "string",
                    "description": "Start date for the summary period in YYYY-MM-DD format (e.g. '2026-01-01'). Only messages on or after this date are included.",
                },
                "end_date": {
                    "type": "string",
                    "description": "End date for the summary period in YYYY-MM-DD format (e.g. '2026-02-01'). Only messages on or before this date are included.",
                },
            },
            "required": ["phone_number"],
        },
    },
    {
        "name": "list_scheduled_tasks",
        "description": (
            "List all currently scheduled messages/tasks. "
            "Use this when the user asks what is scheduled, what reminders exist, or to see pending tasks."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "cancel_scheduled_task",
        "description": (
            "Cancel a scheduled message by its task ID. "
            "Use this when the user asks to cancel, remove, or stop a scheduled message."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task ID to cancel (obtained from list_scheduled_tasks).",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "get_chats",
        "description": (
            "Get a list of recent WhatsApp chats (both individual contacts and groups). "
            "Each chat has an id, name, and whether it is a group. "
            "Use this to look up a group's chat ID by name before sending a message, "
            "or to find a contact's chat ID. Always call this first when the user "
            "refers to a chat by name instead of phone number."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max number of chats to return. Default is 20.",
                },
            },
        },
    },
    {
        "name": "toggle_sleep_mode",
        "description": (
            "Turn sleep mode on or off. "
            "When the user says they are going to sleep, says goodnight, or wants to stop "
            "receiving messages, turn sleep mode ON. "
            "When the user says they are awake, says good morning, or wants to resume, "
            "turn sleep mode OFF. "
            "While sleep mode is on, the bot auto-replies once to anyone who messages "
            "and then ignores further messages from them to save tokens."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "boolean",
                    "description": "True to enable sleep mode, False to disable it.",
                },
            },
            "required": ["enabled"],
        },
    },
]


class GeminiAgent:
    """
    Main agent that orchestrates WhatsApp interactions using Gemini.
    Supports function calling — the model can decide to use WhatsApp tools
    (send, schedule, search, summarize, etc.) based on natural language.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            logger.warning("GOOGLE_API_KEY not found in environment variables")
        
        genai.configure(api_key=api_key)
        
        self.model_name = "gemini-2.5-flash"
        
        # Create model WITH tool declarations
        self.model = GenerativeModel(
            self.model_name,
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
        )
        
        # Also keep a tool-free model for one-shot tasks (summarize, compose)
        self.model_no_tools = GenerativeModel(self.model_name)
        
        # Per-user chat sessions
        self.chat_sessions: Dict[str, Any] = {}
        
        # Tool handlers: name -> async callable
        # These are set by main.py via set_tool_handlers()
        self._tool_handlers: Dict[str, Callable[..., Awaitable[Any]]] = {}
        
        # Max tool call rounds to prevent infinite loops
        self.max_tool_rounds = 5
        
        # Retry configuration for rate limits
        self.max_retries = 3
        self.base_retry_delay = 5  # seconds
        
        # Context window management
        self.max_history_turns = 30      # Hard cap on conversation turns
        self.max_token_budget = 16000    # Token budget for chat history
        self.system_prompt_turns = 2     # First 2 entries are the system prompt pair
        
    def _get_system_instructions(self) -> str:
        """Get the system prompt/instructions for Gemini"""
        return """You are a helpful WhatsApp assistant bot.

You have access to tools that let you perform real actions on WhatsApp:
- Send messages to contacts and groups
- Schedule messages (one-time or recurring)
- Search through past messages
- Summarize chat history
- List and cancel scheduled tasks
- Look up contacts and groups by name

CRITICAL RULES:
- When the user mentions a contact or group BY NAME (e.g. "send hello to mum", "message the Family group"), you MUST call get_chats first to find their chat ID. NEVER ask the user for a phone number if they gave you a name — look it up yourself.
- When the user provides a phone number directly, use it as-is.
- When the user asks you to DO something (send, schedule, search, summarize), USE the appropriate tool. Do NOT just describe what you would do.
- When the user is just chatting or asking a general question, respond normally without tools.
- Always confirm what you did after executing a tool.
- If a tool fails, explain the error clearly.
- Parse times carefully — use HH:MM 24-hour format.
- Be concise but friendly in your responses.
- Use context from past messages when provided.
"""

    def _get_or_create_chat(self, user_id: str):
        """Get existing chat session or create a new one"""
        if user_id not in self.chat_sessions:
            history = [
                {
                    "role": "user",
                    "parts": [self._get_system_instructions()]
                },
                {
                    "role": "model",
                    "parts": ["Understood! I'm your WhatsApp assistant. I can send messages, schedule them, search through your chats, and more. Just ask me naturally and I'll take care of it! 🤖"]
                }
            ]
            self.chat_sessions[user_id] = self.model.start_chat(history=history)
        return self.chat_sessions[user_id]
    
    def set_tool_handlers(self, handlers: Dict[str, Callable[..., Awaitable[Any]]]):
        """
        Register tool handler functions.
        
        Args:
            handlers: Dict mapping tool name -> async callable.
                      Each callable receives **kwargs matching the tool's parameter schema
                      and returns a dict with the result.
        """
        self._tool_handlers = handlers
        logger.info(f"Registered {len(handlers)} tool handlers: {list(handlers.keys())}")

    async def process_message(
        self,
        user_message: str,
        user_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Process a user message and generate a response.
        Supports an agentic tool-calling loop: if Gemini responds with a
        function_call, we execute it and feed the result back until the
        model returns a text response.
        
        Args:
            user_message: The message from the user
            user_id: Unique identifier for the user
            context: Additional context (e.g., from RAG)
        
        Returns:
            Final text response message
        """
        chat = self._get_or_create_chat(user_id)
        
        # Trim history before sending to stay within context limits
        self._trim_history(chat)
        
        # Append RAG context if available
        if context and context.get("relevant_messages"):
            context_text = self._format_context(context["relevant_messages"])
            user_message = f"{user_message}\n\nRelevant context from past messages:\n{context_text}"
        
        for attempt in range(self.max_retries + 1):
            try:
                # Initial message to the model
                response = await chat.send_message_async(user_message)
                
                # Agentic tool loop
                for round_num in range(self.max_tool_rounds):
                    # Check if the response contains a function call
                    function_call = self._extract_function_call(response)
                    
                    if function_call is None:
                        # No tool call — model returned a text response, we're done
                        break
                    
                    tool_name = function_call.name
                    tool_args = dict(function_call.args) if function_call.args else {}
                    
                    logger.info(f"Tool call (round {round_num + 1}): {tool_name}({tool_args})")
                    
                    # Execute the tool
                    tool_result = await self._execute_tool(tool_name, tool_args)
                    
                    logger.info(f"Tool result: {json.dumps(tool_result, default=str)[:200]}")
                    
                    # Send function response back to the model
                    response = await chat.send_message_async(
                        genai.protos.Content(
                            parts=[
                                genai.protos.Part(
                                    function_response=genai.protos.FunctionResponse(
                                        name=tool_name,
                                        response={"result": tool_result},
                                    )
                                )
                            ]
                        )
                    )
                
                return response.text
                
            except ResourceExhausted as e:
                retry_delay = self._parse_retry_delay(e) or self.base_retry_delay * (2 ** attempt)
                if attempt < self.max_retries:
                    logger.warning(
                        f"Rate limit hit (attempt {attempt + 1}/{self.max_retries + 1}). "
                        f"Retrying in {retry_delay:.0f}s..."
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(f"Rate limit exceeded after {self.max_retries + 1} attempts.")
                    return (
                        "⏳ I'm being rate-limited by the API right now. "
                        "Please wait a minute and try again."
                    )
            except Exception as e:
                logger.error(f"Error processing message with Gemini: {e}", exc_info=True)
                return f"I encountered an error: {str(e)}"
    
    def _trim_history(self, chat):
        """
        Trim chat history to stay within both turn count and token limits.
        Always preserves the first 2 entries (system prompt pair).
        """
        history = chat.history
        sp = self.system_prompt_turns  # entries to always keep
        
        # 1. Hard cap on turns
        if len(history) > self.max_history_turns + sp:
            removed = len(history) - (self.max_history_turns + sp)
            chat.history = history[:sp] + history[sp + removed:]
            logger.debug(f"Trimmed {removed} old turns (turn cap)")
            history = chat.history
        
        # 2. Token budget trim
        try:
            token_count = self.model.count_tokens(history).total_tokens
            while token_count > self.max_token_budget and len(history) > sp + 2:
                # Remove the oldest non-system turn pair (user+model)
                chat.history = history[:sp] + history[sp + 2:]
                history = chat.history
                token_count = self.model.count_tokens(history).total_tokens
                logger.debug(f"Trimmed 2 entries (token budget), now {token_count} tokens")
        except Exception as e:
            logger.warning(f"Token counting failed, relying on turn cap only: {e}")
    
    @staticmethod
    def _parse_retry_delay(exc: ResourceExhausted) -> float:
        """Extract the retry delay (seconds) from a ResourceExhausted error, if present."""
        try:
            match = re.search(r'retry in ([\d.]+)s', str(exc), re.IGNORECASE)
            if match:
                return float(match.group(1))
        except Exception:
            pass
        return 0
    
    def _extract_function_call(self, response):
        """
        Extract a function_call from the model response, if present.
        Returns the FunctionCall proto or None.
        """
        try:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'function_call') and part.function_call.name:
                    return part.function_call
        except (IndexError, AttributeError):
            pass
        return None
    
    async def _execute_tool(self, tool_name: str, tool_args: dict) -> dict:
        """
        Execute a tool by name with given arguments.
        Looks up the handler registered via set_tool_handlers().
        """
        handler = self._tool_handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}. No handler registered."}
        
        try:
            result = await handler(**tool_args)
            return result
        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}", exc_info=True)
            return {"error": f"Tool '{tool_name}' failed: {str(e)}"}
    
    def _format_context(self, messages: List[Dict]) -> str:
        """Format RAG context for inclusion in prompt"""
        formatted = []
        for msg in messages[:5]:
            formatted.append(
                f"[{msg['timestamp']}] {msg['sender']}: {msg['content']}"
            )
        return "\n".join(formatted)
    
    async def summarize_messages(
        self,
        messages: List[Dict[str, Any]],
        summary_type: str = "general"
    ) -> str:
        """
        Generate a summary of messages (one-shot, no tools).
        """
        if not messages:
            return "No messages to summarize."
        
        messages_text = "\n\n".join([
            f"[{msg.get('timestamp', 'Unknown time')}] "
            f"{msg.get('from', 'Unknown')}: {msg.get('body', '')}"
            for msg in messages
        ])
        
        prompt = f"""Please provide a {summary_type} summary of the following WhatsApp messages:

{messages_text}

Summary requirements:
- Highlight key topics and decisions
- Note any action items or important dates
- Group related messages together
- Keep it concise but informative
"""
        
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.model_no_tools.generate_content_async(prompt)
                return response.text
            except ResourceExhausted as e:
                retry_delay = self._parse_retry_delay(e) or self.base_retry_delay * (2 ** attempt)
                if attempt < self.max_retries:
                    logger.warning(f"Rate limit on summarize (attempt {attempt + 1}). Retrying in {retry_delay:.0f}s...")
                    await asyncio.sleep(retry_delay)
                else:
                    return "⏳ Rate-limited by the API. Please wait a minute and try again."
            except Exception as e:
                logger.error(f"Error summarizing messages: {e}")
                return f"Error creating summary: {str(e)}"
    
    async def compose_message(
        self,
        purpose: str,
        recipient: str,
        context: Optional[str] = None
    ) -> str:
        """
        Compose a message for a specific purpose (one-shot, no tools).
        """
        prompt = f"""Compose a WhatsApp message with the following details:

Purpose: {purpose}
Recipient: {recipient}
{f'Context: {context}' if context else ''}

The message should be:
- Appropriate for WhatsApp (casual but professional if needed)
- Concise and clear
- Friendly in tone
- Directly address the purpose

Just provide the message text, nothing else.
"""
        
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.model_no_tools.generate_content_async(prompt)
                return response.text.strip()
            except ResourceExhausted as e:
                retry_delay = self._parse_retry_delay(e) or self.base_retry_delay * (2 ** attempt)
                if attempt < self.max_retries:
                    logger.warning(f"Rate limit on compose (attempt {attempt + 1}). Retrying in {retry_delay:.0f}s...")
                    await asyncio.sleep(retry_delay)
                else:
                    return "⏳ Rate-limited by the API. Please wait a minute and try again."
            except Exception as e:
                logger.error(f"Error composing message: {e}")
                return f"Error composing message: {str(e)}"
    
    def clear_history(self, user_id: str):
        """Clear conversation history for a user"""
        if user_id in self.chat_sessions:
            del self.chat_sessions[user_id]
