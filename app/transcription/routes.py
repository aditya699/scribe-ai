"""
Author: Aditya Bhatt
"""
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status, Response
from .schemas import StartTranscriptionRequest, StartTranscriptionResponse, EndTranscriptionRequest, EndTranscriptionResponse, AudioChunkMetadata, TranscriptUpdate, WebSocketError, ConnectionConfirmed
from .utils import start_transcription_session, end_transcription_session, validate_websocket_connection, mark_websocket_connected, mark_websocket_disconnected, process_websocket_message, process_audio_chunk_complete, process_audio_chunk_background, process_audio_chunk_with_semaphore, is_websocket_open  , create_task_cleanup_callback
from app.database.mongo import log_error
import asyncio

router = APIRouter(prefix="/v1/transcription", tags=["transcription"])

@router.post("/start", response_model=StartTranscriptionResponse, status_code=status.HTTP_201_CREATED)
async def start_transcription(request: StartTranscriptionRequest, response: Response):
    """
    Start a new real-time transcription session for a patient consultation.
    
    Args:
        request: StartTranscriptionRequest with session_id
        
    Returns:
        StartTranscriptionResponse with transcription session details
    """
    try:
        # Create the transcription session
        transcription_session = await start_transcription_session(request.session_id)
        
        # Set Location header for created resource
        response.headers["Location"] = f"/v1/transcription/{transcription_session.transcription_session_id}"
        
        return StartTranscriptionResponse(
            success=True,
            message="Transcription session started successfully",
            transcription_session_id=transcription_session.transcription_session_id
        )
        
    except ValueError as e:
        # Handle validation errors (session not found, not active, etc.)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Log unexpected errors
        await log_error(
            error=e,
            location="transcription/routes.py - start_transcription",
            additional_info=request.model_dump()
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start transcription session"
        )

@router.post("/end", response_model=EndTranscriptionResponse, status_code=status.HTTP_200_OK)
async def end_transcription(request: EndTranscriptionRequest):
    """
    End a real-time transcription session.
    
    Args:
        request: EndTranscriptionRequest with transcription_session_id
        
    Returns:
        EndTranscriptionResponse confirming session ended
    """
    try:
        # End the transcription session
        await end_transcription_session(request.transcription_session_id)
        
        return EndTranscriptionResponse(
            success=True,
            message="Transcription session ended successfully"
        )
        
    except ValueError as e:
        # Handle validation errors (session not found, already ended, etc.)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        # Log unexpected errors
        await log_error(
            error=e,
            location="transcription/routes.py - end_transcription",
            additional_info=request.model_dump()
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to end transcription session"
        )
    

