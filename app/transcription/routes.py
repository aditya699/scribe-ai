"""
Author: Aditya Bhatt
"""
from fastapi import APIRouter, HTTPException, WebSocket, status, Response
from .schemas import StartTranscriptionRequest, StartTranscriptionResponse, EndTranscriptionRequest, EndTranscriptionResponse, AudioChunkMetadata, TranscriptUpdate, WebSocketError, ConnectionConfirmed
from .utils import start_transcription_session, end_transcription_session, validate_websocket_connection, mark_websocket_connected, mark_websocket_disconnected, process_websocket_message, process_audio_chunk
from app.database.mongo import log_error

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
        await websocket.send_text(confirmation.model_dump_json())
        
        # 5. Keep connection alive and process messages
        expected_sequence = 0  # Track expected chunk sequence
        
        while True:
            # Wait for messages from mobile app
            message = await websocket.receive()
            
            if "text" in message:
                # Text message (JSON metadata)
                import json
                try:
                    json_data = json.loads(message["text"])
                    response = await process_websocket_message(transcription_session_id, json_data)
                    await websocket.send_text(json.dumps(response))
                except json.JSONDecodeError:
                    error_response = {
                        "type": "error",
                        "error_code": "INVALID_JSON",
                        "error_message": "Invalid JSON format"
                    }
                    await websocket.send_text(json.dumps(error_response))
                    
            elif "bytes" in message:
                # Binary message (audio data)
                audio_data = message["bytes"]
                response = await process_audio_chunk(
                    transcription_session_id, 
                    expected_sequence, 
                    audio_data
                )
                await websocket.send_text(json.dumps(response))
                expected_sequence += 1  # Increment for next chunk
                
            else:
                # Unknown message type
                error_response = {
                    "type": "error", 
                    "error_code": "UNKNOWN_MESSAGE_TYPE",
                    "error_message": "Message must be text or binary"
                }
                await websocket.send_text(json.dumps(error_response))
            
    except ValueError as e:
        # Validation failed - close connection with error
        await websocket.close(code=4000, reason=str(e))
        
    except Exception as e:
        # Log unexpected errors
        await log_error(
            error=e,
            location="transcription/routes.py - transcription_websocket",
            additional_info={"transcription_session_id": transcription_session_id}
        )
        await websocket.close(code=1011, reason="Internal server error")
        
    finally:
        # Always mark as disconnected when WebSocket closes
        try:
            await mark_websocket_disconnected(transcription_session_id)
        except:
            pass  # Don't fail if cleanup fails