"""
Notification routes for WhatsApp webhooks and status tracking
Author: Aditya Bhatt
"""
from fastapi import APIRouter, Request, HTTPException, status
from typing import Dict, Any
from app.database.mongo import log_error, get_db
from .schemas import NotificationStatus
from .services import update_notification_status
from datetime import datetime, timezone

router = APIRouter(prefix="/v1/notifications", tags=["notifications"])


@router.post("/twilio/whatsapp/status")
async def whatsapp_status_callback(request: Request) -> Dict[str, str]:
    """
    Twilio webhook endpoint for WhatsApp message status updates.
    
    Twilio calls this endpoint whenever a message status changes:
    - queued → sent → delivered → read
    - Or queued → failed/undelivered
    
    Args:
        request: FastAPI request containing Twilio webhook data
        
    Returns:
        Dict[str, str]: Success confirmation for Twilio
        
    Raises:
        HTTPException: If webhook processing fails
    """
    form_data = None
    try:
        # Parse Twilio webhook form data
        form_data = await request.form()
        
        # Extract key Twilio parameters with proper type handling
        message_sid: str = str(form_data.get("MessageSid", ""))
        message_status: str = str(form_data.get("MessageStatus", ""))
        error_code: str = str(form_data.get("ErrorCode", ""))
        error_message: str = str(form_data.get("ErrorMessage", ""))
        
        if not message_sid or not message_status:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required Twilio parameters"
            )
        
        # Map Twilio status to our enum
        try:
            notification_status = NotificationStatus(message_status)
        except ValueError:
            # Unknown status from Twilio - log but don't fail
            await log_error(
                error=ValueError(f"Unknown Twilio status: {message_status}"),
                location="notifications/routes.py - whatsapp_status_callback",
                additional_info={
                    "message_sid": message_sid,
                    "twilio_status": message_status
                }
            )
            # Use a fallback status
            notification_status = NotificationStatus.failed if "fail" in message_status.lower() else NotificationStatus.queued
        
        # Update notification status in database
        await update_notification_status(
            message_sid=message_sid,
            new_status=notification_status,
            error_code=error_code,
            error_message=error_message
        )
        
        return {"status": "success", "message": "Status update processed"}
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        await log_error(
            error=e,
            location="notifications/routes.py - whatsapp_status_callback",
            additional_info={"request_body": str(form_data) if form_data is not None else "unavailable"}
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process status callback"
        )


@router.get("/health")
async def notifications_health_check() -> Dict[str, Any]:
    """
    Health check for notifications module.
    Verifies database connectivity and Twilio configuration.
    
    Returns:
        Dict[str, Any]: Health status with service checks
    """
    try:
        from .services import get_whatsapp_service
        
        health_status: Dict[str, Any] = {
            "status": "healthy",
            "module": "notifications",
            "checks": {}
        }
        
        # Check database connection
        try:
            db = await get_db()
            await db.command('ping')
            health_status["checks"]["database"] = "connected"
        except Exception as e:
            health_status["checks"]["database"] = f"error: {str(e)}"
            health_status["status"] = "unhealthy"
        
        # Check Twilio configuration (without making API call)
        try:
            await get_whatsapp_service()  # This validates env vars
            health_status["checks"]["twilio_config"] = "valid"
        except Exception as e:
            health_status["checks"]["twilio_config"] = f"error: {str(e)}"
            health_status["status"] = "unhealthy"
        
        return health_status
        
    except Exception as e:
        await log_error(
            error=e,
            location="notifications/routes.py - notifications_health_check",
            additional_info={}
        )
        
        return {
            "status": "unhealthy",
            "module": "notifications",
            "error": "Health check failed"
        }