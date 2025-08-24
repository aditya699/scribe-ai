from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    # Existing settings
    MONGO_URI: str
    OPENAI_API_KEY: str
    BLOB_STORAGE_ACCOUNT_KEY: str
    TWILIO_ACCOUNT_SID: str
    TWILIO_AUTH_TOKEN: str
    TWILIO_WHATSAPP_FROM: str
    WEBHOOK_BASE_URL: str

    model_config = SettingsConfigDict(env_file=Path(__file__).parent.parent.parent / ".env")

settings = Settings()