'''
NOTE:

1.This is a client for mongodb, which needs to be initialized once and reused.
2.Using PyMongo's native async client for MongoDB operations.
Refer:
https://pymongo.readthedocs.io/en/4.13.0/async-tutorial.html

'''
# db/mongo.py

from pymongo import AsyncMongoClient
from app.core.config import settings
from datetime import datetime
import traceback

#Initialize client and db (note:These will be initialized once and reused in all functions or routes)
client: AsyncMongoClient | None = None
db = None


async def get_client():
    """
    Get or initialize the MongoDB client.
    """
    global client
    if client is None:
        try:
            client = AsyncMongoClient(
                settings.MONGO_URI,
                serverSelectionTimeoutMS=5000,
                connectTimeoutMS=5000,
                maxPoolSize=50,
                retryWrites=True
            )
            # Test the connection immediately
            await client.admin.command('ping')
            print("MongoDB client initialized and tested")
        except Exception as e:
            print(f"Failed to initialize MongoDB client: {str(e)}")
            client = None  # Reset on failure
            raise
    return client

async def get_db():
    """Get the database instance."""
    global db
    if db is None:
        client = await get_client()
        db = client["ScribeAI"]
    return db

async def log_error(error: Exception, location: str, additional_info: dict = None):
    """
    Log an error to the MongoDB database.
    
    Args:
        error: The exception that occurred
        location: Where the error occurred (e.g., function name, route)
        additional_info: Any additional information to log (optional)
    """
    try:
        db = await get_db()
        error_collection = db["error_logs"]
        
        error_doc = {
            "timestamp": datetime.utcnow(),
            "error_type": type(error).__name__,
            "error_message": str(error),
            "location": location,
            "traceback": traceback.format_exc(),
            "additional_info": additional_info or {}
        }
        
        await error_collection.insert_one(error_doc)
    except Exception as e:
        # If error logging fails, print to console as fallback
        print(f"Failed to log error to MongoDB: {str(e)}")
        print(f"Original error: {str(error)}")
        print(f"Location: {location}")
        if additional_info:
            print(f"Additional info: {additional_info}")

    
