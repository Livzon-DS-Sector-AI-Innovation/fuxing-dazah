"""法规知识卡片 — 数据模型与文档清单。

每份法规标准文档预提取与 6 个 AI 输出字段直接相关的结构化摘要，
注入到 AI prompt 中替代模型训练记忆。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ═══════════════════════════════════════════════════════════════════════════
# 知识卡片数据模型
# ═══════════════════════════════════════════════════════════════════════════


class KnowledgeCard(BaseModel):
    """单份法规文档的结构化知识卡片。

    每张卡片对应一份法规标准文档，提取与隐患识别最相关的核心内容。
    所有字段按需填充——并非每份文档都涉及所有 6 个维度。
    """

    document_title: str = Field(..., description="文档标题")
    document_category: str = Field(
        ..., description="分类: laws_regulations / standards / management_systems"
    )
    priority: str = Field(
        ..., description="优先级: P0(必须注入) / P1(空间充裕时注入) / P2(按需注入)"
    )

    # ── 与 6 个 AI 输出字段对应的知识内容 ──

    hazard_type_definitions: str | None = Field(
        None, description="→ hazard_type: 隐患分类（人/物/环/管）的原文定义"
    )
    hazard_category_criteria: str | None = Field(
        None, description="→ hazard_category: 13 类隐患类别的判定标准和典型场景"
    )
    hazard_level_criteria: str | None = Field(
        None, description="→ hazard_level: 重大/较大/一般隐患的分级标准原文"
    )
    key_defect_examples: str | None = Field(
        None, description="→ key_defect: 典型缺陷描述范例"
    )
    rectification_requirements: str | None = Field(
        None, description="→ rectification_suggestion: 整改措施要求和防护标准"
    )
    legal_basis_clauses: str | None = Field(
        None, description="→ major_hazard_basis: 可直接引用的法规条文"
    )

    # ── 元数据 ──

    full_document_ref: str | None = Field(
        None, description="完整文档的存储引用（knowledge_articles.id 或文件路径）"
    )
    extracted_at: str | None = Field(
        None, description="知识卡片提取时间（ISO 格式）"
    )
    version: int = Field(1, description="知识卡片版本号")


class KnowledgeDocumentMeta(BaseModel):
    """法规文档元信息（对应设计方案 5.1 节 13 份文档清单）。"""

    title: str
    category: str
    priority: str  # P0 / P1 / P2
    feishu_url: str
    file_token: str  # 从 feishu_url 中提取


# ═══════════════════════════════════════════════════════════════════════════
# 13 份法规文档清单（来自 AI隐患识别工作流设计方案 第五章）
# ═══════════════════════════════════════════════════════════════════════════

KNOWLEDGE_DOCUMENTS: list[KnowledgeDocumentMeta] = [
    KnowledgeDocumentMeta(
        title="《中华人民共和国安全生产法》",
        category="laws_regulations",
        priority="P0",
        feishu_url="https://j0eukrlohu.feishu.cn/file/GGCuboOZJoxax2x7aVXcXyrWnAM",
        file_token="GGCuboOZJoxax2x7aVXcXyrWnAM",
    ),
    KnowledgeDocumentMeta(
        title="GB/T 13861-2022《生产过程危险和有害因素分类与代码》",
        category="standards",
        priority="P0",
        feishu_url="https://j0eukrlohu.feishu.cn/file/T5vibjFWHo9JW6xWvDHc3RDEntg",
        file_token="T5vibjFWHo9JW6xWvDHc3RDEntg",
    ),
    KnowledgeDocumentMeta(
        title="GB 30871-2022《危险化学品企业特殊作业安全规范》",
        category="standards",
        priority="P0",
        feishu_url="https://j0eukrlohu.feishu.cn/file/OAhjbyKGzofVrOxIXn7ccMxDnIh",
        file_token="OAhjbyKGzofVrOxIXn7ccMxDnIh",
    ),
    KnowledgeDocumentMeta(
        title="《化工和危险化学品生产经营单位重大生产安全事故隐患判定标准（试行）》",
        category="laws_regulations",
        priority="P0",
        feishu_url="https://j0eukrlohu.feishu.cn/file/WphXbQ5cdomIrYx0YOmcY9mtnph",
        file_token="WphXbQ5cdomIrYx0YOmcY9mtnph",
    ),
    KnowledgeDocumentMeta(
        title="《集团安全生产十大禁令》",
        category="management_systems",
        priority="P0",
        feishu_url="https://j0eukrlohu.feishu.cn/file/W1kPbhGd7o3kF8x25mnc6XMrndg",
        file_token="W1kPbhGd7o3kF8x25mnc6XMrndg",
    ),
    # ── P1 ──
    KnowledgeDocumentMeta(
        title="GB 3836.1-2010《爆炸性环境 第1部分：设备 通用要求》",
        category="standards",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/ABvZbDesZoItebxhC0ZcsEN0nOb",
        file_token="ABvZbDesZoItebxhC0ZcsEN0nOb",
    ),
    KnowledgeDocumentMeta(
        title="GB 50016《建筑设计防火规范》",
        category="standards",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/SzYQb0QjSovoEvxNOwJcM1m2nmj",
        file_token="SzYQb0QjSovoEvxNOwJcM1m2nmj",
    ),
    KnowledgeDocumentMeta(
        title="GB 50160《石油化工企业设计防火标准》",
        category="standards",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/Z9GNbKFhFoteRYxOX5KcpSkjnFe",
        file_token="Z9GNbKFhFoteRYxOX5KcpSkjnFe",
    ),
    KnowledgeDocumentMeta(
        title="《工贸行业重大生产安全事故隐患判定标准》",
        category="laws_regulations",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/KjKpbSMghorMYFxsTSbceaa8nGf",
        file_token="KjKpbSMghorMYFxsTSbceaa8nGf",
    ),
    KnowledgeDocumentMeta(
        title="《危险化学品安全管理条例》",
        category="laws_regulations",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/EVsrb3ZUmoMWrbxI2x8c5gHHnol",
        file_token="EVsrb3ZUmoMWrbxI2x8c5gHHnol",
    ),
    KnowledgeDocumentMeta(
        title="《安全生产事故隐患排查治理暂行规定》（安监总局16号令）",
        category="laws_regulations",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/ELvVb2b5joD9emxXCXfcfUERn1f",
        file_token="ELvVb2b5joD9emxXCXfcfUERn1f",
    ),
    # ── P1 危险源辨识专用 ──
    KnowledgeDocumentMeta(
        title="GB 6441-2025《企业职工伤亡事故分类》",
        category="standards",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/SDF4bMrr6oTWY6x8Bfocb7tUnFb",
        file_token="SDF4bMrr6oTWY6x8Bfocb7tUnFb",
    ),
    KnowledgeDocumentMeta(
        title="GB 12801-2025《生产过程安全基本要求》",
        category="standards",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/OcmnbhYCIoD6whxKQKWcKhEvnLb",
        file_token="OcmnbhYCIoD6whxKQKWcKhEvnLb",
    ),
    KnowledgeDocumentMeta(
        title="GB 5083-2023《生产设备安全卫生设计总则》",
        category="standards",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/GWibb6GYQoIt7rxrMqvct1jknTc",
        file_token="GWibb6GYQoIt7rxrMqvct1jknTc",
    ),
    KnowledgeDocumentMeta(
        title="HG 20571-2014《化工企业安全卫生设计规范》",
        category="standards",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/GKBKbkqz1okRUXxegdacG569nAb",
        file_token="GKBKbkqz1okRUXxegdacG569nAb",
    ),
    KnowledgeDocumentMeta(
        title="《危险化学品双重预防机制建设指导手册》（2021版）",
        category="risk_assessment_standards",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/Pv8Jb1LGmo9d0nxkqxNcGDvUnHc",
        file_token="Pv8Jb1LGmo9d0nxkqxNcGDvUnHc",
    ),
    KnowledgeDocumentMeta(
        title="《企业安全风险分级管控和隐患排查治理双重预防机制建设 通则》",
        category="risk_assessment_standards",
        priority="P1",
        feishu_url="https://j0eukrlohu.feishu.cn/file/AoHmbkj8PohiQyx5HezcNGKvnGc",
        file_token="AoHmbkj8PohiQyx5HezcNGKvnGc",
    ),
    # ── P2 ──
    KnowledgeDocumentMeta(
        title="《中华人民共和国特种设备安全法》",
        category="laws_regulations",
        priority="P2",
        feishu_url="https://j0eukrlohu.feishu.cn/file/L9J7bKkMsoUFc1xsuBAcnu5Ondh",
        file_token="L9J7bKkMsoUFc1xsuBAcnu5Ondh",
    ),
    KnowledgeDocumentMeta(
        title="GB 4053.3-2009《固定式钢梯及平台安全要求》",
        category="standards",
        priority="P2",
        feishu_url="https://j0eukrlohu.feishu.cn/file/SR0vb00ploawA6xof2ecHWlunmb",
        file_token="SR0vb00ploawA6xof2ecHWlunmb",
    ),
    KnowledgeDocumentMeta(
        title="国卫疾控发[2015]92号《职业病危害因素分类目录》",
        category="laws_regulations",
        priority="P2",
        feishu_url="https://j0eukrlohu.feishu.cn/file/IqU0bZbmnoUiH1xLt2ecR2Von2f",
        file_token="IqU0bZbmnoUiH1xLt2ecR2Von2f",
    ),
    KnowledgeDocumentMeta(
        title="GB/T 50493-2019《石油化工可燃气体和有毒气体检测报警设计标准》",
        category="standards",
        priority="P2",
        feishu_url="https://j0eukrlohu.feishu.cn/file/L6q7b1SofooyRQxlKIscCNQ9n4c",
        file_token="L6q7b1SofooyRQxlKIscCNQ9n4c",
    ),
    KnowledgeDocumentMeta(
        title="SH/T 3097-2017《石油化工静电接地设计规范》",
        category="standards",
        priority="P2",
        feishu_url="https://j0eukrlohu.feishu.cn/file/WkFJb1kRno08lbxqQeKc2T1fnYg",
        file_token="WkFJb1kRno08lbxqQeKc2T1fnYg",
    ),
    KnowledgeDocumentMeta(
        title="GB 7231《工业管道的基本识别色、识别符号和安全标识》",
        category="standards",
        priority="P2",
        feishu_url="https://j0eukrlohu.feishu.cn/file/QOBKbRJwiojqNOxMhBMcMVlrnCd",
        file_token="QOBKbRJwiojqNOxMhBMcMVlrnCd",
    ),
    KnowledgeDocumentMeta(
        title="GB/T 4272-2024《设备及管道绝热技术通则》",
        category="standards",
        priority="P2",
        feishu_url="https://j0eukrlohu.feishu.cn/file/MbKjb97pHoOlELxPMJyciSienTg",
        file_token="MbKjb97pHoOlELxPMJyciSienTg",
    ),
    KnowledgeDocumentMeta(
        title="《危险化学品企业双重预防机制数字化建设工作指南（试行）》",
        category="risk_assessment_standards",
        priority="P2",
        feishu_url="https://j0eukrlohu.feishu.cn/file/IuHAbu60doeVkexHnWHc9i9enQh",
        file_token="IuHAbu60doeVkexHnWHc9i9enQh",
    ),
]


def get_documents_by_priority(priority: str) -> list[KnowledgeDocumentMeta]:
    """按优先级筛选文档清单。"""
    return [d for d in KNOWLEDGE_DOCUMENTS if d.priority == priority]
