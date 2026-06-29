"""Knowledge injection layer — assembles regulation knowledge cards into AI prompt context.

Before each AI hazard identification call, loads published knowledge cards from the DB
and formats them as structured Markdown for prompt injection. When ai_service is provided,
uses KnowledgeCardSelector to intelligently select only the most relevant cards.

Usage:
    from app.modules.safety.knowledge import KnowledgeInjector

    injector = KnowledgeInjector(session)
    context = await injector.build_knowledge_context()
    # -> pass to AIHazardIdentifier(knowledge_context=context)

    # With smart selection:
    context = await injector.build_knowledge_context(
        hazard_description="防爆电箱堵头未封堵",
        department="原料药生产部",
        ai_service=ai_service,
        max_cards=5,
    )
"""

from __future__ import annotations

import json as _json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.knowledge.knowledge_card import KnowledgeCard

if TYPE_CHECKING:
    from app.platform.integrations.ai.client import AIService

logger = logging.getLogger(__name__)

KNOWLEDGE_CARD_COLUMN = "knowledge_card"

KNOWLEDGE_HEADER = """## 法规知识库

⚠️ **重要指令**：以下是本次隐患识别必须严格参照的法规标准原文摘要。
所有判断（分类、类别、级别、整改建议、判定依据）必须基于以下内容，
**不得依赖你的训练记忆**。若以下内容不足以做出判断，填写“知识库信息不足，待人工确认”。
"""


