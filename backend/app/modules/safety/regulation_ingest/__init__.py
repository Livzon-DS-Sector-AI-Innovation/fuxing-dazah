"""法规收录服务（regulation_ingest）——契约①接收侧执行层。

爬取/解析/暂存在 ragplus-x（知识层）；本包只做业务收录：预去重 →
AI 相关性判定 → 写 Bitable 台账（含修订编排）→ 契约②生命周期回执 →
doc_map 登记 → 飞书推送 → run 级留痕。
"""

from app.modules.safety.regulation_ingest.service import RegulationIngestService

__all__ = ["RegulationIngestService"]
