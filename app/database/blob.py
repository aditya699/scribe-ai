# db/blob.py
from azure.storage.blob.aio import BlobServiceClient
from app.database.mongo import log_error
from app.core.config import settings

# Global client (initialized once, reused everywhere)
blob_client: BlobServiceClient | None = None

async def get_blob_client():
    """
    Get or initialize the Azure Blob Storage client.
    """
    global blob_client
    if blob_client is None:
        try:
            blob_client = BlobServiceClient.from_connection_string(
                settings.BLOB_STORAGE_ACCOUNT_KEY
            )
            
            # Test the connection by listing containers (lightweight operation)
            containers = blob_client.list_containers()
            async for container in containers:
                # Just test that we can iterate - we don't need to do anything with the container
                break  # Exit after first container to keep it lightweight
            
            print("Blob Storage client initialized and tested")
        except Exception as e:
            print(f"Failed to initialize Blob Storage client: {str(e)}")
            blob_client = None  # Reset on failure
            
            # Log the error to MongoDB (if available)
            try:
                await log_error(
                    error=e,
                    location="get_blob_client",
                    additional_info={"action": "initialize_blob_client"}
                )
            except:
                pass  # MongoDB might not be available during startup
            
            raise
    return blob_client