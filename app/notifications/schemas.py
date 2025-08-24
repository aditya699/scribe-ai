"""
Notification schemas for WhatsApp messaging
Author: Aditya Bhatt
"""
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional
from enum import Enum
import uuid

def utc_now() -> datetime:
    """
    Returns the current UTC time with timezone information.
    
    Returns:
        datetime: Current UTC timestamp with timezone info
    
    Raises:
        OSError: If system clock is unavailable
    """
    return datetime.now(timezone.utc)

class NotificationStatus(str, Enum):
    """Status of WhatsApp notification delivery"""
    pending = "pending"           # Message created but not yet sent to Twilio
    queued = "queued"            # Message queued in Twilio, waiting for delivery
    sent = "sent"                # Message sent to WhatsApp servers
    delivered = "delivered"       # Message delivered to recipient device
    read = "read"                # Message read by recipient (if read receipts enabled)
    failed = "failed"            # Message failed to deliver
    undelivered = "undelivered"  # Message could not be delivered
    
class WhatsAppNotification(BaseModel):
    """WhatsApp notification record"""
    notification_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(..., description="Patient session this notification is for")
    patient_whatsapp_number: str = Field(..., description="Patient's WhatsApp number")
    patient_name: str = Field(..., description="Patient's name for personalization")
    
    # Message details
    message_content: str = Field(..., description="WhatsApp message text")
    notification_type: str = Field(default="transcription_complete", description="Type of notification")
    
    # Delivery tracking
    status: NotificationStatus = NotificationStatus.pending
    sent_at: Optional[datetime] = Field(default=None, description="When message was sent")
    delivered_at: Optional[datetime] = Field(default=None, description="When message was delivered")
    failed_at: Optional[datetime] = Field(default=None, description="When message failed")
    
    # Twilio response data
    twilio_message_sid: Optional[str] = Field(default=None, description="Twilio message SID for tracking")
    error_message: Optional[str] = Field(default=None, description="Error details if delivery failed")
    
    # Timestamps
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)