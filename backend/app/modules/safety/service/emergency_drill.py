"""应急演练管理 Service — CRUD + AI 方案生成 + 隐患追踪。

三环节：计划 → 实施 → 复核。
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.safety.models import (
    DrillCollectionRecord,
    DrillHazardLink,
    EmergencyDrillDocument,
    EmergencyDrillRecord,
)
from app.modules.safety.schemas.emergency_drills import DrillStatsResponse

logger = logging.getLogger(__name__)

# ── AI Prompt ──

_DRILL_PLAN_SYSTEM_PROMPT = """你是一名应急管理专家，熟悉《生产经营单位生产安全事故应急预案编制导则》（GB/T 29639-2020）和《生产安全事故应急预案管理办法》（AQ/T 9007-2019）。

你的任务是根据提供的演练计划信息，结合参考法规标准，生成一份标准化的应急演练方案。

★人名规则（重要）：
- 提供的计划信息中如果包含真实姓名（如组织人、参演人员等），在方案中必须使用这些真实姓名。
- 未提供姓名的角色，一律使用占位符「【待填写】」表示，严禁编造或捏造任何姓名。
- 演练脚本中的对白，涉及人物时人名用「【待填写】」占位，角色职责保留。

方案必须包含以下8个部分，每部分都需要详细描述：

一、应急演练目的：本次演练的具体目标（如检验预案可行性、提升应急处置能力、磨合部门协作机制等），列出3-5条具体目的。

二、演练领导小组：列出总指挥、副总指挥、成员。每项标注姓名/角色和具体职责。姓名必须来自提供的计划信息，没有的用「【待填写】」。

三、演练所需器材：详细设备物资清单，每项标注名称和数量。根据演练类型合理推断补充（如消防类需灭火器、防护服、警戒带；泄漏类需防化服、吸附材料、检测仪）。

四、参演人员：参演总人数、各部门/班组人数分配。

五、现场组织及职责：至少分为现场指挥（1人）、抢险组、通讯协调组。每组详细说明职责和行动指令。人名用「【待填写】」或提供的真实姓名。

六、演练程序及步骤：按时间顺序列出准备、实施、总结三阶段。每步标注时间、地点、情景设定、参与人员。

七、演练设置（★核心部分）：精确到分钟的详细演练脚本。
  格式示例：
  【15:30 事故触发】情景：xxx。【待填写】（现场指挥）："各小组注意，启动应急预案！" 【待填写】（抢险组长）："收到！抢险组立即行动！"
  【15:31 应急响应】情景：xxx。【待填写】（通讯）："已通知相关部门，请求支援。" 【待填写】（动作）：穿戴防护装备，赶赴现场。
  ...至少列出8-10个时间段的详细脚本。

八、演练要求：参演人员纪律、安全注意事项、保密要求、记录要求等。

