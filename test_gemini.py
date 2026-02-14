import asyncio
import os
import logging
from gemini_agent import GeminiAgent

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    print("Testing Gemini Agent...")
    
    # Check for API key
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not found. Please set it to run the test.")
        return

    try:
        agent = GeminiAgent()
        print("Gemini Agent initialized.")
        
        user_id = "test_user_123"
        message = "Hello, who are you and what can you do?"
        
        print(f"\nSending message: {message}")
        response = await agent.process_message(message, user_id)
        
        print(f"\nResponse:\n{response}")
        
    except Exception as e:
        print(f"Test failed with error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
