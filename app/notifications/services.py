"""
WhatsApp notification services using Twilio API
Author: Aditya Bhatt
"""
from typing import Optional, Dict, Any
from twilio.rest import Client
from twilio.base.exceptions import TwilioException
import asyncio
from app.database.mongo import log_error, get_db
from .schemas import WhatsAppNotification, NotificationStatus
from datetime import datetime, timezone
from app.core.config import settings


class TwilioWhatsAppService:
    """Service for sending WhatsApp messages through Twilio API"""
    
    def __init__(self, webhook_base_url: Optional[str] = None) -> None:
        """
        Initialize Twilio WhatsApp service with environment credentials.
        
        Args:
            webhook_base_url: Base URL for status callbacks (e.g., https://abc123.ngrok.io)
                            If None, will try to get from WEBHOOK_BASE_URL env var
        
        Raises:
            ValueError: If required environment variables are missing
        """
        self.account_sid: str = settings.TWILIO_ACCOUNT_SID
        self.auth_token: str = settings.TWILIO_AUTH_TOKEN
        self.from_number: str = settings.TWILIO_WHATSAPP_FROM
        self.webhook_base_url: Optional[str] = webhook_base_url or settings.WEBHOOK_BASE_URL
        
        if not all([self.account_sid, self.auth_token, self.from_number]):
            raise ValueError("Missing required Twilio environment variables")
    
    def _normalize_whatsapp_number(self, number: str) -> str:
        """Ensure WhatsApp number has E.164 with +91 default if missing country code."""
        cleaned = number.strip().replace(" ", "")
        if cleaned.startswith("+"):
            return cleaned
        # If number begins with 0, drop leading zeros
        while cleaned.startswith("0"):
            cleaned = cleaned[1:]
        # Default to India country code
        return f"+91{cleaned}"
    
    def _create_transcription_complete_message(self, patient_name: str) -> str:
        """
        Create personalized message for transcription completion.
        
        Args:
            patient_name: Patient's name for personalization
            
        Returns:
            str: Formatted WhatsApp message content
        """
        return (
            f"Hello {patient_name}, hope you get well soon! 🏥 "
            f"Your consultation transcription is complete. "
            f"If you have any doubts regarding what the doctor said "
            f"and want to revisit anything, ping your message back to us."
        )
    
    async def send_transcription_complete_notification(
        self, 
        session_id: str,
        patient_whatsapp_number: str,
        patient_name: str
    ) -> WhatsAppNotification:
        """
        Send transcription complete notification to patient via WhatsApp.
        
        Args:
            session_id: Patient session ID
            patient_whatsapp_number: Patient's WhatsApp number
            patient_name: Patient's name for personalization
            
        Returns:
            WhatsAppNotification: Notification record with delivery status
            
        Raises:
            TwilioException: If Twilio API call fails
            Exception: For database or other errors
        """
        # Create notification record
        message_content = self._create_transcription_complete_message(patient_name)
        
        notification = WhatsAppNotification(
            session_id=session_id,
            patient_whatsapp_number=patient_whatsapp_number,
            patient_name=patient_name,
            message_content=message_content,
            status=NotificationStatus.pending
        )
        
        try:
            # Build message creation parameters
            normalized_number = self._normalize_whatsapp_number(patient_whatsapp_number)
            message_params = {
                "from_": self.from_number,
                "body": message_content,
                "to": f"whatsapp:{normalized_number}"
            }
            
            # Add status callback URL if webhook base URL is provided
            if self.webhook_base_url:
                message_params["status_callback"] = f"{self.webhook_base_url}/v1/notifications/twilio/whatsapp/status"

            # Run the synchronous Twilio client call in a thread to avoid blocking
            message = await asyncio.to_thread(self._send_message_sync, message_params)
            
            # Update notification with Twilio queue confirmation
            notification.status = NotificationStatus.queued  # Not "sent"!
            notification.sent_at = datetime.now(timezone.utc)  # Time queued to Twilio
            notification.twilio_message_sid = message.sid
            
            # Store notification in database
            await self._store_notification(notification)
            
            return notification
            
        except TwilioException as e:
            # Handle Twilio-specific errors
            notification.status = NotificationStatus.failed
            notification.failed_at = datetime.now(timezone.utc)
            notification.error_message = str(e)
            
            await log_error(
                error=e,
                location="notifications/services.py - send_transcription_complete_notification",
                additional_info={
                    "session_id": session_id,
                    "patient_whatsapp_number": patient_whatsapp_number,
                    "twilio_error": str(e)
                }
            )
            
            # Store failed notification in database
            await self._store_notification(notification)
            raise
            
        except Exception as e:
            # Handle other errors
            notification.status = NotificationStatus.failed
            notification.failed_at = datetime.now(timezone.utc)
            notification.error_message = str(e)
            
            await log_error(
                error=e,
                location="notifications/services.py - send_transcription_complete_notification",
                additional_info={
                    "session_id": session_id,
                    "patient_whatsapp_number": patient_whatsapp_number
                }
            )
            
            # Store failed notification in database
            await self._store_notification(notification)
            raise
    
    def _send_message_sync(self, message_params: Dict[str, Any]):
        """Blocking Twilio call executed in a thread via asyncio.to_thread."""
        client = Client(self.account_sid, self.auth_token)
        return client.messages.create(**message_params)

    async def _store_notification(self, notification: WhatsAppNotification) -> None:
        """
        Store notification record in database.
        
        Args:
            notification: WhatsApp notification to store
            
        Raises:
            Exception: If database storage fails
        """
        try:
            db = await get_db()
            notifications_collection = db["whatsapp_notifications"]
            
            doc = notification.model_dump(exclude_none=True)
            result = await notifications_collection.insert_one(doc)
            
            if not result.inserted_id:
                raise Exception("Failed to store notification in database")
                
        except Exception as e:
            await log_error(
                error=e,
                location="notifications/services.py - _store_notification",
                additional_info={"notification_id": notification.notification_id}
            )
            raise


