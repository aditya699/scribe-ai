"""
Author: Aditya Bhatt
"""

from app.database.mongo import get_db, log_error
from .schemas import TranscriptionSession, TranscriptionStatus
from typing import Optional

async def start_transcription_session(session_id: str) -> TranscriptionSession:
    """
    Create a new transcription session for the given patient session.
    
    Args:
        session_id: The patient session ID to start transcribing
        
    Returns:
        TranscriptionSession: The created transcription session
        
    Raises:
        ValueError: If session_id doesn't exist
        Exception: For database errors
    """
    try:
        db = await get_db()
        
        # 1. Verify the patient session exists
        sessions_collection = db["sessions"]
        patient_session = await sessions_collection.find_one(
            {"session_id": session_id},
            {"_id": 0, "session_id": 1, "status": 1}
        )
        
        if not patient_session:
            raise ValueError(f"Patient session {session_id} not found")
        
        if patient_session["status"] != "active":
            raise ValueError(f"Patient session {session_id} is not active")
        
        # 2. Check for existing active transcription session (idempotency)
        transcription_collection = db["transcription_sessions"]
        existing_transcription = await transcription_collection.find_one(
            {
                "session_id": session_id,
                "status": {"$in": ["starting", "streaming"]}  # Active statuses
            },
            {"_id": 0}
        )
        
        if existing_transcription:
            # Return existing session instead of creating duplicate
            return TranscriptionSession.model_validate(existing_transcription)
        
        # 3. Create new transcription session
        transcription_session = TranscriptionSession(
            session_id=session_id,
            status=TranscriptionStatus.starting
        )
        
        # 4. Insert into database
        transcription_collection = db["transcription_sessions"]
        doc = transcription_session.model_dump(exclude_none=True)
        
        result = await transcription_collection.insert_one(doc)
        if not result.inserted_id:
            raise Exception("Failed to create transcription session in database")
        
        return transcription_session
        
    except ValueError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - start_transcription_session",
            additional_info={"session_id": session_id}
        )
        raise

async def end_transcription_session(transcription_session_id: str) -> None:
    """
    End a transcription session.
    
    Args:
        transcription_session_id: The transcription session to end
        
    Raises:
        ValueError: If transcription session doesn't exist or already ended
        Exception: For database errors
    """
    try:
        db = await get_db()
        transcription_collection = db["transcription_sessions"]
        
        # 1. Find the transcription session
        session = await transcription_collection.find_one(
            {"transcription_session_id": transcription_session_id},
            {"_id": 0}
        )
        
        if not session:
            raise ValueError(f"Transcription session {transcription_session_id} not found")
        
        if session["status"] in ["completed", "failed"]:
            raise ValueError(f"Transcription session {transcription_session_id} already ended")
        
        # 2. Update session to completed status
        from datetime import datetime, timezone
        
        update_result = await transcription_collection.update_one(
            {"transcription_session_id": transcription_session_id},
            {
                "$set": {
                    "status": "completed",
                    "ended_at": datetime.now(timezone.utc)
                }
            }
        )
        
        if update_result.modified_count == 0:
            raise Exception("Failed to update transcription session status")
        
        # Session ended successfully
        return
        
    except ValueError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - end_transcription_session",
            additional_info={"transcription_session_id": transcription_session_id}
        )
        raise