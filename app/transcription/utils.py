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

async def validate_websocket_connection(transcription_session_id: str) -> bool:
    """
    Validate that a transcription session can accept WebSocket connection.
    
    Args:
        transcription_session_id: The transcription session to validate
        
    Returns:
        bool: True if connection is allowed, False otherwise
        
    Raises:
        ValueError: If session doesn't exist or is in invalid state
        Exception: For database errors
    """
    try:
        db = await get_db()
        transcription_collection = db["transcription_sessions"]
        
        # Find the transcription session
        session = await transcription_collection.find_one(
            {"transcription_session_id": transcription_session_id},
            {"_id": 0, "status": 1, "websocket_connected": 1}
        )
        
        if not session:
            raise ValueError(f"Transcription session {transcription_session_id} not found")
        
        # Check if session is in valid state for WebSocket
        valid_statuses = ["starting", "streaming"]
        if session["status"] not in valid_statuses:
            raise ValueError(f"Session status '{session['status']}' cannot accept WebSocket connection")
        
        # Check if WebSocket already connected
        if session.get("websocket_connected", False):
            raise ValueError(f"WebSocket already connected to session {transcription_session_id}")
        
        return True
        
    except ValueError:
        # Re-raise validation errors as-is
        raise
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - validate_websocket_connection",
            additional_info={"transcription_session_id": transcription_session_id}
        )
        raise

async def mark_websocket_connected(transcription_session_id: str) -> None:
    """
    Mark a transcription session as having an active WebSocket connection.
    
    Args:
        transcription_session_id: The transcription session that connected
        
    Raises:
        Exception: For database errors
    """
    try:
        from datetime import datetime, timezone
        
        db = await get_db()
        transcription_collection = db["transcription_sessions"]
        
        # Update session to mark WebSocket as connected
        update_result = await transcription_collection.update_one(
            {"transcription_session_id": transcription_session_id},
            {
                "$set": {
                    "websocket_connected": True,
                    "websocket_connected_at": datetime.now(timezone.utc),
                    "status": "streaming"  # Update status to streaming when WebSocket connects
                }
            }
        )
        
        if update_result.modified_count == 0:
            raise Exception(f"Failed to mark WebSocket connected for session {transcription_session_id}")
        
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - mark_websocket_connected",
            additional_info={"transcription_session_id": transcription_session_id}
        )
        raise

async def mark_websocket_disconnected(transcription_session_id: str) -> None:
    """
    Mark a transcription session as having lost WebSocket connection.
    Only resets status to 'starting' if currently streaming.
    
    Args:
        transcription_session_id: The transcription session that disconnected
        
    Raises:
        Exception: For database errors
    """
    try:
        from datetime import datetime, timezone
        
        db = await get_db()
        transcription_collection = db["transcription_sessions"]
        
        # First get current status
        session = await transcription_collection.find_one(
            {"transcription_session_id": transcription_session_id},
            {"_id": 0, "status": 1}
        )
        
        if not session:
            return  # Session doesn't exist, nothing to update
        
        # Prepare update - always mark WebSocket as disconnected
        update_fields = {
            "websocket_connected": False,
            "websocket_disconnected_at": datetime.now(timezone.utc)
        }
        
        # Only reset status to 'starting' if currently streaming
        if session["status"] == "streaming":
            update_fields["status"] = "starting"
        
        # Update session 
        update_result = await transcription_collection.update_one(
            {"transcription_session_id": transcription_session_id},
            {"$set": update_fields}
        )
        
        if update_result.modified_count == 0:
            raise Exception(f"Failed to mark WebSocket disconnected for session {transcription_session_id}")
        
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - mark_websocket_disconnected",
            additional_info={"transcription_session_id": transcription_session_id}
        )
        raise

