from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional
import uuid

class SessionCreateRequest(BaseModel):
    doctor_id: str = Field(..., description="Doctor's Registration Number")
    patient_whatsapp_number: str = Field(..., description="Patient's WhatsApp number")
    patient_name: str = Field(..., description="Patient's full name")

class SessionResponse(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    doctor_id: str
    patient_whatsapp_number: str
    patient_name: str
    created_at: datetime
    status: str = "active"

class SessionCreateResponse(BaseModel):
    success: bool
    message: str
    session: SessionResponse