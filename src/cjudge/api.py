import os

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from cjudge.identity_api import router as identity_router
from cjudge.identity import checked_cipher
from cjudge.events import lifespan
from cjudge.tasks_api import router as tasks_router
from cjudge.labs_api import admin_router as labs_admin, student_router as labs_student

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=os.getenv("CJUDGE_ALLOWED_HOSTS", "localhost,127.0.0.1").split(","),
)
app.include_router(identity_router)
app.include_router(tasks_router)
app.include_router(labs_admin)
app.include_router(labs_student)


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
                checked_cipher(connection)
        finally:
            engine.dispose()
    except (KeyError, SQLAlchemyError, RuntimeError) as error:
        raise HTTPException(status_code=503, detail="Service unavailable") from error
    return {"status": "ready"}
