from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_db
from app.main import app  # noqa: A001
from app.platform.identity.models import User  # noqa: F401
from app.modules.safety.app_config.store import store as _safety_app_config_store

settings = get_settings()

# Test engine uses NullPool so each test gets a fresh connection on its own event loop.
_test_engine = create_async_engine(
    settings.DATABASE_URL,
    poolclass=pool.NullPool,
)
_test_session_factory = async_sessionmaker(
    _test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(autouse=True)
def safety_app_config_db_stub(monkeypatch: pytest.MonkeyPatch):
    """安全模块应用配置中心 DB 层 stub 为空（autouse）。

    生效优先级 env > DB 活行 > 代码默认：stub DB 层保证「未显式 setenv 的键」
    在测试里恒走 env/代码默认，不被本地 dev 库（可能已被启动播种写入真实值）
    的行污染——误发事故教训的防御层。需要 DB 层行为的测试自行覆写本 stub。
    """
    monkeypatch.setattr(_safety_app_config_store, "_fetch_rows", lambda: {})
    _safety_app_config_store.invalidate()
    yield


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide an AsyncSession that rolls back after each test."""
    async with _test_session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """Provide an AsyncClient with get_db overridden to use a rolled-back session.

    2026-11-13 P0 鉴权修复后追加：get_current_user 覆写为免登录口径（取库内
    第一个用户）。此前端点参数写 ``: Any = RequireUser`` 导致依赖根本不执行，
    client 走「无鉴权」路径；修复后依赖真实执行，全局覆写维持既有测试口径
    （RequireAdmin 的权限校验由各用例按需覆写 get_user_permissions）。
    """
    from app.platform.identity.deps import get_current_user
    from sqlalchemy import select as _select

    async def _override_get_current_user() -> User | None:
        async with _test_session_factory() as s:
            return (
                await s.execute(_select(User).limit(1))
            ).scalar_one_or_none()

    async with _test_session_factory() as session:
        async def _override_get_db() -> AsyncIterator[AsyncSession]:
            try:
                yield session
            finally:
                pass  # session lifecycle is managed by the outer fixture

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_current_user] = _override_get_current_user
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        app.dependency_overrides.clear()
        await session.rollback()


@pytest.fixture(autouse=True)
def regulation_push_isolated(monkeypatch: pytest.MonkeyPatch):
    """法规收录推送隔离（autouse）：默认钉死 PushNotifier 的真实投递。

    误发事故教训（2026-11-04）：推送 V1.2 主路径并入安全速递后，任何走到
    promote 的测试都会把测试样例数据（《危险化学品安全管理条例》等）真发到
    安全AI创新交流群，每跑一轮测试重发一次。默认全局 no-op（upsert/
    群卡/私发），需要断言推送行为的测试自行覆写本桩（如 push_off 与
    push_notifier 命名空间单测各自的 monkeypatch，后设优先）。
    """
    from app.modules.safety.regulation_ingest import push_notifier as _pn

    async def _noop_upsert(report_date, key, cell, **kwargs):
        return True

    async def _noop_card(**kwargs):
        return "test-msg-id"

    monkeypatch.setattr(_pn, "upsert_daily_digest", _noop_upsert)
    monkeypatch.setattr(_pn, "send_group_card", _noop_card)
    monkeypatch.setattr(_pn, "send_user_card", _noop_card)
    yield


@pytest.fixture(autouse=True)
def warehouse_push_isolated(monkeypatch: pytest.MonkeyPatch):
    """仓储飞书推送隔离（autouse）：钉死传输总闸 _send_create 的真实投递。

    误发事故教训（2026-11-05）：五金库 direct 领取卡等事件推送的发送层
    在测试里无桩，跑五金库测试时每轮把「测试供应商/发酵」样例卡真发到
    WAREHOUSE_TEST_CHAT_ID 群（push_tasks 无 DB 行的任务回退注册表默认
    enabled=True + env 目标；db_session rollback 后库里无痕但飞书收不回）。

    隔离层级必须钉在 **_send_create（唯一网络出口）**而非
    send_card_to_target/send_card：send_card / send_card_to_user /
    send_card_to_target / send_text 全部漏斗到 _send_create——钉传输层
    既保证零触网，又不劫持测试在这些业务层自行 monkeypatch 的采集桩
    （fixture 先装、测试体内后装，后设优先；express_notify 采 send_card、
    picking_supplier 采 _send_create、push_center 失败注入 send_card
    三族因此全部兼容，2026-11-05 二期验收实测）。
    """
    from app.modules.warehouse.feishu import notification as _wn

    async def _dry_run_create(payload):
        _wn.logger.info(
            "[test-stub] 仓库飞书传输隔离: receive_id=%s msg_type=%s",
            payload.get("receive_id"), payload.get("msg_type"),
        )
        return _wn.DRY_RUN_MESSAGE_ID

    monkeypatch.setattr(_wn, "_send_create", _dry_run_create)
    yield
