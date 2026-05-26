from fastapi import HTTPException, status


class AppException(HTTPException):
    def __init__(
        self,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        message: str = "请求错误",
        detail: str | None = None,
    ) -> None:
        self.message = message
        self.detail_msg = detail
        super().__init__(status_code=status_code, detail=detail or message)


class NotFoundException(AppException):
    def __init__(self, resource: str = "资源", resource_id: str | None = None) -> None:
        message = f"{resource}不存在"
        if resource_id:
            message = f"{resource}({resource_id})不存在"
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            message=message,
        )


class DuplicateException(AppException):
    def __init__(self, field: str, value: str) -> None:
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            message=f"{field}已存在",
            detail=f"{field}: {value} 已被使用",
        )


class ForbiddenException(AppException):
    def __init__(self, message: str = "没有权限执行此操作") -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            message=message,
        )
