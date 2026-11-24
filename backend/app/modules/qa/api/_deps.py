"""QA 模块权限依赖：所有 QA 门禁在此集中声明。

- 权限码固定三段 ``qa:<resource>:<action>``。
- 读取门禁 = ``qa:all:read`` OR 域读码 OR 该域写码（写权限隐含读）。
"""

from app.platform.permission.deps import require_permission

# 知识库：主数据 / 文件台账 / 版本 / 关联 / 检索 / 预览
_KNOWLEDGE_READ_CODES = (
    "qa:all:read",
    "qa:master:create",
    "qa:master:update",
    "qa:master:manage",
    "qa:document:create",
    "qa:document:update",
    "qa:document:manage",
    "qa:version:create",
    "qa:version:set_current",
    "qa:version:manage",
    "qa:relation:manage",
    "qa:config:manage",
)
_DEVIATION_READ_CODES = (
    "qa:all:read",
    "qa:deviation:read",
    "qa:deviation:create",
    "qa:deviation:update",
)
_CAPA_READ_CODES = (
    "qa:all:read",
    "qa:capa:read",
    "qa:capa:create",
    "qa:capa:update",
)
_APR_READ_CODES = (
    "qa:all:read",
    "qa:apr:read",
    "qa:apr:enter",
    "qa:apr:manage",
    "qa:apr:export",
    "qa:apr:lock",
)
_COA_READ_CODES = (
    "qa:all:read",
    "qa:coa:read",
    "qa:coa:manage",
    "qa:coa:issue",
)

knowledge_read = require_permission(*_KNOWLEDGE_READ_CODES)
master_create = require_permission("qa:master:create")
master_update = require_permission("qa:master:update")
master_manage = require_permission("qa:master:manage")
document_create = require_permission("qa:document:create")
document_update = require_permission("qa:document:update")
document_manage = require_permission("qa:document:manage")
version_create = require_permission("qa:version:create")
version_set_current = require_permission("qa:version:set_current")
version_manage = require_permission("qa:version:manage")
relation_manage = require_permission("qa:relation:manage")
config_manage = require_permission("qa:config:manage")
audit_read = require_permission("qa:audit:read")
proposal_publish = require_permission("qa:master:create", "qa:master:update")

# 偏差 / CAPA
deviation_read = require_permission(*_DEVIATION_READ_CODES)
deviation_create = require_permission("qa:deviation:create")
deviation_update = require_permission("qa:deviation:update")
deviation_assist = require_permission("qa:deviation:create", "qa:deviation:update")
capa_read = require_permission(*_CAPA_READ_CODES)
capa_create = require_permission("qa:capa:create")
capa_update = require_permission("qa:capa:update")

# 部门等表单引用：知识库与偏差表单都会用到，取两个读域并集
reference_read = require_permission(*_KNOWLEDGE_READ_CODES, *_DEVIATION_READ_CODES)

# PQR
apr_read = require_permission(*_APR_READ_CODES)
apr_manage = require_permission("qa:apr:manage")
apr_enter = require_permission("qa:apr:enter")
apr_export = require_permission("qa:apr:export")
apr_lock = require_permission("qa:apr:lock")

# COA
coa_read = require_permission(*_COA_READ_CODES)
coa_manage = require_permission("qa:coa:manage")
coa_issue = require_permission("qa:coa:issue")
