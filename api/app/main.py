# api/app/main.py
from fastapi import FastAPI

app = FastAPI(
    title="Gun Violence Dashboard API",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}
