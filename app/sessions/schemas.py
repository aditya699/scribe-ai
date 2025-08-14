"""
Author: Aditya Bhatt 

NOTE:
1.utc_now() is a function that returns the current UTC time with timezone information


"""
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional
from enum import Enum
import uuid

def utc_now():
    """
    Returns the current UTC time with timezone information
    """
    return datetime.now(timezone.utc)

class SessionStatus(str, Enum):
    """
    Status of the session
    """
    active = "active"
    closed = "closed"
    archived = "archived"

class SessionCreateRequest(BaseModel):
    """
    Request model for creating a new session , what information doctor will enter upfront
    """
    doctor_id: str = Field(..., min_length=1, description="Doctor's unique identifier")
    patient_whatsapp_number: str = Field(..., min_length=1, description="Patient's WhatsApp number")
    patient_name: str = Field(..., min_length=1, max_length=100, description="Patient's full name")
    
    request_id: Optional[str] = Field(
        default=None,
        description="Idempotency key to ensure same request isn't processed twice"
    )
class SessionDB(BaseModel):
    """Database model with all fields for the session"""
    schema_version: int = Field(default=1, description="Schema version for migration tracking")
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    doctor_id: str
    patient_whatsapp_number: str
    patient_name: str
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    status: SessionStatus = SessionStatus.active
    consultation_summary: Optional[str] = None
    transcription: Optional[str] = None
    follow_up_count: int = 0
    request_id: Optional[str] = Field(
        default=None,
        description="Idempotency key used to deduplicate session creation"
    )

class SessionResponse(BaseModel):
    """
    Response model for the session , when someone wants to get the session details
    """
    session_id: str
    doctor_id: str
    patient_whatsapp_number: str
    patient_name: str
    created_at: datetime
    updated_at: datetime
    status: SessionStatus
    schema_version: int = 1

class SessionCreateResponse(BaseModel):
    """
    Response model for the session creation
    """
    success: bool
    message: str
    session: SessionResponse