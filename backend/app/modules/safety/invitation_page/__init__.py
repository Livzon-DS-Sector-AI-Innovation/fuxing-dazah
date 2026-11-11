"""运动会宣传函页面包：模板渲染 + 内容管理 + GitHub Pages 发布。

结构：
- ``template.html``（Jinja2）+ ``content.json``（默认内容）+ ``assets/``（二维码/会徽）随包发布；
- 运行时内容覆盖与发布快照写入 ``backend/var/invitation/``（git 忽略），
  结构：``var/invitation/content.json``（当前生效内容）与 ``var/invitation/snapshots/``；
- 发布走 GitHub contents API 单文件 PUT；token/仓库/路径来自 settings
  （INVITATION_GITHUB_TOKEN / INVITATION_GITHUB_REPO / INVITATION_GITHUB_PATH）。

设计边界（一期）：只承载"现有宣传函"的渲染与发布；从零创作新页面不在本包职责内。
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_PKG_DIR = Path(__file__).parent
_TEMPLATE_NAME = "template.html"
_DEFAULT_CONTENT = _PKG_DIR / "content.json"
_QR_PATH = _PKG_DIR / "assets" / "qr.png"
_LOGO_PATH = _PKG_DIR / "assets" / "logo.png"

# 运行时可写目录（内容覆盖 + 快照），随 backend 工作目录解析
_VAR_DIR = Path("var") / "invitation"
_SNAPSHOT_DIR = _VAR_DIR / "snapshots"
_SNAPSHOT_KEEP = 10

_SECTIONS = (
    "meta描述", "页头", "信息条", "温馨提示", "流程",
    "项目", "积分", "奖项", "赛区", "助威", "尾部", "报名",
)


def _b64(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_PKG_DIR)),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def default_content() -> dict[str, Any]:
    """包内默认内容（随代码版本更新）。"""
    return json.loads(_DEFAULT_CONTENT.read_text(encoding="utf-8"))


def load_content() -> dict[str, Any]:
    """当前生效内容：运行时覆盖优先，缺省回落包内默认。"""
    override = _VAR_DIR / "content.json"
    if override.exists():
        try:
            return json.loads(override.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("invitation 内容覆盖文件损坏，回落包内默认")
    return default_content()


def save_content(content: dict[str, Any]) -> Path:
    """保存运行时内容覆盖。"""
    _VAR_DIR.mkdir(parents=True, exist_ok=True)
    path = _VAR_DIR / "content.json"
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def validate_content(content: dict[str, Any]) -> list[str]:
    """结构性校验：返回问题清单（空列表 = 通过）。"""
    problems: list[str] = []
    for key in _SECTIONS:
        if key not in content:
            problems.append(f"缺少板块「{key}」")
    for day in content.get("流程", []):
        for field in ("日期", "主题", "条目"):
            if field not in day:
                problems.append(f"流程[{day.get('日期', '?')}] 缺字段「{field}」")
    for row in content.get("积分", {}).get("行", []):
        if len(row.get("分数", [])) != 3:
            problems.append(f"积分[{row.get('赛制', '?')}] 分数必须为 3 项")
    if len(content.get("赛区", [])) != 8:
        problems.append("赛区必须为 8 项")
    return problems


def render(content: dict[str, Any]) -> str:
    """渲染完整 HTML（含内嵌二维码/会徽）。"""
    return _env().get_template(_TEMPLATE_NAME).render(
        c=content,
        qr_uri=_b64(_QR_PATH),
        logo_uri=_b64(_LOGO_PATH),
    )


# ── 快照 ──────────────────────────────────────────────────────────

def snapshot_current(html: str, content: dict[str, Any]) -> Path:
    """发布前保存当前版本快照（html + content），保留最近 _SNAPSHOT_KEEP 份。"""
    _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    p_html = _SNAPSHOT_DIR / f"index-{ts}.html"
    p_json = _SNAPSHOT_DIR / f"content-{ts}.json"
    p_html.write_text(html, encoding="utf-8")
    p_json.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    # 只保留最近 N 份
    snaps = sorted(_SNAPSHOT_DIR.glob("index-*.html"))
    for old in snaps[:-_SNAPSHOT_KEEP]:
        old.unlink(missing_ok=True)
    for old in sorted(_SNAPSHOT_DIR.glob("content-*.json"))[:-_SNAPSHOT_KEEP]:
        old.unlink(missing_ok=True)
    return p_json


def latest_snapshot() -> tuple[str, dict[str, Any]] | None:
    """最近一份快照的 (html, content)；无快照返回 None。"""
    snaps = sorted(_SNAPSHOT_DIR.glob("index-*.html"))
    if not snaps:
        return None
    html = snaps[-1].read_text(encoding="utf-8")
    p_json = snaps[-1].with_name(snaps[-1].name.replace("index-", "content-"))
    content = json.loads(p_json.read_text(encoding="utf-8")) if p_json.exists() else default_content()
    return html, content


# ── GitHub Pages 发布 ─────────────────────────────────────────────

def _github_conf() -> tuple[str, str, str, str]:
    """(token, repo, path, public_url)，从 settings 读取。"""
    from app.core.config import get_settings
    s = get_settings()
    return (
        s.INVITATION_GITHUB_TOKEN,
        s.INVITATION_GITHUB_REPO,
        s.INVITATION_GITHUB_PATH,
        s.INVITATION_PUBLIC_URL,
    )


async def fetch_published_html() -> str | None:
    """拉取当前线上 HTML（发布前快照用）；失败返回 None。"""
    token, repo, path, _ = _github_conf()
    if not token:
        return None
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
    if resp.status_code != 200:
        logger.warning("拉取线上宣传函失败 %s: %s", resp.status_code, resp.text[:200])
        return None
    data = resp.json()
    return base64.b64decode(data.get("content", "")).decode("utf-8")


async def publish_html(html: str, message: str) -> dict[str, Any]:
    """发布 HTML 到 GitHub Pages（contents API 单文件 PUT）。

    返回 {ok, url?, error?}。未配置 token 时 ok=False 并给出配置指引。
    """
    token, repo, path, public_url = _github_conf()
    if not token:
        return {
            "ok": False,
            "error": (
                "未配置 INVITATION_GITHUB_TOKEN：请在 .env 配置 GitHub fine-grained token"
                "（Contents 读写、仅授权 mid-autumn-invitation 仓库）后重试；"
                "本次修改已保存为本地草稿，配置后重新发布即可生效。"
            ),
        }
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        get_resp = await client.get(url, headers=headers)
        sha = None
        if get_resp.status_code == 200:
            sha = get_resp.json().get("sha")
        payload: dict[str, Any] = {
            "message": message or "update invitation via feishu bot",
            "content": base64.b64encode(html.encode("utf-8")).decode(),
        }
        if sha:
            payload["sha"] = sha
        put_resp = await client.put(url, headers=headers, json=payload)
    if put_resp.status_code not in (200, 201):
        detail = put_resp.text[:300]
        logger.warning("发布宣传函失败 %s: %s", put_resp.status_code, detail)
        return {"ok": False, "error": f"GitHub 发布失败（HTTP {put_resp.status_code}）：{detail}"}
    return {"ok": True, "url": public_url, "note": "GitHub Pages 构建 1-2 分钟后生效"}