请以 JSON 格式返回：
{
  "title": "XX部门XX演练方案",
  "summary": "方案摘要（200字以内）",
  "sections": [
    {"heading": "一、应急演练目的", "content": "1. xxx\n2. xxx\n3. xxx"},
    {"heading": "二、演练领导小组", "content": "总指挥：【待填写】（职责）\n副总指挥：【待填写】（职责）\n成员：【待填写】、【待填写】"},
    {"heading": "三、演练所需器材", "content": "- 器材1（数量）\n- 器材2（数量）"},
    {"heading": "四、参演人员", "content": "..."},
    {"heading": "五、现场组织及职责", "content": "现场指挥（1人）：【待填写】\n抢险组（X人）：【待填写】\n通讯协调组（X人）：【待填写】"},
    {"heading": "六、演练程序及步骤", "content": "时间：\n地点：\n情景设定：\n参与人员："},
    {"heading": "七、演练设置", "content": "【15:30 事故触发】\n情景：xxx\n【待填写】：\\"对白\\"\n【待填写】（动作）：描述\n\\n【15:31 应急响应】..."},
    {"heading": "八、演练要求", "content": "1. xxx\n2. xxx"}
  ],
  "cited_regulations": [
    {"title": "法规名称", "article": "条款号", "excerpt": "引用摘要"}
  ]
}"""


# ── Service ──


async def _upload_generated_plan_to_bitable(
    record: "EmergencyDrillRecord",
    content_json: dict,
    title: str,
) -> None:
    """Generate .docx from AI content and upload to Bitable 演练方案 field.

    Called by generate_drill_plan() after AI generation. Failure does NOT block.
    """
    import pathlib
    import tempfile

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.shared import Pt

    from app.modules.safety.feishu.bitable_client import SafetyBitableClient

    # ── ① Render .docx from AI JSON（统一宋体，标题加粗、正文常规，避免字体混杂）──
    docx = Document()
    # 统一字体：正文 + 标题都用宋体 SimSun，中文东亚字体也设置
    normal_style = docx.styles["Normal"]
    normal_style.font.name = "SimSun"
    normal_style.font.size = Pt(11)
    normal_style.element.rPr.rFonts.set(qn("w:eastAsia"), "SimSun")

    def _set_font(run, *, bold: bool = False, size: int = 11):
        run.font.name = "SimSun"
        run._element.rPr.rFonts.set(qn("w:eastAsia"), "SimSun")
        run.font.size = Pt(size)
        run.font.bold = bold

    # 文档标题（居中、加粗、二号）
    title_p = docx.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run(title)
    _set_font(title_run, bold=True, size=18)

    summary = content_json.get("summary", "")
    if summary:
        p = docx.add_paragraph()
        run = p.add_run(f"【摘要】{summary}")
        _set_font(run, size=10)

    for sec in content_json.get("sections", []):
        heading = sec.get("heading", "")
        content = sec.get("content", "")
        if heading:
            hp = docx.add_paragraph()
            hrun = hp.add_run(heading)
            _set_font(hrun, bold=True, size=14)
        if content:
            for line in content.split("\n"):
                stripped = line.strip()
                if not stripped:
                    continue
                bp = docx.add_paragraph()
                brun = bp.add_run(stripped)
                _set_font(brun, size=11)

    # Save to temp file
    safe_name = title.replace("/", "_").replace("\\", "_")
    tmp_path = pathlib.Path(tempfile.gettempdir()) / f"{safe_name}.docx"
    docx.save(str(tmp_path))
    logger.debug("Generated plan docx: %s (%d bytes)", tmp_path, tmp_path.stat().st_size)

    # ── ② Upload to Bitable ──
    from app.modules.safety.bitable_config.store import store

    conn = store.get_connection("emergency_drill", "main")
    if conn is None or conn.status == "disabled":
        return
    app_token, table_id = conn.app_token, conn.table_id
    if not app_token or not table_id or not record.feishu_record_id:
        return

    client = SafetyBitableClient(app_token=app_token, table_id=table_id)
    upload = await client.upload_media(str(tmp_path.resolve()), f"{safe_name}.docx")
    if not upload:
        logger.warning("Failed to upload plan docx to Bitable")
        return

    await client.update_record(
        record_id=record.feishu_record_id,
        fields={"演练方案（AI）": [{"file_token": upload["file_token"], "name": f"{safe_name}.docx"}]},
    )
    logger.info("Plan docx uploaded to Bitable: record_id=%s", record.feishu_record_id)

    # Clean up temp file
    try:
        tmp_path.unlink()
    except OSError:
        pass


class EmergencyDrillService:
    """应急演练管理业务服务。"""

    # ── 计划阶段字段约束（供 AI 解析参考）──
    PLAN_FIELD_CONSTRAINTS = {
        "drill_type": "演练类型，必须为以下之一：应急疏散演练、现场岗位处置、专项应急演练、综合应急演练、消防器材培训",
        "drill_content": "演练内容，简要描述本次演练的场景和目的（50-200字）",
        "department": "演练部门名称",
        "organizer": "演练组织人姓名",
        "participants": "参演人员范围描述",
        "coop_department": "配合部门名称（可为空）",
        "duration": "演练课时，如'1小时'、'2小时'",
        "plan_time": "计划演练时间，格式YYYY-MM-DD或中文描述",
        "plan_time_ref": "计划日期参考，格式YYYY-MM-DD",
        "notes": "备注信息（可为空）",
    }

    def __init__(self, session: AsyncSession):
        self.session = session

    # ══════════════════════════════════════════════════════
    # 查询
    # ══════════════════════════════════════════════════════

    async def list_records(
        self,
        skip: int = 0,
        limit: int = 20,
        *,
        department: str | None = None,
        drill_type: str | None = None,
        status: str | None = None,
        keyword: str | None = None,
        stage: str | None = None,
    ) -> tuple[list[EmergencyDrillRecord], int]:
        """分页查询演练记录。

        stage 可选值：plan（计划阶段：无实施时间）、execution（实施阶段：有实施时间）、
        review（复核阶段：有复核状态）。execution 不再排除 status 非空的记录，
        已复核（status 非空）但已执行的演练也能被查（execution 只看有没有执行时间）。
        """
        base = select(EmergencyDrillRecord).where(~EmergencyDrillRecord.is_deleted)
        count_base = select(func.count(EmergencyDrillRecord.id)).where(
            ~EmergencyDrillRecord.is_deleted
        )

        if department:
            base = base.where(EmergencyDrillRecord.department == department)
            count_base = count_base.where(EmergencyDrillRecord.department == department)
        if drill_type:
            base = base.where(EmergencyDrillRecord.drill_type == drill_type)
            count_base = count_base.where(EmergencyDrillRecord.drill_type == drill_type)
        if status:
            base = base.where(EmergencyDrillRecord.status == status)
            count_base = count_base.where(EmergencyDrillRecord.status == status)
        if keyword:
            kw = EmergencyDrillRecord.drill_content.ilike(f"%{keyword}%")
            base = base.where(kw)
            count_base = count_base.where(kw)
        if stage == "plan":
            base = base.where(EmergencyDrillRecord.execution_time.is_(None))
            count_base = count_base.where(EmergencyDrillRecord.execution_time.is_(None))
        elif stage == "execution":
            base = base.where(
                EmergencyDrillRecord.execution_time.isnot(None),
            )
            count_base = count_base.where(
                EmergencyDrillRecord.execution_time.isnot(None),
            )
        elif stage == "review":
            base = base.where(
                EmergencyDrillRecord.status.isnot(None),
            )
            count_base = count_base.where(
                EmergencyDrillRecord.status.isnot(None),
            )

        total = (await self.session.scalar(count_base)) or 0
        query = base.offset(skip).limit(limit).order_by(EmergencyDrillRecord.created_at.desc())
        result = await self.session.execute(query)
        items = list(result.scalars().all())
        return items, total

    async def get_record(self, record_id: uuid.UUID) -> EmergencyDrillRecord | None:
        query = select(EmergencyDrillRecord).where(
            EmergencyDrillRecord.id == record_id,
            ~EmergencyDrillRecord.is_deleted,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_record_by_feishu_id(self, feishu_record_id: str) -> EmergencyDrillRecord | None:
        query = select(EmergencyDrillRecord).where(
            EmergencyDrillRecord.feishu_record_id == feishu_record_id,
            ~EmergencyDrillRecord.is_deleted,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    # ══════════════════════════════════════════════════════
    # AI 方案生成
    # ══════════════════════════════════════════════════════

    async def generate_drill_plan(self, record_id: uuid.UUID) -> EmergencyDrillDocument | None:
        """基于计划阶段字段生成标准化演练方案。

        读写 Bitable 的「演练方案」附件列。
        """
        record = await self.get_record(record_id)
        if not record:
            return None

        # ── 构建 prompt（计划字段 = 关键词）──
        plan_fields = []
        if record.drill_content:
            plan_fields.append(f"演练内容：{record.drill_content}")
        if record.drill_type:
            plan_fields.append(f"演练类型：{record.drill_type}")
        if record.department:
            plan_fields.append(f"部门：{record.department}")
        if record.organizer:
            plan_fields.append(f"组织人：{record.organizer}")
        if record.participants:
            plan_fields.append(f"参演人员：{record.participants}")
        if record.coop_department:
            plan_fields.append(f"配合部门：{record.coop_department}")
        if record.duration:
            plan_fields.append(f"课时：{record.duration}")
        if record.plan_time:
            plan_fields.append(f"计划时间：{record.plan_time}")
        if record.alert_person:
            plan_fields.append(f"提醒人员：{record.alert_person}")
        if record.notes:
            plan_fields.append(f"备注：{record.notes}")

        user_prompt = "\n".join(plan_fields) if plan_fields else record.drill_content or ""

        if not user_prompt.strip():
            logger.warning("No plan fields to generate drill plan: id=%s", record_id)
            return None

        # ── AI 服务 ──
        try:
            from app.modules.safety.service.config import create_ai_service
            ai_service = create_ai_service("text")
        except Exception:
            logger.exception("Failed to create AI service")
            return None

        # ── RAG + AI（统一审计 scope）──
        knowledge_md = ""
        regulation_list: list[dict[str, str]] = []
        response_text = ""
        try:
            from app.modules.safety.ai_audit import ai_audit_scope
            from app.modules.safety.knowledge.retriever import SafetyKnowledgeRetriever

            with ai_audit_scope(
                scenario="drill_plan_generation",
                resource_type="drill_record",
                resource_id=record_id,
                channel="web",
            ):
                # RAG 检索
                try:
                    query_text = f"{record.drill_type or ''} {record.drill_content or ''} 应急演练".strip()
                    retriever = SafetyKnowledgeRetriever(self.session, ai_service=ai_service)
                    ctx = await retriever.retrieve(
                        description=query_text,
                        categories=["laws_regulations", "standards", "management_systems"],
                        target_chunks=6,
                    )
                    knowledge_md = retriever.build_injection_context(ctx) or ""
                    for chunk in ctx.chunks[:6]:
                        title = getattr(chunk, "source_doc", None) or ""
                        if title:
                            regulation_list.append({
                                "title": title,
                                "article": getattr(chunk, "source_article", "") or "",
                                "excerpt": (getattr(chunk, "chunk_text", "") or "")[:200],
                            })
                except Exception:
                    logger.warning("RAG retrieval failed", exc_info=True)

                if knowledge_md:
                    user_prompt += f"\n\n参考法规：\n{knowledge_md}"

                # 调用 AI
                response_text = await ai_service.chat(
                    [
                        {"role": "system", "content": _DRILL_PLAN_SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format="json_object",
                )
        except Exception:
            logger.exception("AI call failed: record_id=%s", record_id)
            return None
        finally:
            await ai_service.close()

        # ── 估算 token 用量 ──
        estimated_tokens = (
            len(_DRILL_PLAN_SYSTEM_PROMPT) // 3
            + len(user_prompt) // 3
            + len(response_text) // 3
        )

        # ── 解析响应 ──
        try:
            response_json = json.loads(response_text)
        except json.JSONDecodeError:
            response_json = {"title": record.drill_content, "sections": []}

        doc_title = response_json.get("title") or f"{record.drill_content} — 演练方案"

        # ── 存储文档 ──
        version = await self._next_version(record_id)
        doc = EmergencyDrillDocument(
            resource_type="drill_record",
            resource_id=record_id,
            doc_type="drill_plan",
            title=doc_title,
            content=response_text,
            content_json=response_json,
            generation_params={"record_id": str(record_id)},
            cited_regulations=regulation_list or response_json.get("cited_regulations"),
            ai_model=getattr(ai_service, "model", None),
            ai_tokens_used=estimated_tokens,
            version=version,
        )
        self.session.add(doc)
        await self.session.flush()

        # ── 创建飞书云文档（降级：失败不阻塞）──
        try:
            from app.modules.safety.feishu.docx_service import FeishuDocxService

            docx = FeishuDocxService()
            result = await docx.create_drill_document(response_json, doc_title)
            if result:
                feishu_doc_id, feishu_doc_url = result
                doc.feishu_doc_id = feishu_doc_id
                doc.feishu_doc_url = feishu_doc_url
                doc.feishu_doc_status = "created"
            else:
                doc.feishu_doc_status = "failed"
        except Exception:
            logger.warning("Feishu doc creation failed, continuing: record_id=%s", record_id)
            doc.feishu_doc_status = "failed"

        # ── 上传生成的方案 .docx 到 Bitable「演练方案」字段（降级：失败不阻塞）──
        try:
            await _upload_generated_plan_to_bitable(record, response_json, doc_title)
        except Exception:
            logger.warning(
                "Bitable plan upload failed, continuing: record_id=%s", record_id, exc_info=True,
            )

        logger.info("AI drill plan generated: doc_id=%s record_id=%s", doc.id, record_id)
        return doc

    async def get_documents(self, record_id: uuid.UUID) -> list[EmergencyDrillDocument]:
        query = (
            select(EmergencyDrillDocument)
            .where(
                EmergencyDrillDocument.resource_id == record_id,
                ~EmergencyDrillDocument.is_deleted,
            )
            .order_by(EmergencyDrillDocument.version.desc())
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # ══════════════════════════════════════════════════════
    # AI 附件解析 → 计划字段
    # ══════════════════════════════════════════════════════

    @staticmethod
    async def parse_drill_plan_fields(document_text: str) -> dict[str, str]:
        """从演练计划文档中 AI 提取结构化字段。

        由 collection handler 调用，不依赖 session。
        返回可直接写入 Bitable 的中文字段名 dict。
        """
        from app.modules.safety.ai_audit import ai_audit_scope
        from app.modules.safety.service.config import create_ai_service

        ai = create_ai_service("text")

        system_prompt = """你是一名应急管理专家，擅长从演练计划文档中提取结构化信息。

