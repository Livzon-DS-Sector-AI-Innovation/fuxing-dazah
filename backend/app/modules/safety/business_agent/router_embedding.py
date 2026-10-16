"""1-D 路由 II：嵌入相似度层（规则 miss 后、核心兜底前介入）。

- 每域一组示例问题（大白话优先，与关键词互补），向量经 EmbeddingService 批量
  生成后进程内缓存；用户消息向量与其做 numpy 余弦，top 域过阈值则挂该域工具集。
- 开关 ``SAFETY_AGENT_ROUTER_EMBEDDING``（默认开，0/false/off 关闭）。
- 嵌入服务不可用/异常 → 返回 None，调用方走核心兜底 15（路由永不抛出）。
- 示例向量首用一次性批量生成（embed 自带 LRU，重复消息零成本）。
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

EMBEDDING_ROUTER_SWITCH = "SAFETY_AGENT_ROUTER_EMBEDDING"
SIMILARITY_THRESHOLD = 0.55  # 初值；随 20 问回归集调优

# 每域示例问题（与 INTENT_KEYWORDS 互补：偏大白话/同义改写，不含关键词原词）
DOMAIN_EXAMPLES: dict[str, list[str]] = {
    "warehouse": [
        "仓库里乙醇还有多少库存",
        "最近一周入库了哪些物料",
        "上个月领用了多少硫酸",
        "呆料清单给我看一下",
        "这批物料放行了没有",
        "哪些物料快到复验期了",
        "查一下这个物料代码是什么",
        "仓储的不合格物料有哪些",
        "库存流水汇总一下",
        "仓库还剩多少批号在库",
    ],
    "hazard": [
        "现场发现的问题还有多少没处理完",
        "哪个部门问题最多",
        "上次检查留下的尾巴清了没",
        "帮我把没关闭的问题清单拉出来",
        "这个月安全问题趋势怎么样",
        "车间里有什么不安全的地方",
        "之前上报的缺陷处理到什么程度了",
        "给我看下督办情况",
        "哪里的整改还没验收",
        "泄漏点处理好了吗",
    ],
    "knowledge": [
        "储罐之间的距离怎么规定",
        "动火证办理条件是什么",
        "这个操作有没有依据可查",
        "国家对这个有什么要求",
        "哪里能查到权威说法",
        "帮我解释一下这条规定什么意思",
        "新版本和老版本差在哪",
        "这属于哪个标准管",
        "有没有相关条款可以引用",
        "查一下权威资料",
    ],
    "oh": [
        "谁体检结果有异常",
        "接触有害物质的岗位有哪些人",
        "听力不好的人有几个",
        "换岗位之前要做什么检查",
        "离岗时要不要做体检",
        "复查的人安排了没有",
        "哪些人属于重点监护对象",
        "厂里职业病风险高不高",
        "体检报告 AI 怎么解读的",
        "异常指标后续怎么跟踪",
    ],
    "drill": [
        "今年安排了哪些演习",
        "消防演练做过几次了",
        "下个月有什么演习安排",
        "上次疏散演习效果怎么样",
        "帮我编一份演习方案",
        "演练记录谁来复核",
        "应急处置卡有没有",
        "新员工要不要参加演习",
        "演习发现问题整改了吗",
        "什么时候搞综合演练",
    ],
    "alarm": [
        "昨晚警报响了多少次",
        "哪个车间误报最多",
        "烟感报警是什么原因",
        "报警频次比上周高吗",
        "值班室记录的异常有哪些",
        "火警误动作查清楚没",
        "帮我出一份报警分析",
        "探头报警分布在哪里",
        "这段时间报警趋势如何",
        "重复报警的点位是哪个",
    ],
    "special_op": [
        "今天现场有什么施工",
        "明天有哪些作业安排",
        "这个礼拜动火几次",
        "登高作业有没有报备",
        "有限空间进去了几个人",
        "临时用电批了多久",
        "周末有哪些非常规作业",
        "作业票开出来了没",
        "计划外施工多不多",
        "高危作业集中在哪几天",
    ],
    "ehs_change": [
        "工艺改动有没有走流程",
        "设备更换登记了吗",
        "最近有哪些变更事项",
        "改了什么影响安全的东西",
        "变更评审通过没有",
        "原料换了算不算变更",
        "布局调整报备了吗",
        "变更台账给我看看",
        "新改的项目验收了没",
        "哪些变更还在走审批",
    ],
    "work_ticket": [
        "票据审得严不严",
        "有没有人证不符的情况",
        "外包干活的人资质齐吗",
        "作业许可哪里没合规",
        "审票常见问题有哪些",
        "现场监护到位没有",
        "乙方人员名单核过没",
        "哪些票被打回来了",
        "违章作业查到几起",
        "实名制落实得怎么样",
    ],
    "cert_warning": [
        "谁的证快到期的",
        "电工证还有多久有效",
        "复审提醒发出去没有",
        "哪些资质需要续了",
        "特种作业人员证件齐不齐",
        "快过期证书清单给我",
        "什么时候安排复训",
        "证件过期了还能干吗",
        "监护人证书谁该换了",
        "本季度有多少证要续",
    ],
    "chemical": [
        "库房里存了哪些危险品",
        "这个原料安全数据去哪查",
        "两种东西放一起有没有问题",
        "现场存量超没超标",
        "有毒物质怎么防护",
        "化学品台账给我拉一份",
        "泄漏了该怎么应急处置",
        "易制爆的有哪些",
        "接触限值是多少",
        "仓库混放风险大不大",
    ],
    "guardian_subsidy": [
        "上个月监工费怎么算",
        "看守人员津贴明细",
        "加班盯现场的钱发了吗",
        "特殊岗位津贴有多少人领",
        "帮我核一下这个月的补贴",
        "谁的分没算进去",
        "津贴标准是几档",
        "统计下各车间补贴总额",
        "这笔钱按什么口径发",
        "监护人费用月报",
    ],
    "contractor_admission": [
        "外来施工队备案了吗",
        "乙方进场手续办完没",
        "第三方人员审核进度",
        "哪些单位还没通过准入",
        "供应商安全协议签了没",
        "新进外包队伍有哪些",
        "准入材料补齐了没有",
        "外来单位名单给我",
        "合作方资质过期没",
        "入厂培训做了吗",
    ],
    "office": [
        "把这个整理成一篇文稿",
        "帮我建个在线表格",
        "刚才那份资料存成文件",
        "会上要用的演示材料做一下",
        "搜下共享空间里那份制度",
        "把这页内容导出",
        "新建一个知识库页面",
        "给这份文档加个协作者",
        "表格里补一列数据",
        "把结论汇总到文档里",
    ],
    "urs": [
        "采购前的需求书帮忙把关",
        "设备选型技术要求评估",
        "这份需求文件合规吗",
        "新采购的风险点在哪",
        "用户需求书有没有漏项",
        "投标文件技术部分审一下",
        "设备技术规格合理性",
        "采购风险打分怎么样",
        "需求偏离项列出来",
        "出具一份评估意见",
    ],
    "ops": [
        "系统最近运行得怎么样",
        "后台任务有没有失败的",
        "AI 这块花了多少资源",
        "昨天的定时任务跑了吗",
        "配置都改了什么",
        "监控面板看什么状态",
        "调度有没有堆积",
        "接口调用成功率如何",
        "日志里有什么异常",
        "采集任务卡住了没",
    ],
}

_domain_vectors: dict[str, list[list[float]]] | None = None


def switch_enabled() -> bool:
    """嵌入层开关（默认开；0/false/off 关闭）。"""
    return os.environ.get(EMBEDDING_ROUTER_SWITCH, "1").strip().lower() not in (
        "0", "false", "off",
    )


async def _get_embedder():
    """复用 core.memory 的 EmbeddingService 单例（懒加载）。"""
    from app.modules.safety.business_agent.core.memory import _get_embedder as get

    return await get()


async def _ensure_domain_vectors() -> dict[str, list[list[float]]]:
    """域示例向量（进程内缓存，首用批量生成一次）。"""
    global _domain_vectors
    if _domain_vectors is None:
        embedder = await _get_embedder()
        vectors: dict[str, list[list[float]]] = {}
        for domain, examples in DOMAIN_EXAMPLES.items():
            vecs = await embedder.embed_batch(list(examples))
            vectors[domain] = [v for v in vecs if v]
        _domain_vectors = {
            d: vs for d, vs in vectors.items() if vs
        }
    return _domain_vectors


def _cosine(a: list[float], b: list[float]) -> float:
    import numpy as np

    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(va @ vb / (na * nb))


async def classify(message: str) -> tuple[str, float] | None:
    """嵌入相似度分类：返回 (top 域, 置信度)。

    开关关闭 / 服务不可用 / 最高分低于阈值 / 任何异常 → None（走核心兜底）。
    """
    if not switch_enabled() or not message or not message.strip():
        return None
    try:
        vectors = await _ensure_domain_vectors()
        if not vectors:
            return None
        embedder = await _get_embedder()
        qvec = await embedder.embed(message)
        best_domain: str | None = None
        best_score = -1.0
        for domain, vecs in vectors.items():
            score = max(_cosine(qvec, v) for v in vecs)
            if score > best_score:
                best_domain, best_score = domain, score
        if best_domain and best_score >= SIMILARITY_THRESHOLD:
            return best_domain, round(best_score, 4)
        return None
    except Exception:
        logger.debug("embedding router unavailable → core fallback", exc_info=True)
        return None


def reset_cache() -> None:
    """清空示例向量缓存（测试用）。"""
    global _domain_vectors
    _domain_vectors = None
