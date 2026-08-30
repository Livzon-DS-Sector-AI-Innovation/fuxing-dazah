"""PDF 渲染回归测试：pdfium 并发渲染堆破坏（进程崩溃）。

背景：pypdfium2（pdfium）在 macOS 上并发渲染会破坏堆，进程直接 SIGABRT
（malloc: pointer being freed was not allocated）。此类崩溃无法在测试进程内
捕获（崩溃会杀死 pytest 本身），必须用子进程隔离执行并发渲染，断言退出码为 0。
修复方式：render_pdf_images_as_base64 内部用模块级锁串行化渲染。
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[3]

# 子进程脚本：并发调用渲染封装（若渲染未串行化会堆破坏崩溃）
RENDER_SCRIPT = textwrap.dedent(
    """
    import asyncio

    import pymupdf

    from app.modules.meter.ai_service import render_pdf_images_as_base64

    def make_pdf(i: int) -> bytes:
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((50, 100), f"校准日期: 2026-08-{i:02d}", fontsize=14)
        return doc.tobytes()

    async def main() -> None:
        pdfs = [make_pdf(i) for i in range(4)]
        # 模拟 analyze 的 4 并发：同时发起 4 个渲染
        for _ in range(10):
            results = await asyncio.gather(
                *(render_pdf_images_as_base64(p) for p in pdfs)
            )
            assert all(len(r) == 1 for r in results)

    asyncio.run(main())
    print("RENDER OK")
    """
)


def test_concurrent_pdf_render_does_not_crash() -> None:
    """4 并发 PDF 渲染应稳定完成，进程不应因 pdfium 堆破坏而崩溃。"""
    result = subprocess.run(
        [sys.executable, "-c", RENDER_SCRIPT],
        capture_output=True,
        cwd=BACKEND_ROOT,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, (
        f"并发渲染进程崩溃（exit={result.returncode}）:\n{result.stderr.decode()}"
    )
    assert b"RENDER OK" in result.stdout
