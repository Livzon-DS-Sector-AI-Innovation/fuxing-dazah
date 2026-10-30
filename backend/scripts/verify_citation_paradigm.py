"""实弹验证：引用编号锚定契约（2026-10-30 修复后回归）。

直接调用 run_knowledge_chat（与 agent 工具同一条链路），
检查：answer 中 [N] 引用的文档与 sources[N-1] 是否一致、
是否存在给 sources 之外标准名标号的情况、末尾是否自带参考区块。

用法：cd backend && .venv/bin/python scripts/verify_citation_paradigm.py [query]
"""
from __future__ import annotations

import asyncio
import re
import sys

from app.core.database import async_session_factory


async def main() -> None:
    query = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "知识库中有这个规范吗？ SH/T 3020-2013《石油化工仪表供气设计规范》6.1.2"
    )
    from app.modules.safety.knowledge.query_service import run_knowledge_chat

    async with async_session_factory() as db:
        answer, sources = await run_knowledge_chat(
            query=query, db=db, user_id=None, enable_web_search=False,
        )

    print("═" * 60)
    print("ANSWER:")
    print(answer)
    print("═" * 60)
    print(f"SOURCES ({len(sources)}):")
    for i, s in enumerate(sources, 1):
        print(f"  [{i}] {s.get('doc_title')}  ref={s.get('article_ref')}")

    # ── 契约校验 ──
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    ok = True
    if any(n < 1 or n > len(sources) for n in cited):
        print(f"❌ 越界编号: {[n for n in cited if n > len(sources)]}")
        ok = False
    # 检查每个 [N] 前的《...》是否与 sources[N-1].doc_title 相容
    for m in re.finditer(r"《([^》]{4,80})》\s*\[(\d+)\]", answer):
        title, n = m.group(1), int(m.group(2))
        src_title = sources[n - 1]["doc_title"] if 1 <= n <= len(sources) else ""
        key = re.sub(r"[-/\\s︱︱（）() _]+", "", title)[:10]
        src_key = re.sub(r"[-/\\s︱︱（）() _]+", "", src_title)[:10]
        if key and src_key and key[:6] not in src_key and src_key[:6] not in key:
            print(f"❌ 编号错位: 《{title}》[{n}] 但 sources[{n}] = {src_title}")
            ok = False
    if re.search(r"(📚|📖)\s*参考", answer) or "## 参考法规" in answer:
        print("❌ 回答自带参考法规区块（应剥离/禁止）")
        ok = False
    print("─" * 60)
    print("✅ 引用编号契约校验通过" if ok else "❌ 存在违约，见上")


if __name__ == "__main__":
    asyncio.run(main())
