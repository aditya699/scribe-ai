"""
Author: Aditya Bhatt
"""

from app.database.mongo import get_db, log_error
from .schemas import TranscriptionSession, TranscriptionStatus
from typing import Optional
import asyncio

TRANSCRIPTION_WORKER_POOL = asyncio.Semaphore(5)  # ← HERE IS THE SEMAPHORE


def is_websocket_open(websocket) -> bool:
    """
    Check if WebSocket connection is still open and ready to send messages.
    Checks both client and application states to prevent double-close scenarios.
    
    Args:
        websocket: FastAPI WebSocket connection object
        
    Returns:
        bool: True if WebSocket is fully open, False otherwise
    """
    try:
        from starlette.websockets import WebSocketState
        return (
            hasattr(websocket, 'client_state') and 
            hasattr(websocket, 'application_state') and
            websocket.client_state == WebSocketState.CONNECTED and
            websocket.application_state == WebSocketState.CONNECTED
        )
    except Exception:
        return False


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
    Begin ending a transcription session.
    Sets status to 'ending' to allow background tasks to complete.
    
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
        
        if session["status"] in ["ending", "completed", "failed"]:
            raise ValueError(f"Transcription session {transcription_session_id} already ended")
        
        # 2. Update session to ending status (not completed yet)
        from datetime import datetime, timezone
        
        update_result = await transcription_collection.update_one(
            {"transcription_session_id": transcription_session_id},
            {
                "$set": {
                    "status": "ending",  # Changed from "completed" to "ending"
                    "ending_started_at": datetime.now(timezone.utc)  # Track when ending began
                }
            }
        )
        
        if update_result.modified_count == 0:
            raise Exception("Failed to update transcription session status to ending")
        
        # Note: Background tasks will complete and then mark as "completed"
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
    Transcribe an audio chunk using OpenAI whisper-1 model.
    
    Args:
        transcription_session_id: The transcription session
        chunk_id: The audio chunk to transcribe
        
    Returns:
        str: Transcribed text from the audio chunk
        
    Raises:
        Exception: For transcription or storage errors
    """
    async with TRANSCRIPTION_WORKER_POOL:
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
            
            # 4. Call OpenAI Transcription API
            openai_client = await get_openai_client()
            
            transcription = await openai_client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
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
    

async def process_audio_chunk_background(response_buffer: dict, next_sequence_to_send: list, websocket, transcription_session_id: str, sequence_number: int, audio_data: bytes, buffer_lock: asyncio.Lock):
    """
    Background task for processing audio chunks without blocking the WebSocket receive loop.
    Uses response buffer to ensure responses are sent in correct sequence order.
    
    Args:
        response_buffer: Dict to store completed responses waiting to be sent
        next_sequence_to_send: Mutable list [sequence_number] shared across tasks
        websocket: WebSocket connection to send responses
        transcription_session_id: The transcription session
        sequence_number: Which chunk this is (0, 1, 2...)
        audio_data: Raw audio bytes from mobile app
    """
    try:
        # Run the complete processing pipeline
        response = await process_audio_chunk_complete(
            transcription_session_id, 
            sequence_number, 
            audio_data
        )
        
        # CRITICAL SECTION: Use the lock here
        async with buffer_lock:
            # Store response in buffer instead of sending immediately
            response_buffer[sequence_number] = response
            
            # Send buffered responses in correct sequence order
            await send_buffered_responses(response_buffer, next_sequence_to_send, websocket)
        
    except Exception as e:
        # Log error but don't crash the WebSocket
        await log_error(
            error=e,
            location="transcription/utils.py - process_audio_chunk_background",
            additional_info={
                "transcription_session_id": transcription_session_id,
                "sequence_number": sequence_number,
                "audio_size_bytes": len(audio_data)
            }
        )

        # 🔒 CRITICAL: Insert error into buffer instead of immediate send
        async with buffer_lock:
            # Create error response for this sequence
            from .schemas import WebSocketError
            error_response = WebSocketError(
                error_code="PROCESSING_ERROR",
                error_message=f"Failed to process audio chunk {sequence_number}",
                sequence_number=sequence_number
            )
            
            # Insert error into buffer like any other response
            response_buffer[sequence_number] = error_response.model_dump()
            
            # Send buffered responses in correct sequence order
            await send_buffered_responses(response_buffer, next_sequence_to_send, websocket)


async def process_audio_chunk_with_semaphore(response_buffer: dict, next_sequence_to_send: list, websocket, transcription_session_id: str, sequence_number: int, audio_data: bytes, buffer_lock: asyncio.Lock):
    """
    Semaphore-controlled background task for processing audio chunks.
    Limits the total number of concurrent processing tasks to prevent resource exhaustion.
    
    Args:
        response_buffer: Dict to store completed responses waiting to be sent
        next_sequence_to_send: Mutable list [sequence_number] shared across tasks
        websocket: WebSocket connection to send responses
        transcription_session_id: The transcription session
        sequence_number: Which chunk this is (0, 1, 2...)
        audio_data: Raw audio bytes from mobile app
    """
    # Acquire worker from pool (blocks if all 5 workers busy)
    async with TRANSCRIPTION_WORKER_POOL:
        await process_audio_chunk_background(
            response_buffer, 
            next_sequence_to_send, 
            websocket, 
            transcription_session_id, 
            sequence_number, 
            audio_data,
            buffer_lock
        )


async def send_buffered_responses(response_buffer: dict, next_sequence_to_send: list, websocket):
    """
    Send buffered responses in correct sequence order.
    Only sends responses when all previous sequences are ready.
    NOTE: This function must be called within buffer_lock to prevent race conditions.
    
    Args:
        response_buffer: Dict storing completed responses {sequence_number: response}
        next_sequence_to_send: Mutable list [sequence_number] shared across tasks
        websocket: WebSocket connection to send responses
    """
    import json
    
    # Keep sending responses while the next expected sequence is ready
    while next_sequence_to_send[0] in response_buffer:
        try:
            # 🔒 CHECK WEBSOCKET STATE BEFORE SENDING
            if not is_websocket_open(websocket):
                # WebSocket is closed - stop trying to send and clear buffer
                await log_error(
                    error=Exception("WebSocket closed during buffered response send"),
                    location="transcription/utils.py - send_buffered_responses",
                    additional_info={"remaining_buffer_size": len(response_buffer)}
                )
                response_buffer.clear()  # Clear buffer to prevent memory leak
                break
            
            # Get the response for the next sequence
            response = response_buffer[next_sequence_to_send[0]]
            
            # Send it to mobile app
            await websocket.send_text(json.dumps(response))
            
            # Remove from buffer (already sent)
            del response_buffer[next_sequence_to_send[0]]
            
            # Move to next sequence (update shared state)
            next_sequence_to_send[0] += 1
            
        except Exception as e:
            # If sending fails, log and stop trying
            await log_error(
                error=e,
                location="transcription/utils.py - send_buffered_responses",
                additional_info={
                    "sequence_number": next_sequence_to_send[0],
                    "buffer_size": len(response_buffer)
                }
            )
            # Clear buffer to prevent endless retry loop
            response_buffer.clear()
            break


async def check_and_complete_session(transcription_session_id: str, active_tasks: dict) -> None:
    """
    Check if session is ending and all background tasks are complete.
    If so, transition status from 'ending' to 'completed'.
    
    Args:
        transcription_session_id: The transcription session to check
        active_tasks: Dictionary of currently active background tasks
    """
    try:
        db = await get_db()
        transcription_collection = db["transcription_sessions"]
        
        # Get current session status
        session = await transcription_collection.find_one(
            {"transcription_session_id": transcription_session_id},
            {"_id": 0, "status": 1}
        )
        
        if not session or session["status"] != "ending":
            # Only check completion for sessions in "ending" status
            return
        
        # Check if any background tasks are still running
        running_tasks = [task for task in active_tasks.values() if not task.done()]
        
        if len(running_tasks) == 0:
            # All background tasks completed - mark session as completed
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
            
            if update_result.modified_count > 0:
                print(f"✅ Session {transcription_session_id} marked as completed - all tasks finished")
            else:
                print(f"⚠️ Failed to mark session {transcription_session_id} as completed")
        else:
            print(f"⏳ Session {transcription_session_id} still ending - {len(running_tasks)} tasks remaining")
            
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/utils.py - check_and_complete_session",
            additional_info={
                "transcription_session_id": transcription_session_id,
                "active_task_count": len(active_tasks)
            }
        )


def create_task_cleanup_callback(active_tasks: dict, sequence_number: int, transcription_session_id: str):
    """
    Create a callback function that removes completed tasks and checks for session completion.
    
    Args:
        active_tasks: Dictionary storing background task references
        sequence_number: The sequence number of the task to remove
        transcription_session_id: Session ID for completion checking
        
    Returns:
        Callback function to be attached to the task
    """
    def cleanup_callback(task):
        """Remove completed task and check if session can be completed"""
        try:
            # Remove the completed task from tracking dictionary
            active_tasks.pop(sequence_number, None)
            print(f"🧹 Cleaned up completed task for chunk {sequence_number}")
            
            # Check if this was the last task for an ending session
            asyncio.create_task(check_and_complete_session(transcription_session_id, active_tasks))
            
        except Exception as e:
            # Don't let cleanup errors crash anything
            print(f"⚠️ Warning: Failed to cleanup task {sequence_number}: {e}")
    
    return cleanup_callback