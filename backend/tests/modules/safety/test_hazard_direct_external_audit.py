"""督办通报检查未整改隐患栏（公司内检查=主表栏头对齐 + 管委会检查=外审直读）单元测试。

纯内存桩验证，不打飞书网络。分两层（接缝沿 build_bulletin 既有惯例，
2026-10-21 拍板确认）：
- ``external_audit`` 纯函数：to_view 状态从宽映射 / 北京日界 / fetch None
  路径 / 外审节渲染分支；
- ``bulletin.build_bulletin`` 集成：外审节拼接位置 / stats 新键 / 早退分支 /
  外审源缺席时输出与现状**逐字节一致**（值守轮询误刷的回归锚）。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.safety.service.hazard_direct import (
    bitable_repo,
    bulletin,
    external_audit,
)

_BJ = timezone(timedelta(hours=8))


def _ms(y: int, m: int, d: int) -> int:
    """北京日零点的 Bitable 毫秒时间戳（仿真实表日期字段存储）。"""
    return int(datetime(y, m, d, tzinfo=_BJ).timestamp() * 1000)


# ── 外审表记录构造 ──────────────────────────────────────────────


def _ext_record(
    seq: int,
    *,
    status: list[str] | None = None,
    dept: list[str] | None = None,
    desc: str | None = None,
    plan: str = "",
    persons: list[dict[str, str]] | None = None,
    checked_ms: int | None = None,
    target_ms: int | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "序号": seq,
        "缺陷项描述": desc if desc is not None else f"外审缺陷#{seq} 描述",
        "整改方案": plan or None,
        "隐患部门": dept if dept is not None else ["提炼工程二部"],
        "整改状态": status if status is not None else ["未关闭"],
        "责任人": persons if persons is not None else [
            {"id": f"ou_ext_{seq}", "name": f"责任人{seq}"},
        ],
    }
    if checked_ms is not None:
        fields["检查时间"] = checked_ms
    if target_ms is not None:
        fields["目标完成日期"] = target_ms
    return {"record_id": f"rec_ext_{seq}", "fields": fields}


# ── to_view：状态从宽映射 / 字段解析 ────────────────────────────


def test_to_view_closed_only_when_explicit_closed() -> None:
    """仅「已关闭」视为关闭；未关闭/空值/异常值从宽为未关闭（不漏报）。"""
    assert external_audit.to_view(
        _ext_record(1, status=["已关闭"])
    ).closed is True
    assert external_audit.to_view(
        _ext_record(2, status=["未关闭"])
    ).closed is False

    missing = _ext_record(3)
    missing["fields"].pop("整改状态")
    assert external_audit.to_view(missing).closed is False

    assert external_audit.to_view(
        _ext_record(4, status=["乱填的值"])
    ).closed is False


def test_to_view_in_progress_state() -> None:
    """「整改中」三态映射：不算关闭也不算未关闭（不进预警）。"""
    view = external_audit.to_view(_ext_record(1, status=["整改中"]))
    assert view.in_progress is True and view.closed is False
    assert external_audit.to_view(_ext_record(2)).in_progress is False


def test_to_view_skips_blank_description() -> None:
    assert external_audit.to_view(_ext_record(1, desc="   ")) is None
    assert external_audit.to_view({"record_id": "r", "fields": {}}) is None


def test_to_view_fields_and_beijing_dates() -> None:
    """日期字段按北京日界解析（UTC datetime 直接 .date() 会早一天）。"""
    view = external_audit.to_view(_ext_record(
        5,
        dept=["提炼工程四部", "动力部"],
        plan="联系外包整改",
        persons=[
            {"id": "ou_hong", "name": "洪川林"},
            {"userId": "ou_liu", "name": "刘柳兵"},
        ],
        checked_ms=_ms(2026, 10, 19),
        target_ms=_ms(2026, 12, 31),
    ))
    assert view.seq == 5
    assert view.departments == ["提炼工程四部", "动力部"]
    assert view.plan == "联系外包整改"
    assert view.checked_at == date(2026, 10, 19)
    assert view.target_date == date(2026, 12, 31)
    assert view.responsible == [("洪川林", "ou_hong"), ("刘柳兵", "ou_liu")]


def test_to_view_field_overrides_for_emergency_bureau() -> None:
    """省应急局源字段覆盖：方案列=「目前进展」、无目标完成日期列。"""
    rec = _ext_record(
        6, dept=["环保工程中心"], plan="待设备部出方案",
        persons=[{"id": "ou_yang", "name": "杨剑"}],
        checked_ms=_ms(2026, 10, 27),
    )
    rec["fields"]["目前进展"] = [{"text": "待进行招标", "type": "text"}]
    view = external_audit.to_view(
        rec, plan_field="目前进展", target_field=None,
    )
    assert view.plan == "待进行招标"
    assert view.target_date is None
    assert view.checked_at == date(2026, 10, 27)


# ── fetch：源未配置 → None ──────────────────────────────────────


async def test_fetch_returns_none_when_source_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.modules.safety.service.bitable_direct import reader as bd_reader
    from app.modules.safety.service.bitable_direct.errors import BitableConfigError

    def raise_cfg(*args: Any, **kw: Any) -> None:
        raise BitableConfigError("未配置或已停用")

    monkeypatch.setattr(bd_reader, "resolve_client", raise_cfg)
    assert await external_audit.fetch_external_audit() is None


# ── build_external_section：渲染分支 ────────────────────────────


def test_section_groups_mentions_link_and_stats() -> None:
    views = [
        external_audit.to_view(_ext_record(
            1, dept=["提炼工程二部"],
            persons=[{"id": "ou_cai", "name": "蔡万进"}],
            checked_ms=_ms(2026, 10, 19), target_ms=_ms(2026, 10, 31),
        )),
        external_audit.to_view(_ext_record(
            2, dept=["动力部"],
            persons=[{"id": "ou_liu", "name": "刘柳兵"}],
            checked_ms=_ms(2026, 10, 19),
        )),
        external_audit.to_view(_ext_record(3, dept=["动力部"])),
        external_audit.to_view(_ext_record(4, status=["已关闭"])),
        external_audit.to_view(_ext_record(5, dept=["动力部"], status=["整改中"])),
    ]
    lines, stats = external_audit.build_external_section(
        views, app_token="APP", table_id="TBL", today=date(2026, 10, 21),
    )
    body = "\n".join(lines)

    assert stats == {
        "ext_open": 3, "ext_closed": 1, "ext_doing": 1, "ext_depts": 2,
        "ext_by_dept": {"提炼工程二部": 1, "动力部": 2},
    }
    assert "管委会检查未整改隐患" in body
    assert "🔴 未关闭 **3** 条  ·  ✅ 已关闭 1 条  ·  涉及 **2** 个部门" in body
    # 部门按未关闭数降序：动力部在前
    assert body.index("**动力部（2条）**") < body.index("**提炼工程二部**")
    assert "<at id=ou_cai></at>" in body and "<at id=ou_liu></at>" in body
    # 已关闭项与整改中项都不进明细（整改中与主表同口径不预警）
    assert "外审缺陷#4" not in body
    assert "外审缺陷#5" not in body
    assert "外审缺陷#1 描述" in body
    # 目标日期纯展示、检查日期带天数
    assert "目标：2026-10-31" in body
    assert "检查：2026-10-19（2 天）" in body
    assert (
        "https://j0eukrlohu.feishu.cn/base/APP?table=TBL&record=rec_ext_1" in body
    )


def test_section_all_closed_line_and_plain_dept_head() -> None:
    """全部关闭出收口行；无责任人的部门头纯文本不 @。"""
    views = [
        external_audit.to_view(_ext_record(i, status=["已关闭"]))
        for i in (1, 2)
    ]
    lines, stats = external_audit.build_external_section(views)
    body = "\n".join(lines)
    assert stats["ext_open"] == 0 and stats["ext_closed"] == 2
    assert "✅ 管委会检查已全部关闭（累计 2 条）" in body

    solo = external_audit.to_view(_ext_record(1, persons=[]))
    lines, _ = external_audit.build_external_section(
        [solo], today=date(2026, 10, 21),
    )
    body = "\n".join(lines)
    assert "**提炼工程二部**" in body
    assert "<at" not in body


# ── build_bulletin 集成（既有接缝）──────────────────────────────


def _internal_record(
    no: str,
    *,
    dept: str = "设备工程部",
    persons: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "隐患编号": no,
        "隐患描述": f"{no} 隐患描述",
        "整改责任人": persons if persons is not None else [
            {"id": f"ou_{no}", "name": "张三"},
        ],
        "整改责任人.部门": [dept],
        "督办等级": "红色预警",
        "整改状态": "未关闭",
    }
    return {"record_id": f"rec_{no}", "fields": fields}


def _patch_render_deps(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict[str, Any]],
) -> None:
    """桩掉网络/DB 依赖（对齐 test_hazard_direct_bulletin 同款惯例）。"""
    from app.modules.safety.bitable_config.store import store as bitable_store
    from app.modules.safety.service import responsible_mapping
    from app.modules.safety.service.hazard_direct import progress_track

    async def fake_fetch(client: Any) -> list[dict[str, Any]]:
        return records

    async def fake_marks(views: Any) -> dict[str, str]:
        return {}

    async def fake_fallback(names: list[str]) -> dict[str, str]:
        return {n: f"ou_fb_{n}" for n in names}

    monkeypatch.setattr(bulletin, "_fetch_targets", fake_fetch)
    monkeypatch.setattr(progress_track, "compute_marks", fake_marks)
    monkeypatch.setattr(bulletin, "_load_person_open_ids", fake_fallback)
    monkeypatch.setattr(
        responsible_mapping, "DEPARTMENT_RESPONSIBLE_OVERRIDE", {},
    )
    monkeypatch.setattr(
        bitable_store, "get_connection",
        lambda *a: SimpleNamespace(
            app_token="app", table_id="tbl", status="active",
        ),
    )


def _stub_external_multi(
    monkeypatch: pytest.MonkeyPatch,
    stubs: dict[str, list[dict[str, Any]] | None | Exception],
) -> None:
    """多检查源桩：kind → None(源缺席)/列表(直读结果)/Exception(源故障)。

    未出现在 stubs 里的 kind 一律视为源未配置（缺席）。
    """

    async def fake_fetch(spec: Any = None) -> list[Any] | None:
        sp = spec or external_audit.SOURCE_MGMT
        kind = getattr(sp, "kind", sp)
        if kind not in stubs:
            return None
        records = stubs[kind]
        if isinstance(records, Exception):
            raise records
        if records is None:
            return None
        return [
            external_audit.to_view(
                r, plan_field=sp.plan_field, target_field=sp.target_field,
            )
            for r in records
        ]

    monkeypatch.setattr(external_audit, "fetch_external_audit", fake_fetch)


def _stub_external(
    monkeypatch: pytest.MonkeyPatch,
    records: list[dict[str, Any]] | None,
    kind: str = "defect_summary",
) -> None:
    """单源桩（默认管委会检查源；其余源保持缺席）。"""
    _stub_external_multi(monkeypatch, {kind: records})


async def test_build_bulletin_merges_external_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """外审节位于内部明细之后、部门汇总之前；统计与部门汇总并入外审。"""
    _patch_render_deps(monkeypatch, [_internal_record("HZ-001")])
    _stub_external(monkeypatch, [
        _ext_record(
            1, dept=["设备工程部"],
            persons=[{"id": "ou_cai", "name": "蔡万进"}],
            checked_ms=_ms(2026, 10, 19), target_ms=_ms(2026, 10, 31),
        ),
        _ext_record(2, status=["已关闭"]),
    ])

    content, stats = await bulletin.build_bulletin()

    assert stats["ext_open"] == 1 and stats["ext_closed"] == 1
    assert stats["ext_sources"]["管委会检查"]["by_dept"] == {"设备工程部": 1}
    # 详情直接从公司内检查栏开始（无标题/日期/速览行）
    assert content.startswith("━")
    assert "【隐患督办通报】" not in content and "📅" not in content
    # 顺序：公司内检查栏头 → 内部明细 → 管委会检查栏头 → 部门汇总
    i_int = content.index("📌 公司内检查未整改隐患")
    i_detail = content.index("HZ-001 隐患描述")
    i_ext = content.index("📌 管委会检查未整改隐患")
    i_summary = content.index("📌 各部门未关闭隐患数量汇总")
    assert i_int < i_detail < i_ext < i_summary
    assert "<at id=ou_cai></at>" in content
    # 底部部门汇总：同部门内外合并
    assert "**设备工程部**：红色预警 1 条　+　管委会检查未整改 1 条" in content


async def test_build_bulletin_unchanged_when_external_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回归锚：外审源缺席时输出与「无外审节」基线逐字节一致（值守不误刷）。

    基线含 2026-10-22 拍板的公司内检查栏头（主表数据同级栏目化）。
    """
    _patch_render_deps(monkeypatch, [_internal_record("HZ-001")])
    _stub_external(monkeypatch, None)

    content, stats = await bulletin.build_bulletin()

    expected = (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 公司内检查未整改隐患\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔴 红色预警 **1** 条  ·  🟡 一般预警 **0** 条  ·  涉及 **1** 个部门\n\n"
        "**设备工程部**　<at id=ou_HZ-001></at>\n"
        "**1.** HZ-001 隐患描述\n"
        "等级：-｜检查类型：-｜0天\n"
        "[📋 查看记录](https://j0eukrlohu.feishu.cn/base/app?table=tbl&record=rec_HZ-001)\n"
        "\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📌 各部门未关闭隐患数量汇总\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "**设备工程部**：红色预警 1 条\n"
    )
    assert content == expected
    assert "ext_open" not in stats


