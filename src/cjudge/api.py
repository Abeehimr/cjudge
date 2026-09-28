import os

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=os.getenv("CJUDGE_ALLOWED_HOSTS", "localhost,127.0.0.1").split(","),
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/ready")
async def ready() -> dict[str, str]:
    try:
        engine = create_engine(os.environ["DATABASE_URL"], connect_args={"connect_timeout": 2})
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()
    except (KeyError, SQLAlchemyError) as error:
        raise HTTPException(status_code=503, detail="Service unavailable") from error
    return {"status": "ready"}
