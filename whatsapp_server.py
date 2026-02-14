"""
WhatsApp MCP Server
Provides WhatsApp functionality as MCP tools for Claude
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from mcp.server import Server
from mcp.types import Tool, TextContent
import logging

# Import WhatsApp client (you'll need to choose: whatsapp-web.js wrapper or Baileys)
# This is a placeholder - actual implementation depends on your choice
from whatsapp_client import WhatsAppClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class WhatsAppMCPServer:
    def __init__(self, session_path: str = "./session"):
        self.server = Server("whatsapp-mcp-server")
        self.wa_client = WhatsAppClient(session_path)
        self.setup_tools()
        
    def setup_tools(self):
        """Register all WhatsApp tools"""
        
        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            return [
                Tool(
                    name="get_messages",
                    description="Retrieve messages from a WhatsApp chat or group",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "chat_id": {
                                "type": "string",
                                "description": "Phone number or group ID"
                            },
                            "limit": {
                                "type": "number",
                                "description": "Maximum number of messages to retrieve",
                                "default": 50
                            },
                            "start_date": {
                                "type": "string",
                                "description": "ISO format start date (optional)"
                            },
                            "end_date": {
                                "type": "string",
                                "description": "ISO format end date (optional)"
                            }
                        },
                        "required": ["chat_id"]
                    }
                ),
                Tool(
                    name="send_message",
                    description="Send a message to a WhatsApp contact or group",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "phone_number": {
                                "type": "string",
                                "description": "Recipient phone number with country code"
                            },
                            "message": {
                                "type": "string",
                                "description": "Message text to send"
                            },
                            "reply_to": {
                                "type": "string",
                                "description": "Message ID to reply to (optional)"
                            }
                        },
                        "required": ["phone_number", "message"]
                    }
                ),
                Tool(
                    name="schedule_message",
                    description="Schedule a message to be sent at a specific time",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "phone_number": {
                                "type": "string",
                                "description": "Recipient phone number"
                            },
                            "message": {
                                "type": "string",
                                "description": "Message to send"
                            },
                            "schedule_time": {
                                "type": "string",
                                "description": "ISO datetime string for when to send"
                            },
                            "recurring": {
                                "type": "boolean",
                                "description": "Whether this is a recurring message",
                                "default": False
                            },
                            "recurrence_pattern": {
                                "type": "string",
                                "description": "Recurrence pattern: daily, weekly, monthly",
                                "enum": ["daily", "weekly", "monthly"]
                            }
                        },
                        "required": ["phone_number", "message", "schedule_time"]
                    }
                ),
                Tool(
                    name="get_chat_list",
                    description="Get list of all chats and groups",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "number",
                                "description": "Maximum number of chats to return",
                                "default": 20
                            }
                        }
                    }
                ),
                Tool(
                    name="search_messages",
                    description="Search for messages containing specific text",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query"
                            },
                            "chat_id": {
                                "type": "string",
                                "description": "Limit search to specific chat (optional)"
                            },
                            "limit": {
                                "type": "number",
                                "description": "Maximum results",
                                "default": 10
                            }
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="get_contact_info",
                    description="Get information about a contact",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "phone_number": {
                                "type": "string",
                                "description": "Contact phone number"
                            }
                        },
                        "required": ["phone_number"]
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Handle tool calls"""
            try:
                if name == "get_messages":
                    result = await self.get_messages(**arguments)
                elif name == "send_message":
                    result = await self.send_message(**arguments)
                elif name == "schedule_message":
                    result = await self.schedule_message(**arguments)
                elif name == "get_chat_list":
                    result = await self.get_chat_list(**arguments)
                elif name == "search_messages":
                    result = await self.search_messages(**arguments)
                elif name == "get_contact_info":
                    result = await self.get_contact_info(**arguments)
                else:
                    raise ValueError(f"Unknown tool: {name}")
                
                return [TextContent(
                    type="text",
                    text=json.dumps(result, indent=2)
                )]
            except Exception as e:
                logger.error(f"Error in {name}: {str(e)}")
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": str(e)})
                )]
    
    async def get_messages(
        self, 
        chat_id: str, 
        limit: int = 50,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve messages from a chat"""
        try:
            messages = await self.wa_client.get_messages(
                chat_id=chat_id,
                limit=limit,
                start_date=start_date,
                end_date=end_date
            )
            
            return {
                "success": True,
                "chat_id": chat_id,
                "message_count": len(messages),
                "messages": [
                    {
                        "id": msg.id,
                        "from": msg.from_number,
                        "body": msg.body,
                        "timestamp": msg.timestamp.isoformat(),
                        "type": msg.type
                    }
                    for msg in messages
                ]
            }
        except Exception as e:
            logger.error(f"Error retrieving messages: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def send_message(
        self, 
        phone_number: str, 
        message: str,
        reply_to: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send a message"""
        try:
            result = await self.wa_client.send_message(
                phone_number=phone_number,
                message=message,
                reply_to=reply_to
            )
            
            return {
                "success": True,
                "message_id": result.id,
                "recipient": phone_number,
                "sent_at": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error sending message: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def schedule_message(
        self,
        phone_number: str,
        message: str,
        schedule_time: str,
        recurring: bool = False,
        recurrence_pattern: Optional[str] = None
    ) -> Dict[str, Any]:
        """Schedule a message for later"""
        from task_scheduler import TaskScheduler
        
        try:
            scheduler = TaskScheduler()
            task_id = await scheduler.schedule_message(
                phone_number=phone_number,
                message=message,
                schedule_time=datetime.fromisoformat(schedule_time),
                recurring=recurring,
                recurrence_pattern=recurrence_pattern
            )
            
            return {
                "success": True,
                "task_id": task_id,
                "scheduled_for": schedule_time,
                "recurring": recurring
            }
        except Exception as e:
            logger.error(f"Error scheduling message: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_chat_list(self, limit: int = 20) -> Dict[str, Any]:
        """Get list of chats"""
        try:
            chats = await self.wa_client.get_chats(limit=limit)
            
            return {
                "success": True,
                "chat_count": len(chats),
                "chats": [
                    {
                        "id": chat.id,
                        "name": chat.name,
                        "is_group": chat.is_group,
                        "last_message_time": chat.last_message_time.isoformat() if chat.last_message_time else None,
                        "unread_count": chat.unread_count
                    }
                    for chat in chats
                ]
            }
        except Exception as e:
            logger.error(f"Error getting chat list: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def search_messages(
        self, 
        query: str, 
        chat_id: Optional[str] = None,
        limit: int = 10
    ) -> Dict[str, Any]:
        """Search messages"""
        try:
            messages = await self.wa_client.search_messages(
                query=query,
                chat_id=chat_id,
                limit=limit
            )
            
            return {
                "success": True,
                "query": query,
                "result_count": len(messages),
                "messages": [
                    {
                        "id": msg.id,
                        "chat_id": msg.chat_id,
                        "from": msg.from_number,
                        "body": msg.body,
                        "timestamp": msg.timestamp.isoformat()
                    }
                    for msg in messages
                ]
            }
        except Exception as e:
            logger.error(f"Error searching messages: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def get_contact_info(self, phone_number: str) -> Dict[str, Any]:
        """Get contact information"""
        try:
            contact = await self.wa_client.get_contact(phone_number)
            
            return {
                "success": True,
                "phone_number": phone_number,
                "name": contact.name,
                "is_business": contact.is_business,
                "status": contact.status
            }
        except Exception as e:
            logger.error(f"Error getting contact info: {e}")
            return {
                "success": False,
                "error": str(e)
            }
    
    async def initialize(self):
        """Initialize WhatsApp client"""
        await self.wa_client.initialize()
        logger.info("WhatsApp MCP Server initialized")
    
    async def run(self):
        """Run the MCP server"""
        from mcp.server.stdio import stdio_server
        
        await self.initialize()
        
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


async def main():
    server = WhatsAppMCPServer()
    await server.run()


if __name__ == "__main__":
    asyncio.run(main())