async def test_build_bulletin_external_failure_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """外审源故障只影响外审节缺席，内部督办照常出。"""
    _patch_render_deps(monkeypatch, [_internal_record("HZ-001")])
    _stub_external(monkeypatch, RuntimeError("外审源故障"))

    content, stats = await bulletin.build_bulletin()

    assert "管委会" not in content
    assert "ext_open" not in stats
    assert "HZ-001 隐患描述" in content


async def test_build_bulletin_external_empty_table_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """外审表已配置但零记录：整节缺席，不出只有标题的空节。"""
    _patch_render_deps(monkeypatch, [_internal_record("HZ-001")])
    _stub_external(monkeypatch, [])

    content, stats = await bulletin.build_bulletin()

    assert "管委会" not in content
    assert "ext_open" not in stats


async def test_build_bulletin_external_only_no_early_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """内部为空且外审有未关闭：不走「今日无」早退，外审节照常出。"""
    _patch_render_deps(monkeypatch, [])
    _stub_external(monkeypatch, [
        _ext_record(1, dept=["提炼工程二部"], checked_ms=_ms(2026, 10, 19)),
    ])

    content, stats = await bulletin.build_bulletin()

    assert stats["total"] == 0 and stats["ext_open"] == 1
    assert "✅ **今日无红色预警/一般预警隐患**" in content
    assert "管委会检查未整改隐患" in content
    assert "**提炼工程二部**：管委会检查未整改 1 条" in content