请从以下文档中提取应急演练计划的各项字段，严格按照 JSON 格式返回：

{
  "drill_type": "演练类型",
  "drill_content": "演练内容",
  "department": "演练部门",
  "organizer": "组织人",
  "participants": "参演人员",
  "coop_department": "配合部门",
  "duration": "课时",
  "plan_time": "计划时间",
  "plan_time_ref": "计划日期",
  "notes": "备注"
}

规则：
- drill_type 必须为以下之一：应急疏散演练、现场岗位处置、专项应急演练、综合应急演练、消防器材培训。如果文档没有明确说明，根据内容推断最匹配的类型。
- drill_content 用 50-200 字简洁描述演练场景和目的。
- 文档中找不到的字段设为空字符串 ""。
- 日期统一为 YYYY-MM-DD 格式。
- 不要输出任何 JSON 之外的内容。"""

        # 截断过长文档（DeepSeek 上下文限制）
        text = document_text[:12000]

        with ai_audit_scope(
            scenario="drill_plan_parsing",
            channel="system",
        ):
            try:
                response = await ai.chat(
                    [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"演练计划文档内容：\n\n{text}"},
                    ],
                    response_format="json_object",
                )
            except Exception:  # noqa: BLE001 — 含场景停用(ScenarioDisabledError)等,按「字段缺失走默认」降级
                logger.warning("AI plan parsing request failed（含 AI 场景停用），返回空字段")
                return {}
            finally:
                await ai.close()

        try:
            parsed = json.loads(response)
        except Exception:  # noqa: BLE001 — 原仅捕获 JSONDecodeError,扩大兜底
            logger.warning("AI plan parsing returned invalid JSON")
            return {}

        # 字段映射：英文 key → Bitable 中文列名
        field_map = {
            "drill_type": "演练类型",
            "drill_content": "演练内容",
            "department": "演练部门",
            "organizer": "组织人",
            "participants": "参演人员",
            "coop_department": "配合部门",
            "duration": "课时",
            "plan_time": "计划时间",
            "notes": "备  注",
        }

        result: dict = {}
        for en_key, cn_field in field_map.items():
            if en_key == "plan_time_ref":
                continue  # 日期字段单独处理
            value = parsed.get(en_key, "") or ""
            if value:
                result[cn_field] = value

        # 日期字段特殊处理：Bitable Date 类型需要毫秒时间戳
        plan_time_ref_str = parsed.get("plan_time_ref", "")
        if plan_time_ref_str:
            try:
                dt = datetime.strptime(plan_time_ref_str.strip()[:10], "%Y-%m-%d")
                result["计划时间参考"] = int(dt.timestamp() * 1000)
            except ValueError:
                pass  # 无法解析则跳过

        logger.info("AI parsed drill plan fields: %s", list(result.keys()))
        return result

    # ══════════════════════════════════════════════════════
    # 隐患追踪
    # ══════════════════════════════════════════════════════

    async def create_hazards_from_issues(self, record_id: uuid.UUID) -> list[dict[str, Any]]:
        """将「演练问题」拆分为隐患记录并建立关联。

        已有隐患编号的跳过不重复创建。
        """
        record = await self.get_record(record_id)
        if not record or not record.issues or not record.issues.strip():
            return []

        # 已关联的跳过
        existing_links = await self._get_hazard_links(record_id)
        if existing_links:
            logger.info("Hazard links already exist for record_id=%s", record_id)
            return [
                {"hazard_id": str(link.hazard_report_id), "drill_record_id": str(record_id)}
                for link in existing_links
            ]

        # AI 拆分问题
        issues_list = await self._parse_issues_with_ai(record.issues, record_id)
        if not issues_list:
            # Fallback：整段作为一条隐患
            issues_list = [{"description": record.issues, "hazard_type": "其他隐患"}]

        from app.modules.safety.models import HazardReport

        # 生成今天的隐患编号前缀
        today_str = datetime.now().strftime("%Y%m%d")
        # 查询今天已有的隐患数量（含软删除，因为唯一约束跨软删除记录）
        cnt_q = select(func.count(HazardReport.id)).where(
            HazardReport.hazard_no.like(f"HZ-{today_str}-%")
        )
        existing = (await self.session.scalar(cnt_q)) or 0

        created = []
        seq = existing

        for issue in issues_list:
            try:
                seq += 1
                description = issue.get("description", "")
                hazard_type = issue.get("hazard_type", "其他隐患")

                hazard = HazardReport(
                    hazard_no=f"HZ-{today_str}-{seq:03d}",
                    description=description,
                    hazard_type=hazard_type,
                    department=record.department,
                    discovered_by_name=record.organizer or "",
                    discovered_at=datetime.now(tz=UTC),
                    hazard_level=issue.get("risk_level", "一般"),
                    notes=f"[应急演练] {record.drill_content or ''}"[:500],
                )
                self.session.add(hazard)
                await self.session.flush()

                # 创建关联
                link = DrillHazardLink(
                    drill_record_id=record_id,
                    hazard_report_id=hazard.id,
                )
                self.session.add(link)

                created.append({
                    "hazard_id": str(hazard.id),
                    "description": description,
                })
                logger.info(
                    "Created hazard from drill issue: hazard_id=%s drill_id=%s",
                    hazard.id, record_id,
                )
            except Exception:
                logger.exception("Failed to create hazard for issue: %s", issue.get("description", ""))

        await self.session.flush()
        return created

    async def get_hazard_links(self, record_id: uuid.UUID) -> list[dict[str, Any]]:
        """查询关联的隐患记录及状态。"""
        links = await self._get_hazard_links(record_id)
        if not links:
            return []

        from app.modules.safety.models import HazardReport

        result = []
        for link in links:
            hq = select(HazardReport).where(
                HazardReport.id == link.hazard_report_id,
                ~HazardReport.is_deleted,
            )
            hazard = (await self.session.execute(hq)).scalar_one_or_none()
            if hazard:
                result.append({
                    "hazard_id": str(hazard.id),
                    "hazard_no": getattr(hazard, "hazard_no", ""),
                    "description": hazard.description or "",
                    "status": getattr(hazard, "status", ""),
                    "rectification_status": getattr(hazard, "rectification_status", ""),
                })
        return result

    async def check_and_complete(self, record_id: uuid.UUID) -> bool:
        """检查关联隐患是否全部关闭，是则自动标记状态=已完成。"""
        links = await self._get_hazard_links(record_id)
        if not links:
            return False

        from app.modules.safety.models import HazardReport

        all_closed = True
        for link in links:
            hq = select(HazardReport).where(
                HazardReport.id == link.hazard_report_id,
                ~HazardReport.is_deleted,
            )
            hazard = (await self.session.execute(hq)).scalar_one_or_none()
            if hazard:
                rect_status = getattr(hazard, "rectification_status", "") or ""
                if rect_status not in ("closed", "verified"):
                    all_closed = False
                    break

        if all_closed:
            stmt = (
                update(EmergencyDrillRecord)
                .where(EmergencyDrillRecord.id == record_id)
                .values(status="已完成", updated_at=func.now())
            )
            await self.session.execute(stmt)
            logger.info("Drill record auto-completed: id=%s", record_id)
            return True
        return False

    # ══════════════════════════════════════════════════════
    # 统计
    # ══════════════════════════════════════════════════════

    async def get_stats(self) -> DrillStatsResponse:
        no_del = ~EmergencyDrillRecord.is_deleted

        total_q = select(func.count(EmergencyDrillRecord.id)).where(no_del)
        total = (await self.session.scalar(total_q)) or 0

        executed_q = select(func.count(EmergencyDrillRecord.id)).where(
            no_del, EmergencyDrillRecord.execution_time.isnot(None),
        )
        executed = (await self.session.scalar(executed_q)) or 0

        completed_q = select(func.count(EmergencyDrillRecord.id)).where(
            no_del, EmergencyDrillRecord.status == "已完成",
        )
        completed = (await self.session.scalar(completed_q)) or 0

        pending = total - completed

        # 按类型
        by_type_raw = await self.session.execute(
            select(EmergencyDrillRecord.drill_type, func.count(EmergencyDrillRecord.id))
            .where(no_del)
            .group_by(EmergencyDrillRecord.drill_type)
        )
        by_type = {row[0] or "未分类": row[1] for row in by_type_raw.all()}

        # 按部门
        by_dept_raw = await self.session.execute(
            select(EmergencyDrillRecord.department, func.count(EmergencyDrillRecord.id))
            .where(no_del)
            .group_by(EmergencyDrillRecord.department)
        )
        by_department = {row[0] or "未分类": row[1] for row in by_dept_raw.all()}

        return DrillStatsResponse(
            total=total,
            executed=executed,
            completed=completed,
            pending=pending,
            by_type=by_type,
            by_department=by_department,
        )

    # ══════════════════════════════════════════════════════
    # 收录记录
    # ══════════════════════════════════════════════════════

    async def list_collection_records(
        self,
        skip: int = 0,
        limit: int = 20,
        *,
        parse_status: str | None = None,
    ) -> tuple[list[DrillCollectionRecord], int]:
        base = select(DrillCollectionRecord).where(~DrillCollectionRecord.is_deleted)
        count_base = select(func.count(DrillCollectionRecord.id)).where(
            ~DrillCollectionRecord.is_deleted
        )
        if parse_status:
            base = base.where(DrillCollectionRecord.parse_status == parse_status)
            count_base = count_base.where(DrillCollectionRecord.parse_status == parse_status)

        total = (await self.session.scalar(count_base)) or 0
        query = base.offset(skip).limit(limit).order_by(DrillCollectionRecord.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all()), total

    async def get_collection_record(self, record_id: uuid.UUID) -> DrillCollectionRecord | None:
        query = select(DrillCollectionRecord).where(
            DrillCollectionRecord.id == record_id,
            ~DrillCollectionRecord.is_deleted,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_collection_stats(self) -> dict:
        no_del = ~DrillCollectionRecord.is_deleted
        total = (await self.session.scalar(
            select(func.count(DrillCollectionRecord.id)).where(no_del)
        )) or 0
        parsed = (await self.session.scalar(
            select(func.count(DrillCollectionRecord.id)).where(
                no_del, DrillCollectionRecord.parse_status == "parsed"
            )
        )) or 0
        pending = (await self.session.scalar(
            select(func.count(DrillCollectionRecord.id)).where(
                no_del, DrillCollectionRecord.parse_status == "pending"
            )
        )) or 0
        failed = (await self.session.scalar(
            select(func.count(DrillCollectionRecord.id)).where(
                no_del, DrillCollectionRecord.parse_status == "failed"
            )
        )) or 0
        return {"total": total, "parsed": parsed, "pending": pending, "failed": failed}

    # ══════════════════════════════════════════════════════
    # 内部
    # ══════════════════════════════════════════════════════

    async def _next_version(self, record_id: uuid.UUID) -> int:
        q = select(func.max(EmergencyDrillDocument.version)).where(
            EmergencyDrillDocument.resource_id == record_id,
            ~EmergencyDrillDocument.is_deleted,
        )
        v = await self.session.scalar(q)
        return (v or 0) + 1

    async def _get_hazard_links(self, record_id: uuid.UUID) -> list[DrillHazardLink]:
        q = select(DrillHazardLink).where(
            DrillHazardLink.drill_record_id == record_id,
        )
        result = await self.session.execute(q)
        return list(result.scalars().all())

    async def _parse_issues_with_ai(self, issues_text: str, record_id: uuid.UUID) -> list[dict[str, Any]]:
        """用 AI 将演练问题文本拆分为结构化的隐患列表。"""
        ai_service = None
        try:
            from app.modules.safety.ai_audit import ai_audit_scope
            from app.modules.safety.service.config import create_ai_service
            ai_service = create_ai_service("text")

            prompt = f"""将以下演练中发现的问题拆分为独立的安全隐患条目。

每个问题提取为 JSON 数组，每项包含：
- description: 隐患描述（简洁）
- hazard_type: 隐患类型（设备设施/消防安全/电气安全/危险化学品/作业环境/人员操作/应急管理/其他隐患）
- risk_level: 风险等级（一般/较大/重大）

演练问题：
{issues_text}

请只返回 JSON 数组，不要其他文字。"""

            with ai_audit_scope(
                scenario="drill_issue_parsing",
                resource_type="drill_record",
                resource_id=record_id,
                channel="system",
            ):
                response = await ai_service.chat(
                    [{"role": "user", "content": prompt}],
                    response_format="json_object",
                )
            data = json.loads(response)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                items = data.get("items") or data.get("issues") or data.get("hazards") or []
                if isinstance(items, list):
                    return items
            return []
        except Exception:
            logger.warning("Failed to parse issues with AI, using fallback", exc_info=True)
            return []
        finally:
            if ai_service is not None:
                await ai_service.close()
