"""MSDS 台账表审核/修订字段一次性落地（幂等，可重复跑）。

- 「外观与现状」列改名「外观与性状」（GB/T 16483 标准术语，修正历史错别字；
  field_id 不变、数据不动，代码映射新旧名兼容）
- 新建「错别字审核」(单选：未审核/无错别字/疑似错别字)、「错别字明细」(文本)、
  「修订记录」(文本)——错别字审核 + 修订同步机制载体列

用法：cd backend && PYTHONPATH=. uv run python scripts/tmp/setup_msds_review_fields.py
"""

import asyncio

from dotenv import load_dotenv

load_dotenv(".env.development")

from app.modules.safety.bitable_config.store import store  # noqa: E402
from app.modules.safety.feishu.bitable_client import SafetyBitableClient  # noqa: E402

OLD_APPEARANCE = "外观与现状"
NEW_APPEARANCE = "外观与性状"

NEW_FIELDS: list[tuple[str, int, dict | None]] = [
    ("标签要素", 1, None),  # 2026-11-02：PDF 标签要素列（空值由 GHS 规则推导兜底）
    ("错别字审核", 3, {"options": [
        {"name": "未审核"}, {"name": "无错别字"}, {"name": "疑似错别字"}, {"name": "已自动修正"},
    ]}),
    ("错别字明细", 1, None),
    ("修订记录", 1, None),
]


async def main() -> None:
    conn = store.get_connection("msds", "registry")
    if not conn:
        print("MSDS registry 连接未配置")
        return
    client = SafetyBitableClient(app_token=conn.app_token, table_id=conn.table_id)
    fields = await client.list_fields()
    names = {f.get("field_name") for f in fields}
    print(f"现有字段 {len(names)} 个")

    # ① 外观列改名（新旧名都存在/都已改名 → 跳过；改名必须带 field_type，
    #    否则 Bitable 报 99992402 field validation failed）
    if NEW_APPEARANCE in names:
        print(f"[skip] {NEW_APPEARANCE} 已存在（列名已是标准术语）")
    elif OLD_APPEARANCE in names:
        fld = next(f for f in fields if f.get("field_name") == OLD_APPEARANCE)
        result = await client.update_field(
            fld["field_id"], field_name=NEW_APPEARANCE, field_type=fld.get("type"),
        )
        print(f"[rename] {OLD_APPEARANCE} → {NEW_APPEARANCE}: {'OK' if result else 'FAILED'}")
    else:
        print(f"[warn] {OLD_APPEARANCE}/{NEW_APPEARANCE} 列均不存在，跳过改名")

    # ② 机制字段建列（单选已存在时补齐缺的选项——update_field 需全量 options）
    for name, ftype, property_ in NEW_FIELDS:
        existing = next((f for f in fields if f.get("field_name") == name), None)
        if existing is None:
            created = await client.create_field(name, ftype, property_=property_)
            print(f"[create] {name} (type={ftype}): {'OK' if created else 'FAILED'}")
            continue
        if ftype == 3 and property_:
            want = [o["name"] for o in property_["options"]]
            have = [o.get("name") for o in (existing.get("property") or {}).get("options", [])]
            missing = [n for n in want if n not in have]
            if missing:
                # 已有选项保留完整对象（含 id），新选项仅 name——全量传回
                raw_opts = (existing.get("property") or {}).get("options", [])
                merged = [o for o in raw_opts if o.get("name") in have] + [{"name": n, "color": 3} for n in missing]
                # 坑：单选更新必须同时带 field_name（飞书校验要求，否则 99992402）
                r = await client.update_field(
                    existing["field_id"], field_name=name, field_type=ftype,
                    property_={"options": merged},
                )
                print(f"[update] {name} 补选项 {missing}: {'OK' if r else 'FAILED'}")
            else:
                print(f"[skip] {name} 选项已齐")
        else:
            print(f"[skip] {name} 已存在")

    final = {f.get("field_name") for f in await client.list_fields()}
    print(f"最终字段 {len(final)} 个；机制字段就绪："
          f"{all(n in final for n, _, _ in NEW_FIELDS)}")


if __name__ == "__main__":
    asyncio.run(main())
