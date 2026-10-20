"""应用配置域注册表 — 安全模块 env→DB 迁移的代码唯一事实源。

本文件注册安全模块全部可 DB 化的配置键（key 恒等于原环境变量名，零改名）。
env 中仅保留：飞书 App 凭证（SAFETY_FEISHU_APP_ID/SECRET）与 AI API Key
（SAFETY_AI_*/SAFETY_EMBEDDING_*，走 ai_config 配置中心）。

生效优先级（store.py 实现）：**进程 env（非空）> DB 活行（enabled 且 value
非空）> 本 registry 默认值**。env 优先为刻意设计：

1. 既有测试以 ``monkeypatch.setenv`` 隔离推送（误发事故教训），语义零回归；
2. env 保留为运维应急通道（写回 env + 重启即夺回控制权）；
3. 「迁移到 DB」通过清空 .env 中对应键达成，而非让 env 失效。

registry 三重角色（对齐 bitable_config/registry 惯例）：

1. **默认值层**：store 解析链的代码默认；
2. **播种来源**：``seed_app_config_from_env`` 只补「无行且 env 有值」的键；
3. **写校验依据**：未知键拒绝写入（DB 只能改值不能新增键）。

零副作用导入（不 import store/models），供 alembic 与测试直接引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ConfigType = Literal["bool", "int", "str"]
ConfigCategory = Literal[
    "chat_id",       # 推送目标（群/个人）
    "feature_flag",  # 功能开关
    "direct_gate",   # 直读闸门（含 CACHE_TTL 数值项）
    "poll_param",    # 隐患轮询调参
    "credential",    # 外部系统凭证（DB 存储但展示/审计脱敏）
    "misc",          # 其余
]


@dataclass(frozen=True)
class ConfigItem:
    """单条配置的元数据（key = 原 env 变量名）。"""

    key: str
    category: ConfigCategory
    type: ConfigType
    default: str | int | bool
    description: str = ""
    # 启动语义冻结键：改动需重启生效（UI 展示提示；循环启动/模块 import 时读取）
    restart_required: bool = False
    # 展示与审计脱敏（****后4位）
    secret: bool = False
    # int 下限（int 类型用；TTL 类允许 0=关，其余默认 1）
    minimum: int = 1
    # str 允许字面量 off（加发群停用哨兵）
    allow_off: bool = False


def _flag(key: str, default: bool, desc: str, **kw: object) -> ConfigItem:
    return ConfigItem(key, "feature_flag", "bool", default, desc, **kw)  # type: ignore[arg-type]


def _gate(key: str, default: bool, desc: str, **kw: object) -> ConfigItem:
    return ConfigItem(key, "direct_gate", "bool", default, desc, **kw)  # type: ignore[arg-type]


def _ttl(key: str, desc: str, default: int = 60) -> ConfigItem:
    return ConfigItem(key, "direct_gate", "int", default, desc, minimum=0)


_ITEMS: tuple[ConfigItem, ...] = (
    # ══════════════════════════════════════════════════════════
    # 推送目标（chat_id）
    # ══════════════════════════════════════════════════════════
    ConfigItem(
        "SAFETY_WORKTICKET_GROUP_ID", "chat_id", "str",
        "oc_d102e1a11eaaa9a1de3b41859de9d0c1",
        "作业票审核报告推送群（特殊作业自动分配群）",
    ),
    ConfigItem(
        "SAFETY_CHEMICAL_INVENTORY_DAILY_CHAT_ID", "chat_id", "str",
        "oc_f05532603bd7682fc520929c01aca88d",
        "危化品库存日报推送群（安全AI创新交流群）",
    ),
    ConfigItem(
        "SAFETY_CHEMICAL_DAILY_EXTRA_CHAT_ID", "chat_id", "str",
        "oc_ae9c3a305430cb196e42130f69b052bc",
        "危化品日报加发群（危险品日报群）；off = 停用加发（空 = 回落默认群）",
        allow_off=True,
    ),
    ConfigItem(
        "SAFETY_DAILY_DIGEST_CHAT_ID", "chat_id", "str",
        "oc_f05532603bd7682fc520929c01aca88d",
        "「安全速递」每日总卡目标群",
    ),
    ConfigItem(
        "SAFETY_HAZARD_BULLETIN_FORWARD_CHAT_ID", "chat_id", "str", "",
        "督办通报速递格子「推送到群」按钮目标群（空 = 不渲染按钮）",
        allow_off=True,
    ),
    ConfigItem(
        "SAFETY_FACILITY_NOTICE_CHAT_ID", "chat_id", "str",
        "oc_f05532603bd7682fc520929c01aca88d",
        "设施校验滚动批次卡目标群（默认=安全速递总卡群）",
    ),
    ConfigItem(
        "SAFETY_SPECIAL_OP_EXTRA_REPORT_CHAT_ID", "chat_id", "str",
        "oc_4ab4a89f7bbb2450f5e0e341bf0f5f10",
        "特殊作业晨/晚报加发群（特殊作业报备及日报表群）；off = 停用加发（空 = 回落默认群）",
        allow_off=True,
    ),
    ConfigItem(
        "SAFETY_FIRE_ALARM_ANALYSIS_CHAT_ID", "chat_id", "str", "",
        "消防报警日报/月报推送群（空 = 不推送）",
    ),
    ConfigItem(
        "SAFETY_CENTRAL_ALARM_ANALYSIS_CHAT_ID", "chat_id", "str", "",
        "中控报警日报推送群（空 = 不推送）",
    ),
    ConfigItem(
        "SAFETY_CHEMICAL_INVENTORY_WEEKLY_CHAT_ID", "chat_id", "str", "",
        "危化品库存周报推送群（空 = 用调度任务 DB 目标/代码默认群）",
    ),
    ConfigItem(
        "SAFETY_FEISHU_BOT_OPEN_ID", "chat_id", "str",
        "ou_33d2fe6a5714c4e808248c05cf66205a",
        "安全助手机器人自身 open_id（@ 识别去重；机器人重建后需更新）",
    ),
    ConfigItem(
        "SAFETY_REGULATION_CRAWLER_NOTIFY_CHAT_ID", "chat_id", "str", "",
        "法规爬虫结果通知群（空 = 不推送）",
    ),
    ConfigItem(
        "SAFETY_REGULATION_CRAWLER_NOTIFY_USERS", "chat_id", "str", "",
        "法规爬虫结果通知人（逗号分隔 ou_ 列表；空 = 不私发）",
    ),

    # ══════════════════════════════════════════════════════════
    # 功能开关（feature_flag）
    # ══════════════════════════════════════════════════════════
    _flag(
        "SAFETY_DAILY_DIGEST_ENABLED", True,
        "「安全速递」总卡模式总开关（开 = 各报告并入当日总卡；关 = 各报告独立群卡）",
    ),
    _flag(
        "SAFETY_HAZARD_NOTIFICATIONS_ENABLED", True,
        "隐患复查/整改 DM 通知开关",
    ),
    _flag(
        "SAFETY_SUPERVISION_NOTIFICATION_ENABLED", False,
        "督办等级通知开关（hazard_supervision）",
    ),
    _flag(
        "SAFETY_SUPERVISION_TEST_MODE", True,
        "督办计算测试模式（true = 不实际推送，仅记录）",
    ),
    _flag(
        "SAFETY_FIRE_INSPECTION_PDF_ENABLED", False,
        "消防点检 PDF 归档开关（调度任务）",
    ),
    _flag(
        "SAFETY_FIRE_ALARM_DAILY_DM_ENABLED", False,
        "消防报警日报部门过滤私发开关（一部门一卡，动态名单）",
    ),
    _flag(
        "SAFETY_CENTRAL_ALARM_DAILY_DM_ENABLED", False,
        "中控报警日报部门过滤私发开关（一部门一卡，动态名单）",
    ),
    _flag(
        "SAFETY_AGENT_URS_DELEGATION", False,
        "URS 域 Agent 委派试点开关（开 = URS 意图经 delegate 元工具走域子流程；"
        "关 = 挂载式整域工具集，一键回退）",
    ),

    # ══════════════════════════════════════════════════════════
    # 直读闸门（direct_gate）— 隐患域轮询旗标为启动语义（需重启）
    # ══════════════════════════════════════════════════════════
    _gate(
        "SAFETY_HAZARD_DIRECT_POLL_ENABLED", False,
        "隐患直读轮询总开关（关闭时 ①②③④ 轮询协程不启动）",
        restart_required=True,
    ),
    _gate(
        "SAFETY_HAZARD_AI_POLL_ENABLED", False,
        "隐患 AI 分析轮询（①；以总开关打开为前提）",
        restart_required=True,
    ),
    _gate(
        "SAFETY_HAZARD_REVIEW_POLL_ENABLED", False,
        "AI 整改审核轮询（②；以总开关打开为前提）",
        restart_required=True,
    ),
    _gate(
        "SAFETY_HAZARD_SUPERVISION_POLL_ENABLED", False,
        "督办等级计算轮询（③；以总开关打开为前提）",
        restart_required=True,
    ),
    _gate(
        "SAFETY_HAZARD_BULLETIN_WATCH_ENABLED", False,
        "督办通报值守轮询（④ 周四 13:00-18:00，速递格子变化即刷新；以总开关打开为前提）",
        restart_required=True,
    ),
    _gate(
        "SAFETY_HAZARD_EVENT_SYNC_ENABLED", False,
        "旧路径：Bitable 事件 → 平台库镜像（hazard_reports）+ 事件驱动 AI",
    ),
    _gate(
        "SAFETY_HAZARD_CATCHUP_ENABLED", False,
        "旧路径：启动时 Bitable 漏单恢复（写平台库）",
    ),
    _gate(
        "SAFETY_SPECIAL_OP_DIRECT_ENABLED", False,
        "特殊作业直读总开关（开 = 日报直读一览表 + 停旧事件镜像/对账）",
    ),
    _gate(
        "SAFETY_SPECIAL_OP_EVENT_SYNC_ENABLED", False,
        "特殊作业旧路径：Bitable 事件镜像（直读开后默认停，可显式恢复双跑）",
    ),
    _gate(
        "SAFETY_SPECIAL_OP_SYNC_JOB_ENABLED", False,
        "特殊作业旧路径：08:00 全量对账 / 17:00 增量同步",
    ),
    _gate(
        "SAFETY_SPECIAL_OP_WRITEBACK_RISK_ENABLED", False,
        "特殊作业直读回写「日报风险等级（AI）」列",
    ),
    _gate(
        "SAFETY_SPECIAL_OP_DIGEST_CARD_ENABLED", True,
        "特殊作业日报速递卡版式（关 = 旧长卡；构建失败自动回退不影响送达）",
    ),
    _gate(
        "SAFETY_FIRE_ALARM_DIRECT_ENABLED", False,
        "消防报警直读总开关（开 = 生成路径直读 Bitable + 停旧链路）",
    ),
    _gate(
        "SAFETY_FIRE_ALARM_EVENT_SYNC_ENABLED", False,
        "消防报警旧路径：Bitable 事件镜像",
    ),
    _gate(
        "SAFETY_FIRE_ALARM_SYNC_JOB_ENABLED", False,
        "消防报警旧路径：生成前全量同步兜底",
    ),
    _gate(
        "SAFETY_FIRE_ALARM_WRITEBACK_AI_ENABLED", False,
        "消防报警 AI 分析结果回写 Bitable 4 个 AI 列",
    ),
    _gate(
        "SAFETY_CENTRAL_ALARM_DIRECT_ENABLED", False,
        "中控报警直读总开关（开 = 生成/查询直读 + 停旧链路）",
    ),
    _gate(
        "SAFETY_CENTRAL_ALARM_EVENT_SYNC_ENABLED", False,
        "中控报警旧路径：Bitable 事件镜像",
    ),
    _gate(
        "SAFETY_CENTRAL_ALARM_SYNC_JOB_ENABLED", False,
        "中控报警旧路径：生成前全量同步兜底",
    ),
    _gate(
        "SAFETY_CERT_DIRECT_ENABLED", False,
        "持证到期直读总开关（3 表全量直读）",
    ),
    _gate(
        "SAFETY_CERT_EVENT_SYNC_ENABLED", False,
        "持证到期旧路径：Bitable 事件镜像",
    ),
    _gate(
        "SAFETY_CHEMICAL_INVENTORY_DIRECT_ENABLED", False,
        "危化品库存直读总开关（日报/周报编排与查询路径）",
    ),
    _gate(
        "SAFETY_CHEMICAL_INVENTORY_EVENT_SYNC_ENABLED", False,
        "危化品库存旧路径：Bitable 事件镜像",
    ),
    ConfigItem(
        "SAFETY_CHEMICAL_INVENTORY_SOURCE", "direct_gate", "str",
        "bitable",
        "危化品库存数据源（bitable=总表直读（默认，行为不变）| sheet=飞书《危险品日报表》"
        "电子表格直读；回滚=拨回 bitable）",
    ),
    ConfigItem(
        "SAFETY_CHEMICAL_INVENTORY_SHEET_REVISION", "misc", "str", "",
        "《危险品日报表》revision 状态（运行时记录：{revision}|{最后变化日}；"
        "19:30 日报判「数据未更新」用，勿手改）",
    ),
    _gate(
        "SAFETY_KEY_RISK_OP_DIRECT_ENABLED", False,
        "关键风险作业直读总开关（台账/统计/详情/导出与 Agent 查询）",
    ),
    _gate(
        "SAFETY_KEY_RISK_OP_EVENT_SYNC_ENABLED", False,
        "关键风险作业旧路径：Bitable 事件镜像",
    ),
    _gate(
        "SAFETY_CONTRACTOR_ADMISSION_DIRECT_ENABLED", False,
        "相关方准入直读总开关（台账/统计/详情与 Agent 查询）",
    ),
    _gate(
        "SAFETY_CONTRACTOR_ADMISSION_EVENT_SYNC_ENABLED", False,
        "相关方准入旧路径：事件镜像 + 事件自动 AI 审核",
    ),
    _gate(
        "SAFETY_CONTRACTOR_ADMISSION_WRITEBACK_AI_ENABLED", False,
        "相关方准入直读 AI 审核结果回写 Bitable 3 列",
    ),
    _gate(
        "SAFETY_EMERGENCY_DRILL_DIRECT_ENABLED", False,
        "应急演练直读开关（本域仅此一个；事件链路承载归集/评估不可关）",
    ),
    _gate(
        "SAFETY_KNOWLEDGE_DIRECT_ENABLED", False,
        "法规标准清单直读开关（query_latest_regulations；镜像承重不可退订）",
    ),
    _gate(
        "SAFETY_MSDS_DIRECT_ENABLED", False,
        "MSDS 台账直读开关（query_msds(kind=documents)；采集/台账订阅不可退订）",
    ),
    _gate(
        "SAFETY_OH_DIRECT_ENABLED", False,
        "职业健康直读开关（仅 query_oh(entity=hazard_factors) 切直读）",
    ),
    _gate(
        "SAFETY_HAZARD_ID_DIRECT_ENABLED", False,
        "危险源辨识直读开关（仅 query_hazard_identifications）",
    ),
    _gate(
        "SAFETY_EHS_CHANGE_DIRECT_ENABLED", False,
        "EHS 变更直读开关（仅 query_ehs_changes）",
    ),
    _ttl(
        "SAFETY_KEY_RISK_OP_DIRECT_CACHE_TTL_SECONDS",
        "关键风险作业直读视图进程内 TTL 缓存秒数（0 = 关）",
        300,
    ),
    _ttl(
        "SAFETY_KNOWLEDGE_DIRECT_CACHE_TTL_SECONDS",
        "法规清单直读视图 TTL 缓存秒数（0 = 关）",
    ),
    _ttl(
        "SAFETY_MSDS_DIRECT_CACHE_TTL_SECONDS",
        "MSDS 直读视图 TTL 缓存秒数（0 = 关）",
    ),
    _ttl(
        "SAFETY_OH_DIRECT_CACHE_TTL_SECONDS",
        "职业健康直读视图 TTL 缓存秒数（0 = 关）",
    ),
    _ttl(
        "SAFETY_HAZARD_ID_DIRECT_CACHE_TTL_SECONDS",
        "危险源辨识直读视图 TTL 缓存秒数（0 = 关）",
    ),
    _ttl(
        "SAFETY_EHS_CHANGE_DIRECT_CACHE_TTL_SECONDS",
        "EHS 变更直读视图 TTL 缓存秒数（0 = 关）",
        300,
    ),
    _ttl(
        "SAFETY_FIRE_ALARM_DIRECT_CACHE_TTL_SECONDS",
        "消防报警窗口拉取 TTL 缓存秒数（0 = 关；日报/月报 strict 现拉；单例创建时读取，改后需重启）",
        300,
    ),
    _ttl(
        "SAFETY_CENTRAL_ALARM_DIRECT_CACHE_TTL_SECONDS",
        "中控报警窗口拉取 TTL 缓存秒数（0 = 关；日报 strict 现拉；单例创建时读取，改后需重启）",
        300,
    ),

    # ══════════════════════════════════════════════════════════
    # 隐患轮询调参（poll_param）— interval/stagger 启动冻结（需重启）
    # ══════════════════════════════════════════════════════════
    ConfigItem(
        "SAFETY_HAZARD_POLL_INTERVAL_SECONDS", "poll_param", "int", 300,
        "轮询间隔秒数（下限 60）", restart_required=True, minimum=60,
    ),
    ConfigItem(
        "SAFETY_HAZARD_POLL_STAGGER_SECONDS", "poll_param", "int", 150,
        "② 相对 ① 错开秒数（代码默认 = 间隔一半，随间隔推算）",
        restart_required=True, minimum=0,
    ),
    ConfigItem(
        "SAFETY_HAZARD_SUPERVISION_STAGGER_SECONDS", "poll_param", "int", 75,
        "③ 相对 ① 错开秒数（代码默认 = 间隔四分之一，随间隔推算）",
        restart_required=True, minimum=0,
    ),
    ConfigItem(
        "SAFETY_HAZARD_BULLETIN_WATCH_INTERVAL_SECONDS", "poll_param", "int", 60,
        "④ 值守轮询间隔秒数（下限 30；窗口内每分钟比对一次速递格子）",
        restart_required=True, minimum=30,
    ),
    ConfigItem(
        "SAFETY_HAZARD_POLL_BATCH_LIMIT", "poll_param", "int", 200,
        "单轮最多处理条数",
    ),
    ConfigItem(
        "SAFETY_HAZARD_POLL_CONCURRENCY", "poll_param", "int", 3,
        "单轮内并发数（Bitable 写入仍串行化）",
    ),
    ConfigItem(
        "SAFETY_HAZARD_POLL_LOCK_TTL", "poll_param", "int", 600,
        "per-record 处理锁 TTL 秒数",
    ),
    ConfigItem(
        "SAFETY_HAZARD_ALERT_MIN_FAILURES", "poll_param", "int", 10,
        "单轮失败条数达到该值推送告警",
    ),
    ConfigItem(
        "SAFETY_HAZARD_ALERT_AFTER_ROUNDS", "poll_param", "int", 3,
        "连续失败轮数达到该值推送告警",
    ),

    # ══════════════════════════════════════════════════════════
    # 作业票平台凭证（credential）— 展示/审计脱敏
    # ══════════════════════════════════════════════════════════
    ConfigItem(
        "SAFETY_PLATFORM_BASE_URL", "credential", "str",
        "http://192.168.5.7:9550",
        "工业互联网安全生产数智化平台地址（尾斜杠自动去除）",
    ),
    ConfigItem(
        "SAFETY_PLATFORM_TENANT_ID", "credential", "str", "",
        "平台租户 ID（Tenant-Id 头）",
    ),
    ConfigItem(
        "SAFETY_PLATFORM_ORG_CODE", "credential", "str", "",
        "平台组织编码",
    ),
    ConfigItem(
        "SAFETY_PLATFORM_USERNAME", "credential", "str", "",
        "平台登录账号", secret=True,
    ),
    ConfigItem(
        "SAFETY_PLATFORM_PASSWORD_MD5", "credential", "str", "",
        "平台登录密码 MD5", secret=True,
    ),
    ConfigItem(
        "SAFETY_PLATFORM_AUTH_BASIC", "credential", "str", "",
        "平台 Basic 认证头（user:secret）", secret=True,
    ),

    # ══════════════════════════════════════════════════════════
    # 法规爬虫（crawler 归 feature_flag/misc）
    # ══════════════════════════════════════════════════════════
    _flag(
        "SAFETY_REGULATION_CRAWLER_ENABLED", False,
        "法规爬虫调度开关",
    ),
    ConfigItem(
        "SAFETY_REGULATION_INGEST_SECRET", "credential", "str", "",
        "法规收录推送校验 secret（空 = 不校验；契约① X-Ingest-Secret 头）",
        secret=True,
    ),
    ConfigItem(
        "SAFETY_REGULATION_CRAWLER_MAX_AI_TOKENS_PER_RUN", "misc", "int", 20000,
        "法规收录单批 AI token 预算上限（超限标 pending 留痕，不调 AI）",
        minimum=0,
    ),

    # ══════════════════════════════════════════════════════════
    # ragplus-x 知识层（一期壳换芯：检索外接 + 入库短路同一总闸）
    # ══════════════════════════════════════════════════════════
    _flag(
        "SAFETY_RAGPLUS_SEARCH_ENABLED", False,
        "法规/MSDS 检索走 ragplus-x 知识层总开关（开=三壳内核走 RagplusClient、"
        "本地切片向量化短路；关=旧三层管线，回退路径）",
    ),
    ConfigItem(
        "SAFETY_RAGPLUS_BASE_URL", "misc", "str",
        "http://localhost:8085",
        "ragplus-x 知识层地址（尾斜杠自动去除）",
    ),
    ConfigItem(
        "SAFETY_RAGPLUS_API_TOKEN", "credential", "str", "",
        "ragplus-x 检索服务 token（ragflow- 前缀，retrieval 作用域；"
        "入库脚本 bootstrap 自动创建写入，不进代码/git）",
        secret=True,
    ),
    ConfigItem(
        "SAFETY_RAGPLUS_TIMEOUT_SECONDS", "misc", "int", 10,
        "ragplus-x 检索超时秒数",
    ),
    ConfigItem(
        "SAFETY_RAGPLUS_DATASET_NAMES", "misc", "str",
        "安全法规标准,MSDS",
        "ragplus-x 检索库名单（逗号分隔；已废止归档库不在名单内即被排除）",
    ),
    ConfigItem(
        "SAFETY_RAGPLUS_WEB_URL", "misc", "str",
        "http://192.168.100.7:8086",
        "RagFlow 引擎 Web 地址（文档详情外链用；文档列表页 /dataset/files/<dataset_id>）",
    ),

    # ══════════════════════════════════════════════════════════
    # 杂项（misc）
    # ══════════════════════════════════════════════════════════
    ConfigItem(
        "SAFETY_PHOENIX_ENDPOINT", "misc", "str", "",
        "Phoenix 可观测性端点（空 = tracing 关闭；import 时读取，需重启）",
        restart_required=True,
    ),
    ConfigItem(
        "SAFETY_CHEMICAL_INVENTORY_SURGE_RATIO", "misc", "str", "0.30",
        "危化品库存日环比激增判定比例阈值",
    ),
    ConfigItem(
        "SAFETY_CHEMICAL_INVENTORY_SURGE_ABS_T", "misc", "str", "1.0",
        "危化品库存激增判定绝对量阈值（T）",
    ),
    ConfigItem(
        "SAFETY_FIRE_INSPECTION_APP_TOKEN", "misc", "str",
        "BlktbbYg1abyIesUQ17cYFqrn4e",
        "消防点检 Bitable app_token",
    ),
    ConfigItem(
        "SAFETY_FIRE_INSPECTION_TABLE_ID", "misc", "str",
        "tblUB2sT3b3GBerU",
        "消防点检 Bitable table_id",
    ),
    ConfigItem(
        "SAFETY_FIRE_INSPECTION_REPORT_FIELD_ID", "misc", "str",
        "fldpZSHrTd",
        "消防点检「报告」字段 field_id",
    ),
)

# 构造时断言：键唯一（重复键会在 dict 推导时静默覆盖，故显式校验）
REGISTRY: dict[str, ConfigItem] = {item.key: item for item in _ITEMS}
assert len(REGISTRY) == len(_ITEMS), "应用配置注册表存在重复 key"

# 类别中文标签（前端/列表 API 用）
CATEGORY_LABELS: dict[str, str] = {
    "chat_id": "推送目标",
    "feature_flag": "功能开关",
    "direct_gate": "直读闸门",
    "poll_param": "轮询调参",
    "credential": "平台凭证",
    "misc": "杂项",
}


def get_item(key: str) -> ConfigItem:
    """未知键抛 ValueError（消息以「未知配置键」开头，API 层映射 404）。"""
    item = REGISTRY.get(key)
    if item is None:
        raise ValueError(f"未知配置键: {key}")
    return item


def iter_items() -> tuple[ConfigItem, ...]:
    """全部注册项（按注册顺序；展示/播种/断言用）。"""
    return _ITEMS
