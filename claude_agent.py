"""
Claude Agent Orchestrator
Main agent that processes WhatsApp messages and commands
"""

import os
import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from anthropic import Anthropic
import logging

logger = logging.getLogger(__name__)


class ClaudeAgent:
    """
    Main agent that orchestrates WhatsApp interactions using Claude
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.model = "claude-sonnet-4-20250514"
        self.max_tokens = 4000
        self.conversation_history: Dict[str, List[Dict]] = {}
        
    def _get_system_prompt(self) -> str:
        """Get the system prompt for Claude"""
        return """You are a helpful WhatsApp assistant that helps users manage their messages.

You have access to the following tools through MCP:
1. get_messages - Retrieve messages from a chat
2. send_message - Send a message to a contact
3. schedule_message - Schedule a message for later
4. get_chat_list - Get list of all chats
5. search_messages - Search for specific messages
6. get_contact_info - Get contact information

Your capabilities:
1. **Summarization**: Summarize messages from specific contacts or groups
   - Example: "Summarize messages from John today"
   - Example: "What did the team discuss in the group chat this week?"

2. **Message Sending**: Send messages to contacts
   - Example: "Send 'Hello' to +1234567890"
   - Example: "Reply to Sarah with 'Thanks!'"

3. **Scheduling**: Schedule messages for specific times
   - Example: "Send 'Good morning' to +9876543210 tomorrow at 8 AM"
   - Example: "Remind me to call John every day at 5 PM"

4. **Search & Retrieval**: Find specific messages or information
   - Example: "Search for messages about 'project deadline'"
   - Example: "What did Sarah say about the meeting?"

Guidelines:
- Always parse dates and times carefully
- Convert phone numbers to proper format
- Provide clear, concise summaries
- Ask for clarification when needed
- Be helpful and proactive
- Use RAG context when available for better responses

When summarizing messages:
- Group by topic or sender
- Highlight important information
- Include timestamps for context
- Keep summaries concise but informative

When scheduling:
- Confirm the scheduled time with the user
- Handle timezone conversions
- Support recurring messages
"""
    
    async def process_message(
        self,
        user_message: str,
        user_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Process a user message and generate a response
        
        Args:
            user_message: The message from the user
            user_id: Unique identifier for the user
            context: Additional context (e.g., from RAG)
        
        Returns:
            Response message
        """
        # Initialize conversation history for this user
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = []
        
        # Build messages for Claude
        messages = self.conversation_history[user_id].copy()
        
        # Add context from RAG if available
        if context and context.get("relevant_messages"):
            context_text = self._format_context(context["relevant_messages"])
            user_message = f"{user_message}\n\nRelevant context from past messages:\n{context_text}"
        
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        try:
            # Call Claude with MCP tools
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self._get_system_prompt(),
                messages=messages
            )
            
            # Extract response
            assistant_message = ""
            tool_results = []
            
            for block in response.content:
                if block.type == "text":
                    assistant_message += block.text
                elif block.type == "tool_use":
                    # Handle tool use
                    tool_result = await self._execute_tool(block)
                    tool_results.append(tool_result)
            
            # If tools were used, get final response
            if tool_results:
                messages.append({
                    "role": "assistant",
                    "content": response.content
                })
                
                messages.append({
                    "role": "user",
                    "content": tool_results
                })
                
                final_response = self.client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    system=self._get_system_prompt(),
                    messages=messages
                )
                
                assistant_message = "".join(
                    block.text for block in final_response.content 
                    if block.type == "text"
                )
            
            # Update conversation history
            self.conversation_history[user_id].append({
                "role": "user",
                "content": user_message
            })
            self.conversation_history[user_id].append({
                "role": "assistant",
                "content": assistant_message
            })
            
            # Keep only last 10 exchanges
            if len(self.conversation_history[user_id]) > 20:
                self.conversation_history[user_id] = self.conversation_history[user_id][-20:]
            
            return assistant_message
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return f"I encountered an error: {str(e)}"
    
    async def _execute_tool(self, tool_use_block) -> Dict[str, Any]:
        """Execute an MCP tool"""
        # This would be handled by the MCP server
        # For now, return a placeholder
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_block.id,
            "content": "Tool execution handled by MCP server"
        }
    
    def _format_context(self, messages: List[Dict]) -> str:
        """Format RAG context for inclusion in prompt"""
        formatted = []
        for msg in messages[:5]:  # Limit to top 5 relevant messages
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
        Generate a summary of messages
        
        Args:
            messages: List of message dictionaries
            summary_type: Type of summary (general, topic, timeline)
        
        Returns:
            Summary text
        """
        if not messages:
            return "No messages to summarize."
        
        # Format messages for Claude
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
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text
    
    async def compose_message(
        self,
        purpose: str,
        recipient: str,
        context: Optional[str] = None
    ) -> str:
        """
        Compose a message for a specific purpose
        
        Args:
            purpose: Purpose of the message
            recipient: Recipient name or number
            context: Additional context
        
        Returns:
            Composed message
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
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        return response.content[0].text.strip()
    
    def clear_history(self, user_id: str):
        """Clear conversation history for a user"""
        if user_id in self.conversation_history:
            del self.conversation_history[user_id]
