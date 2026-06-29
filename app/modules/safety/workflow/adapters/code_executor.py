"""DazahCodeExecutor — Python 代码沙箱执行器。

graphon 的 code 节点调用 CodeExecutorProtocol.execute()。
此适配器提供简单的 subprocess 隔离执行。
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DazahCodeExecutor:
    """Python 代码沙箱执行器。

    第一阶段使用 subprocess 提供基本隔离。
    后续可升级为 Docker 沙箱增强安全性。
    """

    def __init__(self, timeout: int = 30):
        self._timeout = timeout

    def execute(
        self, code: str, inputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """在受限环境中执行 Python 代码。

        Args:
            code: Python 代码，必须定义 main(inputs) -> dict 函数
            inputs: 传递给 main() 的输入变量

        Returns:
            main() 的返回值

        Raises:
            subprocess.TimeoutExpired: 执行超时
            RuntimeError: 代码执行异常
        """
        inputs = inputs or {}

        # 构建完整的 Python 脚本
        script = self._build_script(code, inputs)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8",
        ) as f:
            f.write(script)
            script_path = f.name

        try:
            result = subprocess.run(
                ["python", script_path],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"代码执行失败 (exit={result.returncode}): {result.stderr[:500]}"
                )

            # 解析 stdout 中的 JSON 输出
            import json as _json
            output_text = result.stdout.strip()
            if not output_text:
                return {}

            # 取最后一行 JSON
            for line in reversed(output_text.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    try:
                        return _json.loads(line)
                    except _json.JSONDecodeError:
                        pass
            return {}

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"代码执行超时（>{self._timeout}s）")
        finally:
            Path(script_path).unlink(missing_ok=True)

    def _build_script(self, code: str, inputs: dict[str, Any]) -> str:
        """将用户代码包装为可执行的完整 Python 脚本。"""
        import json as _json

        return f"""\
# -*- coding: utf-8 -*-
import json as _json
import math
import re
import datetime

# ---- 用户代码 ----
{code}

# ---- 自动执行 ----
if __name__ == "__main__":
    inputs = _json.loads({_json.dumps(_json.dumps(inputs, ensure_ascii=False))})
    result = main(inputs)
    print(_json.dumps(result, ensure_ascii=False))
"""
