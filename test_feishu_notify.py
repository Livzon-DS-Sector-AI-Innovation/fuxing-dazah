"""飞书通知诊断脚本 — 验证 token 获取和消息发送是否正常。

用法: uv run python -X utf8 test_feishu_notify.py <飞书open_id>

会依次测试：
1. 获取 tenant_access_token
2. 发送一条测试消息到指定用户
"""

import asyncio
import sys

from app.platform.integrations.feishu.notification import send_user_card


async def main():
    if len(sys.argv) < 2:
        print(
            "用法: uv run python -X utf8 "
            "test_feishu_notify.py <飞书open_id>"
        )
        print(
            "示例: uv run python -X utf8 "
            "test_feishu_notify.py ou_879f60593cd58f0b7c64941d8b74a26d"
        )
        return

    open_id = sys.argv[1]
    print(f"\n🔍 测试发送飞书通知到 open_id={open_id}")
    print("=" * 60)

    print("\n📤 发送测试消息...")
    ok = await send_user_card(
        open_id=open_id,
        title="🧪 测试通知",
        content="这是一条测试消息，如果你收到了，说明飞书通知功能正常。",
    )

    if ok:
        print("\n✅ 发送成功！请检查飞书消息。")
    else:
        print("\n❌ 发送失败，请查看上方日志中的错误详情。")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
