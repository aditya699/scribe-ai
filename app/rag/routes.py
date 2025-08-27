"""
RAG routes for incoming WhatsApp messages
Author: Aditya Bhatt
"""
from fastapi import APIRouter, Request, HTTPException, status
from typing import Dict
from app.database.mongo import log_error
from .utils import store_incoming_message, lookup_and_update_patient_info

router = APIRouter(prefix="/v1/rag", tags=["rag"])


@router.post("/whatsapp/incoming")
async def handle_incoming_whatsapp_message(request: Request) -> Dict[str, str]:
    """
    Twilio webhook endpoint for incoming WhatsApp messages from patients.
    
    Patients send follow-up questions to this endpoint for RAG-based responses.
    
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
        
        # Extract Twilio parameters for incoming messages
        from_number: str = str(form_data.get("From", ""))  # Patient's WhatsApp 
        message_body: str = str(form_data.get("Body", ""))  # Patient's question
        message_sid: str = str(form_data.get("MessageSid", ""))  # Twilio SID
        
        # Validate required parameters
        if not from_number or not message_body or not message_sid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing required Twilio parameters"
            )
        
        # Clean WhatsApp number format (remove "whatsapp:" prefix)
        patient_whatsapp_number = from_number.replace("whatsapp:", "").strip()
        if not patient_whatsapp_number.startswith("+"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid WhatsApp number format"
            )
        
        # Store incoming message in database
        incoming_message = await store_incoming_message(
            twilio_message_sid=message_sid,
            patient_whatsapp_number=patient_whatsapp_number,
            message_body=message_body
        )
        
        # Look up patient information and update message
        patient_found = await lookup_and_update_patient_info(incoming_message.message_id)
        
        if patient_found:
            print(f"✅ Patient found for {patient_whatsapp_number}")
        else:
            print(f"❌ No consultation history found for {patient_whatsapp_number}")
        
        # Log successful receipt
        print(f"📨 Incoming message from {patient_whatsapp_number}: {message_body[:50]}...")
        
        # Return success to Twilio (this prevents Twilio retries)
        return {
            "status": "received",
            "message": "Incoming message stored successfully"
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log unexpected errors
        await log_error(
            error=e,
            location="rag/routes.py - handle_incoming_whatsapp_message",
            additional_info={"form_data": str(form_data) if form_data else "unavailable"}
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process incoming WhatsApp message"
        )