class KnowledgeInjector:
    """法规知识注入器。

    在 AI 调用前从 knowledge_articles 表加载已发布的知识卡片，
    组装为 Markdown 文本注入到 prompt 中。

    支持两种加载模式：
    - 全量模式：按优先级加载全部卡片（ai_service=None）
    - 智能模式：用 AI 智能选择相关卡片后注入（ai_service 传入时）

    数据库不可用时自动降级为硬编码 fallback，确保换服务器部署时 AI 识别不受影响。
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._cache: list[KnowledgeCard] | None = None

    async def build_knowledge_context(
        self,
        hazard_description: str = "",
        department: str | None = None,
        include_priority: str = "P2",
        ai_service: AIService | None = None,
        max_cards: int = 5,
    ) -> str:
        """构建注入 prompt 的知识上下文（供 AI隐患识别 / AI整改审核 使用）。

        Args:
            hazard_description: 隐患描述文本（供智能选择器匹配）
            department: 部门名称（供智能选择器匹配）
            include_priority: 最高优先级（默认 P2 = 全部卡片）
            ai_service: 传入则启用 AI 智能卡片选择；不传入则加载全部卡片
            max_cards: 智能选择时的最大卡片数量

        Returns:
            组装好的 Markdown 知识上下文文本
        """
        cards = await self._load_cards(include_priority)
        if not cards:
            logger.warning("未找到已发布的知识卡片，使用空上下文")
            return "(法规知识库暂未加载，请依据通用安全知识进行判断，但不要编造法规条文。)"

        # 智能选择
        if ai_service and len(cards) > max_cards:
            from app.modules.safety.knowledge.card_selector import (
                KnowledgeCardSelector,
            )
            selector = KnowledgeCardSelector(ai_service)
            selected = await selector.select(
                cards=cards,
                hazard_description=hazard_description,
                department=department,
                max_cards=max_cards,
            )
            if selected:
                cards = selected
                logger.info(
                    "智能卡片选择: %d/%d 张被选中用于隐患识别",
                    len(cards), len(self._cache or []),
                )

        sections: list[str] = [KNOWLEDGE_HEADER]
        for card in cards:
            section = self._format_card(card)
            if section:
                sections.append(section)

        sections.append(
            "\n---\n"
            f"**知识库覆盖范围**：以上共 {len(cards)} 份法规标准文档。\n"
            "请严格基于以上原文内容进行隐患识别，并在 major_hazard_basis 中逐字引用原文条文。"
        )
        return "\n\n".join(sections)

    async def get_relevant_clauses(self, hazard_type: str, hazard_category: str) -> str:
        """获取与指定隐患类型相关的法规条文。"""
        cards = await self._load_cards("P1")
        clauses: list[str] = []
        for card in cards:
            if card.legal_basis_clauses:
                clauses.append(f"**{card.document_title}** 相关条文：\n{card.legal_basis_clauses}")
        return "\n\n".join(clauses) if clauses else ""

    async def build_context(
        self,
        categories: list[str] | None = None,
        max_cards: int = 3,
        ai_service: AIService | None = None,
        hazard_description: str = "",
    ) -> str | None:
        """按类别筛选知识卡片并组装为 Markdown 上下文（供危险源辨识 Orchestrator 使用）。

        Args:
            categories: 需要的知识卡片类别列表（如 ["laws_regulations", "standards"]），
                        None 表示不筛选类别
            max_cards: 最多注入的卡片数量（按优先级排序后取前 N 张）
            ai_service: 传入则启用 AI 智能卡片选择
            hazard_description: 隐患描述（供智能选择器匹配）

        Returns:
            组装好的 Markdown 文本，无可用卡片时返回 None
        """
        cards = await self._load_cards("P2")
        if not cards:
            return None

        # 按类别筛选
        if categories:
            cards = [c for c in cards if c.document_category in categories]

        if not cards:
            logger.warning("无匹配类别的知识卡片: categories=%s", categories)
            return None

        # 智能选择（在类别筛选之后、max_cards 截断之前）
        if ai_service and len(cards) > max_cards:
            from app.modules.safety.knowledge.card_selector import (
                KnowledgeCardSelector,
            )
            selector = KnowledgeCardSelector(ai_service)
            selected = await selector.select(
                cards=cards,
                hazard_description=hazard_description,
                max_cards=max_cards,
            )
            if selected:
                cards = selected

        # 按优先级排序，取前 N 张
        priority_order = {"P0": 0, "P1": 1, "P2": 2}
        cards.sort(key=lambda c: priority_order.get(c.priority, 2))
        cards = cards[:max_cards]

        sections: list[str] = [KNOWLEDGE_HEADER]
        for card in cards:
            section = self._format_card(card)
            if section:
                sections.append(section)

        sections.append(
            "\n---\n"
            f"**知识库覆盖范围**：以上共 {len(cards)} 份法规标准文档。\n"
            "请严格基于以上原文内容进行判断，不得依赖训练记忆。"
        )
        return "\n\n".join(sections)

    async def get_cards_summary(self) -> list[dict[str, Any]]:
        """获取知识卡片状态摘要（供诊断命令使用）。"""
        cards = await self._load_cards("P2")
        field_names = [
            "hazard_type_definitions", "hazard_category_criteria",
            "hazard_level_criteria", "key_defect_examples",
            "rectification_requirements", "legal_basis_clauses",
        ]
        return [
            {
                "title": c.document_title,
                "category": c.document_category,
                "priority": c.priority,
                "fields_populated": [n for n in field_names if getattr(c, n)],
                "version": c.version,
            }
            for c in cards
        ]

    # ── 内部：卡片加载 ──

    async def _load_cards(self, max_priority: str = "P2") -> list[KnowledgeCard]:
        """加载知识卡片（优先 DB，fallback 硬编码）。"""
        if self._cache is not None:
            return self._filter_by_priority(self._cache, max_priority)

        cards: list[KnowledgeCard] = []
        # DB 异常不在此处捕获 —— 向上传播到 savepoint 层，
        # 由 savepoint handler rollback 后设置 knowledge_context = None。
        db_cards = await self._load_from_db()
        if db_cards:
            logger.info("从 DB 加载了 %d 张知识卡片", len(db_cards))
            cards = db_cards

        if not cards:
            cards = self._build_fallback_cards()
            logger.info("使用硬编码 fallback 知识卡片: %d 张", len(cards))

        self._cache = cards
        return self._filter_by_priority(cards, max_priority)

    async def _load_from_db(self) -> list[KnowledgeCard]:
        """从 safety.knowledge_articles 表加载已发布的卡片。"""
        result = await self.session.execute(
            text(
                "SELECT id, title, category, knowledge_card, card_version "
                "FROM safety.knowledge_articles "
                "WHERE status = 'published' AND knowledge_card IS NOT NULL "
                "AND is_deleted = false "
                "ORDER BY card_version DESC"
            )
        )
        rows = result.fetchall()

        cards: list[KnowledgeCard] = []
        for row in rows:
            try:
                card_data = row.knowledge_card
                if isinstance(card_data, str):
                    card_data = _json.loads(card_data)
                card_data["document_title"] = row.title or card_data.get("document_title", "")
                card_data["document_category"] = row.category or card_data.get("document_category", "")
                card_data["full_document_ref"] = str(row.id)
                card_data.setdefault("priority", "P1")
                card_data.setdefault("version", getattr(row, "card_version", 1) or 1)
                cards.append(KnowledgeCard(**card_data))
            except Exception as e:
                logger.warning("解析知识卡片失败 (article=%s): %s", row.id, e)
                continue

        return cards

    @staticmethod
    def _filter_by_priority(cards: list[KnowledgeCard], max_priority: str) -> list[KnowledgeCard]:
        """按优先级筛选卡片（P0 < P1 < P2）。"""
        priority_order = {"P0": 0, "P1": 1, "P2": 2}
        max_level = priority_order.get(max_priority, 2)
        filtered = [c for c in cards if priority_order.get(c.priority, 2) <= max_level]
        filtered.sort(key=lambda c: priority_order.get(c.priority, 2))
        return filtered

    # ═══════════════════════════════════════════════════════════════════════════
    # 硬编码 Fallback 知识卡片（26 张）
    #
    # 覆盖两份设计文件全部 25 份法规文档 + 1 份 LEC 方法论参考：
    #   - AI隐患识别Harness 第5.1节：13 份
    #   - 危险源辨识必须引用的法规标准清单：15 份
    #   - 两份重合：安全生产法、GB/T 13861、特种设备安全法
    #
    # 组织方式：
    #   ① P0 卡片（5 张）—— 核心判定与分类标准
    #   ② P1 卡片（12 张）—— 类别判定与整改措施
    #   ③ P2 卡片（8 张 + 1 方法论）—— 专项技术标准与补充
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _build_fallback_cards() -> list[KnowledgeCard]:
        """硬编码 fallback 知识卡片（P0/P1/P2 全部文档的核心内容）。

        这些卡片随代码一起部署，确保换服务器后 AI 识别立即可用。
        DB 中的知识卡片是增量优化（更完整的原文引用、更新的法规），
        优先级高于 fallback。

        覆盖两个 AI 工作流：
        - AI 隐患识别：hazard_type_definitions, hazard_category_criteria 等
        - AI 危险源辨识：通过 build_context(categories) 按脚本类别筛选注入
        """
        return [
            # ═══════════════════════════════════════════════════════════════
            # P0（5 张）—— 核心判定与分类标准
            #   GB/T 13861、GB 30871、安全生产法、重大隐患判定标准、十大禁令
            #   （Harness + 危险源辨识共用）
            # ═══════════════════════════════════════════════════════════════

            # ━━ P0-1: GB/T 13861-2022（已有卡片，保持不变）━━
            KnowledgeCard(
                document_title="GB/T 13861-2022 《生产过程危险和有害因素分类与代码》",
                document_category="standards",
                priority="P0",
                hazard_type_definitions=(
                    "该标准将危险和有害因素分为四大类：\n"
                    "1. 人的因素（代码1）：包括心理/生理性危险和有害因素（超负荷、健康异常、"
                    "从事禁忌作业、心理异常等）和行为性危险和有害因素（指挥错误、操作错误、"
                    "监护失误等）。\n"
                    "2. 物的因素（代码2）：包括物理性危险和有害因素（设备/设施/工具/附件缺陷、"
                    "防护缺陷、电伤害、噪声、振动、电离辐射、运动物伤害、明火、高低温物质、"
                    "信号缺陷、标志缺陷、有害光照等）和化学性危险和有害因素（爆炸品、压缩气体、"
                    "易燃品、有毒物质、腐蚀品、粉尘与气溶胶等）。\n"
                    "3. 环境因素（代码3）：包括室内外作业场所环境不良（地面滑、通道狭窄、照明不良、"
                    "通风不良、缺氧、空气质量差等）。\n"
                    "4. 管理因素（代码4）：包括安全管理机构不健全、制度不完善、操作规程不规范、"
                    "培训不足、安全检查不到位、应急预案不完善等。"
                ),
                hazard_category_criteria=(
                    "该标准按代码分类对应以下典型危险和有害因素类别：\n"
                    "- 设备设施：对应代码2中设备/设施/工具/附件缺陷（代码2101）\n"
                    "- 危化储存：对应代码2中化学性危险和有害因素（代码22）\n"
                    "- 应急管理：对应代码4中应急救援体系缺陷\n"
                    "- 仪表+电气：对应代码2中电伤害（代码2104）、信号缺陷（代码2111）\n"
                    "- 防雷防静电：对应代码2中防雷/防静电设施缺陷\n"
                    "- 职业健康+劳保防护：对应代码2中噪声/振动/粉尘/有毒物质，代码1中防护用品使用不当\n"
                    "- 三违作业：对应代码1中指挥错误（代码1201）、操作错误（代码1202）、监护失误（代码1203）\n"
                    "- 6S：对应代码3中室内外作业场所环境不良\n"
                    "- 标签标识：对应代码2中标志缺陷（代码2112）\n"
                    "- 工艺管理：对应代码4中操作规程不规范、工艺控制缺陷\n"
                    "- 承包商缺陷：对应代码4中承包商安全管理制度不健全\n"
                    "- 内页资料：对应代码4中安全管理规章制度不完善、记录不完整\n"
                    "- 特殊作业：对应代码1中监护失误+代码2中危险作业场所防护缺陷"
                ),
                rectification_requirements=(
                    "GB/T 13861-2022 要求对识别出的危险和有害因素，应采取以下管控措施：\n"
                    "1. 消除：优先考虑通过设计、工艺改造消除危险因素\n"
                    "2. 替代：用低危险性替代高危险性\n"
                    "3. 工程控制：采取隔离、防护、通风、除尘等工程技术措施\n"
                    "4. 管理控制：制定操作规程、安全管理制度、安全培训、安全检查\n"
                    "5. 个体防护：配备合适的劳动防护用品（PPE）"
                ),
                legal_basis_clauses=(
                    "GB/T 13861-2022 第4章：危险和有害因素分类与代码规定了生产过程危险和有害因素"
                    "的分类原则、编码方法和代码结构。"
                ),
            ),

            # ━━ P0-2: GB 30871-2022（新增 — Harness 第5.1节 #3）━━
            KnowledgeCard(
                document_title="GB 30871-2022 《危险化学品企业特殊作业安全规范》",
                document_category="standards",
                priority="P0",
                hazard_category_criteria=(
                    "GB 30871-2022 规定了8类特殊作业的安全管理要求：\n"
                    "1. 动火作业：分为特级/一级/二级动火，需办理动火作业票\n"
                    "2. 受限空间作业：进入受限空间须检测氧气/有毒气体/可燃气体浓度\n"
                    "3. 盲板抽堵作业：需制定盲板图、编号管理\n"
                    "4. 高处作业：2m及以上需佩戴安全带、设置安全绳挂点\n"
                    "5. 吊装作业：划定警戒区、持证上岗\n"
                    "6. 临时用电作业：办理临时用电票、安装漏电保护\n"
                    "7. 动土作业：开挖前确认地下管线位置\n"
                    "8. 断路作业：设置警示标识和绕行路线\n"
                    "\n"
                    "每类特殊作业均需办理《安全作业票》，明确作业负责人、监护人、"
                    "作业时间、风险辨识和防护措施。"
                ),
                key_defect_examples=(
                    "特殊作业常见缺陷：\n"
                    "- 动火作业票审批签章不完整（监护人/负责人栏空白）\n"
                    "- 受限空间作业未进行气体检测、未配备应急救援器材\n"
                    "- 高处作业未佩戴安全带、平台未设安全绳挂点\n"
                    "- 临时用电未安装漏电保护器、线路敷设不规范\n"
                    "- 吊装作业未划定警戒区、起重机未经检验\n"
                    "- 作业票审批时间与实际作业时间不符\n"
                    "- 票证过期未重新办理"
                ),
                rectification_requirements=(
                    "GB 30871-2022 第4.7条要求：特殊作业审批手续应齐全，"
                    "票证内容应填写完整。第5.2条要求：高处作业人员应正确佩戴"
                    "符合要求的安全带。\n"
                    "整改优先级：立即停止违规作业→补办审批手续→培训相关人员"
                    "→建立票证三级审核制度→每周抽查归档票证。"
                ),
                legal_basis_clauses=(
                    "GB 30871-2022 第4.7条：特殊作业审批手续应齐全，票证内容应填写完整。"
                    "第5.2条：高处作业人员应正确佩戴符合要求的安全带。"
                    "第6.3条：受限空间作业前应进行气体检测。"
                ),
            ),

            # ━━ P0-3: 安全生产法（新增 — Harness #1 + 危险源辨识清单 #1）━━
            KnowledgeCard(
                document_title="《中华人民共和国安全生产法》（2021年修订）",
                document_category="laws_regulations",
                priority="P0",
                hazard_level_criteria=(
                    "安全生产法中的隐患分级依据：\n"
                    "- 第41条：生产经营单位应当建立健全并落实生产安全事故隐患排查治理制度，"
                    "采取技术、管理措施，及时发现并消除事故隐患\n"
                    "- 第42条：生产经营场所的疏散通道应符合紧急疏散要求，"
                    "标志明显、保持畅通（违反→较大/重大隐患）\n"
                    "- 第45条：生产经营单位必须为从业人员提供符合标准的劳动防护用品，"
                    "并监督、教育从业人员按使用规则佩戴使用\n"
                    "- 第46条：进行爆破、吊装、动火、临时用电等危险作业，应安排专人进行"
                    "现场安全管理"
                ),
                legal_basis_clauses=(
                    "《安全生产法》第41条：生产经营单位应当建立健全并落实生产安全事故隐患排查治理制度。\n"
                    "第42条：生产经营场所的疏散通道应符合紧急疏散要求，标志明显、保持畅通。\n"
                    "第45条：生产经营单位必须为从业人员提供符合标准的劳动防护用品。\n"
                    "第46条：危险作业应安排专人进行现场安全管理。\n"
                    "第62条：生产经营单位使用劳务派遣人员，劳务派遣人员与本单位从业人员"
                    "享有同等安全生产权利。"
                ),
            ),

            # ━━ P0-4: 化工重大隐患判定标准（已有卡片，保持不变）━━
            KnowledgeCard(
                document_title="《化工和危险化学品生产经营单位重大生产安全事故隐患判定标准（试行）》",
                document_category="laws_regulations",
                priority="P0",
                hazard_level_criteria=(
                    "依据该判定标准，以下情形应当判定为**重大隐患**：\n"
                    "1. 危险化学品生产、经营单位主要负责人和安全生产管理人员未依法经考核合格\n"
                    "2. 特种作业人员未持证上岗\n"
                    "3. 涉及“两重点一重大”的生产装置、储存设施外部安全防护距离不符合国家标准要求\n"
                    "4. 涉及重点监管危险化工工艺的装置未实现自动化控制，系统未实现紧急停车功能\n"
                    "5. 构成一级、二级重大危险源的危险化学品罐区未实现紧急切断功能\n"
                    "6. 涉及毒性气体、液化气体、剧毒液体的一级、二级重大危险源未配备独立的安全仪表系统\n"
                    "7. 涉及爆炸危险性化学品的生产装置控制室、交接班室布置在装置区内\n"
                    "8. 全压力式液化烃储罐未按国家标准设置注水措施\n"
                    "9. 危险化学品生产、储存、使用企业未按国家标准分区分类储存危险化学品，超量、超品种"
                    "储存、相互禁配物质混放混存\n"
                    "10. 爆炸危险场所未按国家标准安装使用防爆电气设备\n"
                    "11. 涉及可燃和有毒有害气体泄漏的场所未按国家标准设置检测报警装置\n"
                    "12. 企业未建立安全风险研判与承诺公告制度\n"
                    "13. 化工生产装置未按国家标准要求设置双重电源供电\n"
                    "14. 油气储罐未按规定设置温度、液位、压力测量仪表和连锁装置\n"
                    "15. 控制室或机柜间面向具有火灾、爆炸危险性装置一侧不满足防火防爆要求\n"
                    "16. 安全阀、爆破片等安全附件未正常投用"
                ),
                legal_basis_clauses=(
                    "《化工和危险化学品生产经营单位重大生产安全事故隐患判定标准（试行）》"
                    "全文共20条，规定了化工企业重大隐患的具体判定情形。"
                ),
            ),

            # ━━ P0-5: 十大禁令（已有卡片，保持不变）━━
            KnowledgeCard(
                document_title="《集团安全生产十大禁令》",
                document_category="management_systems",
                priority="P0",
                hazard_level_criteria=(
                    "违反集团安全生产十大禁令的，直接判定为**重大隐患**：\n"
                    "1. 严禁违章指挥和强令他人冒险作业\n"
                    "2. 严禁不具备相应资格的人员从事特殊作业\n"
                    "3. 严禁未按规定进行动火、受限空间等特殊作业审批或审批手续不全\n"
                    "4. 严禁在爆炸危险场所使用非防爆设备和工具\n"
                    "5. 严禁未按规定穿戴劳动防护用品进入生产作业现场\n"
                    "6. 严禁未采取可靠措施从事高处作业\n"
                    "7. 严禁未经许可停用、拆除或变更安全设施、消防设施和联锁装置\n"
                    "8. 严禁危险化学品违规存放和超量储存\n"
                    "9. 严禁未经培训合格的人员独立上岗操作\n"
                    "10. 严禁隐瞒、谎报、迟报生产安全事故"
                ),
                legal_basis_clauses=(
                    "《集团安全生产十大禁令》属于企业内部管理制度，是安全生产的红线。"
                    "违反任何一条即为重大隐患，应立即停止相关作业并整改。"
                ),
            ),

            # ═══════════════════════════════════════════════════════════════
            # P1（12 张）—— 类别判定与整改措施
            # ═══════════════════════════════════════════════════════════════

            # ━━ P1-1: GB 3836.1-2010（新增 — Harness #4）━━
            KnowledgeCard(
                document_title="GB 3836.1-2010 《爆炸性环境 第1部分：设备 通用要求》",
                document_category="standards",
                priority="P1",
                hazard_category_criteria=(
                    "GB 3836 系列标准规定了爆炸性环境中电气设备的设计、选型和安装要求。\n"
                    "防爆区域分为 Zone 0/1/2（气体）和 Zone 20/21/22（粉尘），"
                    "不同区域对应不同的防爆等级要求（Ex d 隔爆型、Ex e 增安型、Ex i 本安型等）。\n"
                    "关键判定点：\n"
                    "- 爆炸危险场所是否按区域划分正确选用防爆电气\n"
                    "- 防爆电气引入装置（电缆入口）是否使用防爆堵头封堵\n"
                    "- 密封圈是否与电缆外径匹配\n"
                    "- 接地连接是否完好"
                ),
                key_defect_examples=(
                    "防爆电气常见缺陷：\n"
                    "- 防爆电箱备用引入口未使用防爆堵头封堵\n"
                    "- 防爆接线盒密封圈老化开裂\n"
                    "- 非防爆设备（普通插座、开关）安装在防爆区域内\n"
                    "- 防爆面锈蚀、螺栓缺失或未紧固\n"
                    "- 电缆进线口未使用防爆电缆引入装置\n"
                    "- 隔爆面间隙超标（>0.2mm）"
                ),
                legal_basis_clauses=(
                    "GB 3836.1-2010 第15章：电气设备引入装置的密封要求。"
                    "GB 3836.2-2010 第11章：隔爆型 'd' 的隔爆接合面要求。"
                ),
            ),

            # ━━ P1-2: GB 50016（新增 — Harness #5）━━
            KnowledgeCard(
                document_title="GB 50016 《建筑设计防火规范》",
                document_category="standards",
                priority="P1",
                rectification_requirements=(
                    "消防通道与疏散要求：\n"
                    "- 疏散通道净宽度不应小于1.1m（第7.3.1条）→ 实际要求≥1.4m更安全\n"
                    "- 疏散门应向疏散方向开启，不得使用卷帘门、转门\n"
                    "- 防火间距：甲类厂房与民用建筑≥25m，与明火/散发火花地点≥30m\n"
                    "- 消防车道净宽度≥4m，净高度≥4m，转弯半径≥12m\n"
                    "- 消防器材（灭火器/消火栓）前方1m内不得堆放物品\n"
                    "\n"
                    "整改要求：立即清理堵塞→地面施划禁停标线→修订定置管理制度"
                    "→每月专项检查消防通道。"
                ),
                legal_basis_clauses=(
                    "GB 50016 第7.3.1条：疏散通道的净宽度不应小于1.1m。"
                    "第7.1.8条：消防车道的净宽度和净高度均不应小于4.0m。"
                ),
            ),

            # ━━ P1-3: GB 50160（新增 — Harness #6）━━
            KnowledgeCard(
                document_title="GB 50160 《石油化工企业设计防火标准》",
                document_category="standards",
                priority="P1",
                hazard_category_criteria=(
                    "GB 50160 适用于石油化工企业的防火设计，关键控制点：\n"
                    "- 装置区与罐区之间的防火间距要求\n"
                    "- 液化烃储罐的防火堤容积和高度要求\n"
                    "- 甲/乙类装置区控制室的抗爆设计\n"
                    "- 可燃液体储罐的氮封/浮顶等安全措施\n"
                    "- 装卸区（栈台）的防火间距和防流散措施\n"
                    "- 消防水系统和泡沫灭火系统的配置要求"
                ),
                rectification_requirements=(
                    "石化防火整改要点：\n"
                    "- 防火间距不足时采取防火墙/水幕等补偿措施\n"
                    "- 罐区防火堤内有效容积不小于最大罐容量\n"
                    "- 可燃气体/有毒气体检测报警系统定期校验\n"
                    "- 消防泵房供电按一级负荷配置（双电源或柴油泵）"
                ),
                legal_basis_clauses=(
                    "GB 50160 第4章：区域规划与工厂总平面布置的防火要求。"
                    "第5章：石油化工工艺装置的防火设计。第6章：储运设施的防火设计。"
                ),
            ),

            # ━━ P1-4: 工贸行业重大隐患判定标准（新增 — Harness #8）━━
            KnowledgeCard(
                document_title="《工贸行业重大生产安全事故隐患判定标准》",
                document_category="laws_regulations",
                priority="P1",
                hazard_level_criteria=(
                    "工贸行业重大隐患判定（区别于化工行业判定标准）：\n"
                    "- 粉尘防爆类：粉尘爆炸危险场所未使用防爆电气、未设置泄爆装置\n"
                    "- 有限空间类：未对有限空间进行辨识、未设置警示标识、未配备应急器材\n"
                    "- 涉氨制冷类：氨制冷机房未设置氨气泄漏报警装置\n"
                    "- 冶金类：高温熔融金属运输路径存在积水、转炉/电炉冷却水系统失效\n"
                    "- 建材类：水泥工厂煤粉制备系统未设置防爆装置\n"
                    "- 机械类：铸造熔炼炉冷却水系统未设置温度/流量监测报警"
                ),
                legal_basis_clauses=(
                    "《工贸行业重大生产安全事故隐患判定标准》全文，"
                    "涵盖粉尘防爆、有限空间、涉氨制冷、冶金、建材、机械等行业。"
                ),
            ),

            # ━━ P1-5: 危化品安全管理条例（新增 — Harness #9）━━
            KnowledgeCard(
                document_title="《危险化学品安全管理条例》",
                document_category="laws_regulations",
                priority="P1",
                legal_basis_clauses=(
                    "《危险化学品安全管理条例》核心条文：\n"
                    "- 第12条：危险化学品生产、储存企业应取得危险化学品安全生产许可证\n"
                    "- 第19条：危险化学品应储存在专用仓库/专用场地/专用储存室内，"
                    "由专人负责管理\n"
                    "- 第20条：危险化学品专用仓库应符合国家标准对安全、消防的要求，"
                    "设置明显标志\n"
                    "- 第21条：剧毒化学品以及储存数量构成重大危险源的其他危险化学品，"
                    "应在专用仓库内单独存放，实行双人收发、双人保管制度\n"
                    "- 第25条：危险化学品应当按国家标准分区分类储存，"
                    "禁止超量、超品种储存，禁止相互禁配物质混放混存"
                ),
                hazard_level_criteria=(
                    "违反以下条款直接判定为重大隐患：\n"
                    "- 未取得安全生产许可证擅自生产/储存（第12条）\n"
                    "- 剧毒品未实行双人收发双人保管（第21条）\n"
                    "- 禁配物质混放混存（第25条）\n"
                    "- 未在专用仓库储存危险化学品（第19条）"
                ),
            ),

            # ━━ P1-6: 安监总局16号令（新增 — Harness #12）━━
            KnowledgeCard(
                document_title="《安全生产事故隐患排查治理暂行规定》（安监总局16号令）",
                document_category="laws_regulations",
                priority="P1",
                rectification_requirements=(
                    "16号令规定的隐患治理闭环流程：\n"
                    "1. 发现登记：发现隐患后及时登记，建立隐患台账\n"
                    "2. 评估分级：按严重程度分为一般隐患和重大隐患\n"
                    "3. 制定方案：重大隐患需制定治理方案（目标/任务/方法/经费/责任人/时限/预案）\n"
                    "4. 整改实施：落实整改措施，重大隐患期间应采取监控预警和应急措施\n"
                    "5. 验收销号：整改完成后验收确认，验收不合格的不得恢复生产\n"
                    "6. 统计分析：定期统计分析隐患排查治理情况\n"
                    "\n"
                    "重大隐患应报告当地安监部门和有关部门。"
                ),
                legal_basis_clauses=(
                    "16号令第10条：生产经营单位应当定期组织安全生产管理人员、"
                    "工程技术人员和其他相关人员排查本单位的事故隐患。\n"
                    "第14条：对于重大事故隐患，生产经营单位应当及时向安全监管监察部门"
                    "和有关部门报告。\n"
                    "第15条：重大事故隐患治理方案应当包括以下内容：治理的目标和任务、"
                    "采取的方法和措施、经费和物资的落实、负责治理的机构和人员、"
                    "治理的时限和要求、安全措施和应急预案。"
                ),
            ),

            # ━━ P1-7: GB 6441-2025（已有卡片，保持不变）━━
            KnowledgeCard(
                document_title="GB 6441-2025 《企业职工伤亡事故分类》",
                document_category="standards",
                priority="P1",
                hazard_type_definitions=(
                    "GB 6441-2025 将企业职工伤亡事故分为 20 类：\n"
                    "1. 物体打击 2. 车辆伤害 3. 机械伤害 4. 起重伤害\n"
                    "5. 触电 6. 淹溺 7. 灼烫 8. 火灾 9. 高处坠落\n"
                    "10. 坍塌 11. 冒顶片帮 12. 透水 13. 放炮 14. 火药爆炸\n"
                    "15. 容器爆炸 16. 其他爆炸 17. 中毒和窒息\n"
                    "18. 其他伤害（刺割、绞碾、腐蚀、动物伤害等）\n"
                    "19. 职业病 20. 其他职业病。\n\n"
                    "其中化工业常见事故类型：火灾、容器爆炸、"
                    "中毒和窒息、灼烫、触电、机械伤害、高处坠落、物体打击。"
                ),
                hazard_category_criteria=(
                    "事故类别与危险源的对应关系：\n"
                    "- 物体打击：设备部件飞出、物料坠落、工具掉落\n"
                    "- 机械伤害：运动部件夹伤、绞伤、剪切、碾伤\n"
                    "- 灼烫：高温物质、热表面、酸碱化学灼伤\n"
                    "- 中毒和窒息：毒性气体泄漏、缺氧环境、封闭空间\n"
                    "- 容器爆炸：压力容器超压、反应失控、燃气爆炸\n"
                    "- 触电：电气设备漏电、静电放电、雷击"
                ),
                legal_basis_clauses=(
                    "GB 6441-2025 第3章：伤亡事故分类原则、分类方法和类别代码。"
                    "第4章：各类伤亡事故的定义、判定要点和典型场景。"
                ),
            ),

            # ━━ P1-8: GB 12801-2025（已有卡片，保持不变）━━
            KnowledgeCard(
                document_title="GB 12801-2025 《生产过程安全基本要求》",
                document_category="standards",
                priority="P1",
                hazard_type_definitions=(
                    "GB 12801-2025 规定了生产过程安全的基本要求，包括：\n"
                    "1. 生产工艺安全设计原则\n"
                    "2. 生产设备安全配置要求\n"
                    "3. 作业环境安全条件\n"
                    "4. 工艺操作安全规范\n"
                    "5. 压力容器、锅炉等特种设备安全要求\n"
                    "6. 危险化学品生产、储存、使用安全要求"
                ),
                rectification_requirements=(
                    "生产过程安全控制措施优先级：\n"
                    "1. 消除：通过工艺改造消除危险因素\n"
                    "2. 替代：用低危险性物质替代高危险性物质\n"
                    "3. 工程控制：安装防护装置、联锁、报警、通风、温控、压控等\n"
                    "4. 管理控制：操作规程、巡检制度、作业许可、交接班制度\n"
                    "5. 个体防护：配备完善的个人防护装备（PPE）\n"
                    "6. 应急准备：制定应急预案、配备应急器材、定期演练"
                ),
                legal_basis_clauses=(
                    "GB 12801-2025 替代 GB/T 12801-2008，由推荐性标准升级为强制性标准。"
                    "第5章：生产工艺安全要求；第6章：生产设备安全要求；"
                    "第7章：特种设备安全要求；第8章：危险化学品安全要求。"
                ),
            ),

            # ━━ P1-9: GB 5083-2023（新增 — 危险源辨识清单 #7）━━
            KnowledgeCard(
                document_title="GB 5083-2023 《生产设备安全卫生设计总则》",
                document_category="standards",
                priority="P1",
                hazard_type_definitions=(
                    "GB 5083-2023 规定了生产设备安全卫生设计的基本原则：\n"
                    "1. 本质安全原则：设备设计应优先采用本质安全措施，"
                    "使设备在预定使用和合理可预见的误用情况下均能保证安全\n"
                    "2. 防护装置要求：运动部件必须设置防护罩/防护栏/防护网\n"
                    "3. 紧急停止：每台设备应在操作位和危险区域设置紧急停止按钮（红色蘑菇头）\n"
                    "4. 联锁保护：防护门打开时设备应自动停机（安全联锁）\n"
                    "5. 人机工程：操作手柄/按钮/踏板高度和力矩应符合人体工程学\n"
                    "6. 噪声控制：设备运行时噪声不应超过85dB(A)"
                ),
                rectification_requirements=(
                    "设备安全整改要点：\n"
                    "- 旋转部件（皮带轮/链条/联轴器）必须安装固定式防护罩\n"
                    "- 冲压/剪切设备必须配备双手操作或光电保护装置\n"
                    "- 紧急停止按钮应为红色、蘑菇头、自锁式，标示明显\n"
                    "- 安全联锁装置不得被旁路或拆除\n"
                    "- 高温表面（>60℃）应加装隔热防护或警示标识"
                ),
                legal_basis_clauses=(
                    "GB 5083-2023 第5章：本质安全设计原则。第6章：防护装置和安全装置。"
                    "第7章：紧急停止和联锁保护。第10章：噪声与振动控制。"
                ),
            ),

            # ━━ P1-10: HG 20571-2014（新增 — 危险源辨识清单 #9）━━
            KnowledgeCard(
                document_title="HG 20571-2014 《化工企业安全卫生设计规范》",
                document_category="standards",
                priority="P1",
                hazard_category_criteria=(
                    "HG 20571-2014 对化工企业安全卫生设计的要求：\n"
                    "- 总平面布置：生产区/储存区/办公区应分区布置，"
                    "甲类火灾危险区应独立设置\n"
                    "- 工艺系统安全：涉及“两重点一重大”的装置须设置 SIS（安全仪表系统）\n"
                    "- 泄压与排放：压力容器应设置安全阀/爆破片，排放口不得朝向人行通道\n"
                    "- 防火防爆：有火灾爆炸危险的车间应采取通风换气措施，"
                    "可燃气体可能积聚处设置检测报警\n"
                    "- 防毒防尘：有毒有害作业场所应设置局部排风和全面通风\n"
                    "- 职业卫生：产生粉尘/毒物/噪声/振动的场所应设置工程控制措施"
                ),
                key_defect_examples=(
                    "化工安全设计常见缺陷：\n"
                    "- 甲类火灾危险车间与办公室贴邻布置\n"
                    "- 安全阀排放口朝向操作通道\n"
                    "- 涉及重点监管工艺的装置未配备独立 SIS\n"
                    "- 可燃气体检测报警器未定期校准\n"
                    "- 有毒作业场所未设置事故通风和洗眼器\n"
                    "- 泄爆面积不足或泄爆方向朝向人员密集区"
                ),
                legal_basis_clauses=(
                    "HG 20571-2014 第3章：厂址选择与总平面布置。\n"
                    "第4章：工艺系统安全卫生设计。\n"
                    "第5章：防火防爆设计。第8章：职业卫生防护。"
                ),
            ),

            # ━━ P1-11: 双重预防机制建设指导手册（已有卡片，保持不变）━━
            KnowledgeCard(
                document_title="《危险化学品双重预防机制建设指导手册》（2021版）",
                document_category="risk_assessment_standards",
                priority="P1",
                hazard_level_criteria=(
                    "双重预防机制中的风险分级控制原则：\n"
                    "1. 风险分级管控：重大、较大、一般、低风险四个等级\n"
                    "2. 管控层级：\n"
                    "   - 重大风险（红）：公司级管控，主要负责人承担\n"
                    "   - 较大风险（橙）：部门级管控，安全工程中心+各部门\n"
                    "   - 一般风险（黄）：班组/岗位级管控\n"
                    "   - 低风险（蓝）：班组/岗位级管控\n"
                    "3. 措施优先级：消除→替代→工程控制→管理控制→PPE→应急"
                ),
                rectification_requirements=(
                    "双重预防机制要求企业建立：\n"
                    "1. 风险分级管控制度：明确各级风险的管控层级、责任人和措施\n"
                    "2. 隐患排查治理制度\n"
                    "3. 风险告知制度\n"
                    "4. 隐患治理闭环：发现→登记→评估→整改→验证→销号"
                ),
                legal_basis_clauses=(
                    "《危险化学品双重预防机制建设指导手册》（2021版）第4章："
                    "风险分级管控体系建设；第5章：隐患排查治理体系建设。"
                ),
            ),

            # ━━ P1-12: 双重预防机制建设通则（新增 — 危险源辨识清单 #15）━━
            KnowledgeCard(
                document_title="《企业安全风险分级管控和隐患排查治理双重预防机制建设 通则》",
                document_category="risk_assessment_standards",
                priority="P1",
                hazard_level_criteria=(
                    "双重预防机制通则中的风险等级划分标准：\n"
                    "- 一级风险（红色/重大风险）：D ≥ 320，由公司级管控\n"
                    "- 二级风险（橙色/较大风险）：160 ≤ D < 320，由部门级管控\n"
                    "- 三级风险（黄色/一般风险）：70 ≤ D < 160，由班组级管控\n"
                    "- 四级风险（蓝色/低风险）：D < 70，由岗位级管控\n"
                    "\n"
                    "风险点划分方法：按设施/部位/场所/区域/操作/作业活动划分，"
                    "遵循'大小适中、便于分类、功能独立、易于管理、范围清晰'原则。"
                ),
                rectification_requirements=(
                    "双重预防机制建设要点：\n"
                    "1. 风险辨识范围应覆盖所有作业活动和设备设施\n"
                    "2. 风险评价采用 LEC、LS、风险矩阵等方法\n"
                    "3. 风险管控措施应逐级落实到具体岗位和管理层级\n"
                    "4. 设置风险告知牌（岗位风险+管控措施+应急处置）\n"
                    "5. 建立隐患排查清单（日常/专项/综合性检查表）\n"
                    "6. 隐患治理实现PDCA闭环管理"
                ),
                legal_basis_clauses=(
                    "《企业安全风险分级管控和隐患排查治理双重预防机制建设 通则》"
                    "第5章：风险分级管控。第6章：隐患排查治理。第7章：持续改进。"
                ),
            ),

            # ═══════════════════════════════════════════════════════════════
            # P2（9 张）—— 专项技术标准与补充
            # ═══════════════════════════════════════════════════════════════

            # ━━ P2-1: 特种设备安全法（新增 — Harness #10 + 危险源辨识清单 #5）━━
            KnowledgeCard(
                document_title="《中华人民共和国特种设备安全法》",
                document_category="laws_regulations",
                priority="P2",
                legal_basis_clauses=(
                    "《特种设备安全法》核心条文：\n"
                    "- 第33条：特种设备使用单位应当在特种设备投入使用前或投入使用后30日内，"
                    "向质检部门办理使用登记，取得使用登记证书\n"
                    "- 第34条：特种设备使用单位应当建立特种设备安全技术档案\n"
                    "- 第35条：特种设备使用单位应当对在用特种设备进行经常性维护保养和定期自行检查，"
                    "并作出记录\n"
                    "- 第36条：特种设备使用单位应当对在用特种设备的安全附件、安全保护装置"
                    "进行定期校验、检修\n"
                    "- 第40条：特种设备使用单位应当按照安全技术规范的要求，"
                    "在检验合格有效期届满前一个月向特种设备检验机构提出定期检验要求\n"
                    "- 第48条：特种设备存在严重事故隐患，无改造/修理价值，"
                    "或达到安全技术规范规定的报废条件的，使用单位应当依法履行报废义务"
                ),
                hazard_category_criteria=(
                    "特种设备安全管理类别（8大类）：\n"
                    "锅炉、压力容器（含气瓶）、压力管道、电梯、起重机械、"
                    "场（厂）内专用机动车辆、客运索道、大型游乐设施。\n"
                    "化工厂常见特种设备：压力容器（反应釜/储罐/换热器）、"
                    "压力管道（蒸汽/物料/燃气管道）、锅炉、起重机械（行车/电动葫芦）、"
                    "叉车。"
                ),
            ),

            # ━━ P2-2: GB 4053.3-2009（新增 — Harness #11）━━
            KnowledgeCard(
                document_title="GB 4053.3-2009 《固定式钢梯及平台安全要求》",
                document_category="standards",
                priority="P2",
                key_defect_examples=(
                    "钢梯平台常见缺陷：\n"
                    "- 平台未设置踢脚板（高度≥100mm）\n"
                    "- 扶手栏杆高度不足（要求≥1050mm）\n"
                    "- 踏板间距过大或踏板缺失\n"
                    "- 钢梯倾角过大（固定式钢斜梯倾角应为30°~75°）\n"
                    "- 梯段高度超过3m未设中间平台\n"
                    "- 平台底板锈蚀严重或孔洞未修补\n"
                    "- 扶手未延伸到平台末端或梯段起点"
                ),
                rectification_requirements=(
                    "钢梯平台安全整改标准：\n"
                    "- 扶手高度：工作平台≥1050mm，梯段≥900mm\n"
                    "- 踢脚板：平台边缘须设置高度≥100mm的踢脚板\n"
                    "- 踏板：踏板间距应均匀，踏板前端厚度≥4mm\n"
                    "- 荷载：平台活荷载≥2.0kN/m²，梯段活荷载≥3.5kN/m\n"
                    "- 防腐：钢构件应做防腐处理（热浸镀锌或涂装）\n"
                    "- 标识：承载能力标示牌固定在醒目位置"
                ),
                legal_basis_clauses=(
                    "GB 4053.3-2009 第4章：钢斜梯的安全要求。"
                    "第5章：钢直梯的安全要求。第6章：平台及通道的安全要求。"
                ),
            ),

            # ━━ P2-3: 职业病危害因素分类目录（新增 — 危险源辨识清单 #4）━━
            KnowledgeCard(
                document_title="国卫疾控发[2015]92号 《职业病危害因素分类目录》",
                document_category="laws_regulations",
                priority="P2",
                hazard_type_definitions=(
                    "职业病危害因素分为以下10大类：\n"
                    "1. 粉尘类（矽尘、煤尘、石棉尘、水泥尘、有机粉尘等52种）\n"
                    "2. 化学因素类（苯、甲苯、二甲苯、甲醛、氨、氯、硫酸、盐酸、"
                    "硫化氢、一氧化碳等375种）\n"
                    "3. 物理因素类（噪声、高温、振动、电离辐射、紫外线等15种）\n"
                    "4. 放射因素类（放射性物质和射线装置）\n"
                    "5. 生物因素类（炭疽杆菌、布鲁氏菌、森林脑炎病毒等6种）\n"
                    "6. 导致职业性皮肤病的危害因素（9类）\n"
                    "7. 导致职业性眼病的危害因素（5类）\n"
                    "8. 导致职业性耳鼻喉口腔疾病的危害因素（4类）\n"
                    "9. 导致职业性肿瘤的危害因素（11类）\n"
                    "10. 其他职业病危害因素（5类）"
                ),
                legal_basis_clauses=(
                    "国卫疾控发[2015]92号《职业病危害因素分类目录》全文。"
                    "对应《职业病防治法》第16条：用人单位工作场所存在职业病目录所列"
                    "职业病危害因素的，应当及时、如实向所在地卫生行政部门申报危害项目。"
                ),
            ),

            # ━━ P2-4: GB/T 50493-2019（新增 — 危险源辨识清单 #8）━━
            KnowledgeCard(
                document_title="GB/T 50493-2019 《石油化工可燃气体和有毒气体检测报警设计标准》",
                document_category="standards",
                priority="P2",
                key_defect_examples=(
                    "气体检测报警常见缺陷：\n"
                    "- 释放源附近未设置检测器或检测器位置不当\n"
                    "- 可燃气体检测器安装高度错误（比空气轻的气体应装在上方，"
                    "比空气重的应装在下方）\n"
                    "- 检测器未定期校准（校准周期一般不超过1年）\n"
                    "- 报警值设定不合理（可燃气体一级报警≤25%LEL，二级≤50%LEL）\n"
                    "- 报警信号未接入有人值守的控制室或值班室\n"
                    "- 检测器被遮挡、污染或腐蚀\n"
                    "- 现场未设声光报警器"
                ),
                rectification_requirements=(
                    "气体检测报警设置标准：\n"
                    "- 可燃气体释放源：检测器距释放源≤7.5m（户外）/≤5m（室内）\n"
                    "- 有毒气体释放源：检测器距释放源≤2m（户外）/≤1m（室内）\n"
                    "- 比空气轻的气体（H2/NH3）：检测器装在释放源上方0.5~2.0m\n"
                    "- 比空气重的气体（LPG/汽油蒸气）：检测器装在释放源下方0.3~0.6m\n"
                    "- 报警器应独立于控制系统，现场+控制室双报警"
                ),
                legal_basis_clauses=(
                    "GB/T 50493-2019 第4章：检测点的确定原则。"
                    "第5章：检测器和报警控制器的设置。第6章：检测报警系统的安装。"
                ),
            ),

            # ━━ P2-5: SH/T 3097-2017（新增 — 危险源辨识清单 #10）━━
            KnowledgeCard(
                document_title="SH/T 3097-2017 《石油化工静电接地设计规范》",
                document_category="standards",
                priority="P2",
                key_defect_examples=(
                    "静电接地常见缺陷：\n"
                    "- 管道法兰间未设静电跨接线（少于5条螺栓时须跨接）\n"
                    "- 跨接线断裂、松动或腐蚀\n"
                    "- 储罐/容器未做防静电接地\n"
                    "- 防静电接地电阻超标（要求≤100Ω）\n"
                    "- 取样/装车/卸车时未使用静电接地报警器\n"
                    "- 爆炸危险区域人体静电消除器缺失或失效\n"
                    "- 防静电工作服/鞋未按周期检测导电性能"
                ),
                rectification_requirements=(
                    "静电接地整改标准：\n"
                    "- 管道法兰跨接：≤5条螺栓须用铜编织带跨接，电阻≤0.03Ω\n"
                    "- 储罐接地：容积≥50m³或直径≥2.5m的储罐接地点≥2处\n"
                    "- 汽车/火车装卸台：设置专用静电接地端子\n"
                    "- 人体静电释放：爆炸危险区入口须设人体静电释放装置\n"
                    "- 接地电阻：防静电接地≤100Ω，防雷接地≤10Ω\n"
                    "- 检测周期：每年至少检测一次接地电阻"
                ),
                legal_basis_clauses=(
                    "SH/T 3097-2017 第4章：静电接地范围。第5章：静电接地方式。"
                    "第6章：静电接地的检测与维护。"
                ),
            ),

            # ━━ P2-6: GB 7231（新增 — 危险源辨识清单 #11）━━
            KnowledgeCard(
                document_title="GB 7231 《工业管道的基本识别色、识别符号和安全标识》",
                document_category="standards",
                priority="P2",
                key_defect_examples=(
                    "管道标识常见缺陷：\n"
                    "- 管道无基本识别色或颜色错误\n"
                    "- 管道无介质名称和流向标识\n"
                    "- 标识褪色、脱落或模糊不清\n"
                    "- 危险化学品管道（酸/碱/溶剂）无危险警示标识\n"
                    "- 管道穿越墙/楼板处未在两侧标识\n"
                    "- 同一管廊多条管道无法区分介质\n"
                    "- 阀门/法兰处未标识"
                ),
                hazard_category_criteria=(
                    "管道基本识别色标准（8大类）：\n"
                    "- 水：艳绿色（G03）\n"
                    "- 蒸汽：大红色（R03）\n"
                    "- 空气：淡灰色（B03）\n"
                    "- 气体（除空气/蒸汽外）：中黄色（Y07）\n"
                    "- 酸/碱：紫色（P02）\n"
                    "- 可燃液体：棕色（YR05）\n"
                    "- 其他液体：黑色\n"
                    "- 氧气：淡蓝色（PB06）\n"
                    "\n"
                    "标识应包含：介质名称 + 流向箭头 + 压力/温度等级（必要时）"
                ),
                legal_basis_clauses=(
                    "GB 7231 第4章：基本识别色的规定。第5章：识别符号。"
                    "第6章：安全标识。"
                ),
            ),

            # ━━ P2-7: GB/T 4272-2024（新增 — 危险源辨识清单 #12）━━
            KnowledgeCard(
                document_title="GB/T 4272-2024 《设备及管道绝热技术通则》",
                document_category="standards",
                priority="P2",
                key_defect_examples=(
                    "绝热保温常见缺陷：\n"
                    "- 绝热层破损、脱落或大面积缺失\n"
                    "- 保冷层出现结露、结霜或冰挂（冷量损失）\n"
                    "- 绝热层受潮导致保温效果严重下降\n"
                    "- 保温层外护层（铝皮/铁皮）腐蚀穿孔\n"
                    "- 高温管道（>60℃）无防烫伤绝热和警示标识\n"
                    "- 低温管道（<0℃）绝热层未做防潮层\n"
                    "- 阀门/法兰处绝热缺失\n"
                    "- 绝热材料与介质温度不匹配（超温使用导致碳化）"
                ),
                rectification_requirements=(
                    "绝热整改标准：\n"
                    "- 高温管道（>60℃）：绝热层外表面温度≤50℃，防烫伤\n"
                    "- 低温管道（<0℃）：绝热层外表面不得结露，需做防潮层\n"
                    "- 绝热层厚度按经济厚度法计算，满足节能要求\n"
                    "- 外护层采用铝合金板/镀锌钢板/不锈钢板，接缝向下防雨水渗入\n"
                    "- 阀门/法兰处应采用可拆卸式绝热盒或柔性绝热套\n"
                    "- 绝热材料更换周期一般8~12年"
                ),
                legal_basis_clauses=(
                    "GB/T 4272-2024 替代 GB/T 4272-2008。"
                    "第4章：绝热材料的选择。第5章：绝热结构设计。"
                    "第6章：绝热工程施工与验收。"
                ),
            ),

            # ━━ P2-8: 双重预防数字化建设指南（新增 — 危险源辨识清单 #14）━━
            KnowledgeCard(
                document_title="《危险化学品企业双重预防机制数字化建设工作指南（试行）》",
                document_category="risk_assessment_standards",
                priority="P2",
                rectification_requirements=(
                    "双重预防数字化建设要点：\n"
                    "1. 风险清单数字化：建立企业风险点电子台账，"
                    "每个风险点有唯一编码、风险等级、管控措施和责任人\n"
                    "2. 隐患排查移动化：使用移动终端（防爆手机/PDA）进行现场检查，"
                    "拍照上传、自动定位、实时同步\n"
                    "3. 隐患闭环在线流转：发现→评估→派单→整改→复查→销号全流程线上管理\n"
                    "4. 预警推送自动化：超期未整改自动推送预警给上级管理者\n"
                    "5. 统计分析可视化：风险四色图、隐患趋势图、整改率统计看板\n"
                    "6. 数据接口标准化：与政府监管平台数据对接"
                ),
                hazard_level_criteria=(
                    "数字化评估指标：\n"
                    "- 风险辨识覆盖率 ≥ 100%（所有作业活动/设备设施）\n"
                    "- 隐患排查任务完成率 ≥ 95%\n"
                    "- 隐患按期整改率 ≥ 90%\n"
                    "- 重大隐患整改率 = 100%\n"
                    "- 风险四色图更新频率：每季度至少1次"
                ),
                legal_basis_clauses=(
                    "《危险化学品企业双重预防机制数字化建设工作指南（试行）》"
                    "第3章：数字化建设内容。第4章：功能要求。第5章：数据管理。"
                ),
            ),

            # ━━ LEC 方法论（保留，非法规但用于危险源辨识风险评价）━━
            KnowledgeCard(
                document_title="LEC 风险评价法——作业条件危险性评价",
                document_category="risk_assessment_standards",
                priority="P0",
                hazard_level_criteria=(
                    "风险等级判定标准（D = L × E × C）：\n"
                    "D ≥ 320 → level_1（一级/重大风险）：立即停止作业\n"
                    "160 ≤ D < 320 → level_2（二级/较大风险）：采取控制措施\n"
                    "70 ≤ D < 160 → level_3（三级/一般风险）：维持现有措施\n"
                    "D < 70 → level_4（四级/低风险）：保持现状"
                ),
                key_defect_examples=(
                    "L 取值参照（事故发生可能性）：\n"
                    "10-完全可以预料 | 6-相当可能 | 3-可能但不经常 |\n"
                    "1-可能性小 | 0.5-很不可能 | 0.2-极不可能 | 0.1-实际不可能\n\n"
                    "E 取值参照（暴露频率）：\n"
                    "10-连续暴露 | 6-每天工作时间内 | 3-每周一次 |\n"
                    "2-每月一次 | 1-每年几次 | 0.5-非常罕见\n\n"
                    "C 取值参照（后果严重性）：\n"
                    "100-大灾难 | 40-灾难 | 15-非常严重 |\n"
                    "7-严重 | 3-重大 | 1-引人注目"
                ),
                legal_basis_clauses=(
                    "LEC 法基于 Graham-Kinney 方法，是国内企业常用的半定量风险评价方法。"
                    "本表格为《危险源辨识助手标准文件》第4.3节“风险评价方法”的评分参照表。"
                ),
            ),
        ]

    # ═══════════════════════════════════════════════════════════════════════════
    # 格式化
    # ═══════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _format_card(card: KnowledgeCard) -> str:
        """将单张 KnowledgeCard 格式化为 Markdown 文本。"""
        attr_labels = {
            "hazard_type_definitions": "隐患分类定义",
            "hazard_category_criteria": "隐患类别判定标准",
            "hazard_level_criteria": "隐患级别分级标准",
            "key_defect_examples": "典型缺陷示例",
            "rectification_requirements": "整改措施要求",
            "legal_basis_clauses": "可引用的法律依据条文",
        }

        parts: list[str] = [
            "### 文档: " + card.document_title,
            "**类别**: " + card.document_category
            + " | **优先级**: " + card.priority,
        ]

        for attr, label in attr_labels.items():
            value = getattr(card, attr, None)
            if value:
                parts.append("\n**" + label + "**:\n" + value)

        parts.append("")
        return "\n".join(parts)