async def test_build_bulletin_all_closed_external_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """内部为空且外审全关闭：「今日无」+ 外审全关闭收口行。"""
    _patch_render_deps(monkeypatch, [])
    _stub_external(monkeypatch, [
        _ext_record(i, status=["已关闭"]) for i in (1, 2, 3)
    ])

    content, stats = await bulletin.build_bulletin()

    assert stats["ext_open"] == 0 and stats["ext_closed"] == 3
    assert "✅ **今日无红色预警/一般预警隐患**" in content
    assert "✅ 管委会检查已全部关闭（累计 3 条）" in content


async def test_build_bulletin_internal_empty_no_internal_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """内部为空：不出「公司内检查」栏头（不出只有标题的空节），管委会节照常。"""
    _patch_render_deps(monkeypatch, [])
    _stub_external(monkeypatch, [
        _ext_record(1, dept=["提炼工程二部"], checked_ms=_ms(2026, 10, 19)),
    ])

    content, stats = await bulletin.build_bulletin()

    assert stats["total"] == 0 and stats["ext_open"] == 1
    assert "✅ **今日无红色预警/一般预警隐患**" in content
    assert "📌 公司内检查未整改隐患" not in content
    assert "📌 管委会检查未整改隐患" in content


async def test_build_bulletin_doing_not_alerted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """整改中与主表同口径不预警：不进明细、不算未关闭，仅收口行计数。

    内部为空 + 外审（1 已关闭 + 2 整改中）：无未关闭 → 早退分支收口行
    并陈「已关闭/整改中」；顶部不出「管委会隐患未关闭」行。
    """
    _patch_render_deps(monkeypatch, [])
    _stub_external(monkeypatch, [
        _ext_record(1, status=["已关闭"], dept=["动力部"]),
        _ext_record(2, status=["整改中"], dept=["动力部"]),
        _ext_record(3, status=["整改中"], dept=["提炼工程二部"]),
    ])

    content, stats = await bulletin.build_bulletin()

    assert stats["ext_open"] == 0 and stats["ext_closed"] == 1
    assert stats["ext_doing"] == 2
    assert "✅ **今日无红色预警/一般预警隐患**" in content
    assert "✅ 管委会检查无未整改项（已关闭 1 条，整改中 2 条）" in content
    assert "管委会检查未整改 **" not in content
    assert "外审缺陷#2" not in content and "外审缺陷#3" not in content


