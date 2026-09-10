"""URS 审核标准库 — seed 通用条款（D12/D3）。

一套通用条款（30-40 条），按五维风险维度归属，含 4 类否决项。
否决项（is_veto=True）在适配阶段由 ``rules.py`` 代码强制为 mandatory，AI 不可改。

字段：item_no / category / risk_dimension / standard_title / standard_ref / is_veto

⚠️ 本清单为业务初稿（§11.3.1），需业务侧审阅后固化；后续可迁入知识库法规表。
"""

# 类别字典：category → 中文标签（前端/卡片展示用）
CATEGORY_LABELS: dict[str, str] = {
    "data_integrity": "GMP数据完整性",
    "motion_guard": "运动部件防护（否决项）",
    "fire_explosion": "防火防爆",
    "environmental": "废水废气处理",
    "mechanical_safety": "机械安全",
    "electrical_safety": "电气安全",
    "data_system": "数据系统",
    "chemical_safety": "化学品安全",
    "env_health": "环境与职业健康",
    "safety_distance": "安全距离与通道",
    "loto": "能源隔离LOTO",
    "noise": "噪声控制",
}

SEED_STANDARD_ITEMS: list[dict] = [
    # ════════════════════════════════════════════════════════════
    # 否决项（一票否决，仅运动部件防护保留；其余强制项改由维度门控/评分约束）
    # ════════════════════════════════════════════════════════════
    {
        "item_no": "S1.1", "category": "data_integrity", "risk_dimension": "data",
        "standard_title": "GMP 数据完整性：具备审计追踪、数据备份、权限管理",
        "standard_ref": "药品生产质量管理规范（GMP）数据可靠性要求", "is_veto": False,
    },
    {
        "item_no": "S2.1", "category": "motion_guard", "risk_dimension": "mechanical",
        "standard_title": "运动部件防护：涉及人员伤害风险的安全底线",
        "standard_ref": "GB/T 8196 机械安全 防护装置", "is_veto": True,
    },
    {
        "item_no": "S3.1", "category": "fire_explosion", "risk_dimension": "electrical",
        "standard_title": "防火防爆：涉及重大事故预防",
        "standard_ref": "GB 50058 爆炸危险环境电力装置设计规范", "is_veto": False,
    },
    {
        "item_no": "S4.1", "category": "environmental", "risk_dimension": "environmental",
        "standard_title": "废水废气处理：环境保护底线要求",
        "standard_ref": "环境保护法 / 排污许可管理条例", "is_veto": False,
    },
    # ════════════════════════════════════════════════════════════
    # 机械风险维度
    # ════════════════════════════════════════════════════════════
    {
        "item_no": "S2.2", "category": "mechanical_safety", "risk_dimension": "mechanical",
        "standard_title": "高温表面防护与标识", "standard_ref": "GB/T 18153 机械安全 可接触表面温度", "is_veto": False,
    },
    {
        "item_no": "S2.3", "category": "mechanical_safety", "risk_dimension": "mechanical",
        "standard_title": "旋转/运动部件安全防护罩", "standard_ref": "GB/T 8196 机械安全 防护装置", "is_veto": False,
    },
    {
        "item_no": "S2.4", "category": "loto", "risk_dimension": "mechanical",
        "standard_title": "LOTO 能源隔离与上锁挂牌点", "standard_ref": "GB/T 33579 机械安全 危险能量控制", "is_veto": False,
    },
    {
        "item_no": "S2.5", "category": "mechanical_safety", "risk_dimension": "mechanical",
        "standard_title": "急停与联锁装置", "standard_ref": "GB/T 16754 机械安全 急停", "is_veto": False,
    },
    {
        "item_no": "S2.6", "category": "safety_distance", "risk_dimension": "mechanical",
        "standard_title": "检修/操作空间与安全距离", "standard_ref": "", "is_veto": False,
    },
    # ════════════════════════════════════════════════════════════
    # 电气风险维度
    # ════════════════════════════════════════════════════════════
    {
        "item_no": "S3.2", "category": "electrical_safety", "risk_dimension": "electrical",
        "standard_title": "电气接地与绝缘保护", "standard_ref": "GB/T 16895 低压电气装置", "is_veto": False,
    },
    {
        "item_no": "S3.3", "category": "electrical_safety", "risk_dimension": "electrical",
        "standard_title": "防爆区域电气设备选型与线路敷设", "standard_ref": "GB 50058 爆炸危险环境电力装置设计规范", "is_veto": False,
    },
    {
        "item_no": "S3.4", "category": "electrical_safety", "risk_dimension": "electrical",
        "standard_title": "防雷防静电接地", "standard_ref": "GB 50057 建筑物防雷设计规范", "is_veto": False,
    },
    {
        "item_no": "S3.5", "category": "electrical_safety", "risk_dimension": "electrical",
        "standard_title": "大功率/高电压设备安全措施", "standard_ref": "", "is_veto": False,
    },
    # ════════════════════════════════════════════════════════════
    # 数据风险维度（GMP 数据完整性延伸）
    # ════════════════════════════════════════════════════════════
    {
        "item_no": "S1.2", "category": "data_system", "risk_dimension": "data",
        "standard_title": "数据采集系统审计追踪（变更/删除留痕）", "standard_ref": "GMP 数据可靠性要求", "is_veto": False,
    },
    {
        "item_no": "S1.3", "category": "data_system", "risk_dimension": "data",
        "standard_title": "数据备份与恢复策略", "standard_ref": "GMP 数据可靠性要求", "is_veto": False,
    },
    {
        "item_no": "S1.4", "category": "data_system", "risk_dimension": "data",
        "standard_title": "用户权限分级管理（三权分立）", "standard_ref": "GMP 数据可靠性要求", "is_veto": False,
    },
    {
        "item_no": "S1.5", "category": "data_system", "risk_dimension": "data",
        "standard_title": "数据采集/监测系统校准与验证", "standard_ref": "GAMP 5 计算机化系统验证", "is_veto": False,
    },
    # ════════════════════════════════════════════════════════════
    # 环境风险维度
    # ════════════════════════════════════════════════════════════
    {
        "item_no": "S4.2", "category": "environmental", "risk_dimension": "environmental",
        "standard_title": "废气排放接口与处理要求", "standard_ref": "大气污染防治法", "is_veto": False,
    },
    {
        "item_no": "S4.3", "category": "environmental", "risk_dimension": "environmental",
        "standard_title": "废水排放接口与去向", "standard_ref": "水污染防治法", "is_veto": False,
    },
    {
        "item_no": "S4.4", "category": "environmental", "risk_dimension": "environmental",
        "standard_title": "固废/危废收集与处置", "standard_ref": "固体废物污染环境防治法", "is_veto": False,
    },
    {
        "item_no": "S4.5", "category": "noise", "risk_dimension": "environmental",
        "standard_title": "噪声排放控制", "standard_ref": "GB 12348 工业企业厂界环境噪声排放标准", "is_veto": False,
    },
    # ════════════════════════════════════════════════════════════
    # 化学风险维度
    # ════════════════════════════════════════════════════════════
    {
        "item_no": "S5.1", "category": "chemical_safety", "risk_dimension": "chemical",
        "standard_title": "腐蚀性物料防护（材质/衬里/防泄漏）", "standard_ref": "", "is_veto": False,
    },
    {
        "item_no": "S5.2", "category": "chemical_safety", "risk_dimension": "chemical",
        "standard_title": "易燃易爆介质安全设计", "standard_ref": "GB 50160 石油化工企业设计防火标准", "is_veto": False,
    },
    {
        "item_no": "S5.3", "category": "chemical_safety", "risk_dimension": "chemical",
        "standard_title": "化学品储存与隔离（MSDS/标识/围堰）", "standard_ref": "危险化学品安全管理条例", "is_veto": False,
    },
    {
        "item_no": "S5.4", "category": "chemical_safety", "risk_dimension": "chemical",
        "standard_title": "有毒有害物质防护与应急（洗眼器/通风）", "standard_ref": "工作场所有害因素职业接触限值", "is_veto": False,
    },
    # ════════════════════════════════════════════════════════════
    # 通用/其他（不绑定单一维度）
    # ════════════════════════════════════════════════════════════
    {
        "item_no": "S6.1", "category": "env_health", "risk_dimension": "none",
        "standard_title": "职业危害因素辨识与防护设施", "standard_ref": "职业病防治法", "is_veto": False,
    },
    {
        "item_no": "S6.2", "category": "env_health", "risk_dimension": "none",
        "standard_title": "设备操作安全操作规程与培训", "standard_ref": "安全生产法", "is_veto": False,
    },
    {
        "item_no": "S6.3", "category": "env_health", "risk_dimension": "none",
        "standard_title": "应急疏散与应急器材配置", "standard_ref": "GB/T 29639 应急预案编制导则", "is_veto": False,
    },
    {
        "item_no": "S6.4", "category": "env_health", "risk_dimension": "none",
        "standard_title": "设备铭牌/标识/中文说明书", "standard_ref": "设备安全监督条例", "is_veto": False,
    },
    {
        "item_no": "S6.5", "category": "env_health", "risk_dimension": "none",
        "standard_title": "投用前确认与验收资料（检测/试车记录）", "standard_ref": "", "is_veto": False,
    },
]
