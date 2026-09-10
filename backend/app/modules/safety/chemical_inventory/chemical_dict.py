"""危化品名称 → 危险性/品类 知识字典（种子，可迭代）。

仅收录常见危化品的标准安全分类，不猜测；匹配不到返回 None（交给 AI/人工）。
"""
from __future__ import annotations

# 名称关键词 → (危险性列表, 品类)
CHEMICAL_DICT: list[tuple[str, list[str], str]] = [
    # 醇/酮/醚/酯/烃类溶剂（易燃）
    ("乙醇", ["flammable"], "溶剂"),
    ("甲醇", ["flammable", "toxic"], "溶剂"),
    ("异丙醇", ["flammable"], "溶剂"),
    ("正丁醇", ["flammable", "irritant"], "溶剂"),
    ("丙酮", ["flammable"], "溶剂"),
    ("乙酸乙酯", ["flammable"], "溶剂"),
    ("乙腈", ["flammable", "toxic"], "溶剂"),
    ("正己烷", ["flammable", "irritant"], "溶剂"),
    ("正庚烷", ["flammable"], "溶剂"),
    ("甲苯", ["flammable", "toxic"], "溶剂"),
    ("四氢呋喃", ["flammable", "irritant"], "溶剂"),
    ("异丙醚", ["flammable"], "溶剂"),
    ("石油醚", ["flammable"], "溶剂"),
    ("苯", ["flammable", "toxic"], "溶剂"),
    ("二甲基甲酰胺", ["flammable", "toxic"], "溶剂"),
    ("二甲基亚砜", ["irritant"], "溶剂"),
    ("氯仿", ["toxic"], "溶剂"),
    ("三氯甲烷", ["toxic"], "溶剂"),
    ("二氯甲烷", ["toxic"], "溶剂"),
    ("甲醛", ["toxic", "irritant"], "其他"),
    ("洗脱剂", ["flammable"], "溶剂"),
    ("废液", ["flammable"], "废液"),
    ("酒精", ["flammable"], "溶剂"),
    # 酸类（腐蚀）
    ("盐酸", ["corrosive"], "酸"),
    ("硫酸", ["corrosive"], "酸"),
    ("磷酸", ["corrosive"], "酸"),
    ("硝酸", ["oxidizer", "corrosive"], "酸"),
    ("冰醋酸", ["corrosive", "flammable"], "酸"),
    ("甲酸", ["corrosive", "flammable"], "酸"),
    ("三氟乙酸", ["corrosive"], "酸"),
    ("醋酸", ["corrosive", "flammable"], "酸"),
    ("乙酸", ["corrosive", "flammable"], "酸"),
    # 碱类（腐蚀）
    ("液碱", ["corrosive"], "碱"),
    ("氢氧化钠", ["corrosive"], "碱"),
    ("氨水", ["corrosive", "irritant"], "碱"),
    ("浓氨", ["corrosive", "irritant"], "碱"),
    ("三乙胺", ["flammable", "corrosive"], "碱"),
    # 氧化剂
    ("高锰酸钾", ["oxidizer", "precursor_explosive"], "氧化剂"),
    ("硝酸钾", ["oxidizer"], "氧化剂"),
    ("过硫酸钾", ["oxidizer"], "氧化剂"),
    ("过氧化氢", ["oxidizer", "corrosive"], "氧化剂"),
    ("双氧水", ["oxidizer", "corrosive"], "氧化剂"),
    # 其他
    ("次氯酸钠", ["corrosive", "oxidizer"], "其他"),
    ("亚硫酸氢钠", ["corrosive"], "其他"),
    ("3-二甲胺基丙胺", ["flammable", "corrosive"], "其他"),
    ("1-羟基苯并三唑", ["explosive", "irritant"], "其他"),
    ("HOBT", ["explosive", "irritant"], "其他"),
    ("珍珠岩", [], "其他"),
    ("清洗剂", [], "其他"),
    # 补充：数据中出现但上面未覆盖的常见危化品（标准 GHS 分类，非猜测）
    ("正丙醇", ["flammable", "irritant"], "溶剂"),
    ("仲丁醇", ["flammable"], "溶剂"),
    ("丁酮", ["flammable", "irritant"], "溶剂"),
    ("甲基乙基酮", ["flammable", "irritant"], "溶剂"),
    ("高氯酸", ["oxidizer", "corrosive"], "酸"),
    ("重铬酸钾", ["oxidizer", "toxic"], "氧化剂"),
    ("氢氧化钾", ["corrosive"], "碱"),
    ("三氯化铁", ["corrosive"], "其他"),
    ("二氯异氰尿酸钠", ["oxidizer", "irritant"], "氧化剂"),
    ("硝普钠", ["toxic"], "其他"),
    ("三溴化磷", ["corrosive"], "其他"),
    ("乳酸", ["irritant"], "酸"),
    ("二氯乙烷", ["flammable", "toxic"], "溶剂"),
    ("二甲基乙酰胺", ["toxic", "irritant"], "溶剂"),
    ("环己烷", ["flammable"], "溶剂"),
    ("吗啡啉", ["flammable", "corrosive"], "溶剂"),
    ("二氧六环", ["flammable"], "溶剂"),
    ("溴水", ["corrosive", "toxic"], "其他"),
    ("碘", ["toxic", "corrosive"], "其他"),
    ("四丁基氢氧化铵", ["corrosive"], "碱"),
    ("叔丁胺", ["flammable", "corrosive"], "溶剂"),
    ("二异丙基乙胺", ["flammable", "corrosive"], "溶剂"),
    ("吡啶", ["flammable", "toxic"], "溶剂"),
    ("水合肼", ["toxic", "corrosive"], "其他"),
    ("卡尔费休", ["toxic", "flammable"], "试剂"),
    ("乙二醇", ["irritant"], "其他"),
    ("丙三醇", [], "其他"),
    ("甘油", [], "其他"),
    ("酒石酸钾钠", [], "其他"),
    ("水杨酸钠", [], "其他"),
    ("三氟乙酸", ["corrosive"], "酸"),
    ("次氯酸钠", ["corrosive", "oxidizer"], "其他"),
    # 第二轮补充：半合成/精进/QC 中出现的常见危化品（标准 GHS 分类）
    ("DMF", ["flammable", "toxic"], "溶剂"),
    ("异辛烷", ["flammable"], "溶剂"),
    ("叔丁醇", ["flammable", "irritant"], "溶剂"),
    ("丙二醇", ["irritant"], "溶剂"),
    ("甲基叔丁基醚", ["flammable"], "溶剂"),
    ("卡氏试剂", ["toxic", "flammable"], "试剂"),
    ("氯化亚砜", ["corrosive", "toxic"], "其他"),
    ("氰化亚铜", ["toxic"], "其他"),
    ("氰化锌", ["toxic"], "其他"),
    ("硼氢化钠", ["flammable", "corrosive"], "其他"),
    ("氰基硼氢化钠", ["toxic"], "其他"),
    ("镁粉", ["flammable"], "其他"),
    ("钯碳", ["flammable"], "其他"),
    ("钯活性炭", ["flammable"], "其他"),
    ("锌粉", ["flammable"], "其他"),
    ("硅油", [], "其他"),
    ("正壬烷", ["flammable"], "溶剂"),
    ("柠檬酸", ["irritant"], "酸"),
    ("硫代乙酰胺", ["toxic"], "其他"),
    ("乙醛", ["flammable", "toxic"], "其他"),
    ("七氟丁酸", ["corrosive"], "酸"),
    ("五氟丙酸", ["corrosive"], "酸"),
    ("溴化铁", ["corrosive"], "其他"),
    ("硼酸", ["irritant"], "其他"),
    ("氯化钠", [], "其他"),
    ("司班", [], "其他"),
    ("戊烷磺酸钠", [], "其他"),
    ("三羟基氨基甲烷", ["irritant"], "其他"),
    ("六次甲基四胺", ["flammable", "irritant"], "其他"),
    ("五氧化二磷", ["corrosive"], "其他"),
    ("丁二酸二辛酯磺酸钠", [], "其他"),
    ("二叔丁基对甲酚", [], "其他"),
    ("甘氨酸", [], "其他"),
    ("正辛醇", ["irritant"], "溶剂"),
    ("正丁醛", ["flammable"], "其他"),
    ("正丙醛", ["flammable"], "其他"),
    ("甲基吡咯烷酮", ["toxic", "irritant"], "溶剂"),
    ("乙烷磺酸钠", [], "其他"),
    ("庚烷磺酸钠", [], "其他"),
    ("咪唑", ["corrosive", "irritant"], "其他"),
    ("凡士林", [], "其他"),
    ("抗坏血酸", [], "其他"),
    ("碳酸氢钠", [], "其他"),
    ("氢氧化钙", ["irritant"], "碱"),
    ("水杨酸", ["irritant"], "酸"),
    ("氯化钾", [], "其他"),
    ("硝普纳", ["toxic"], "其他"),
    # 第三轮补充：漏分类的常见危化品/盐类（标准 GHS 分类，非猜测）
    ("硫化钠", ["toxic", "corrosive"], "其他"),
    ("氯化钡", ["toxic"], "其他"),
    ("氯化钙", [], "其他"),
    ("碳酸钠", ["irritant"], "其他"),
]


def lookup_hazard_category(name: str) -> tuple[list[str], str] | None:
    """名称关键词匹配字典，返回 (危险性, 品类)；匹配不到返回 None。

    优先精确匹配，其次最长关键词匹配（避免「水杨酸」误命中「水杨酸钠」）。
    """
    n = (name or "").strip()
    if not n:
        return None
    for kw, hazards, category in CHEMICAL_DICT:
        if kw == n:
            return list(hazards), category
    best: tuple[list[str], str] | None = None
    best_len = -1
    for kw, hazards, category in CHEMICAL_DICT:
        if kw in n or n in kw:
            if len(kw) > best_len:
                best = (list(hazards), category)
                best_len = len(kw)
    return best