@router.websocket("/{transcription_session_id}/stream")
async def transcription_websocket(websocket: WebSocket, transcription_session_id: str):
    """
    WebSocket endpoint for real-time audio transcription.
    
    Mobile app connects here to stream 8-10 second audio chunks
    and receive real-time transcript updates.
    
    Args:
        websocket: WebSocket connection object
        transcription_session_id: The transcription session to stream for
    """
    active_tasks = {}  # Track background processing tasks (initialized early for cleanup safety)
    try:
        # 1. Validate the transcription session
        await validate_websocket_connection(transcription_session_id)
        
        # 2. Accept the WebSocket connection
        await websocket.accept()
        
        # 3. Mark session as connected in database
        await mark_websocket_connected(transcription_session_id)
        
        # 4. Send connection confirmation to mobile app
        confirmation = ConnectionConfirmed(
            transcription_session_id=transcription_session_id
        )
        if is_websocket_open(websocket):
            await websocket.send_text(confirmation.model_dump_json())
        
        # 5. Keep connection alive and process messages
        expected_sequence = 0  # Track expected chunk sequence
        response_buffer = {}  # Buffer for out-of-order responses
        next_sequence_to_send = [0]  # Mutable reference shared across tasks
        
        # Add this new tracking for metadata-binary pairing
        pending_metadata = {}  # Track metadata waiting for corresponding binary data

        # CREATE THE LOCK HERE - shared across all background tasks
        buffer_lock = asyncio.Lock()
        
        while True:
            try:
                # Wait for messages from mobile app
                message = await websocket.receive()
                
                # Explicitly handle disconnect messages
                if message.get("type") == "websocket.disconnect":
                    print(f"🔌 Client disconnected from session {transcription_session_id}")
                    break
                
                if "text" in message:
                    # Text message (JSON metadata)
                    import json
                    try:
                        json_data = json.loads(message["text"])
                        
                        # Check if this is audio chunk metadata
                        if json_data.get("type") == "audio_chunk_metadata":
                            # Store metadata for later verification
                            metadata_seq = json_data.get("sequence_number")
                            if metadata_seq is not None:
                                pending_metadata[metadata_seq] = json_data
                                print(f"📋 Stored metadata for sequence {metadata_seq}")
                        response = await process_websocket_message(transcription_session_id, json_data)
                        # 🔒 CHECK STATE BEFORE SENDING RESPONSE
                        if is_websocket_open(websocket):
                            await websocket.send_text(json.dumps(response))
                    except json.JSONDecodeError:
                        error_response = {
                            "type": "error",
                            "error_code": "INVALID_JSON",
                            "error_message": "Invalid JSON format"
                        }
                        # 🔒 CHECK STATE BEFORE SENDING ERROR
                        if is_websocket_open(websocket):
                            await websocket.send_text(json.dumps(error_response))
                        
                elif "bytes" in message:
                    # Binary message (audio data) - CHECK SESSION STATUS FIRST
                    import json
                    from app.database.mongo import get_db

                    # Verify session is still accepting audio
                    db = await get_db()
                    transcription_collection = db["transcription_sessions"]
                    session = await transcription_collection.find_one(
                        {"transcription_session_id": transcription_session_id},
                        {"_id": 0, "status": 1}
                    )
                    
                    if not session:
                        error_response = {
                            "type": "error",
                            "error_code": "SESSION_NOT_FOUND",
                            "error_message": f"Transcription session {transcription_session_id} not found",
                            "sequence_number": expected_sequence
                        }
                        if is_websocket_open(websocket):
                            await websocket.send_text(json.dumps(error_response))
                        expected_sequence += 1
                        continue
                    
                    # Reject new audio if session is ending or completed
                    if session["status"] in ["ending", "completed", "failed"]:
                        error_response = {
                            "type": "error",
                            "error_code": "SESSION_ENDING",
                            "error_message": f"Session status is '{session['status']}', not accepting new audio",
                            "sequence_number": expected_sequence
                        }
                        if is_websocket_open(websocket):
                            await websocket.send_text(json.dumps(error_response))
                        expected_sequence += 1
                        continue

                    # Session is active - proceed with existing validation
                    audio_data = message["bytes"]

                    # Hard check: Verify binary data matches previously sent metadata
                    if expected_sequence not in pending_metadata:
                        # Fail fast - no metadata received for this sequence
                        error_response = {
                            "type": "error",
                            "error_code": "MISSING_METADATA",
                            "error_message": f"No metadata received for audio chunk sequence {expected_sequence}",
                            "sequence_number": expected_sequence
                        }
                        
                        # 🔒 CHECK STATE BEFORE SENDING ERROR
                        if is_websocket_open(websocket):
                            await websocket.send_text(json.dumps(error_response))
                        
                        # Skip processing this unverified chunk
                        expected_sequence += 1
                        continue

                    # Get the metadata for verification
                    metadata = pending_metadata[expected_sequence]
                    advertised_size = metadata.get("chunk_size_bytes", 0)
                    
                    # Verify binary size matches metadata size
                    if len(audio_data) != advertised_size:
                        error_response = {
                            "type": "error", 
                            "error_code": "SIZE_MISMATCH",
                            "error_message": f"Binary chunk size {len(audio_data)} bytes doesn't match metadata size {advertised_size} bytes",
                            "sequence_number": expected_sequence
                        }
                        
                        # 🔒 CHECK STATE BEFORE SENDING ERROR
                        if is_websocket_open(websocket):
                            await websocket.send_text(json.dumps(error_response))
                        
                        # Remove invalid metadata and skip processing
                        del pending_metadata[expected_sequence]
                        expected_sequence += 1
                        continue

                    # Hard check: Enforce advertised chunk size limit (1MB)
                    MAX_CHUNK_SIZE_BYTES = 1048576  # 1MB as advertised in ConnectionConfirmed
                    if len(audio_data) > MAX_CHUNK_SIZE_BYTES:
                        # Fail fast with error envelope
                        error_response = {
                            "type": "error",
                            "error_code": "CHUNK_TOO_LARGE", 
                            "error_message": f"Audio chunk size {len(audio_data)} bytes exceeds maximum {MAX_CHUNK_SIZE_BYTES} bytes",
                            "sequence_number": expected_sequence
                        }
                        
                        # 🔒 CHECK STATE BEFORE SENDING ERROR
                        if is_websocket_open(websocket):
                            await websocket.send_text(json.dumps(error_response))
                        
                        # Remove metadata and skip processing this oversized chunk
                        del pending_metadata[expected_sequence]
                        expected_sequence += 1
                        continue
                    
                    print(f"📦 Received audio chunk {expected_sequence} ({len(audio_data)} bytes) - verified against metadata")
                    
                    # All validations passed - remove metadata and proceed with processing
                    del pending_metadata[expected_sequence]

                    # Size/sequence validation passed - proceed with background processing
                    task = asyncio.create_task(
                        process_audio_chunk_with_semaphore(
                            response_buffer,
                            next_sequence_to_send, 
                            websocket, 
                            transcription_session_id, 
                            expected_sequence, 
                            audio_data,
                            buffer_lock
                        )
                    )
                    
                    # Create and attach cleanup callback to remove task when it completes
                    cleanup_callback = create_task_cleanup_callback(active_tasks, expected_sequence, transcription_session_id)
                    task.add_done_callback(cleanup_callback)
                    
                    # Store task reference (will be auto-removed by callback when done)
                    active_tasks[expected_sequence] = task
                    expected_sequence += 1  # Increment for next chunk
                    
                else:
                    # Unknown message type
                    error_response = {
                        "type": "error", 
                        "error_code": "UNKNOWN_MESSAGE_TYPE",
                        "error_message": "Message must be text or binary"
                    }
                    # 🔒 CHECK STATE BEFORE SENDING ERROR
                    if is_websocket_open(websocket):
                        await websocket.send_text(json.dumps(error_response))
            except WebSocketDisconnect:
                # Proper WebSocket disconnect handling
                print(f"🔌 WebSocket disconnect detected for session {transcription_session_id}")
                break
            except Exception as e:
                # Handle other unexpected errors
                print(f"❌ Unexpected WebSocket error: {str(e)}")
                await log_error(
                    error=e,
                    location="transcription/routes.py - transcription_websocket - message_loop",
                    additional_info={"transcription_session_id": transcription_session_id}
                )
                break
            
    except ValueError as e:
        # Validation failed - close connection with error
        print(f"❌ Validation failed: {str(e)}")
        if is_websocket_open(websocket):
            await websocket.close(code=4000, reason=str(e))
        
    except Exception as e:
        # Log unexpected errors
        print(f"❌ WebSocket error: {str(e)}")
        await log_error(
            error=e,
            location="transcription/routes.py - transcription_websocket",
            additional_info={"transcription_session_id": transcription_session_id}
        )
        # 🔒 ONLY CLOSE IF NOT ALREADY CLOSED
        if is_websocket_open(websocket):
            try:
                await websocket.close(code=1011, reason="Internal server error")
            except:
                pass  # Already closed by client or network
        
    finally:
        print(f"🧹 Cleaning up WebSocket session {transcription_session_id}")
        # Cancel any active background tasks
        try:
            for task_id, task in active_tasks.items():
                if not task.done():
                    print(f"🛑 Cancelling background task for chunk {task_id}")
                    task.cancel()
            # Wait for tasks to finish cancelling (with timeout)
            if active_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*active_tasks.values(), return_exceptions=True),
                        timeout=5.0
                    )
                except asyncio.TimeoutError:
                    print(f"⚠️ Some background tasks didn't cancel within 5 seconds")
        except Exception:
            pass
        # Always mark as disconnected when WebSocket closes
        try:
            await mark_websocket_disconnected(transcription_session_id)
        except:
            pass  # Don't fail if cleanup fails
        