async def process_websocket_message(transcription_session_id: str, message: dict) -> dict:
    """
    Process incoming WebSocket message from mobile app.
    
    Args:
        transcription_session_id: The transcription session
        message: WebSocket message received from mobile app
        
    Returns:
        dict: Response to send back to mobile app
        
    Raises:
        ValueError: For invalid message format
        Exception: For processing errors
    """
    try:
        from .schemas import AudioChunkMetadata, WebSocketError
        import json
        
        # Check message type
        message_type = message.get("type")
        
        if message_type == "audio_chunk_metadata":
            # Mobile app is telling us about incoming audio chunk
            metadata = AudioChunkMetadata.model_validate(message)
            
            # Validate the transcription session is still active
            db = await get_db()
            transcription_collection = db["transcription_sessions"]
            
            session = await transcription_collection.find_one(
                {"transcription_session_id": transcription_session_id},
                {"_id": 0, "status": 1}
            )
            
            if not session:
                error = WebSocketError(
                    error_code="SESSION_NOT_FOUND",
                    error_message=f"Transcription session {transcription_session_id} not found"
                )
                return error.model_dump()
            
            if session["status"] not in ["streaming"]:
                error = WebSocketError(
                    error_code="SESSION_NOT_STREAMING", 
                    error_message=f"Session status is {session['status']}, not accepting audio"
                )
                return error.model_dump()
            
            # Return confirmation that we're ready for the audio chunk
            return {
                "type": "metadata_received",
                "message": f"Ready to receive audio chunk {metadata.sequence_number}",
                "sequence_number": metadata.sequence_number,
                "expected_size_bytes": metadata.chunk_size_bytes
            }
        
        else:
            # Unknown message type
            error = WebSocketError(
                error_code="UNKNOWN_MESSAGE_TYPE",
                error_message=f"Unknown message type: {message_type}"
            )
            return error.model_dump()
        
    except ValueError as e:
        # Invalid message format
        error = WebSocketError(
            error_code="INVALID_MESSAGE_FORMAT",
            error_message=str(e)
        )
        return error.model_dump()
        
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - process_websocket_message",
            additional_info={
                "transcription_session_id": transcription_session_id,
                "message": message
            }
        )
        
        error = WebSocketError(
            error_code="PROCESSING_ERROR",
            error_message="Failed to process message"
        )
        return error.model_dump()

async def process_audio_chunk(transcription_session_id: str, sequence_number: int, audio_data: bytes) -> dict:
    """
    Process binary audio chunk received via WebSocket.
    
    Args:
        transcription_session_id: The transcription session
        sequence_number: Which chunk this is (0, 1, 2...)
        audio_data: Raw audio bytes from mobile app
        
    Returns:
        dict: Response with processing status
        
    Raises:
        Exception: For storage or processing errors
    """
    try:
        from .schemas import AudioChunk, WebSocketError
        from app.database.blob import get_blob_client
        import uuid
        
        # 1. Create audio chunk record
        chunk_id = str(uuid.uuid4())
        # Frontend records WebM/Opus; preserve original container/codec for compatibility
        blob_path = f"audio-chunks/{transcription_session_id}/{sequence_number:06d}_{chunk_id}.webm"
        
        audio_chunk = AudioChunk(
            chunk_id=chunk_id,
            transcription_session_id=transcription_session_id,
            sequence_number=sequence_number,
            blob_path=blob_path
        )
        
        # 2. Store audio data in blob storage
        blob_client = await get_blob_client()
        container_name = "audio-chunks"
        
        # Upload audio bytes to blob storage
        blob_client_for_chunk = blob_client.get_blob_client(
            container=container_name,
            blob=blob_path
        )
        
        await blob_client_for_chunk.upload_blob(
            data=audio_data,
            overwrite=True,
            content_type="audio/webm"
        )
        
        # 3. Store chunk metadata in database
        db = await get_db()
        chunks_collection = db["audio_chunks"]
        doc = audio_chunk.model_dump(exclude_none=True)
        
        result = await chunks_collection.insert_one(doc)
        if not result.inserted_id:
            raise Exception("Failed to store audio chunk metadata")
        
        # 4. Return success response
        return {
            "type": "audio_chunk_stored",
            "message": f"Audio chunk {sequence_number} stored successfully",
            "chunk_id": chunk_id,
            "sequence_number": sequence_number
        }
        
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - process_audio_chunk",
            additional_info={
                "transcription_session_id": transcription_session_id,
                "sequence_number": sequence_number,
                "audio_size_bytes": len(audio_data)
            }
        )
        
        error = WebSocketError(
            error_code="AUDIO_STORAGE_ERROR",
            error_message="Failed to store audio chunk"
        )
        return error.model_dump()