async def test_build_bulletin_two_external_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """管委会检查/重大隐患（省应急局）同级各一节：节顺序、逐源汇总段、字段覆盖。

    重大隐患节走 SourceSpec 覆盖：栏头全名「重大隐患」（不套未整改模板）、
    方案列=「目前进展」→「进展：」前缀、无目标完成日期列。
    """
    _patch_render_deps(monkeypatch, [])
    eb_record = _ext_record(
        11, dept=["环保工程中心"], desc="环保装置未见工艺设计图",
        plan="待进行招标", checked_ms=_ms(2026, 10, 27),
    )
    eb_record["fields"]["目前进展"] = eb_record["fields"].pop("整改方案")
    eb_record["fields"].pop("目标完成日期", None)
    _stub_external_multi(monkeypatch, {
        "defect_summary": [
            _ext_record(
                1, dept=["提炼工程二部"],
                persons=[{"id": "ou_cai", "name": "蔡万进"}],
                checked_ms=_ms(2026, 10, 19), target_ms=_ms(2026, 10, 31),
            ),
        ],
        "emergency_bureau": [
            eb_record,
            _ext_record(12, dept=["环保工程中心"], status=["整改中"]),
        ],
    })

    content, stats = await bulletin.build_bulletin()

    assert stats["ext_open"] == 2  # 管委会 1 + 重大隐患 1（整改中不计）
    assert stats["ext_sources"]["重大隐患"]["doing"] == 1
    # 节顺序：今日无（内部空）→ 管委会检查 → 重大隐患 → 部门汇总
    i_mgmt = content.index("📌 管委会检查未整改隐患")
    i_eb = content.index("📌 重大隐患")
    i_summary = content.index("📌 各部门未关闭隐患数量汇总")
    assert i_mgmt < i_eb < i_summary
    # 重大隐患明细：「进展：」前缀（字段覆盖）、无「目标：」段；整改中不进明细
    eb_body = content[i_eb:i_summary]
    assert "环保装置未见工艺设计图" in eb_body
    assert "进展：待进行招标" in eb_body
    assert "目标：" not in eb_body
    assert "外审缺陷#12" not in content
    # 部门汇总逐源分段
    assert "**提炼工程二部**：管委会检查未整改 1 条" in content
    assert "**环保工程中心**：重大隐患未整改 1 条" in content
    # 速递格概览行逐源标注
    assert bulletin._overview_stats_line(stats) == (
        "未关闭 **2** 项 ｜ 🔴 红色预警 2（含管委会检查 1、重大隐患 1）"
        " · 🟡 一般预警 0"
    )


