import os

from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from cjudge.identity.api import router as identity_router
from cjudge.identity import checked_cipher
from cjudge.events import lifespan
from cjudge.tasks.api import router as tasks_router
from cjudge.labs.api import admin_router as labs_admin, student_router as labs_student
from cjudge.submissions.api import admin_router as submissions_admin, student_router as submissions_student
from cjudge.judging.api import router as judging_admin
from cjudge.submissions.review_api import router as review_admin
from cjudge.labs.scoreboard import router as scoreboard_router
from cjudge.authoring.api import router as authoring_admin
from cjudge.labs import exports, archive  # Register protected CSV routes before including the lab router.

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=os.getenv("CJUDGE_ALLOWED_HOSTS", "localhost,127.0.0.1").split(","),
)
app.include_router(identity_router)
app.include_router(tasks_router)
app.include_router(labs_admin)
app.include_router(labs_student)
app.include_router(submissions_admin)
app.include_router(submissions_student)
app.include_router(judging_admin)
app.include_router(review_admin)
app.include_router(scoreboard_router)
app.include_router(authoring_admin)


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
