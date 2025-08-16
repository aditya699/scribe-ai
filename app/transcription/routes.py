"""
Author: Aditya Bhatt
"""
from fastapi import APIRouter, HTTPException, status, Response
from .schemas import StartTranscriptionRequest, StartTranscriptionResponse, EndTranscriptionRequest, EndTranscriptionResponse
from .utils import start_transcription_session, end_transcription_session
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