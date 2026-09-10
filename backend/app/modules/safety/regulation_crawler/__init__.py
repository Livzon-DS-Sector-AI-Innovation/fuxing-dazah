"""安全生产法规标准抓取推送系统。

从外部政府网站爬取法规标准 → 写入飞书多维表格（Bitable）
→ knowledge_bitable_handler 自动同步到 PostgreSQL → RAG 检索。

架构：
- engine/   — 爬虫引擎（策略模式：API / Playwright / HTTP 解析）
- writer/   — Bitable 写入适配（字段映射 + 去重）
- notifier/ — 飞书卡片推送
- api.py    — Webhook 接收 + 手动触发 API
- service.py — 编排调度服务
"""

from app.modules.safety.regulation_crawler.service import RegulationCrawlerService

__all__ = ["RegulationCrawlerService"]
