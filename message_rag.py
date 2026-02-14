"""
RAG System for WhatsApp Messages
Stores and retrieves message context using embeddings
"""

import os
from typing import List, Dict, Any, Optional
from datetime import datetime
import chromadb
from chromadb.config import Settings
import logging

logger = logging.getLogger(__name__)


class MessageRAG:
    """
    Retrieval-Augmented Generation system for WhatsApp messages
    Uses ChromaDB for vector storage
    """
    
    def __init__(
        self,
        collection_name: str = "whatsapp_messages",
        persist_directory: str = "./chroma_db",
        embedding_model: str = "voyage-2"
    ):
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        
        # Initialize ChromaDB
        self.client = chromadb.Client(Settings(
            persist_directory=persist_directory,
            anonymized_telemetry=False
        ))
        
        # Get or create collection
        try:
            self.collection = self.client.get_collection(collection_name)
            logger.info(f"Loaded existing collection: {collection_name}")
        except:
            self.collection = self.client.create_collection(
                name=collection_name,
                metadata={"description": "WhatsApp message embeddings"}
            )
            logger.info(f"Created new collection: {collection_name}")
    
    async def index_message(
        self,
        message_id: str,
        content: str,
        sender: str,
        chat_id: str,
        timestamp: datetime,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Index a single message
        
        Args:
            message_id: Unique message identifier
            content: Message text
            sender: Sender phone number or name
            chat_id: Chat identifier
            timestamp: Message timestamp
            metadata: Additional metadata
        """
        try:
            # Prepare metadata
            meta = {
                "sender": sender,
                "chat_id": chat_id,
                "timestamp": timestamp.isoformat(),
                "date": timestamp.date().isoformat(),
                **(metadata or {})
            }
            
            # Add to collection
            self.collection.add(
                ids=[message_id],
                documents=[content],
                metadatas=[meta]
            )
            
            logger.debug(f"Indexed message: {message_id}")
            
        except Exception as e:
            logger.error(f"Error indexing message {message_id}: {e}")
    
    async def index_messages_batch(
        self,
        messages: List[Dict[str, Any]]
    ):
        """
        Index multiple messages at once
        
        Args:
            messages: List of message dictionaries with fields:
                - id, content, sender, chat_id, timestamp
        """
        try:
            ids = []
            documents = []
            metadatas = []
            
            for msg in messages:
                if not msg.get("content"):
                    continue
                    
                ids.append(msg["id"])
                documents.append(msg["content"])
                
                timestamp = msg.get("timestamp")
                if isinstance(timestamp, str):
                    timestamp = datetime.fromisoformat(timestamp)
                
                metadatas.append({
                    "sender": msg.get("sender", "unknown"),
                    "chat_id": msg.get("chat_id", "unknown"),
                    "timestamp": timestamp.isoformat() if timestamp else "",
                    "date": timestamp.date().isoformat() if timestamp else "",
                })
            
            if ids:
                self.collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas
                )
                logger.info(f"Indexed {len(ids)} messages in batch")
            
        except Exception as e:
            logger.error(f"Error in batch indexing: {e}")
    
    async def search_messages(
        self,
        query: str,
        n_results: int = 5,
        chat_id: Optional[str] = None,
        sender: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant messages
        
        Args:
            query: Search query
            n_results: Number of results to return
            chat_id: Filter by chat ID
            sender: Filter by sender
            start_date: Filter by start date
            end_date: Filter by end date
        
        Returns:
            List of relevant messages with metadata
        """
        try:
            # Build where clause for filtering
            where_clause = {}
            
            if chat_id:
                where_clause["chat_id"] = chat_id
            
            if sender:
                where_clause["sender"] = sender
            
            # Date filtering is more complex, handled post-retrieval
            
            # Query the collection
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results * 2 if (start_date or end_date) else n_results,
                where=where_clause if where_clause else None
            )
            
            # Format results
            messages = []
            for i, doc_id in enumerate(results["ids"][0]):
                message = {
                    "id": doc_id,
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i],
                    "distance": results["distances"][0][i]
                }
                
                # Apply date filtering
                if start_date or end_date:
                    msg_timestamp = datetime.fromisoformat(
                        message["metadata"]["timestamp"]
                    )
                    
                    if start_date and msg_timestamp < start_date:
                        continue
                    if end_date and msg_timestamp > end_date:
                        continue
                
                messages.append(message)
                
                if len(messages) >= n_results:
                    break
            
            return messages
            
        except Exception as e:
            logger.error(f"Error searching messages: {e}")
            return []
    
    async def get_context_for_query(
        self,
        query: str,
        chat_id: Optional[str] = None,
        n_results: int = 5
    ) -> Dict[str, Any]:
        """
        Get formatted context for a query to pass to Claude
        
        Args:
            query: User query
            chat_id: Optional chat ID to limit search
            n_results: Number of results
        
        Returns:
            Dictionary with relevant messages and metadata
        """
        messages = await self.search_messages(
            query=query,
            n_results=n_results,
            chat_id=chat_id
        )
        
        # Format for Claude
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                "content": msg["content"],
                "sender": msg["metadata"]["sender"],
                "timestamp": msg["metadata"]["timestamp"],
                "relevance_score": 1 - msg["distance"]  # Convert distance to similarity
            })
        
        return {
            "query": query,
            "relevant_messages": formatted_messages,
            "message_count": len(formatted_messages)
        }
    
    async def delete_chat_messages(self, chat_id: str):
        """Delete all messages from a specific chat"""
        try:
            # ChromaDB doesn't support delete by metadata directly
            # We need to get IDs first then delete
            results = self.collection.get(
                where={"chat_id": chat_id}
            )
            
            if results["ids"]:
                self.collection.delete(ids=results["ids"])
                logger.info(f"Deleted {len(results['ids'])} messages from {chat_id}")
        
        except Exception as e:
            logger.error(f"Error deleting messages: {e}")
    
    async def delete_old_messages(self, days: int = 90):
        """
        Delete messages older than specified days
        
        Args:
            days: Number of days to keep
        """
        try:
            cutoff_date = datetime.now().date() - timedelta(days=days)
            
            # Get all messages
            all_messages = self.collection.get()
            
            # Find old message IDs
            old_ids = []
            for i, metadata in enumerate(all_messages["metadatas"]):
                msg_date = datetime.fromisoformat(metadata["date"]).date()
                if msg_date < cutoff_date:
                    old_ids.append(all_messages["ids"][i])
            
            if old_ids:
                self.collection.delete(ids=old_ids)
                logger.info(f"Deleted {len(old_ids)} old messages")
        
        except Exception as e:
            logger.error(f"Error deleting old messages: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about the indexed messages"""
        try:
            count = self.collection.count()
            
            return {
                "total_messages": count,
                "collection_name": self.collection_name
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {"error": str(e)}


# Alternative: Using Voyage AI embeddings directly
class VoyageMessageRAG(MessageRAG):
    """
    RAG implementation using Voyage AI embeddings
    Requires VOYAGE_API_KEY environment variable
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Initialize Voyage client
        try:
            import voyageai
            self.voyage_client = voyageai.Client(
                api_key=os.getenv("VOYAGE_API_KEY")
            )
            self.use_voyage = True
        except ImportError:
            logger.warning("Voyage AI not installed, falling back to ChromaDB embeddings")
            self.use_voyage = False
    
    async def _get_embedding(self, text: str) -> List[float]:
        """Get embedding from Voyage AI"""
        if self.use_voyage:
            result = self.voyage_client.embed(
                [text],
                model=self.embedding_model
            )
            return result.embeddings[0]
        return None
