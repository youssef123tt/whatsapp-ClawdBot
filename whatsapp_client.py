"""
WhatsApp Client Wrapper
Abstracts WhatsApp communication using whatsapp-web.js
"""

import asyncio
import json
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass
import subprocess
import logging
import uuid

logger = logging.getLogger(__name__)


@dataclass
class Message:
    """WhatsApp message data structure"""
    id: str
    from_number: str
    chat_id: str
    body: str
    timestamp: datetime
    type: str = "text"
    is_group: bool = False
    is_group: bool = False
    author: Optional[str] = None
    from_me: bool = False


@dataclass
class Chat:
    """WhatsApp chat data structure"""
    id: str
    name: str
    is_group: bool
    last_message_time: Optional[datetime] = None
    unread_count: int = 0


@dataclass
class Contact:
    """WhatsApp contact data structure"""
    phone_number: str
    name: str
    is_business: bool = False
    status: str = ""


class WhatsAppClient:
    """
    WhatsApp client using whatsapp-web.js via Node.js bridge
    
    This implementation uses a Node.js subprocess to communicate with
    whatsapp-web.js library. It uses a background reader loop to handle
    both command responses and incoming events.
    """
    
    def __init__(self, session_path: str = "./session"):
        self.session_path = session_path
        self.process = None
        self.ready_event = asyncio.Event()
        self.pending_requests: Dict[str, asyncio.Future] = {}
        self.event_handler: Optional[Callable[[str, Dict[str, Any]], Any]] = None
        
    def set_event_handler(self, handler: Callable[[str, Dict[str, Any]], Any]):
        """Set handler for incoming events (like messages)"""
        self.event_handler = handler

    async def initialize(self):
        """Initialize WhatsApp client"""
        logger.info("Initializing WhatsApp client...")
        
        # Start Node.js bridge process
        self.process = await asyncio.create_subprocess_exec(
            'node',
            'whatsapp_bridge.js',
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Start reader tasks
        asyncio.create_task(self._read_stdout())
        asyncio.create_task(self._read_stderr())
        
        # Wait for ready signal
        logger.info("Waiting for WhatsApp bridge to be ready...")
        await self.ready_event.wait()
        logger.info("WhatsApp client ready!")

    async def _read_stdout(self):
        """Read stdout from subprocess and handle JSON messages"""
        while True:
            line = await self.process.stdout.readline()
            if not line:
                break
                
            line_str = line.decode().strip()
            if not line_str:
                continue

            # Check for READY signal
            if "READY" in line_str:
                self.ready_event.set()
                continue
                
            try:
                data = json.loads(line_str)
                
                # Check if it's a response to a request
                if "request_id" in data:
                    request_id = data["request_id"]
                    if request_id in self.pending_requests:
                        future = self.pending_requests.pop(request_id)
                        if not future.done():
                            if data.get("success"):
                                future.set_result(data.get("data"))
                            else:
                                # Log full error response from bridge
                                logger.error(f"Bridge returned error response: {json.dumps(data, indent=2)}")
                                error_msg = data.get("error", "Unknown error")
                                # Try to get more details from error_obj if available
                                if "error_obj" in data:
                                    logger.error(f"Bridge error_obj: {data.get('error_obj')}")
                                future.set_exception(Exception(error_msg))
                
                # Check if it's an event
                elif "event" in data:
                    if self.event_handler:
                        asyncio.create_task(self.event_handler(data["event"], data.get("data", {})))
                
                else:
                    # Just log unknown JSON
                    logger.debug(f"Received unknown JSON: {line_str}")
                    
            except json.JSONDecodeError:
                # Not JSON, properly log or print (e.g. QR code text representation might end up here?)
                # But mostly QR code is handled by qrcode-terminal which writes to stdout/stderr.
                # If it's the QR code, we want to see it.
                print(line_str) # Ensure user sees it
            except Exception as e:
                logger.error(f"Error processing stdout line: {e}")

    async def _read_stderr(self):
        """Read stderr from subprocess and log it"""
        while True:
            line = await self.process.stderr.readline()
            if not line:
                break
            # Print stderr directly to console for the user to see (QR codes etc)
            print(f"[Bridge Log]: {line.decode().strip()}")

    async def _send_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Send command to Node.js bridge"""
        request_id = str(uuid.uuid4())
        request = {
            "request_id": request_id,
            "command": command,
            "params": params
        }
        
        # Create future for response
        future = asyncio.get_event_loop().create_future()
        self.pending_requests[request_id] = future
        
        try:
            request_json = json.dumps(request) + "\n"
            self.process.stdin.write(request_json.encode())
            await self.process.stdin.drain()
            
            # Wait for response with timeout
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
            
        except asyncio.TimeoutError:
            if request_id in self.pending_requests:
                del self.pending_requests[request_id]
            raise Exception(f"Command {command} timed out")
        except Exception as e:
            if request_id in self.pending_requests:
                del self.pending_requests[request_id]
            # Log full error details
            logger.error(f"Command {command} failed: {e}")
            logger.error(f"Full error: {repr(e)}")
            raise e
    
    async def get_messages(
        self,
        chat_id: str,
        limit: int = 50,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> List[Message]:
        """Retrieve messages from a chat"""
        params = {
            "chat_id": chat_id,
            "limit": limit
        }
        
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
            
        result = await self._send_command("get_messages", params)
        
        messages = []
        for msg_data in result.get("messages", []):
            messages.append(Message(
                id=msg_data["id"],
                from_number=msg_data["from"],
                chat_id=msg_data["chat_id"],
                body=msg_data["body"],
                timestamp=datetime.fromisoformat(msg_data["timestamp"].replace("Z", "+00:00")),
                type=msg_data.get("type", "text"),
                is_group=msg_data.get("is_group", False),
                author=msg_data.get("author"),
                from_me=msg_data.get("fromMe", False)
            ))
        
        return messages
    
    async def send_message(
        self,
        phone_number: str,
        message: str,
        reply_to: Optional[str] = None
    ) -> Message:
        """Send a message"""
        params = {
            "phone_number": phone_number,
            "message": message
        }
        
        if reply_to:
            params["reply_to"] = reply_to
            
        result = await self._send_command("send_message", params)
        
        return Message(
            id=result["id"],
            from_number=result["from"],
            chat_id=result["chat_id"],
            body=message,
            timestamp=datetime.now(),
            type="text"
        )
    
    async def get_chats(self, limit: int = 20) -> List[Chat]:
        """Get list of chats"""
        params = {"limit": limit}
        result = await self._send_command("get_chats", params)
        
        chats = []
        for chat_data in result.get("chats", []):
            chats.append(Chat(
                id=chat_data["id"],
                name=chat_data["name"],
                is_group=chat_data["is_group"],
                last_message_time=datetime.fromisoformat(chat_data["last_message_time"].replace("Z", "+00:00")) if chat_data.get("last_message_time") else None,
                unread_count=chat_data.get("unread_count", 0)
            ))
        
        return chats
    
    async def search_messages(
        self,
        query: str,
        chat_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Message]:
        """Search for messages"""
        params = {
            "query": query,
            "limit": limit
        }
        
        if chat_id:
            params["chat_id"] = chat_id
            
        result = await self._send_command("search_messages", params)
        
        messages = []
        for msg_data in result.get("messages", []):
            messages.append(Message(
                id=msg_data["id"],
                from_number=msg_data["from"],
                chat_id=msg_data["chat_id"],
                body=msg_data["body"],
                timestamp=datetime.fromisoformat(msg_data["timestamp"]),
                type=msg_data.get("type", "text")
            ))
        
        return messages
    
    async def get_contact(self, phone_number: str) -> Contact:
        """Get contact information"""
        params = {"phone_number": phone_number}
        result = await self._send_command("get_contact", params)
        
        return Contact(
            phone_number=phone_number,
            name=result.get("name", "Unknown"),
            is_business=result.get("is_business", False),
            status=result.get("status", "")
        )
    
    async def close(self):
        """Close WhatsApp client"""
        if self.process:
            self.process.terminate()
            await self.process.wait()
            logger.info("WhatsApp client closed")