# ── all_clear_line：收口行分支 ──────────────────────────────────


def test_all_clear_line_variants() -> None:
    assert external_audit.all_clear_line({}, "管委会检查") == ""
    assert external_audit.all_clear_line({"ext_closed": 3}, "管委会检查") == (
        "✅ 管委会检查已全部关闭（累计 3 条）"
    )
    assert external_audit.all_clear_line({"ext_doing": 2}, "重大隐患") == (
        "✅ 重大隐患无未整改项（整改中 2 条）"
    )
    assert external_audit.all_clear_line(
        {"ext_closed": 1, "ext_doing": 2}, "管委会检查",
    ) == "✅ 管委会检查无未整改项（已关闭 1 条，整改中 2 条）"


# ── 速递格子概览统计行 ─────────────────────────────────────────


def test_overview_stats_line_with_and_without_external() -> None:
    base = {"total": 3, "urgent": 2, "warning": 1}
    assert bulletin._overview_stats_line(base) == (
        "未关闭 **3** 项 ｜ 🔴 红色预警 2 · 🟡 一般预警 1"
    )
    assert bulletin._overview_stats_line({
        **base, "ext_open": 4,
        "ext_sources": {"管委会检查": {"open": 4}},
    }) == (
        "未关闭 **7** 项 ｜ 🔴 红色预警 6（含管委会检查 4） · 🟡 一般预警 1"
    )
    assert bulletin._overview_stats_line({
        **base, "ext_open": 7,
        "ext_sources": {
            "管委会检查": {"open": 3},
            "重大隐患": {"open": 4, "closed": 1},
        },
    }) == (
        "未关闭 **10** 项 ｜ 🔴 红色预警 9（含管委会检查 3、重大隐患 4）"
        " · 🟡 一般预警 1"
    )


# ── 防御性：to_view 不应出现在内部主表渲染路径 ──────────────────


def test_internal_repo_unchanged_for_external_fields() -> None:
    """内部主表 to_view 与外审视图互不污染（外审字段名不进 HazardView）。"""
    view = bitable_repo.to_view(_ext_record(1))
    assert view.description == ""  # 外审字段名（缺陷项描述）非内部字段
