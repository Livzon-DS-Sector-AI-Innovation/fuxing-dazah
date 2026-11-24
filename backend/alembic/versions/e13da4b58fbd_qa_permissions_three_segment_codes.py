"""qa permissions three segment codes

qa:*:read 实际是模块全域读码（所有域读门禁都显式 OR 它），改名为
qa:all:read；偏差/PQR/COA 4 段码与动作词统一为 module:resource:action。
原地 UPDATE code，保留 role_permissions 授权。若应用先于迁移启动导致
新旧码并存，则把旧码有效授权合并到新码后软删旧码。

Revision ID: e13da4b58fbd
Revises: e7b41d0c6a92
Create Date: 2026-11-24 11:29:53.905859
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e13da4b58fbd"
down_revision: str | None = "e7b41d0c6a92"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# old_code, old_resource, old_action, new_code, new_resource, new_action
_RENAMES = [
    ("qa:*:read", "*", "read", "qa:all:read", "all", "read"),
    ("qa:master:deactivate", "master", "deactivate", "qa:master:manage", "master", "manage"),
    ("qa:document:deactivate", "document", "deactivate", "qa:document:manage", "document", "manage"),
    ("qa:version:make_current", "version", "make_current", "qa:version:set_current", "version", "set_current"),
    ("qa:version:disable", "version", "disable", "qa:version:manage", "version", "manage"),
    ("qa:coa:standard:manage", "coa:standard", "manage", "qa:coa:manage", "coa", "manage"),
    ("qa:coa:issue:create", "coa:issue", "create", "qa:coa:issue", "coa", "issue"),
]


def _move(
    conn: sa.Connection,
    old_code: str,
    new_code: str,
    new_resource: str,
    new_action: str,
) -> None:
    params = {
        "old_code": old_code,
        "new_code": new_code,
        "new_resource": new_resource,
        "new_action": new_action,
    }
    # 目标不存在：原地改名；role_permissions 按 permission_id 引用，关联行不受影响
    conn.execute(
        sa.text(
            """
            UPDATE permission.permissions
            SET code = :new_code, resource = :new_resource, action = :new_action,
                is_deleted = false
            WHERE code = :old_code
              AND NOT EXISTS (
                  SELECT 1 FROM permission.permissions WHERE code = :new_code
              )
            """
        ),
        params,
    )
    # 新码若处于软删状态（旧码先被 sync_permissions 软删过），复活它
    conn.execute(
        sa.text(
            "UPDATE permission.permissions SET is_deleted = false WHERE code = :new_code"
        ),
        params,
    )
    # 新旧并存：旧码的有效授权合并到新码（含复活软删授权）
    conn.execute(
        sa.text(
            """
            INSERT INTO permission.role_permissions (id, role_id, permission_id)
            SELECT gen_random_uuid(), rp.role_id, np.id
            FROM permission.role_permissions rp
            JOIN permission.permissions op
              ON op.id = rp.permission_id AND op.code = :old_code
            JOIN permission.permissions np ON np.code = :new_code
            WHERE rp.is_deleted = false
            ON CONFLICT (role_id, permission_id) DO UPDATE SET is_deleted = false
            """
        ),
        params,
    )
    # 并存时软删旧码；改名场景下 code 已是 new，这条不命中
    conn.execute(
        sa.text(
            """
            UPDATE permission.permissions
            SET is_deleted = true
            WHERE code = :old_code
              AND EXISTS (
                  SELECT 1 FROM permission.permissions WHERE code = :new_code
              )
            """
        ),
        params,
    )
    # 软删旧码后同步软删其授权行：否则角色编辑会把已删权限 id 当选中项，
    # 前端权限树找不到对应节点（antd: Tree missing follow keys）
    conn.execute(
        sa.text(
            """
            UPDATE permission.role_permissions
            SET is_deleted = true
            WHERE permission_id IN (
                SELECT id FROM permission.permissions WHERE code = :old_code
            )
            """
        ),
        params,
    )


def upgrade() -> None:
    conn = op.get_bind()
    for old_code, _old_resource, _old_action, new_code, new_resource, new_action in _RENAMES:
        _move(conn, old_code, new_code, new_resource, new_action)


def downgrade() -> None:
    conn = op.get_bind()
    for old_code, old_resource, old_action, new_code, _new_resource, _new_action in reversed(
        _RENAMES
    ):
        _move(conn, new_code, old_code, old_resource, old_action)
