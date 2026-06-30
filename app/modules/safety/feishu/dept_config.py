"""部门负责人 & 分管领导 & 安全员配置表。

数据来源：飞书多维表格「部门负责人一览表」（人工维护），
覆盖 identity.departments 自动同步的不准确数据。
安全员名单由各部门确认后人工维护。

用法：
    from app.modules.safety.feishu.dept_config import DEPARTMENT_CONFIG

    config = DEPARTMENT_CONFIG.get("生产管理部")
    leader_name = config["leader"]           # "佘祥辉"
    supervisor_name = config["supervisor"]   # "温军贤"
    safety_officer_name = config.get("safety_officer")  # None 表示该部门暂未配置安全员
"""

DEPARTMENT_CONFIG: dict[str, dict[str, str]] = {
    "合规监察部":          {"leader": "郭继龙", "supervisor": "刘畅"},
    "生产管理部":          {"leader": "佘祥辉", "supervisor": "温军贤"},
    "仓储部":              {"leader": "陈娇",   "supervisor": "温军贤", "safety_officer": "武春霞"},
    "菌种中心":            {"leader": "黄凤珠", "supervisor": "温军贤", "safety_officer": "翁日生"},
    "设备工程部":          {"leader": "杨银杉", "supervisor": "何远树", "safety_officer": "林恒"},
    "动力部":              {"leader": "刘柳兵", "supervisor": "何远树", "safety_officer": "胡永晟"},
    "发酵工程部":          {"leader": "陈坚超", "supervisor": "暨火兴", "safety_officer": "邓宇"},
    "提炼工程一部":        {"leader": "林礼枫", "supervisor": "吴志华", "safety_officer": "郑雅杰"},
    "提炼工程三部":        {"leader": "林礼枫", "supervisor": "吴志华", "safety_officer": "郑雅杰"},
    "提炼工程二部":        {"leader": "蔡万进", "supervisor": "刘文锋", "safety_officer": "李伟豪"},
    "精制工程一部":        {"leader": "汪功剑", "supervisor": "刘文锋", "safety_officer": "陈宇辉"},
    "提炼工程四部":        {"leader": "洪川林", "supervisor": "刘文锋", "safety_officer": "杨昆"},
    "提炼工程五部":        {"leader": "林东态", "supervisor": "刘文锋", "safety_officer": "蔡嘉旺"},
    "提炼工程六部":        {"leader": "王涛",   "supervisor": "刘文锋", "safety_officer": "陈美丽"},
    "提炼技术精进中心":    {"leader": "刘小刚", "supervisor": "刘文锋", "safety_officer": "李帅"},
    "质量控制部（QC部）":  {"leader": "王凤景", "supervisor": "吴钰彬", "safety_officer": "翁日生"},
    "质量保证部（QA部）":  {"leader": "廖庆云", "supervisor": "吴钰彬", "safety_officer": "翁日生"},
    "法规注册部（RA部）":  {"leader": "蔡榕斌", "supervisor": "吴钰彬"},
    "环保工程中心":        {"leader": "杨剑",   "supervisor": "温军贤", "safety_officer": "罗建华"},
    "安全工程中心":        {"leader": "宁宇晗", "supervisor": "刘畅",   "safety_officer": "王海霞"},
    "AI创新部":            {"leader": "许康福", "supervisor": "许康福", "safety_officer": "许康福"},
    "发酵工程中心":        {"leader": "罗仲鸿", "supervisor": "王健"},
    "提炼半合成工程中心":  {"leader": "陈鑫耀", "supervisor": "王健",   "safety_officer": "黄惠龄"},
    "人力资源部":          {"leader": "陈小娟", "supervisor": "刘畅"},
    "行政后勤部":          {"leader": "林小白", "supervisor": "刘畅",   "safety_officer": "何海师"},
    "采购部":              {"leader": "周亮亮", "supervisor": "刘畅"},
    "财务部":              {"leader": "吴丽文", "supervisor": "雷春建"},
}
