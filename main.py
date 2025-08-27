from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.sessions.routes import router as sessions_router
from app.transcription.routes import router as transcription_router
from app.notifications.routes import router as notifications_router
from app.database.schema_setup import setup_mongodb_schemas
from app.rag.routes import router as rag_router
import uvicorn

app = FastAPI(
    title="Medical RAG Assistant",
    description="WhatsApp-based medical consultation system",
    version="1.0.0"
)

@app.on_event("startup")
async def startup_event():
    """Initialize database schemas and indexes on startup"""
    await setup_mongodb_schemas()
    

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(transcription_router)
app.include_router(notifications_router)    
app.include_router(rag_router)

@app.get("/")
async def root():
    return {"message": "Medical RAG Assistant API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)