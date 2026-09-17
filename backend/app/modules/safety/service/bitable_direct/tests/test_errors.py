"""底座异常层级单测：既有 except 语义必须继续成立。"""

from __future__ import annotations

import pytest

from app.modules.safety.service.bitable_direct import errors


class TestErrorHierarchy:
    def test_base_is_runtime_error(self) -> None:
        assert issubclass(errors.BitableDirectError, RuntimeError)

    @pytest.mark.parametrize(
        "name",
        ["BitableQueryError", "BitableWriteError", "BitableConfigError"],
    )
    def test_subclasses_inherit_base(self, name: str) -> None:
        cls = getattr(errors, name)
        assert issubclass(cls, errors.BitableDirectError)

    def test_catchable_as_runtime_error(self) -> None:
        with pytest.raises(RuntimeError):
            raise errors.BitableQueryError("拉取失败")

    def test_catchable_as_base(self) -> None:
        with pytest.raises(errors.BitableDirectError):
            raise errors.BitableConfigError("连接未配置")

    def test_message_is_preserved(self) -> None:
        exc = errors.BitableWriteError("回写失败 code=1254045")
        assert "1254045" in str(exc)
