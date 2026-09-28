import os

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=os.getenv("CJUDGE_ALLOWED_HOSTS", "localhost,127.0.0.1").split(","),
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
