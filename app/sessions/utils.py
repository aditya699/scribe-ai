from app.database.mongo import get_db, log_error
from typing import Optional
from .schemas import SessionCreateRequest, SessionResponse, SessionDB

async def create_session_in_db(session_request: SessionCreateRequest) -> SessionResponse:
    try:
        db = await get_db()
        sessions = db["sessions"]

        # 1) If client sent a request_id, check if we already processed it
        if session_request.request_id:
            existing = await sessions.find_one(
                {"request_id": session_request.request_id},
                {"_id": 0}
            )
            if existing:
                # Return the previously created session (no duplicate)
                return SessionResponse.model_validate(existing)

        # 2) Build the new session document
        session_db = SessionDB(
            doctor_id=session_request.doctor_id,
            patient_whatsapp_number=session_request.patient_whatsapp_number,
            patient_name=session_request.patient_name,
            # SessionDB now has request_id field; set it if provided
            request_id=session_request.request_id
        )

        doc = session_db.model_dump(exclude_none=True)

        # 3) Insert
        result = await sessions.insert_one(doc)
        if not result.inserted_id:
            raise Exception("Database insertion failed")

        # 4) Return typed response
        return SessionResponse.model_validate(doc)

    except Exception as e:
        await log_error(
            error=e,
            location="sessions/utils.py - create_session_in_db",
            additional_info=session_request.model_dump()
        )
        raise

async def get_session_by_id(session_id: str) -> Optional[SessionResponse]:
    try:
        db = await get_db()
        session_doc = await db["sessions"].find_one(
            {"session_id": session_id},
            {"_id": 0}
        )

        if not session_doc:
            return None

        return SessionResponse.model_validate(session_doc)

    except Exception as e:
        await log_error(
            error=e,
            location="sessions/utils.py - get_session_by_id",
            additional_info={"session_id": session_id}
        )
        raise
