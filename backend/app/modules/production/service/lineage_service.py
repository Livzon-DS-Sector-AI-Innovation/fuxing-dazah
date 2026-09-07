"""工艺路线血缘：版本链解析与跨版本节点家族归并。

复刻（copy_route）会记录 origin_route_id / origin_node_id；数据汇总沿"祖先+自己"
的版本链合并批次数据，解决复刻后看不到前身路线历史批次的问题。

节点对齐规则（路线从新到旧归并进家族）：
- origin 指针优先：节点被某家族成员的 origin_node_id 指向，或自身 origin_node_id
  指向某家族成员 → 同家族（node_code 改名后仍可对齐）；
- node_code 兜底：与某家族任一成员同 code → 同家族（存量只回填了路线级血缘的场景）；
- 都不匹配 → 自成新家族（当前版本新增，或旧版有而当前版删除的工序）。
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.production.models import NodeFieldDef, ProcessRoute, RouteNode
from app.modules.production.repository import route as route_repo

_MAX_CHAIN_DEPTH = 20  # 版本链深度上限，防脏数据成环


@dataclass
class MergedFieldDef:
    """家族归并后的字段定义：node_id 已指向家族代表节点。"""

    node_id: uuid.UUID
    field_key: str
    field_label: str
    unit: str | None
    data_type: str
    sort_order: int


@dataclass
class NodeFamily:
    """跨版本同工序节点家族。

    rep 为最新成员（列/表头/权限锚点）；members 从新到旧排列，
    其全部节点 id 构成数据汇总的取数范围。
    """

    rep: RouteNode
    members: list[RouteNode] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.members:
            self.members = [self.rep]

    @property
    def node_ids(self) -> list[uuid.UUID]:
        return [n.id for n in self.members]

    @property
    def member_id_set(self) -> set[uuid.UUID]:
        return {n.id for n in self.members}


@dataclass
class LineageGraph:
    """数据汇总跨版本合并的解析结果。"""

    chain: list[ProcessRoute]  # 旧 → 新，chain[-1] 为当前路线
    families: list[NodeFamily]  # rep 顺序：当前路线节点按 sort_order 在前，祖先独有家族排后
    merged_defs: dict[uuid.UUID, list[MergedFieldDef]]  # rep 节点 id → 归并字段定义
    rep_by_member: dict[uuid.UUID, uuid.UUID]  # 成员节点 id → rep 节点 id（含自身）
    merged_route_names: list[str]  # 纳入合并的祖先路线名（旧 → 新），无合并时为空

    @property
    def route_ids(self) -> set[uuid.UUID]:
        return {r.id for r in self.chain}


async def get_route_chain(db: AsyncSession, route_id: uuid.UUID) -> list[ProcessRoute]:
    """沿 origin_route_id 上溯，返回"祖先 + 自己"，从旧到新排列。

    起始路线本身不过滤状态（字段趋势允许任意路线）；祖先中跳过草稿路线
    （无生产数据，但继续上溯其前身——草稿中间版截断会导致已发布祖先的
    历史批次丢失）；遇已删除路线或跨产品即止（脏数据防护），visited 集合防环。
    """
    route = await route_repo.get_route(db, route_id)
    if route is None:
        return []
    chain = [route]  # 暂存为新 → 旧
    visited = {route.id}
    current = route
    while (
        current.origin_route_id is not None
        and len(visited) < _MAX_CHAIN_DEPTH
        and current.origin_route_id not in visited
    ):
        ancestor = await route_repo.get_route(db, current.origin_route_id)
        if (
            ancestor is None
            or ancestor.is_deleted
            or ancestor.product_id != route.product_id
        ):
            break
        visited.add(ancestor.id)
        if ancestor.status != "draft":
            chain.append(ancestor)
        current = ancestor
    chain.reverse()
    return chain


def build_node_families(
    chain: list[ProcessRoute], nodes_by_route: dict[uuid.UUID, list[RouteNode]]
) -> list[NodeFamily]:
    """把版本链上各路线的节点归并为跨版本同工序家族（路线从新到旧处理）。"""
    families: list[NodeFamily] = []
    assigned: set[uuid.UUID] = set()
    for route in reversed(chain):  # 新 → 旧，家族首个成员即代表
        for node in nodes_by_route.get(route.id, []):
            if node.id in assigned:
                continue
            # origin 指针优先、node_code 兜底：两遍匹配。OR 链单遍匹配会让
            # 家族遍历顺序决定结果——同名 node_code 的新家族排在指针家族前面时，
            # 祖先节点会按弱规则并入错误家族（跨版本同码复用场景）
            target = next(
                (
                    f
                    for f in families
                    if node.origin_node_id in f.member_id_set
                    or any(m.origin_node_id == node.id for m in f.members)
                ),
                None,
            )
            if target is None:
                target = next(
                    (
                        f
                        for f in families
                        if any(m.node_code == node.node_code for m in f.members)
                    ),
                    None,
                )
            if target is None:
                families.append(NodeFamily(rep=node))
            else:
                target.members.append(node)
            assigned.add(node.id)
    return families


def merge_family_defs(
    family: NodeFamily, defs_by_node: dict[uuid.UUID, list[NodeFieldDef]]
) -> list[MergedFieldDef]:
    """归并家族内各版本的字段定义：按 field_key 去重，最新版本优先。

    当前版本的定义（label/unit/data_type）生效；旧版独有而当前版删除的字段保留、
    排在当前版本字段之后，避免历史列凭空消失造成新的断层。
    """
    merged: list[MergedFieldDef] = []
    seen: set[str] = set()
    for node in family.members:  # 新 → 旧；defs_by_node 内已按 sort_order 排序
        for d in defs_by_node.get(node.id, []):
            if d.field_key in seen:
                continue
            seen.add(d.field_key)
            merged.append(
                MergedFieldDef(
                    node_id=family.rep.id,
                    field_key=d.field_key,
                    field_label=d.field_label,
                    unit=d.unit,
                    data_type=d.data_type,
                    sort_order=d.sort_order,
                )
            )
    return merged


async def resolve_lineage(db: AsyncSession, route_id: uuid.UUID) -> LineageGraph | None:
    """解析路线的版本链、节点家族与归并字段定义；路线不存在返回 None。

    无祖先时退化为单路线行为（每节点自成家族、字段即自身定义），
    数据汇总可统一走家族路径。
    """
    chain = await get_route_chain(db, route_id)
    if not chain:
        return None
    current = chain[-1]

    nodes_by_route: dict[uuid.UUID, list[RouteNode]] = {}
    for r in chain:
        nodes_by_route[r.id] = await route_repo.get_route_nodes(db, r.id)

    families = build_node_families(chain, nodes_by_route)
    families.sort(key=lambda f: (f.rep.route_id != current.id, f.rep.sort_order))

    all_node_ids = [n.id for f in families for n in f.members]
    defs_by_node: dict[uuid.UUID, list[NodeFieldDef]] = {}
    for d in await route_repo.get_field_defs_by_nodes(db, all_node_ids):
        defs_by_node.setdefault(d.node_id, []).append(d)

    merged_defs = {f.rep.id: merge_family_defs(f, defs_by_node) for f in families}
    rep_by_member = {n.id: f.rep.id for f in families for n in f.members}
    merged_route_names = [r.route_name for r in chain[:-1]] if len(chain) > 1 else []
    return LineageGraph(
        chain=chain,
        families=families,
        merged_defs=merged_defs,
        rep_by_member=rep_by_member,
        merged_route_names=merged_route_names,
    )
