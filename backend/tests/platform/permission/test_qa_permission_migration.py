"""QA 权限迁移四态：仅旧码 / 仅新码 / 新旧并存 / 软删旧码。

直接调用迁移文件的 _move，在 db_session 事务里构造合成权限与角色授权，
断言后用夹具统一回滚。防止迁移 SQL 被改坏而测试套件全绿。
"""

from __future__ import annotations

import importlib.util
import uuid
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "alembic/versions/e13da4b58fbd_qa_permissions_three_segment_codes.py"
)
_spec = importlib.util.spec_from_file_location("qa_perm_migration", _MIGRATION)
assert _spec and _spec.loader
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)

_INSERT_ROLE = text(
    "INSERT INTO permission.roles (id, code, name, data_scope, is_deleted) "
    "VALUES (gen_random_uuid(), :code, :code, 'all', false)"
)
_INSERT_PERM = text(
    "INSERT INTO permission.permissions "
    "(id, code, name, module, resource, action, is_deleted) "
    "VALUES (gen_random_uuid(), :code, :code, 'qa', 'probe', 'manage', :deleted)"
)
_INSERT_GRANT = text(
    """
    INSERT INTO permission.role_permissions (id, role_id, permission_id)
    SELECT gen_random_uuid(), r.id, p.id
    FROM permission.roles r, permission.permissions p
    WHERE r.code = :role AND p.code = :perm
    """
)
_SELECT_PERMS = text(
    "SELECT code, is_deleted FROM permission.permissions "
    "WHERE code IN (:old, :new) ORDER BY code"
)
_SELECT_EFFECTIVE_GRANTS = text(
    """
    SELECT p.code FROM permission.role_permissions rp
    JOIN permission.roles r ON r.id = rp.role_id
    JOIN permission.permissions p ON p.id = rp.permission_id
    WHERE r.code = :role AND rp.is_deleted = false AND p.is_deleted = false
    """
)
_SELECT_OLD_LINK_DELETED = text(
    """
    SELECT rp.is_deleted FROM permission.role_permissions rp
    JOIN permission.roles r ON r.id = rp.role_id
    JOIN permission.permissions p ON p.id = rp.permission_id
    WHERE r.code = :role AND p.code = :old
    """
)


async def _run_state(
    db: AsyncSession,
    *,
    insert_old: bool,
    insert_new: bool,
    old_deleted: bool = False,
    new_deleted: bool = False,
    grant: str | None = None,
    run_twice: bool = False,
) -> None:
    suffix = uuid.uuid4().hex[:8]
    role = f"qa_mig_{suffix}"
    old_code = f"qa:probeold{suffix}:manage"
    new_code = f"qa:probenew{suffix}:manage"
    params = {"role": role, "old": old_code, "new": new_code}

    await db.execute(_INSERT_ROLE, {"code": role})
    if insert_old:
        await db.execute(_INSERT_PERM, {"code": old_code, "deleted": old_deleted})
    if insert_new:
        await db.execute(_INSERT_PERM, {"code": new_code, "deleted": new_deleted})
    if grant is not None:
        await db.execute(
            _INSERT_GRANT,
            {"role": role, "perm": old_code if grant == "old" else new_code},
        )
    await db.flush()

    await db.run_sync(
        lambda s: _migration._move(
            s.connection(), old_code, new_code, "probe", "manage"
        )
    )
    if run_twice:
        await db.run_sync(
            lambda s: _migration._move(
                s.connection(), old_code, new_code, "probe", "manage"
            )
        )

    perms = {
        str(row["code"]): bool(row["is_deleted"])
        for row in (await db.execute(_SELECT_PERMS, params)).mappings()
    }
    grants = set(
        (await db.execute(_SELECT_EFFECTIVE_GRANTS, {"role": role})).scalars()
    )

    assert new_code in perms and perms[new_code] is False
    if insert_old and insert_new:
        assert perms[old_code] is True, "新旧并存时旧码应软删"
    else:
        assert old_code not in perms, "原地改名后旧码不应存在"
    assert grants == ({new_code} if grant is not None else set())
    if insert_old and insert_new:
        old_links = (
            await db.execute(_SELECT_OLD_LINK_DELETED, params)
        ).scalars().all()
        assert old_links and all(old_links), "软删旧码时应同步软删其授权行"


async def test_move_handles_four_states(db_session: AsyncSession) -> None:
    await _run_state(db_session, insert_old=True, insert_new=False, grant="old")
    await _run_state(db_session, insert_old=False, insert_new=True, grant="new")
    await _run_state(
        db_session,
        insert_old=True,
        insert_new=True,
        new_deleted=True,
        grant="old",
        run_twice=True,
    )
    await _run_state(
        db_session, insert_old=True, insert_new=False, old_deleted=True
    )
