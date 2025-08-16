
"""
Transcription module schemas - Step 1: Status tracking only
Author: Aditya Bhatt
"""
from enum import Enum
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from typing import Optional
import uuid

def utc_now():
    """Returns current UTC time with timezone info"""
    return datetime.now(timezone.utc)

class TranscriptionStatus(str, Enum):
    """Real-time transcription session status"""
    starting = "starting"           # Session initiated, waiting for first audio
    streaming = "streaming"         # Actively receiving and processing audio chunks  
    ending = "ending"              # Doctor clicked end, finalizing transcription
    completed = "completed"        # Final transcript ready
    failed = "failed"             # Technical failure in processing


class TranscriptionSession(BaseModel):
    """Real-time transcription session - tracks entire conversation"""
    transcription_session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = Field(..., description="Parent patient session")
    
    # Session state
    status: TranscriptionStatus = TranscriptionStatus.starting
    started_at: datetime = Field(default_factory=utc_now)
    ended_at: Optional[datetime] = None
    
    # WebSocket connection tracking
    websocket_connected: bool = Field(default=False, description="Is WebSocket currently connected")
    websocket_connected_at: Optional[datetime] = None
    websocket_disconnected_at: Optional[datetime] = None

    # Transcription results
    transcript: str = Field(default="", description="Transcript text (updates as audio processes)")
    
    # Error handling
    error_message: Optional[str] = None

class StartTranscriptionRequest(BaseModel):
    """Request to start real-time transcription"""
    session_id: str = Field(..., description="Patient session to start transcribing")

class StartTranscriptionResponse(BaseModel):
    """Response when transcription session starts"""
    success: bool
    message: str
    transcription_session_id: str

class EndTranscriptionRequest(BaseModel):
    """Request to end transcription session"""
    transcription_session_id: str = Field(..., description="Transcription session to end")

class EndTranscriptionResponse(BaseModel):
    """Response when transcription session ends"""
    success: bool
    message: str


class AudioChunkMetadata(BaseModel):
    """Metadata sent before audio chunk via WebSocket"""
    type: str = Field(default="audio_chunk_metadata", description="Message type identifier")
    sequence_number: int = Field(..., description="Chunk order (0, 1, 2...)")
    chunk_size_bytes: int = Field(..., description="Size of audio data in bytes")
    duration_seconds: float = Field(..., description="Duration of audio chunk (8-10 seconds)")

class TranscriptUpdate(BaseModel):
    """Real-time transcript update sent via WebSocket"""
    type: str = Field(default="transcript_update", description="Message type identifier")
    sequence_number: int = Field(..., description="Which chunk this transcript is for")
    partial_transcript: str = Field(..., description="Transcript from this specific chunk")
    full_transcript: str = Field(..., description="Complete transcript from all chunks so far")
    processing_time_ms: int = Field(..., description="How long transcription took")

class AudioChunk(BaseModel):
    """Individual audio chunk in real-time stream"""
    chunk_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    transcription_session_id: str = Field(..., description="Parent transcription session")
    sequence_number: int = Field(..., description="Order in the audio stream (0, 1, 2...)")
    blob_path: str = Field(..., description="Path to chunk in blob storage")
    uploaded_at: datetime = Field(default_factory=utc_now)

class AudioChunkUpload(BaseModel):
    """Request to upload an audio chunk"""
    transcription_session_id: str = Field(..., description="Transcription session this chunk belongs to")
    sequence_number: int = Field(..., description="Chunk order (0, 1, 2...)")

class AudioChunkResponse(BaseModel):
    """Response when audio chunk is processed"""
    success: bool
    message: str
    chunk_id: str = Field(..., description="ID of the processed chunk")
    partial_transcript: str = Field(default="", description="Transcript text from this chunk")
    full_transcript: str = Field(..., description="Complete transcript so far")

class WebSocketError(BaseModel):
    """Error message sent via WebSocket when something goes wrong"""
    type: str = Field(default="error", description="Message type identifier")
    error_code: str = Field(..., description="Error code for mobile app to handle")
    error_message: str = Field(..., description="Human readable error description")
    sequence_number: Optional[int] = Field(None, description="Which chunk caused the error, if applicable")

class ConnectionConfirmed(BaseModel):
    """Message sent when WebSocket connection is established"""
    type: str = Field(default="connection_confirmed", description="Message type identifier")
    transcription_session_id: str = Field(..., description="Confirmed transcription session ID")
    message: str = Field(default="WebSocket connected, ready to receive audio", description="Status message")
    max_chunk_size_bytes: int = Field(default=1048576, description="Maximum audio chunk size (1MB)")
    expected_chunk_duration_seconds: int = Field(default=8, description="Expected audio chunk duration")