"""
RAG module schemas - Step 1: Incoming message tracking
Author: Aditya Bhatt
"""
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum
import uuid

def utc_now() -> datetime:
    """Returns current UTC time with timezone info"""
    return datetime.now(timezone.utc)

class MessageProcessingStatus(str, Enum):
    """Status of incoming message processing"""
    received = "received"           # Message received, not yet processed
    processing = "processing"       # Currently generating RAG response
    completed = "completed"         # Response generated and sent successfully
    failed = "failed"              # Failed to generate or send response

class IncomingWhatsAppMessage(BaseModel):
    """Incoming WhatsApp message from patient for RAG consultation"""
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    twilio_message_sid: str = Field(..., description="Twilio message SID for tracking")
    patient_whatsapp_number: str = Field(..., description="Patient's WhatsApp number (with + prefix)")
    message_body: str = Field(..., description="Patient's question/message text")
    
    # Processing status
    status: MessageProcessingStatus = MessageProcessingStatus.received
    received_at: datetime = Field(default_factory=utc_now)
    processed_at: Optional[datetime] = None
    
    # Patient lookup results (filled after lookup)
    patient_found: Optional[bool] = None
    patient_name: Optional[str] = None
    session_ids: Optional[List[str]] = None
    total_sessions: Optional[int] = None
    
    # AI response data (NEW)
    ai_response: Optional[str] = Field(default=None, description="Generated AI response text")
    response_generated_at: Optional[datetime] = Field(default=None, description="When AI response was generated")
    
    # Error handling
    error_message: Optional[str] = None