async def update_notification_status(
    message_sid: str,
    new_status: NotificationStatus,
    error_code: str = "",
    error_message: str = ""
) -> None:
    """
    Update WhatsApp notification status based on Twilio callback.
    
    Args:
        message_sid: Twilio message SID to update
        new_status: New delivery status from Twilio
        error_code: Error code if status indicates failure
        error_message: Error description if status indicates failure
        
    Raises:
        Exception: If database update fails
    """
    try:
        db = await get_db()
        notifications_collection = db["whatsapp_notifications"]
        
        # Build update document
        update_doc: Dict[str, Any] = {
            "status": new_status.value,
            "updated_at": datetime.now(timezone.utc)
        }
        
        # Add timestamp fields based on status
        current_time = datetime.now(timezone.utc)
        
        if new_status == NotificationStatus.sent:
            # Don't override sent_at if already set (from initial queue)
            pass
        elif new_status == NotificationStatus.delivered:
            update_doc["delivered_at"] = current_time
        elif new_status == NotificationStatus.read:
            update_doc["delivered_at"] = current_time  # Ensure delivered_at is set
            update_doc["read_at"] = current_time
        elif new_status in [NotificationStatus.failed, NotificationStatus.undelivered]:
            update_doc["failed_at"] = current_time
            if error_code or error_message:
                update_doc["error_message"] = f"Code: {error_code}, Message: {error_message}" if error_code else error_message
        
        # Update notification record
        result = await notifications_collection.update_one(
            {"twilio_message_sid": message_sid},
            {"$set": update_doc}
        )
        
        if result.matched_count == 0:
            # Notification not found - log warning but don't fail webhook
            await log_error(
                error=Exception(f"Notification with Twilio SID {message_sid} not found"),
                location="notifications/services.py - update_notification_status",
                additional_info={
                    "message_sid": message_sid,
                    "new_status": new_status.value
                }
            )
        elif result.modified_count == 0:
            # No changes made - possibly duplicate webhook
            print(f"⚠️ No changes made for message SID {message_sid} - possible duplicate webhook")
        else:
            print(f"✅ Updated notification {message_sid} to status: {new_status.value}")
            
    except Exception as e:
        await log_error(
            error=e,
            location="notifications/services.py - update_notification_status",
            additional_info={
                "message_sid": message_sid,
                "new_status": new_status.value if new_status else "unknown"
            }
        )
        raise


async def get_whatsapp_service(webhook_base_url: Optional[str] = None) -> TwilioWhatsAppService:
    """
    Factory function to get WhatsApp service instance.
    
    Args:
        webhook_base_url: Base URL for status callbacks (e.g., from ngrok)
    
    Returns:
        TwilioWhatsAppService: Configured service instance
        
    Raises:
        ValueError: If Twilio configuration is invalid
    """
    return TwilioWhatsAppService(webhook_base_url=webhook_base_url)