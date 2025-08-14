from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.sessions.routes import router as sessions_router
import uvicorn

app = FastAPI(
    title="Medical RAG Assistant",
    description="WhatsApp-based medical consultation system",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include sessions router
app.include_router(sessions_router)

@app.get("/")
async def root():
    return {"message": "Medical RAG Assistant API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)