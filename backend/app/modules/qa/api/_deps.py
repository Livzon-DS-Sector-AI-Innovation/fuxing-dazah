"""QA 模块权限依赖：集中实例化（meter/api/_deps 同款）。"""

from app.platform.permission.deps import require_permission

# 读取统一走模块通配读码（与 meter 的 _deps 语义一致）
qa_read = require_permission("qa:*:read")
# 偏差登记表单需要部门联想；只授偏差读码的一线人员也要能取到引用。
deviation_reference_read = require_permission("qa:*:read", "qa:deviation:read")
master_create = require_permission("qa:master:create")
master_update = require_permission("qa:master:update")
master_deactivate = require_permission("qa:master:deactivate")
document_create = require_permission("qa:document:create")
document_update = require_permission("qa:document:update")
document_deactivate = require_permission("qa:document:deactivate")
version_create = require_permission("qa:version:create")
version_current = require_permission("qa:version:make_current")
version_disable = require_permission("qa:version:disable")
relation_manage = require_permission("qa:relation:manage")
config_manage = require_permission("qa:config:manage")
audit_read = require_permission("qa:audit:read")
proposal_publish = require_permission("qa:master:create", "qa:master:update")
