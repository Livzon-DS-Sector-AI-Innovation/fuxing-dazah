from typing import Any

from fastapi.responses import JSONResponse

from app.shared.schemas import ApiResponse


def success_response(
    data: Any = None,
    message: str = "success",
    meta: dict[str, Any] | None = None,
    status_code: int = 200,
) -> JSONResponse:
    body = ApiResponse(code=status_code, message=message, data=data, meta=meta)
    return JSONResponse(content=body.model_dump(mode="json"), status_code=status_code)


def error_response(
    message: str = "请求错误",
    detail: str | None = None,
    status_code: int = 400,
) -> JSONResponse:
    body: dict[str, Any] = {
        "code": status_code,
        "message": message,
    }
    if detail:
        body["detail"] = detail
    return JSONResponse(content=body, status_code=status_code)


def paginated_response(
    data: list[Any],
    page: int,
    page_size: int,
    total: int,
    message: str = "success",
) -> JSONResponse:
    return success_response(
        data=data,
        message=message,
        meta={
            "page": page,
            "page_size": page_size,
            "total": total,
        },
    )
