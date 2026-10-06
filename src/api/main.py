from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os

app = FastAPI(title="MVP Licitaciones API", version="1.0.0")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict to the Web UI origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DA-10: Autenticación delegada con OpenID Connect y autorización basada en roles en la API
def verify_token(token: str):
    # TODO: Implement OIDC token verification against Identity Provider
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return {"user_id": "mock_user", "role": "Analista Comercial"}

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/api/v1/analysis")
async def request_analysis(licitacion_id: str):
    # ASR-11: API responde 202 con identificador de tarea y encola el trabajo
    # TODO: Enqueue to Azure Service Bus
    task_id = "mock_task_id"
    return {"task_id": task_id, "status": "accepted"}

@app.get("/api/v1/analysis/{task_id}")
async def get_analysis_status(task_id: str):
    # TODO: Query DB for task status
    return {"task_id": task_id, "status": "processing"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
