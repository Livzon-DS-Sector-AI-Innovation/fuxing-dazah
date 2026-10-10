"""一次性脚本：收缩 backend/.env.example 的 SAFETY 段为「凭证 + AI keys + 指引」。

删除策略（按块）：
- 以「# ---- 安全模块」开头到下一个空行的块，若块内含被迁移的 SAFETY_ 键则整块删除；
- 主段（# —— 安全模块 safety ——）重写为迁移后说明；
- 保留：SAFETY_FEISHU_APP_ID/SECRET、SAFETY_AI_*、SAFETY_EMBEDDING_*。
"""

from pathlib import Path

KEEP = {
    "SAFETY_FEISHU_APP_ID",
    "SAFETY_FEISHU_APP_SECRET",
    "SAFETY_AI_TEXT_API_KEY",
    "SAFETY_AI_TEXT_BASE_URL",
    "SAFETY_AI_TEXT_MODEL",
    "SAFETY_AI_VISION_API_KEY",
    "SAFETY_AI_VISION_BASE_URL",
    "SAFETY_AI_VISION_MODEL",
    "SAFETY_AI_TEXT_BACKUP_API_KEY",
    "SAFETY_AI_TEXT_BACKUP_BASE_URL",
    "SAFETY_AI_TEXT_BACKUP_MODEL",
    "SAFETY_EMBEDDING_API_KEY",
    "SAFETY_EMBEDDING_BASE_URL",
    "SAFETY_EMBEDDING_MODEL",
}

path = Path(__file__).resolve().parents[2] / ".env.example"
lines = path.read_text(encoding="utf-8").splitlines()

out: list[str] = []
i = 0
removed_blocks = 0
while i < len(lines):
    line = lines[i]
    # 「# ---- 安全模块…」或「# —— 安全模块…」块头：收集到块尾（空行/下一个非本块行）
    if line.startswith("# ---- 安全模块") or (
        line.startswith("# —— 安全模块 safety ——")
    ):
        # 主段头重写
        if line.startswith("# —— 安全模块 safety ——"):
            out.append("# —— 安全模块 safety ——")
            out.append("# 1) 独立飞书应用凭证（事件订阅 / 多维表格 / 消息推送；WS 长连接由凭证存在性控制）")
            out.append("# 2) AI 模型配置（走 ai_config 配置中心：DB 活行 > env > registry 默认）")
            out.append("# 其余全部 SAFETY_* 配置（推送群/功能开关/直读闸门/轮询参数/平台凭证等）")
            out.append("# 已迁「应用配置中心」：safety.app_config_entries 表，前端 安全→系统→应用配置；")
            out.append("# 生效优先级 env（应急通道）> DB 活行 > 代码默认；启动播种把 .env 现值固化进 DB，")
            out.append("# 此后清空本文件中对应键即完成切换（2026-10-10 env→DB 迁移）。")
            i += 1
            continue
        # 迁移块：块 = 头注释 + 后续连续注释/键行，直到空行
        j = i
        block: list[str] = []
        while j < len(lines) and lines[j].strip() != "":
            block.append(lines[j])
            j += 1
        has_migrated = any(
            ln.startswith("SAFETY_") and ln.split("=", 1)[0] not in KEEP for ln in block
        )
        if has_migrated:
            removed_blocks += 1
            i = j
            continue
    out.append(line)
    i += 1

# 折叠连续空行
collapsed: list[str] = []
for ln in out:
    if ln.strip() == "" and collapsed and collapsed[-1].strip() == "":
        continue
    collapsed.append(ln)

path.write_text("\n".join(collapsed) + "\n", encoding="utf-8")
kept = [ln for ln in collapsed if ln.startswith("SAFETY_")]
print(f"removed_blocks={removed_blocks} kept_keys={len(kept)}")
for k in kept:
    print(" ", k.split("=")[0])
