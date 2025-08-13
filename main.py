from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def root():
    return {"message": "This is the backend server for the scribe-ai project"}
