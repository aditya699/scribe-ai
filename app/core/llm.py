# core/llm.py
from openai import AsyncOpenAI
from .config import settings
from app.database.mongo import log_error

# Initialize client (note: This will be initialized once and reused)
client: AsyncOpenAI | None = None

async def get_openai_client():
    """
    Get or initialize the OpenAI client.
    Returns the existing client if already initialized, otherwise creates a new one.
    """
    global client
    try:
        if client is None:
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return client
    
    except Exception as e:
        await log_error(e, "core/llm.py", "get_openai_client")
        raise e