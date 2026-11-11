"""报表用职级：培训人员名单按「职级 + 岗位类别 + 职务」自动计算的分级口径。

规则（2026-11 与培训管理确认，含 M 序列两轮修正）：
参与分级的人员 = 职级为 M 序列（管理岗阶梯，M1 起步即经理级）或
岗位类别为「管理」，或 职级为 S 序列且 ≥ S13（含 S13）。
在此范围内按职务（duty）关键词分级：
- 职务等于「总经理」→ 总经理级及以上
- 职务含 副总经理 / 总监 → 总监级（总监关键词优先于经理，
  覆盖「生产总监兼六部经理」这类兼任职务）；「工程师」→ 总监级
  仅适用于 S13 及以上（M 序列工程师如 M1 高级工程师按序列保底）
- 职务含「经理」且不含「总经理」→ 经理级
- M 序列人员职务未命中以上关键词时保底「经理级」（M1 高级工程师等）；
  「副总经理」「总经理助理」因包含「总经理」不落入经理级档
其余（非管理序列、S13 以下、无职务且非 M 序列等）→ 其他人员。

原始「级别」字段仍在脱敏名单白名单之外（不外显），仅作为本公式的输入；
名单对外只输出计算结果 report_level。
"""

import re

REPORT_LEVEL_FIELD = "report_level"
REPORT_LEVEL_LABEL = "报表用职级"

LEVEL_GM = "总经理级及以上"
LEVEL_DIRECTOR = "总监级"
LEVEL_MANAGER = "经理级"
LEVEL_OTHER = "其他人员"

# 管理岗位类别值（M 序列管理岗在名单中的岗位类别）
MANAGEMENT_CATEGORY = "管理"

# S 序列参与分级的门槛（S13 及以上，含 S13）
_S_LEVEL_THRESHOLD = 13

_S_LEVEL_RE = re.compile(r"^[Ss](\d+)$")
_M_LEVEL_RE = re.compile(r"^[Mm]\d+$")

# 总监级关键词（优先匹配）：副总经理放在「经理」之前生效，
# 使「副总经理」不会因包含「经理」被误判为经理级；「总工程师」是总监级
# 头衔（如 M6 总工程师）。普通「工程师/高级工程师」→ 总监级仅对
# S13 及以上生效，M 序列按序列保底经理级（见 compute_report_level）。
_DIRECTOR_KEYWORDS = ("副总经理", "总监", "总工程师")
_S_DIRECTOR_KEYWORDS = _DIRECTOR_KEYWORDS + ("工程师",)


def _s_track_number(level: str | None) -> int | None:
    """解析 S 序列职级数字（S13 → 13）；非纯 S 职级（M 序列/实习生等）返回 None。"""
    if not level:
        return None
    m = _S_LEVEL_RE.match(level.strip())
    return int(m.group(1)) if m else None


def compute_report_level(
    level: str | None, duty: str | None, job_category: str | None = None,
) -> str:
    """按 职级 + 岗位类别 + 职务 计算报表用职级（纯函数，名单行内即时计算）。"""
    lvl = (level or "").strip()
    s_num = _s_track_number(lvl)
    is_m_track = bool(_M_LEVEL_RE.match(lvl))
    is_mgmt_category = (job_category or "").strip() == MANAGEMENT_CATEGORY

    is_senior_s = s_num is not None and s_num >= _S_LEVEL_THRESHOLD
    if not is_senior_s and not is_m_track and not is_mgmt_category:
        return LEVEL_OTHER

    d = (duty or "").strip()
    if not d:
        # M 序列无职务也保底经理级；S13+/管理类无职务 → 其他人员
        return LEVEL_MANAGER if is_m_track else LEVEL_OTHER
    if d == "总经理":
        return LEVEL_GM
    director_keywords = _S_DIRECTOR_KEYWORDS if is_senior_s else _DIRECTOR_KEYWORDS
    if any(k in d for k in director_keywords):
        return LEVEL_DIRECTOR
    if "经理" in d and "总经理" not in d:
        return LEVEL_MANAGER
    # M 序列职务未命中关键词（高级工程师/总经理助理等）保底经理级
    return LEVEL_MANAGER if is_m_track else LEVEL_OTHER
