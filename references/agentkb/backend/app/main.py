import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api import (
    assignments,
    auth,
    candidates,
    chat,
    documents,
    interviews,
    jobs,
    knowledge_bases,
    model_configs,
    resumes,
    search_chat,
    users,
    workspaces,
)
from app.core.config import settings
from app.core.logging import request_id_var, setup_logging

setup_logging()

app = FastAPI(title=settings.app_name)

_STATUS_CODES = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    413: "FILE_TOO_LARGE",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
}

@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={"code": "VALIDATION_ERROR", "message": str(exc.errors()), "detail": None})

@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    return JSONResponse(status_code=409, content={"code": "CONFLICT", "message": "数据冲突，可能为重复提交", "detail": None})

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", _STATUS_CODES.get(exc.status_code, "INTERNAL_ERROR"))
        message = exc.detail.get("message", "")
    else:
        code = _STATUS_CODES.get(exc.status_code, "INTERNAL_ERROR")
        message = str(exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"code": code, "message": message, "detail": None})

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务器内部错误", "detail": {"request_id": request_id_var.get()}},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_request_id(request: Request, call_next):
    rid = str(uuid.uuid4())[:8]
    request_id_var.set(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


MAX_IMPORT_BODY_BYTES = 10 * 1024 * 1024  # 10MB：JSON 导入请求体上限（配合 records ≤100 双保险）


@app.middleware("http")
async def limit_resume_import_body(request: Request, call_next):
    if (request.method == "POST"
            and request.url.path.startswith("/api/v1/workspaces/")
            and request.url.path.endswith("/resumes/import")):
        length = request.headers.get("content-length")
        if length is not None and length.isdigit() and int(length) > MAX_IMPORT_BODY_BYTES:
            return JSONResponse(status_code=413, content={
                "code": "FILE_TOO_LARGE", "message": f"导入请求体超过 {MAX_IMPORT_BODY_BYTES} 限制", "detail": None})
    return await call_next(request)

@app.get("/health")
async def health():
    return {"status": "ok"}

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(workspaces.router)
app.include_router(model_configs.router)
app.include_router(knowledge_bases.router)
app.include_router(documents.router)
app.include_router(interviews.router)
app.include_router(resumes.router)
app.include_router(candidates.router)
app.include_router(assignments.router)
app.include_router(jobs.router)
app.include_router(search_chat.router)
app.include_router(chat.router)