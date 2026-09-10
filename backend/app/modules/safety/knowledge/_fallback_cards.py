"""Knowledge fallback cards — 当 DB/RAG 无可用卡片时注入的硬编码法规卡片。

自包含：只依赖 knowledge_card.KnowledgeCard，不依赖 DB / LLM / 外部服务。
"""
from __future__ import annotations

from app.modules.safety.knowledge.knowledge_card import KnowledgeCard


def _card(title, category, priority, **kw) -> KnowledgeCard:
    return KnowledgeCard(
        document_title=title,
        document_category=category,
        priority=priority,
        **kw,
    )


def build_fallback_cards() -> list[KnowledgeCard]:
    """返回 26 张硬编码法规知识卡片（每张至少一个内容字段）。"""
    return [
        _card("《中华人民共和国安全生产法》", "laws_regulations", "P0",
              legal_basis_clauses="第3条：安全生产工作坚持安全第一、预防为主、综合治理；第41条：生产经营单位应当建立安全风险分级管控制度，按照安全风险分级采取相应的管控措施，并如实记录。"),
        _card("GB/T 13861-2022《生产过程危险和有害因素分类与代码》", "standards", "P0",
              hazard_type_definitions="人的因素/物的因素/环境因素/管理因素；13 类危害因素分类与代码。"),
        _card("GB 30871-2022《危险化学品企业特殊作业安全规范》", "standards", "P0",
              rectification_requirements="动火、受限空间、高处等特殊作业须办理作业票并落实安全措施后方可作业。"),
        _card("《化工和危险化学品生产经营单位重大生产安全事故隐患判定标准（试行）》", "laws_regulations", "P0",
              hazard_level_criteria="构成重大隐患的情形：未取得安全许可、按钮/联锁失效、可燃有毒气体泄漏报警装置缺失等。"),
        _card("《集团安全生产十大禁令》", "management_systems", "P0",
              key_defect_examples="严禁违章指挥、严禁无票作业、严禁酒后上岗、严禁高处作业不系安全带等。"),
        _card("GB 3836.1-2010《爆炸性环境 第1部分：设备 通用要求》", "standards", "P1",
              hazard_category_criteria="防爆电气设备选型须符合爆炸危险区域划分；防爆堵头缺失、密封圈老化属典型缺陷。"),
        _card("GB 50016-2014《建筑设计防火规范》", "standards", "P1",
              rectification_requirements="防火间距、疏散通道宽度、防火分隔满足规范要求。"),
        _card("《职业病防治法》", "laws_regulations", "P1",
              legal_basis_clauses="用人单位应当提供符合国家职业卫生标准的职业病防护设施和个人防护用品。"),
        _card("GBZ 188-2014《职业健康监护技术规范》", "standards", "P1",
              hazard_type_definitions="接触职业病危害因素的劳动者应进行上岗前、在岗期间、离岗时职业健康检查。"),
        _card("《危险化学品安全管理条例》", "laws_regulations", "P1",
              legal_basis_clauses="危险化学品储存应专区专库、双人收发双人保管，禁忌物品不得混存。"),
        _card("TSG 08-2017《特种设备使用管理规则》", "standards", "P1",
              rectification_requirements="特种设备使用登记、定期检验、作业人员持证上岗。"),
        _card("JGJ 59-2011《建筑施工安全检查标准》", "standards", "P1",
              key_defect_examples="临边防护缺失、脚手板未满铺、洞口未盖板等。"),
        _card("《全民消防安全宣传教育纲要》", "management_systems", "P1",
              rectification_requirements="定期开展消防安全培训、疏散演练。"),
        _card("GB 4053.3-2009《固定式钢梯及平台安全要求》", "standards", "P2",
              rectification_requirements="平台踢脚板高度≥100mm、扶手高度≥1050mm、栏杆立杆间距≤1000mm。"),
        _card("《特种设备安全法》", "laws_regulations", "P2",
              legal_basis_clauses="第33条：特种设备使用单位应当在投入使用前或投入使用后30日内向负责特种设备安全监督管理的部门办理使用登记。"),
        _card("《企业安全生产标准化基本规范》", "management_systems", "P2",
              hazard_type_definitions="目标职责、制度化管理、教育培训、现场管理、安全风险管控及隐患排查治理。"),
        _card("AQ/T 9002-2021《企业安全生产标准化基本规范》", "standards", "P2",
              hazard_level_criteria="重大/较大/一般事故隐患分级判定及闭环管理。"),
        _card("《生产安全事故报告和调查处理条例》", "laws_regulations", "P2",
              legal_basis_clauses="事故发生后1小时内向县级以上人民政府安全生产监督管理部门报告。"),
        _card("《工伤保险条例》", "laws_regulations", "P2",
              legal_basis_clauses="职工发生事故伤害，用人单位应在30日内提出工伤认定申请。"),
        _card("《中华人民共和国消防法》", "laws_regulations", "P2",
              rectification_requirements="保障疏散通道、安全出口畅通，消防设施器材完好有效。"),
        _card("GB 15603-2019《常用化学危险品贮存通则》", "standards", "P2",
              hazard_category_criteria="化学危险品按性质分类贮存，禁忌物应隔离，仓库应通风、避光、防潮。"),
        _card("《工作场所职业病危害警示标识》GBZ 158-2003", "standards", "P2",
              key_defect_examples="职业病危害告知卡、警示标识缺失或模糊。"),
        _card("《有限空间作业安全技术规范》GB/T 35073", "standards", "P2",
              rectification_requirements="先通风、再检测、后作业；作业前进行气体检测并全程监护。"),
        _card("《动火作业安全规范》GB 30871", "standards", "P2",
              key_defect_examples="未办理动火票、未进行可燃气体检测、未设置监护人。"),
        _card("《配电室安全管理规范》", "management_systems", "P2",
              key_defect_examples="配电室门未上锁、挡鼠板缺失、绝缘垫破损、未配置灭火器材。"),
        _card("《隐患排查治理暂行规定》", "laws_regulations", "P2",
              hazard_level_criteria="一般事故隐患由生产经营单位立即组织整改；重大事故隐患应制定治理方案并挂牌督办。"),
    ]