@router.get("/health", response_model=dict)
async def transcription_health_check():
    """
    Health check for transcription module.
    Verifies database, blob storage, and OpenAI API connectivity.
    """
    try:
        from app.database.mongo import get_db
        from app.database.blob import get_blob_client
        from app.core.llm import get_openai_client
        
        health_status = {
            "status": "healthy",
            "module": "transcription",
            "checks": {}
        }
        
        # Check MongoDB connection
        try:
            db = await get_db()
            await db.command('ping')
            health_status["checks"]["database"] = "connected"
        except Exception as e:
            health_status["checks"]["database"] = f"error: {str(e)}"
            health_status["status"] = "unhealthy"
        
        # Check Blob Storage connection
        try:
            blob_client = await get_blob_client()
            # Try to list containers (lightweight check)
            containers = blob_client.list_containers()
            async for container in containers:
                break  # Just test we can iterate
            health_status["checks"]["blob_storage"] = "connected"
        except Exception as e:
            health_status["checks"]["blob_storage"] = f"error: {str(e)}"
            health_status["status"] = "unhealthy"
        
        # Check OpenAI API connection
        try:
            openai_client = await get_openai_client()
            # Simple API test (doesn't count against usage)
            models = await openai_client.models.list()
            health_status["checks"]["openai_api"] = "connected"
        except Exception as e:
            health_status["checks"]["openai_api"] = f"error: {str(e)}"
            health_status["status"] = "unhealthy"
        
        return health_status
        
    except Exception as e:
        await log_error(
            error=e,
            location="transcription/routes.py - transcription_health_check",
            additional_info={}
        )
        
        return {
            "status": "unhealthy",
            "module": "transcription", 
            "error": "Health check failed"
        }
