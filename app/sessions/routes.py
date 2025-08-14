from fastapi import APIRouter, HTTPException, status, Response
from .schemas import SessionCreateRequest, SessionCreateResponse, SessionResponse
from .utils import create_session_in_db, get_session_by_id
from app.database.mongo import log_error

router = APIRouter(prefix="/v1/sessions", tags=["sessions"])

@router.post("/create", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_session(session_request: SessionCreateRequest, response: Response):
    """
    Create a new patient session.
    
    Args:
        session_request: Session creation data from mobile app
        response: FastAPI response object to set headers

    Returns:
        SessionCreateResponse with session details or error
    """
    try:
        session = await create_session_in_db(session_request)
        response.headers["Location"] = f"/v1/sessions/{session.session_id}"

        return SessionCreateResponse(
            success=True,
            message="Session created successfully",
            session=session
        )
    except Exception as e:
        await log_error(
            error=e,
            location="sessions/routes.py - create_session",
            additional_info=session_request.model_dump()
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create session. Please try again."
        )

@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """
    Retrieve a session by its ID.
    
    Args:
        session_id: The unique session identifier
        
    Returns:
        SessionResponse with session details
    """
    try:
        session = await get_session_by_id(session_id)
        
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Session with ID {session_id} not found"
            )
            
        return session
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Log unexpected errors
        await log_error(
            error=e,
            location="sessions/routes.py - get_session",
            additional_info={"session_id": session_id}
        )
        
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve session"
        )

@router.get("/", response_model=dict)
async def health_check():
    """Health check for sessions module"""
    return {"status": "healthy", "module": "sessions"}