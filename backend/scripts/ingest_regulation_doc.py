"""① 知识库补录管线 — 上传前预处理 → ragplus 上传 → 探针命中验证（P1-1 R3b）。

流程：
1. ``--table-style``：表格源 CSV（条文号,内容）→ 每行前缀 ``《法规名》第X条：``
   的结构化文本后上传（引擎切片即可命中条文上下文）；
   常规模式：PDF 原样上传；
2. 复用 ``ragplus_sync.upload_document_to_ragplus``（KB 更新即自动失效 RAG 缓存，
   P1-1 R4）；``--dry-run`` 只产出预处理文本不上传；
3. 上传成功后用探针 query 检索验证新文档可命中（只读 search）。

安全边界：仅 ragplus 开发引擎；上传属写操作——**真实上传前须用户确认**；
不写飞书 Bitable、不发通知。

用法（cwd=backend）::

    # 表格型（如 PPE 配备表）
    .venv/bin/python scripts/ingest_regulation_doc.py --table-style \
        --file ppe.csv --title "个体防护装备配备规范" \
        --probe "安全帽过期" --probe "安全带"

    # PDF 常规（如 GB 30871，待业务提供 PDF 后执行）
    .venv/bin/python scripts/ingest_regulation_doc.py \
        --file gb30871.pdf --title "GB 30871-2022 危险化学品企业特殊作业安全规范" \
        --probe "受限空间作业" --probe "动火作业未办理作业票" --confirm
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from collections.abc import Callable
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any

sys.path.insert(0, os.getcwd())

from app.modules.safety.knowledge import ragplus_sync  # noqa: E402


def _load_eval_module() -> Any:
    """按路径加载评测脚本（复用 ``normalize_name`` 归一口径，避免复制漂移）。"""
    script = Path(__file__).resolve().parent / "hazard_retrieval_eval.py"
    spec = spec_from_file_location("hazard_retrieval_eval", script)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# 文档名归一唯一事实源：hazard_retrieval_eval.normalize_name
normalize_doc_name = _load_eval_module().normalize_name

SearchFn = Callable[..., Any]  # async (question, top_k=8) -> list[RagplusHit-like]

_CONTENT_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _content_type_for(file_name: str) -> str:
    """按文件后缀给上传 content-type（默认 PDF）。"""
    return _CONTENT_TYPES.get(Path(file_name).suffix.lower(), "application/pdf")


def parse_table_csv(path: Path) -> list[tuple[str, str]]:
    """表格 CSV（列：条文号,内容）→ (条文号, 内容) 行；跳过表头与空行。"""
    rows: list[tuple[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        for index, row in enumerate(reader):
            if not row or all(not cell.strip() for cell in row):
                continue
            if index == 0 and any(
                header.strip() in ("条文号", "条款", "编号") for header in row
            ):
                continue
            if len(row) < 2:
                continue
            article, content = row[0].strip(), row[1].strip()
            if article and content:
                rows.append((article, content))
    return rows


def table_to_context_text(
    rows: list[tuple[str, str]], *, doc_title: str
) -> str:
    """(条文号, 内容) 行 → 带条文上下文的结构化文本（每行一个可检索单元）。"""
    lines = [
        f"《{doc_title}》第{article}条：{content}"
        for article, content in rows
    ]
    return "\n".join(lines) + "\n"


async def verify_probe_hits(
    probes: list[str], doc_title: str, *, search: SearchFn | None = None
) -> tuple[bool, dict[str, bool]]:
    """探针 query 检索验证：每个探针的 top 命中文档里应出现新补录文档。

    ``search`` 可注入 fake（单测）；默认 ragplus 客户端。检索异常按 miss 计
    （不抛——补录后验证失败 ≠ 补录失败，报告呈现即可）。
    """
    if not probes:
        return True, {}
    if search is None:
        from app.modules.safety.knowledge.ragplus_client import get_ragplus_client

        client = get_ragplus_client()
        search = client.search
    target = normalize_doc_name(doc_title)
    detail: dict[str, bool] = {}
    for probe in probes:
        try:
            hits = await search(probe, top_k=8)
            names = [normalize_doc_name(getattr(h, "doc_name", "") or "") for h in hits]
            detail[probe] = any(
                target in name or name in target for name in names if name
            )
        except Exception:  # noqa: BLE001 — 验证失败按 miss，不阻断
            detail[probe] = False
    return all(detail.values()), detail


async def run_ingest(
    *,
    file: Path,
    title: str,
    probes: list[str],
    table_style: bool,
    confirm: bool,
    dry_run: bool,
    kb_name: str,
) -> int:
    """补录主流程：预处理（可选）→ dry-run/确认 → 上传 → 探针验证。"""
    if table_style:
        rows = parse_table_csv(file)
        if not rows:
            print(f"表格源无有效行: {file}")
            return 1
        text = table_to_context_text(rows, doc_title=title)
        blob = text.encode("utf-8")
        file_name = file.stem + ".txt"
        content_type = "text/plain"
        print(f"表格预处理: {len(rows)} 行 → {file_name}")
    else:
        blob = file.read_bytes()
        file_name = file.name
        content_type = _content_type_for(file_name)

    if dry_run:
        out = file.with_suffix(".preview.txt")
        out.write_bytes(blob)
        print(f"dry-run：预处理文本已写入 {out}（未上传）")
        return 0

    if not confirm:
        print(
            f"真实上传前须确认：KB={kb_name} 文件={file_name} 大小={len(blob)}B "
            "标题=" + title + "（--confirm 后执行）"
        )
        return 1

    ok = await ragplus_sync.upload_document_to_ragplus(
        domain="regulation",
        biz_key=f"manual-{file.stem}",
        title=title,
        file_name=file_name,
        blob=blob,
        content_type=content_type,
        kb_name=kb_name,
    )
    if not ok:
        print("上传/解析失败（详见 ragplus_sync 日志；映射行 status=failed）")
        return 1
    print(f"上传完成: {title}（RAG 缓存已自动失效）")

    hit, detail = await verify_probe_hits(probes, title)
    for probe, passed in detail.items():
        print(f"探针 {probe!r}: {'命中' if passed else '未命中'}")
    if not hit:
        print("⚠️ 探针未全命中——补录后检索验证不通过，请人工复核切片")
        return 2
    print("✅ 探针全部命中，补录闭环完成")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="① 知识库补录管线（P1-1 R3b）")
    parser.add_argument("--file", required=True, help="PDF 或表格 CSV 路径")
    parser.add_argument("--title", required=True, help="法规/制度完整标题")
    parser.add_argument("--probe", action="append", default=[],
                        help="补录后验证探针 query（可多次）")
    parser.add_argument("--table-style", action="store_true", help="表格型预处理上传")
    parser.add_argument("--dry-run", action="store_true", help="只产出预处理文本不上传")
    parser.add_argument("--confirm", action="store_true", help="确认真实上传")
    parser.add_argument("--kb", default=ragplus_sync.KB_REGULATION, help="目标知识库名")
    args = parser.parse_args(argv)
    return asyncio.run(
        run_ingest(
            file=Path(args.file),
            title=args.title,
            probes=args.probe,
            table_style=args.table_style,
            confirm=args.confirm,
            dry_run=args.dry_run,
            kb_name=args.kb,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
