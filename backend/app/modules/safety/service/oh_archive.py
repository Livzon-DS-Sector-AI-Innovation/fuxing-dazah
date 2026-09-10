"""职业健康体检报告归档 Service（设计 §13.6，ticket 18）。

四条附件链路（L1 人工 Bitable / L2 Web 上传 / L3 机器人单文件 / L4 机器人压缩包）
共用底座：

- `upload_to_exam`：本地文件 → upload_media 上传飞书得 file_token → update_record 写
  Bitable 体检记录表「体检报告附件」（写回不设 _set_sync_ignore：该 changed 事件即
  镜像链路触发源，防循环由下游 AI/人员回写自带 ignore 保证）→ 镜像 changed
  事件自然触发 AI① 解析回填（本服务**不**手动触发 AI，保持单一路径）；
- `match_exam`：文件名/回复文本解析体检号（`Z\\d{12,}`）或姓名 → 匹配平台
  oh_health_exams（体检号精确 / 姓名取最新未体检记录，多条返回候选由用户选择）；
- `extract_zip`：安全解压（§13.6.5：拒绝路径穿越/绝对路径；单文件 ≤50MB、
  解压后总 ≤200MB；仅 PDF/图片；≤20 个文件；其他类型跳过并记录）；
- `archive_files_to_exam`：多文件批量归档（逐文件串行，§13.6.7 A3 限流语义）；
- `archive_and_reply`：L3/L4 机器人归档编排（§13.6.2/§13.6.3）——初始文件消息
  （PDF/图片→L3 单文件，zip→L4 解压批量）与用户回复二次匹配（姓名/体检号/候选
  序号，A2 无持久化：挂起状态仅存内存、TTL 过期即清理）。

Bitable 配置未配置（经配置中心 store 读取，DB 活行 → registry 默认）或体检记录无
feishu_record_id → 告警静默跳过，返回 None，不阻塞调用方。
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.modules.safety.models import OhHealthExam
from app.modules.safety.repository import SafetyRepository

logger = logging.getLogger(__name__)

# ── 常量（对齐设计 §13.6.3 / §13.6.5）──

# 体检号（Bitable 自动编号 Z2026xxx...）
EXAM_NO_RE = re.compile(r"Z\d{12,}")

# Bitable 体检记录表附件字段名（与 oh_bitable_handler 镜像字段一致）
ATTACHMENT_FIELD = "体检报告附件"

# L2/L3 单文件上传限制（≤50MB）
OH_UPLOAD_MAX_SIZE = 50 * 1024 * 1024
OH_UPLOAD_ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}

# 压缩包安全限制（§13.6.5）
ZIP_MAX_FILES = 20
ZIP_MAX_FILE_SIZE = 50 * 1024 * 1024
ZIP_MAX_TOTAL_SIZE = 200 * 1024 * 1024
ZIP_ALLOWED_EXTS = {".pdf", ".jpg", ".jpeg", ".png"}

# 文件名/回复文本姓名解析：先剔除常见后缀词，再取 2-4 个汉字的连续片段
_NAME_SUFFIX_WORDS = (
    "体检报告单", "体检报告", "报告单", "体检表", "体检回执",
    "体检", "报告", "归档", "扫描件", "扫描", "上传", "单",
)
_CJK_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,4}")

# ── L3/L4 机器人归档编排（设计 §13.6.2/§13.6.3，A2 无持久化）──

# 归档上传后等待镜像 → AI① 解析的轮询时长（秒）；超时按当前状态回复
# （pending/parsing 均属「解析中」语义，不阻塞回复）
_ARCHIVE_AWAIT_PARSE_SECONDS = 30.0
_ARCHIVE_PARSE_POLL_INTERVAL = 2.0

# 挂起归档状态 TTL（A2：不持久化会话上下文，仅内存 + 过期清理临时文件）
_PENDING_ARCHIVE_TTL_SECONDS = 30 * 60.0

# 体检类型 → 中文标签（回复候选列表用）
_EXAM_TYPE_LABELS = {
    "pre_employment": "岗前体检",
    "periodic": "在岗期间体检",
    "post_employment": "离岗体检",
    "transfer": "转岗体检",
    "emergency": "应急体检",
}


@dataclass
class _PendingFile:
    """挂起归档的单个文件（匹配失败待二次匹配，文件保留磁盘等待）。"""

    path: str
    name: str
    reason: str = "未匹配体检记录"


@dataclass
class _PendingArchive:
    """一次 L3/L4 归档的挂起状态（chat_id 维度，仅内存，TTL 过期清理）。"""

    chat_id: str
    kind: str                       # "single" | "zip"
    files: list[_PendingFile]       # 待归档（未完成）文件
    candidates: list[dict] | None   # 多条待体检记录候选快照（用户回复序号选择）
    created_at: float = field(default_factory=time.monotonic)


# chat_id → 挂起归档（进程内存；服务重启即失，符合 A2「不持久化」）
_pending_archives: dict[str, _PendingArchive] = {}


def _cleanup_file(path: str) -> None:
    """删除临时文件/目录，并尝试清理已空的父目录（忽略失败）。"""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
    parent = os.path.dirname(path)
    if parent:
        try:
            os.rmdir(parent)
        except OSError:
            pass


def _clear_pending_archives(chat_id: str) -> None:
    """清除 chat_id 的挂起归档并删除其临时文件。"""
    pending = _pending_archives.pop(chat_id, None)
    if pending:
        for f in pending.files:
            _cleanup_file(f.path)


def _sweep_pending_archives() -> None:
    """惰性清扫过期挂起归档（TTL 超时 → 删临时文件 + 移除状态）。"""
    now = time.monotonic()
    for chat_id, pending in list(_pending_archives.items()):
        if now - pending.created_at > _PENDING_ARCHIVE_TTL_SECONDS:
            _clear_pending_archives(chat_id)


def has_pending_oh_archive(chat_id: str) -> bool:
    """是否存在未完成的 OH 归档挂起状态（供机器人文本消息分流判断）。"""
    _sweep_pending_archives()
    return chat_id in _pending_archives


def looks_like_oh_archive_reply(text: str) -> bool:
    """用户回复是否像归档二次匹配输入（体检号 / 序号 / 姓名）。"""
    t = (text or "").strip()
    if not t:
        return False
    if EXAM_NO_RE.search(t):
        return True
    if t.isdigit():
        return True
    return _extract_name(t) is not None


def _exam_brief(exam: OhHealthExam) -> str:
    """候选体检记录摘要（体检号｜登记日期｜类型），供用户选序号。"""
    d = exam.scheduled_date or exam.exam_date
    ds = d.strftime("%Y-%m-%d") if d else "—"
    t = _EXAM_TYPE_LABELS.get(exam.exam_type, exam.exam_type or "体检")
    return f"{exam.exam_no or '未编号'}｜{ds}｜{t}"


def _exam_snapshots(exams: list[OhHealthExam]) -> list[dict]:
    """候选体检记录快照（序号选择用，避免跨请求持有 ORM 对象）。"""
    out: list[dict] = []
    for e in exams:
        d = e.scheduled_date or e.exam_date
        out.append({
            "exam_id": str(e.id),
            "exam_no": e.exam_no,
            "employee_name": e.employee_name,
            "exam_type": e.exam_type,
            "scheduled_date": d.isoformat() if d else None,
        })
    return out


def _parse_status_text(entry: dict) -> str:
    """AI 解析状态 → 回复文案（解析中/完成摘要/失败）。"""
    st = entry.get("status") or "pending"
    if st == "parsed":
        summary = (entry.get("interpretation") or "").strip().replace("\n", " ")
        if summary:
            return f"解析完成：{summary[:120]}"
        return "解析完成"
    if st == "parsing":
        return "解析中"
    if st == "failed":
        return "解析失败（需人工处理）"
    return "排队等待解析"


def _safe_zip_name(name: str) -> bool:
    """zip 条目名安全校验：拒绝空名、绝对路径、盘符与 `..` 路径穿越。"""
    if not name:
        return False
    norm = name.replace("\\", "/")
    if norm.startswith("/"):
        return False
    if re.match(r"^[A-Za-z]:", norm):
        return False
    if ".." in norm.split("/"):
        return False
    return True


def _extract_name(text: str) -> str | None:
    """从文件名/回复文本提取人名（2-4 个汉字连续片段）。

    先剔除体检号与常见后缀词（体检报告/体检/报告/扫描件等），
    再取首个长度 2-4 的汉字片段；无法提取返回 None。
    """
    cleaned = EXAM_NO_RE.sub("", text or "")
    for word in _NAME_SUFFIX_WORDS:
        cleaned = cleaned.replace(word, "")
    for run in _CJK_RUN_RE.findall(cleaned):
        if 2 <= len(run) <= 4:
            return run
    return None


class OhArchiveService:
    """职业健康体检报告归档服务（L2 Web 上传 / L3/L4 机器人归档共用底座）。"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SafetyRepository(session)

    # ── 上传 ──

    @staticmethod
    def _registry_config() -> tuple[str, str]:
        """体检记录表 Bitable 配置（app_token, table_id）；未配置返回空串。

        经配置中心 store 读取（``store.get_connection("oh", "exam_registry")``，
        DB 活行 → registry 默认；未配置/停用返回空串）。
        """
        from app.modules.safety.bitable_config.store import store

        conn = store.get_connection("oh", "exam_registry")
        if conn is None or conn.status == "disabled":
            return "", ""
        return conn.app_token, conn.table_id

    async def _read_record_attachments(self, client: Any, record_id: str) -> list[dict]:
        """读取 Bitable 记录「体检报告附件」现有条目（[{file_token,name,size}]）。"""
        fields = await client.get_record(record_id)
        raw = fields.get(ATTACHMENT_FIELD) or []
        out: list[dict] = []
        for item in raw if isinstance(raw, list) else []:
            if isinstance(item, dict) and item.get("file_token"):
                out.append({
                    "file_token": item["file_token"],
                    "name": item.get("name", ""),
                    "size": item.get("size"),
                })
        return out

    async def upload_to_exam(
        self,
        exam_id: uuid.UUID,
        file_path: str,
        file_name: str,
    ) -> dict | None:
        """上传单文件归档到体检记录 Bitable「体检报告附件」字段。

        流程（L2/L3/L4 共用）：
        - 读取 Bitable 现有附件 → upload_media 上传飞书得 file_token；
        - 幂等：file_token 已存在 → 直接返回（重试安全，不重复写）；
          同名附件 → 覆盖旧条目（重复上传同一文件字段内始终单条）；否则追加；
        - 写回「体检报告附件」不设 _set_sync_ignore——该 changed 事件是镜像链路
          触发源（平台下载 → AI① 解析 → 完整回填，设计 §13.6.1/§13.6.2 L2 单一路径）；
          防循环由下游回写自带 ignore（oh_ai AI智能解读 / oh_person 汇总表）保证；
        - 上传后不手动触发 AI——镜像 changed（_attachments_changed）自然触发。

        Returns:
            附件元数据 dict（file_token/name/size/exam_id/record_id/extra）或 None
            （env 未配置 / 无 feishu_record_id / 上传或写回失败）。

        Raises:
            ValueError: 体检记录不存在。
        """
        exam = await self.repo.get_health_exam_by_id(exam_id)
        if exam is None:
            raise ValueError(f"体检记录不存在: {exam_id}")
        app_token, table_id = self._registry_config()
        if not app_token or not table_id:
            logger.warning("体检记录表 Bitable env 未配置，跳过归档上传: exam=%s", exam_id)
            return None
        record_id = exam.feishu_record_id
        if not record_id:
            logger.warning("体检记录无 feishu_record_id，跳过归档上传: exam=%s", exam_id)
            return None

        from app.modules.safety.feishu.bitable_client import (
            SafetyBitableClient,
            _build_attachment_extra,
        )

        client = SafetyBitableClient(app_token=app_token, table_id=table_id)
        existing = await self._read_record_attachments(client, record_id)

        # 幂等判定基于全部现有 token（同 token 重试 → 不重写）；
        # 同名附件 → 覆盖旧条目（重复上传同一文件名，字段内始终单条）
        existing_tokens = {a.get("file_token") for a in existing}
        remaining = [a for a in existing if a.get("name") != file_name]

        uploaded = await client.upload_media(file_path, file_name)
        if not uploaded or not uploaded.get("file_token"):
            logger.error("体检报告上传飞书失败: exam=%s name=%s", exam_id, file_name)
            return None
        file_token = uploaded["file_token"]

        # 幂等：file_token 已存在（上次写回实际成功后的重试）→ 直接返回
        if file_token in existing_tokens:
            logger.info(
                "体检报告附件已存在，幂等跳过写回: exam=%s name=%s token=%s",
                exam_id, file_name, file_token,
            )
            return {
                "file_token": file_token,
                "name": file_name,
                "size": os.path.getsize(file_path),
                "exam_id": str(exam_id),
                "record_id": record_id,
                "duplicate": True,
            }

        new_attachments = remaining + [{"file_token": file_token, "name": file_name}]
        # 附件写回**不**设 _set_sync_ignore：该 changed 事件正是镜像链路的触发源
        # （下载附件 → AI①解析 → 回填，设计 §13.6.1/§13.6.2 L2，单一路径）。
        # 防循环由下游平台→Bitable 回写自带 ignore 保证：AI智能解读（oh_ai.py）、
        # 人员汇总表/同步标志（oh_person.py）写回前均 _set_sync_ignore。
        ok = await client.update_record(
            record_id=record_id,
            fields={ATTACHMENT_FIELD: new_attachments},
        )
        if not ok:
            logger.error("体检报告附件写回 Bitable 失败: exam=%s record_id=%s", exam_id, record_id)
            return None

        meta: dict[str, Any] = {
            "file_token": file_token,
            "name": file_name,
            "size": os.path.getsize(file_path),
            "exam_id": str(exam_id),
            "record_id": record_id,
        }
        # extra（bitablePerm 下载鉴权）供调用方后续下载附件复用（与镜像三级下载一致）
        field_id = await client.get_field_id_by_name(ATTACHMENT_FIELD)
        if field_id:
            meta["extra"] = _build_attachment_extra(table_id, record_id, field_id, file_token)
        logger.info(
            "体检报告已归档 Bitable: exam=%s record_id=%s name=%s token=%s",
            exam_id, record_id, file_name, file_token,
        )
        return meta

    # ── 匹配 ──

    async def match_exam(
        self,
        file_name: str,
        reply_text: str | None = None,
    ) -> tuple[OhHealthExam | None, list[OhHealthExam]]:
        """文件名/回复文本 → 匹配体检记录（设计 §13.6.3）。

        匹配策略：
        - 体检号（`Z\\d{12,}`）→ 精确匹配（唯一）；
        - 姓名 → 该人员最新「未体检」记录（status=pending）；多条未体检 → 全部返回
          由用户选择（本轮会话内二次匹配，不持久化）；
        - `reply_text` 为用户回复的二次匹配输入（姓名/体检号），优先于文件名。

        Returns:
            (exam, candidates)：exam 为唯一命中（多条/未命中为 None）；
            candidates 为候选列表（含 exam），供机器人回复列表让用户选。
        """
        text = (reply_text or "").strip() or file_name
        m = EXAM_NO_RE.search(text)
        if m:
            exam = await self.repo.get_health_exam_by_no(m.group(0))
            if exam is not None:
                return exam, [exam]
            return None, []

        name = _extract_name(text)
        if not name:
            return None, []
        candidates = await self.repo.get_pending_health_exams_by_name(name)
        if len(candidates) == 1:
            return candidates[0], candidates
        return None, candidates

    # ── 压缩包 ──

    async def extract_zip(self, zip_path: str) -> list[str]:
        """安全解压 zip（设计 §13.6.5）。

        - 路径穿越：拒绝 `..` / 绝对路径 / 盘符条目；
        - 大小：单文件 ≤50MB（校验头 + 抽取时实计），解压后总 ≤200MB；
        - 类型：仅 .pdf/.jpg/.jpeg/.png，其他类型跳过并记录；
        - 数量：单 zip ≤20 个文件。

        Returns:
            解压后的文件路径列表（扁平存放于 uploads/safety/oh_zip/<uuid>/）。

        Raises:
            ValueError: 条目非法（路径穿越/超限）或 zip 损坏。
        """
        target_root = os.path.join("uploads", "safety", "oh_zip", uuid.uuid4().hex)
        os.makedirs(target_root, exist_ok=True)
        extracted: list[str] = []
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                infos = [i for i in zf.infolist() if not i.is_dir()]
                if len(infos) > ZIP_MAX_FILES:
                    raise ValueError(f"压缩包文件数超过上限（{ZIP_MAX_FILES} 个）")
                total_size = 0
                used_names: set[str] = set()
                for info in infos:
                    name = info.filename
                    if not _safe_zip_name(name):
                        raise ValueError(f"压缩包包含非法路径条目: {name!r}")
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in ZIP_ALLOWED_EXTS:
                        logger.warning("压缩包内跳过不支持的文件类型: %s", name)
                        continue
                    if info.file_size > ZIP_MAX_FILE_SIZE:
                        raise ValueError(f"压缩包内单文件超过 50MB 限制: {name}")
                    total_size += info.file_size
                    if total_size > ZIP_MAX_TOTAL_SIZE:
                        raise ValueError("压缩包解压后总大小超过 200MB 限制")

                    base = os.path.basename(name.replace("\\", "/"))
                    target = os.path.join(target_root, base)
                    if os.path.basename(target) in used_names:
                        target = os.path.join(target_root, f"{len(used_names)}_{base}")
                    used_names.add(os.path.basename(target))

                    # 抽取时实计大小（防压缩头虚报的 zip bomb）
                    with zf.open(info) as src, open(target, "wb") as out:
                        actual = 0
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            actual += len(chunk)
                            if actual > ZIP_MAX_FILE_SIZE:
                                raise ValueError(f"压缩包内单文件超过 50MB 限制: {name}")
                            out.write(chunk)
                    extracted.append(target)
            if not extracted:
                shutil.rmtree(target_root, ignore_errors=True)
            return extracted
        except Exception:
            shutil.rmtree(target_root, ignore_errors=True)
            raise

    # ── 批量 ──

    async def archive_files_to_exam(
        self, exam_id: uuid.UUID, files: list[str],
    ) -> list[dict]:
        """多文件批量归档（逐文件串行，§13.6.7 A3 限流语义，避免并发打爆 AI/飞书）。

        Returns:
            每个文件的归档结果 dict（ok=True 含附件元数据；失败含 error/skipped）。
        """
        results: list[dict] = []
        for path in files:
            file_name = os.path.basename(path)
            try:
                meta = await self.upload_to_exam(exam_id, path, file_name)
            except Exception as exc:
                logger.exception("批量归档单文件失败: exam=%s file=%s", exam_id, file_name)
                results.append({"file_name": file_name, "ok": False, "error": str(exc)})
                continue
            if meta is None:
                results.append({"file_name": file_name, "ok": False, "skipped": True})
            else:
                results.append({**meta, "ok": True})
        return results

    # ── L3/L4 机器人归档编排（设计 §13.6.2/§13.6.3，A2 无持久化）──

    async def archive_and_reply(
        self,
        *,
        chat_id: str,
        file_path: str | None = None,
        file_name: str | None = None,
        reply_text: str | None = None,
        await_parse_seconds: float | None = None,
        parse_poll_interval: float | None = None,
    ) -> dict:
        """L3/L4 机器人归档编排（下载后的文件 → 匹配 → 上传 → 回复文案）。

        两种调用形态：
        - 初始文件消息：传 `file_path` + `file_name`（.zip → L4 解压批量归档；
          PDF/图片 → L3 单文件归档）；
        - 用户回复二次匹配：传 `reply_text`（姓名/体检号/候选序号），基于内存
          挂起状态续作（匹配失败的文件保留在磁盘，TTL 内等待用户回复）。

        匹配策略（§13.6.3）：文件名含体检号直接定位；含姓名取该人最新未体检记录；
        多条待归档回复序号列表让用户选；无标识/匹配失败回复询问，用户回复后
        二次匹配（reply_text 优先），本轮会话内生效、不持久化（A2）。

        上传走 `upload_to_exam` → Bitable 附件 changed → 镜像自动触发 AI① 解析
        （不手动触发 AI，单一路径）；回复含归档结果 + AI 解析状态（轮询
        `await_parse_seconds` 秒，超时按当前状态回复「解析中/排队」）。

        Returns:
            {
              "status": "archived"|"ask_name"|"ask_choice"|"rematch_failed"|
                        "invalid_choice"|"error"|"fallthrough"|"no_pending",
              "kind": "single"|"zip",
              "reply": 机器人回复文本（fallthrough/no_pending 时为空，调用方不回复），
              "archived": [{file_name, exam_no, employee_name, ok, ...}],
              "unmatched": [file_name, ...],
            }
        """
        _sweep_pending_archives()
        if reply_text is not None:
            return await self._resume_pending(
                chat_id, reply_text,
                await_parse_seconds=await_parse_seconds,
                parse_poll_interval=parse_poll_interval,
            )
        if not file_path:
            return {"status": "error", "kind": "", "reply": "缺少文件，请重新发送。"}
        # 同会话新的归档文件 → 覆盖旧挂起（旧文件清理）
        if chat_id in _pending_archives:
            _clear_pending_archives(chat_id)
        ext = os.path.splitext(file_name or file_path)[1].lower()
        if ext == ".zip":
            return await self._archive_zip(
                chat_id, file_path,
                await_parse_seconds=await_parse_seconds,
                parse_poll_interval=parse_poll_interval,
            )
        return await self._archive_single(
            chat_id, file_path, file_name or os.path.basename(file_path),
            await_parse_seconds=await_parse_seconds,
            parse_poll_interval=parse_poll_interval,
        )

    async def _archive_single(
        self, chat_id: str, file_path: str, file_name: str,
        await_parse_seconds: float | None = None,
        parse_poll_interval: float | None = None,
    ) -> dict:
        """L3 单文件：匹配 → 唯一命中上传；多条候选回序号列表；无标识询问。"""
        exam, candidates = await self.match_exam(file_name)
        if exam is not None:
            return await self._archive_to_exam(
                chat_id, [(file_path, file_name)], exam, "single",
                await_parse_seconds=await_parse_seconds,
                parse_poll_interval=parse_poll_interval,
            )
        if candidates:
            # 一人多条待归档 → 回复列表让用户选序号（挂起等待回复）
            _pending_archives[chat_id] = _PendingArchive(
                chat_id=chat_id, kind="single",
                files=[_PendingFile(file_path, file_name)],
                candidates=_exam_snapshots(candidates),
            )
            lines = "\n".join(f"{i + 1}. {_exam_brief(e)}" for i, e in enumerate(candidates))
            return {
                "status": "ask_choice", "kind": "single",
                "reply": (
                    f"📎 文件「{file_name}」匹配到多条待体检记录，请回复序号选择：\n{lines}"
                ),
            }
        # 无标识/匹配失败 → 询问（不静默；文件保留，用户回复后二次匹配）
        _pending_archives[chat_id] = _PendingArchive(
            chat_id=chat_id, kind="single",
            files=[_PendingFile(file_path, file_name)], candidates=None,
        )
        return {
            "status": "ask_name", "kind": "single",
            "reply": (
                f"已收到文件「{file_name}」，但无法从文件名识别对应的体检记录。\n"
                f"请回复「姓名」或「体检号」以完成归档。"
            ),
        }

    async def _archive_zip(
        self, chat_id: str, zip_path: str,
        await_parse_seconds: float | None = None,
        parse_poll_interval: float | None = None,
    ) -> dict:
        """L4 压缩包：安全解压 → 逐文件匹配 + 串行上传 → 回复汇总（§13.6.2 L4）。"""
        try:
            extracted = await self.extract_zip(zip_path)
        except ValueError as exc:
            _cleanup_file(zip_path)
            return {
                "status": "error", "kind": "zip",
                "reply": f"❌ 压缩包处理失败：{exc}",
            }
        if not extracted:
            _cleanup_file(zip_path)
            return {
                "status": "error", "kind": "zip",
                "reply": "❌ 压缩包内没有可归档的文件（仅支持 PDF/图片）。",
            }

        archived: list[dict] = []
        unmatched: list[_PendingFile] = []
        failed: list[dict] = []
        for path in extracted:
            name = os.path.basename(path)
            exam, candidates = await self.match_exam(name)
            if exam is None:
                reason = (
                    "多条待体检记录，请回复体检号"
                    if candidates else "未匹配体检记录"
                )
                unmatched.append(_PendingFile(path, name, reason=reason))
                continue
            res = await self.upload_to_exam(exam.id, path, name)
            _cleanup_file(path)  # 已处理文件清理（未匹配的保留在挂起状态）
            if res is None:
                failed.append({
                    "file_name": name, "exam_no": exam.exam_no or "—",
                    "employee_name": exam.employee_name,
                })
                continue
            archived.append({
                "file_name": name, "exam_no": exam.exam_no or "—",
                "employee_name": exam.employee_name, "ok": True,
                "exam_id": str(exam.id),
            })
        _cleanup_file(zip_path)

        # 批量 AI 解析状态轮询（共享轮询预算，A3 逐条串行语义由镜像链路保证）
        parse_map = await self._poll_parse_statuses(
            [a["exam_id"] for a in archived],
            await_parse_seconds=await_parse_seconds,
            parse_poll_interval=parse_poll_interval,
        )
        lines = [
            f"· {a['file_name']} → {a['exam_no']}（{a['employee_name']}）："
            f"已上传，{_parse_status_text(parse_map.get(a['exam_id'], {}))}"
            for a in archived
        ]
        lines += [f"· {f.name} → ⚠️ {f.reason}" for f in unmatched]
        lines += [
            f"· {f['file_name']} → ❌ 归档失败（上传被跳过）" for f in failed
        ]
        ok_n, total = len(archived), len(extracted)
        head = f"✅ 压缩包归档完成：成功 {ok_n} / 共 {total} 个文件"
        if ok_n == 0:
            head = f"❌ 压缩包归档失败：成功 {ok_n} / 共 {total} 个文件"
        reply = head + "\n" + "\n".join(lines)

        if unmatched:
            _pending_archives[chat_id] = _PendingArchive(
                chat_id=chat_id, kind="zip", files=unmatched, candidates=None,
            )
            names = "、".join(f.name for f in unmatched)
            reply += (
                f"\n\n以下文件未归档：{names}\n"
                f"请回复「姓名」或「体检号」以继续归档。"
            )
            return {
                "status": "ask_name", "kind": "zip", "reply": reply,
                "archived": archived, "unmatched": [f.name for f in unmatched],
            }
        return {
            "status": "archived", "kind": "zip", "reply": reply,
            "archived": archived, "unmatched": [],
        }

    async def _resume_pending(
        self, chat_id: str, reply_text: str,
        await_parse_seconds: float | None = None,
        parse_poll_interval: float | None = None,
    ) -> dict:
        """用户回复二次匹配（§13.6.3）：序号选择 / 姓名 / 体检号，本轮会话内生效。"""
        pending = _pending_archives.get(chat_id)
        if pending is None:
            return {"status": "no_pending", "kind": "", "reply": ""}
        text = (reply_text or "").strip()

        # ① 一人多条待归档 → 用户回复序号选择
        if text.isdigit() and pending.candidates:
            idx = int(text) - 1
            if not (0 <= idx < len(pending.candidates)):
                return {
                    "status": "invalid_choice", "kind": pending.kind,
                    "reply": f"❌ 序号无效，请输入 1-{len(pending.candidates)} 之间的数字。",
                }
            snap = pending.candidates[idx]
            exam = await self.repo.get_health_exam_by_id(uuid.UUID(snap["exam_id"]))
            if exam is None:
                return {
                    "status": "rematch_failed", "kind": pending.kind,
                    "reply": "❌ 所选体检记录不存在或已删除，请重新匹配。",
                }
            return await self._archive_to_exam(
                chat_id, [(f.path, f.name) for f in pending.files], exam, pending.kind,
                await_parse_seconds=await_parse_seconds,
                parse_poll_interval=parse_poll_interval,
            )

        # ② 姓名/体检号二次匹配（reply_text 优先于文件名）
        if not looks_like_oh_archive_reply(text):
            return {"status": "fallthrough", "kind": pending.kind, "reply": ""}
        exam, candidates = await self.match_exam(None, text)
        if exam is not None:
            return await self._archive_to_exam(
                chat_id, [(f.path, f.name) for f in pending.files], exam, pending.kind,
                await_parse_seconds=await_parse_seconds,
                parse_poll_interval=parse_poll_interval,
            )
        if candidates:
            pending.candidates = _exam_snapshots(candidates)
            lines = "\n".join(f"{i + 1}. {_exam_brief(e)}" for i, e in enumerate(candidates))
            return {
                "status": "ask_choice", "kind": pending.kind,
                "reply": f"📎 匹配到多条待体检记录，请回复序号选择：\n{lines}",
            }
        # 匹配失败必须回复询问（不静默）；挂起保留等待再次回复
        return {
            "status": "rematch_failed", "kind": pending.kind,
            "reply": "❌ 未找到匹配的体检记录，请确认姓名或体检号后重试（文件将保留等待归档）。",
        }

    async def _archive_to_exam(
        self,
        chat_id: str,
        files: list[tuple[str, str]],
        exam: OhHealthExam,
        kind: str,
        await_parse_seconds: float | None = None,
        parse_poll_interval: float | None = None,
    ) -> dict:
        """上传 files 到体检记录（逐条串行 A3）→ 清理临时文件 → 回复归档结果 + AI 状态。"""
        results = await self.archive_files_to_exam(exam.id, [p for p, _ in files])
        for path, _ in files:
            _cleanup_file(path)
        _clear_pending_archives(chat_id)

        parse = await self._poll_parse_statuses(
            [str(exam.id)],
            await_parse_seconds=await_parse_seconds,
            parse_poll_interval=parse_poll_interval,
        )
        pstatus = parse.get(str(exam.id), {})
        archived: list[dict] = []
        ok_n = 0
        for (path, name), r in zip(files, results):
            ok = bool(r.get("ok"))
            item = {
                "file_name": name, "exam_no": exam.exam_no or "—",
                "employee_name": exam.employee_name, "ok": ok,
            }
            if ok:
                ok_n += 1
            else:
                item["error"] = (
                    r.get("error") or "上传被跳过（Bitable 未配置或体检记录未绑定飞书）"
                )
            archived.append(item)

        if kind == "zip" or len(files) > 1:
            lines = []
            for it in archived:
                if it["ok"]:
                    lines.append(
                        f"· {it['file_name']} → {it['exam_no']}（{it['employee_name']}）："
                        f"已上传，{_parse_status_text(pstatus)}"
                    )
                else:
                    lines.append(
                        f"· {it['file_name']} → ❌ 归档失败：{it['error']}"
                    )
            head = (
                f"✅ 归档成功：{ok_n}/{len(files)} 个文件"
                if ok_n else f"❌ 归档失败：{ok_n}/{len(files)} 个文件"
            )
            return {
                "status": "archived" if ok_n else "error",
                "kind": kind, "reply": head + "\n" + "\n".join(lines),
                "archived": archived,
            }

        it = archived[0]
        if not it["ok"]:
            return {
                "status": "error", "kind": "single",
                "reply": f"❌ 归档失败：{it['error']}", "archived": archived,
            }
        reply = (
            "✅ 体检报告归档成功\n"
            f"· 文件：{it['file_name']}\n"
            f"· 体检号：{it['exam_no']}\n"
            f"· 姓名：{it['employee_name']}\n"
            f"· AI 解析状态：{_parse_status_text(pstatus)}"
        )
        return {"status": "archived", "kind": "single", "reply": reply, "archived": archived}

    async def _poll_parse_statuses(
        self,
        exam_ids: list[str],
        await_parse_seconds: float | None = None,
        parse_poll_interval: float | None = None,
    ) -> dict[str, dict]:
        """轮询体检记录 AI 解析状态（新 session 读取，避免身份图缓存）。

        上传后镜像 changed → AI① 解析为异步链路；此处等 `await_parse_seconds`
        （默认 `_ARCHIVE_AWAIT_PARSE_SECONDS`，0 = 仅读一次当前状态）。
        Returns: {exam_id: {"status": pending/parsing/parsed/failed, "interpretation": str}}
        """
        if not exam_ids:
            return {}
        timeout = (
            _ARCHIVE_AWAIT_PARSE_SECONDS
            if await_parse_seconds is None else max(float(await_parse_seconds), 0.0)
        )
        interval = (
            _ARCHIVE_PARSE_POLL_INTERVAL
            if parse_poll_interval is None else max(float(parse_poll_interval), 0.1)
        )
        out: dict[str, dict] = {}
        remaining = list(exam_ids)
        deadline = time.monotonic() + timeout
        while remaining:
            async with async_session_factory() as session:
                repo = SafetyRepository(session)
                still: list[str] = []
                for eid in remaining:
                    exam = await repo.get_health_exam_by_id(uuid.UUID(eid))
                    st = exam.ai_parse_status if exam else "unknown"
                    entry = {
                        "status": st,
                        "interpretation": (exam.ai_interpretation if exam else "") or "",
                    }
                    if st in ("parsed", "failed") or time.monotonic() >= deadline:
                        out[eid] = entry
                    else:
                        still.append(eid)
                remaining = still
            if remaining and time.monotonic() < deadline:
                await asyncio.sleep(interval)
        return out
