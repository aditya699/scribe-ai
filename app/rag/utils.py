"""
RAG module utilities
Author: Aditya Bhatt
"""
from app.database.mongo import get_db, log_error
from app.rag.schemas import IncomingWhatsAppMessage
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import asyncio

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

async def get_patient_transcripts(session_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Retrieve all transcripts for a patient's sessions.
    
    Args:
        session_ids: List of session IDs for the patient
        
    Returns:
        List of transcript data with metadata
        
    Raises:
        ValueError: If no valid session IDs exist
        Exception: If database query fails
    """
    try:
        db = await get_db()
        
        # First, verify session IDs exist
        sessions_collection = db["sessions"]
        valid_sessions = await sessions_collection.count_documents(
            {"session_id": {"$in": session_ids}}
        )
        
        if valid_sessions == 0:
            raise ValueError(f"No valid sessions found for session_ids: {session_ids}")
        
        # Get transcripts for valid sessions only
        transcription_collection = db["transcription_sessions"]
        transcripts_cursor = transcription_collection.find(
            {
                "session_id": {"$in": session_ids},
                "status": "completed",
                "transcript": {"$exists": True, "$ne": ""}
            },
            {
                "_id": 0,
                "session_id": 1,
                "transcript": 1,
                "started_at": 1,
                "ended_at": 1
            }
        ).sort("started_at", 1)
        
        transcripts = await transcripts_cursor.to_list(length=None)
        
        return transcripts
        
    except ValueError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - get_patient_transcripts",
            additional_info={"session_ids": session_ids}
        )
        raise

async def generate_rag_response(
    patient_name: str,
    patient_question: str,
    transcripts: List[Dict[str, Any]],
    patient_whatsapp_number: str
) -> str:
    """
    Generate RAG response using consultation history and conversation context.
    
    Args:
        patient_name: Patient's name for personalization
        patient_question: Patient's medical query
        transcripts: List of consultation transcripts with metadata
        patient_whatsapp_number: Patient's WhatsApp number for conversation history
        
    Returns:
        str: Generated response for the patient
        
    Raises:
        Exception: If LLM generation fails
    """
    try:
        from app.core.llm import get_openai_client
        
        # Get recent conversation history
        conversation_history = await get_conversation_history(patient_whatsapp_number, limit=8)
        
        # Build consultation context if available
        consultation_context: str = ""
        if transcripts:
            context_parts: List[str] = []
            for i, transcript in enumerate(transcripts, 1):
                consultation_date: str = transcript['started_at'].strftime('%Y-%m-%d')
                context_parts.append(
                    f"Consultation {i} ({consultation_date}):\n{transcript['transcript']}"
                )
            consultation_context = f"\n\nPatient's Previous Consultations:\n{'\n\n'.join(context_parts)}"
        
        # Build conversation context if available
        conversation_context: str = ""
        if conversation_history:
            conv_parts: List[str] = []
            for msg in conversation_history:
                role: str = "Patient" if msg["role"] == "user" else "AI Assistant"
                conv_parts.append(f"{role}: {msg['content']}")
            conversation_context = f"\n\nRecent Conversation:\n{'\n'.join(conv_parts)}"
        
        # Build input prompt with all context
        input_prompt: str = f"""Patient: {patient_name}
                Current Question: {patient_question}{consultation_context}{conversation_context}

                You are a helpful medical AI assistant. Provide helpful medical information and guidance. Reference both consultation history and recent conversation when relevant. Always recommend consulting a healthcare provider for serious concerns. Use simple, clear language and be empathetic. Maintain conversation continuity by acknowledging previous exchanges when appropriate."""
                        
        # Generate response using new Responses API
        openai_client = await get_openai_client()
        
        response = await openai_client.responses.create(
            model="gpt-4.1-mini",
            input=input_prompt,
            temperature=0.1
        )
        
        generated_response: str = response.output_text.strip()
        
        if not generated_response:
            raise Exception("OpenAI returned empty response")
        
        return generated_response
        
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - generate_rag_response",
            additional_info={
                "patient_name": patient_name,
                "question_length": len(patient_question) if patient_question else 0,
                "transcript_count": len(transcripts) if transcripts else 0
            }
        )
        raise

async def store_ai_response(
    message_id: str,
    ai_response: str
) -> None:
    """
    Store AI-generated response in the incoming message record.
    
    Args:
        message_id: ID of the incoming message to update
        ai_response: Generated AI response text
        
    Raises:
        ValueError: If message not found
        Exception: If database update fails
    """
    try:
        db = await get_db()
        incoming_messages_collection = db["incoming_whatsapp_messages"]
        
        # Update message with AI response
        update_result = await incoming_messages_collection.update_one(
            {"message_id": message_id},
            {
                "$set": {
                    "ai_response": ai_response,
                    "response_generated_at": datetime.now(timezone.utc),
                    "status": "completed",
                    "processed_at": datetime.now(timezone.utc)
                }
            }
        )
        
        if update_result.matched_count == 0:
            raise ValueError(f"Message with ID {message_id} not found")
        
        if update_result.modified_count == 0:
            raise Exception(f"Failed to update message {message_id} with AI response")
        
    except ValueError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - store_ai_response",
            additional_info={
                "message_id": message_id,
                "response_length": len(ai_response) if ai_response else 0
            }
        )
        raise

async def store_processing_error(
    message_id: str,
    error_message: str
) -> None:
    """
    Store processing error in the incoming message record.
    
    Args:
        message_id: ID of the incoming message to update
        error_message: Error description for debugging
        
    Raises:
        ValueError: If message not found
        Exception: If database update fails
    """
    try:
        db = await get_db()
        incoming_messages_collection = db["incoming_whatsapp_messages"]
        
        # Update message with error details
        update_result = await incoming_messages_collection.update_one(
            {"message_id": message_id},
            {
                "$set": {
                    "status": "failed",
                    "error_message": error_message,
                    "processed_at": datetime.now(timezone.utc)
                }
            }
        )
        
        if update_result.matched_count == 0:
            raise ValueError(f"Message with ID {message_id} not found")
        
        if update_result.modified_count == 0:
            raise Exception(f"Failed to update message {message_id} with error")
        
    except ValueError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - store_processing_error",
            additional_info={
                "message_id": message_id,
                "original_error": error_message
            }
        )
        raise

async def process_rag_pipeline(message_id: str) -> bool:
    """
    Process complete RAG pipeline for an incoming WhatsApp message.
    
    Args:
        message_id: ID of the incoming message to process
        
    Returns:
        bool: True if processing succeeded, False if failed
        
    Raises:
        Exception: If critical database operations fail
    """
    try:
        db = await get_db()
        incoming_messages_collection = db["incoming_whatsapp_messages"]
        
        # 1. Get the incoming message details
        message_doc = await incoming_messages_collection.find_one(
            {"message_id": message_id},
            {"_id": 0}
        )
        
        if not message_doc:
            raise Exception(f"Message {message_id} not found")
        
        patient_whatsapp_number = message_doc["patient_whatsapp_number"]
        patient_question = message_doc["message_body"]
        
        # 2. Find patient information
        patient_info = await find_patient_by_whatsapp_number(patient_whatsapp_number)
        
        if not patient_info:
            # Patient not found - store and send friendly message
            error_message = "I don't have any consultation records for your number. Please contact your doctor if you need medical assistance."
            await store_processing_error(message_id, error_message)
            await send_rag_response_to_patient(message_id)
            return False
        
        # 3. Get patient transcripts
        try:
            transcripts = await get_patient_transcripts(patient_info["session_ids"])
        except ValueError as e:
            # Session validation failed - store and send error
            error_message = f"Hello {patient_info['patient_name']}, I'm having trouble accessing your consultation records. Please contact your doctor for assistance."
            await store_processing_error(message_id, error_message)
            await send_rag_response_to_patient(message_id)
            return False
        
        if not transcripts:
            # No transcripts available - store and send message
            error_message = f"Hello {patient_info['patient_name']}, I don't have any completed consultation transcripts for you yet. Please contact your doctor if you have medical questions."
            await store_processing_error(message_id, error_message)
            await send_rag_response_to_patient(message_id)
            return False
        
        # 4. Generate AI response
        try:
            ai_response = await generate_rag_response(
                patient_name=patient_info["patient_name"],
                patient_question=patient_question,
                transcripts=transcripts,
                patient_whatsapp_number=patient_whatsapp_number
            )
        except Exception as e:
            # AI generation failed - store and send error
            error_message = f"Hello {patient_info['patient_name']}, I'm experiencing technical difficulties right now. Please try again later or contact your doctor directly."
            await store_processing_error(message_id, error_message)
            await send_rag_response_to_patient(message_id)
            return False
        
        # 5. Store and send successful response
        await store_ai_response(message_id, ai_response)
        await send_rag_response_to_patient(message_id)
        return True
        
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - process_rag_pipeline",
            additional_info={"message_id": message_id}
        )
        
        # Try to store and send generic error if possible
        try:
            await store_processing_error(message_id, "Technical error occurred during processing")
            await send_rag_response_to_patient(message_id)
        except:
            pass  # Don't fail if error handling fails
        
        raise

async def send_rag_response_to_patient(message_id: str) -> bool:
    """
    Send stored AI response to patient via WhatsApp.
    
    Args:
        message_id: ID of the processed message with stored AI response
        
    Returns:
        bool: True if message was sent successfully, False otherwise
        
    Raises:
        Exception: If database operations fail
    """
    try:
        from app.notifications.services import get_whatsapp_service
        
        db = await get_db()
        incoming_messages_collection = db["incoming_whatsapp_messages"]
        
        # Get the message with AI response
        message_doc = await incoming_messages_collection.find_one(
            {"message_id": message_id},
            {"_id": 0}
        )
        
        if not message_doc:
            raise Exception(f"Message {message_id} not found")
        
        # Check if we have an AI response to send
        ai_response = message_doc.get("ai_response")
        if not ai_response:
            # Check if we have an error message to send instead
            error_message = message_doc.get("error_message")
            if error_message:
                ai_response = error_message
            else:
                raise Exception(f"No response or error message found for message {message_id}")
        
        patient_whatsapp_number = message_doc["patient_whatsapp_number"]
        
        # Send WhatsApp message
        whatsapp_service = await get_whatsapp_service()
        
        # Use Twilio's message sending directly (simpler than notification service)
        from twilio.rest import Client
        from app.core.config import settings
        
        # Create normalized WhatsApp number
        normalized_number = patient_whatsapp_number
        if not normalized_number.startswith("+"):
            normalized_number = f"+{normalized_number}"
        
        # Send via Twilio
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        message = await asyncio.to_thread(
            client.messages.create,
            from_=settings.TWILIO_WHATSAPP_FROM,
            body=ai_response,
            to=f"whatsapp:{normalized_number}"
        )
        
        print(f"Sent RAG response to {patient_whatsapp_number}, Twilio SID: {message.sid}")
        return True
        
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - send_rag_response_to_patient",
            additional_info={"message_id": message_id}
        )
        return False

async def get_conversation_history(
    patient_whatsapp_number: str, 
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Get recent conversation history between patient and AI system.
    
    Args:
        patient_whatsapp_number: Patient's WhatsApp number  
        limit: Maximum number of recent messages to retrieve
        
    Returns:
        List of recent messages with patient questions and AI responses
        Format: [{"role": "user", "content": "...", "timestamp": datetime}, ...]
        
    Raises:
        Exception: If database query fails
    """
    try:
        db = await get_db()
        incoming_messages_collection = db["incoming_whatsapp_messages"]
        
        # Get recent completed messages for this patient
        messages_cursor = incoming_messages_collection.find(
            {
                "patient_whatsapp_number": patient_whatsapp_number,
                "status": {"$in": ["completed", "failed"]},
                "$or": [
                    {"ai_response": {"$exists": True, "$ne": None}},
                    {"error_message": {"$exists": True, "$ne": None}}
                ]
            },
            {
                "_id": 0,
                "message_body": 1,
                "ai_response": 1, 
                "error_message": 1,
                "received_at": 1,
                "response_generated_at": 1
            }
        ).sort("received_at", -1).limit(limit)
        
        messages = await messages_cursor.to_list(length=None)
        
        # Convert to conversation format
        conversation_history = []
        
        for msg in reversed(messages):  # Reverse to get chronological order
            # Add user message
            conversation_history.append({
                "role": "user",
                "content": msg["message_body"],
                "timestamp": msg["received_at"]
            })
            
            # Add AI response
            ai_content = msg.get("ai_response") or msg.get("error_message")
            if ai_content:
                conversation_history.append({
                    "role": "assistant", 
                    "content": ai_content,
                    "timestamp": msg.get("response_generated_at") or msg["received_at"]
                })
        
        return conversation_history
        
    except Exception as e:
        await log_error(
            error=e,
            location="rag/utils.py - get_conversation_history",
            additional_info={
                "patient_whatsapp_number": patient_whatsapp_number,
                "limit": limit
            }
        )
        raise
    