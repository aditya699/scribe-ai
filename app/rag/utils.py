"""
RAG module utilities
Author: Aditya Bhatt
"""
from app.database.mongo import get_db, log_error
from typing import Optional, List, Dict, Any
from app.rag.schemas import IncomingWhatsAppMessage


async def find_patient_by_whatsapp_number(patient_whatsapp_number: str) -> Optional[Dict[str, Any]]:
    """
    Find patient information by WhatsApp number.
    
    Args:
        patient_whatsapp_number: Patient's WhatsApp number (with + prefix)
        
    Returns:
        Dict with patient info and session IDs, or None if not found
        Format: {
            "patient_name": str,
            "patient_whatsapp_number": str, 
            "session_ids": List[str],
            "total_sessions": int
        }
        
    Raises:
        Exception: If database query fails
    """
    try:
        db = await get_db()
        sessions_collection = db["sessions"]
        
        # Find all sessions for this WhatsApp number
        sessions_cursor = sessions_collection.find(
            {"patient_whatsapp_number": patient_whatsapp_number},
            {"_id": 0, "session_id": 1, "patient_name": 1, "created_at": 1}
        ).sort("created_at", -1)  # Most recent first
        
        sessions = await sessions_cursor.to_list(length=None)
        
        if not sessions:
            return None
            
        # Extract patient info from most recent session
        most_recent = sessions[0]
        session_ids = [session["session_id"] for session in sessions]
        
        return {
            "patient_name": most_recent["patient_name"],
            "patient_whatsapp_number": patient_whatsapp_number,
            "session_ids": session_ids,
            "total_sessions": len(sessions)
        }
        
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - find_patient_by_whatsapp_number",
            additional_info={"patient_whatsapp_number": patient_whatsapp_number}
        )
        raise

async def store_incoming_message(
    twilio_message_sid: str,
    patient_whatsapp_number: str, 
    message_body: str
) -> IncomingWhatsAppMessage:
    """
    Store incoming WhatsApp message in database.
    
    Args:
        twilio_message_sid: Twilio message SID for tracking
        patient_whatsapp_number: Patient's WhatsApp number (with + prefix)
        message_body: Patient's message text
        
    Returns:
        IncomingWhatsAppMessage: The stored message object
        
    Raises:
        Exception: If database storage fails
    """
    try:
        # Create message object
        incoming_message = IncomingWhatsAppMessage(
            twilio_message_sid=twilio_message_sid,
            patient_whatsapp_number=patient_whatsapp_number,
            message_body=message_body
        )
        
        db = await get_db()
        incoming_messages_collection = db["incoming_whatsapp_messages"]
        
        # Convert to dict and insert
        message_doc = incoming_message.model_dump(exclude_none=True)
        result = await incoming_messages_collection.insert_one(message_doc)
        
        if not result.inserted_id:
            raise Exception("Failed to insert incoming message into database")
            
        return incoming_message
        
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - store_incoming_message",
            additional_info={
                "twilio_message_sid": twilio_message_sid,
                "patient_whatsapp_number": patient_whatsapp_number
            }
        )
        raise

async def lookup_and_update_patient_info(message_id: str) -> bool:
    """
    Look up patient information and update the stored message with patient details.
    
    Args:
        message_id: ID of the incoming message to update with patient info
        
    Returns:
        bool: True if patient was found and updated, False if patient not found
        
    Raises:
        Exception: If database operations fail
    """
    try:
        db = await get_db()
        incoming_messages_collection = db["incoming_whatsapp_messages"]
        
        # Get the message
        message_doc = await incoming_messages_collection.find_one(
            {"message_id": message_id},
            {"_id": 0}
        )
        
        if not message_doc:
            raise Exception(f"Message with ID {message_id} not found")
        
        patient_whatsapp_number = message_doc["patient_whatsapp_number"]
        
        # Look up patient
        patient_info = await find_patient_by_whatsapp_number(patient_whatsapp_number)
        
        if patient_info:
            # Patient found - update message with patient details
            update_result = await incoming_messages_collection.update_one(
                {"message_id": message_id},
                {
                    "$set": {
                        "patient_found": True,
                        "patient_name": patient_info["patient_name"],
                        "session_ids": patient_info["session_ids"],
                        "total_sessions": patient_info["total_sessions"]
                    }
                }
            )
            
            if update_result.modified_count == 0:
                raise Exception(f"Failed to update message {message_id} with patient info")
            
            return True
        else:
            # Patient not found - update message accordingly
            update_result = await incoming_messages_collection.update_one(
                {"message_id": message_id},
                {"$set": {"patient_found": False}}
            )
            
            if update_result.modified_count == 0:
                raise Exception(f"Failed to update message {message_id} with patient not found")
            
            return False
        
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - lookup_and_update_patient_info",
            additional_info={"message_id": message_id}
        )
        raise