async def transcribe_audio_chunk(transcription_session_id: str, chunk_id: str) -> str:
    """
    Transcribe an audio chunk using OpenAI gpt-4o-transcribe model.
    
    Args:
        transcription_session_id: The transcription session
        chunk_id: The audio chunk to transcribe
        
    Returns:
        str: Transcribed text from the audio chunk
        
    Raises:
        Exception: For transcription or storage errors
    """
    try:
        from app.core.llm import get_openai_client
        from app.database.blob import get_blob_client
        import io
        
        # 1. Get audio chunk metadata from database
        db = await get_db()
        chunks_collection = db["audio_chunks"]
        
        chunk_doc = await chunks_collection.find_one(
            {"chunk_id": chunk_id},
            {"_id": 0, "blob_path": 1, "sequence_number": 1}
        )
        
        if not chunk_doc:
            raise Exception(f"Audio chunk {chunk_id} not found")
        
        # 2. Download audio data from blob storage
        blob_client = await get_blob_client()
        container_name = "audio-chunks"
        
        blob_client_for_chunk = blob_client.get_blob_client(
            container=container_name,
            blob=chunk_doc["blob_path"]
        )
        
        # Download audio bytes
        audio_stream = await blob_client_for_chunk.download_blob()
        audio_data = await audio_stream.readall()
        
        # 3. Create file-like object for OpenAI API
        audio_file = io.BytesIO(audio_data)
        # Name with .webm so the API can infer correct container
        audio_file.name = f"chunk_{chunk_doc['sequence_number']}.webm"
        
        # 4. Call OpenAI Transcription API with medical context
        openai_client = await get_openai_client()
        
        transcription = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="en",
        )
        
        return transcription.text.strip()
        
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - transcribe_audio_chunk",
            additional_info={
                "transcription_session_id": transcription_session_id,
                "chunk_id": chunk_id
            }
        )
        raise

async def update_session_transcript(transcription_session_id: str, new_text: str, sequence_number: int) -> str:
    """
    Update the session transcript with new transcribed text.
    
    Args:
        transcription_session_id: The transcription session to update
        new_text: Transcribed text from the latest audio chunk
        sequence_number: Which chunk this text is from
        
    Returns:
        str: The complete updated transcript
        
    Raises:
        Exception: For database errors
    """
    try:
        db = await get_db()
        transcription_collection = db["transcription_sessions"]
        
        # Get current transcript
        session = await transcription_collection.find_one(
            {"transcription_session_id": transcription_session_id},
            {"_id": 0, "transcript": 1}
        )
        
        if not session:
            raise Exception(f"Transcription session {transcription_session_id} not found")
        
        # Append new text to existing transcript
        current_transcript = session.get("transcript", "")
        
        # Add space if transcript already has content
        if current_transcript and new_text:
            updated_transcript = f"{current_transcript} {new_text.strip()}"
        else:
            updated_transcript = new_text.strip()
        
        # Update the session transcript in database
        update_result = await transcription_collection.update_one(
            {"transcription_session_id": transcription_session_id},
            {
                "$set": {
                    "transcript": updated_transcript
                }
            }
        )
        
        if update_result.modified_count == 0:
            raise Exception(f"Failed to update transcript for session {transcription_session_id}")
        
        return updated_transcript
        
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - update_session_transcript",
            additional_info={
                "transcription_session_id": transcription_session_id,
                "sequence_number": sequence_number,
                "new_text_length": len(new_text) if new_text else 0
            }
        )
        raise

async def process_audio_chunk_complete(transcription_session_id: str, sequence_number: int, audio_data: bytes) -> dict:
    """
    Complete pipeline: store audio → transcribe → update session → return response.
    
    Args:
        transcription_session_id: The transcription session
        sequence_number: Which chunk this is (0, 1, 2...)
        audio_data: Raw audio bytes from mobile app
        
    Returns:
        dict: TranscriptUpdate response with full processing results
        
    Raises:
        Exception: For any stage of processing errors
    """
    try:
        from .schemas import TranscriptUpdate, WebSocketError
        import time
        
        start_time = time.time()
        
        # Step 1: Store audio chunk in blob storage
        storage_response = await process_audio_chunk(transcription_session_id, sequence_number, audio_data)
        
        if storage_response.get("type") == "error":
            return storage_response  # Return storage error as-is
        
        chunk_id = storage_response["chunk_id"]
        
        # Step 2: Transcribe the audio chunk
        partial_transcript = await transcribe_audio_chunk(transcription_session_id, chunk_id)
        
        # Step 3: Update session transcript
        full_transcript = await update_session_transcript(transcription_session_id, partial_transcript, sequence_number)
        
        # Step 4: Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Step 5: Create and return transcript update response
        transcript_update = TranscriptUpdate(
            sequence_number=sequence_number,
            partial_transcript=partial_transcript,
            full_transcript=full_transcript,
            processing_time_ms=processing_time_ms
        )
        
        return transcript_update.model_dump()
        
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - process_audio_chunk_complete",
            additional_info={
                "transcription_session_id": transcription_session_id,
                "sequence_number": sequence_number,
                "audio_size_bytes": len(audio_data)
            }
        )
        
        error = WebSocketError(
            error_code="PROCESSING_PIPELINE_ERROR",
            error_message="Failed to process audio chunk completely",
            sequence_number=sequence_number
        )
        return error.model_dump()