"""培训导出模板注册表 — 11 个 docx 模板的元数据与占位符文档。

本文件是三处的共同数据源：
1. training_template_store 上传校验（缺必填标记拒绝入库）
2. 前端模板管理页「可用占位符」展示（GET /hr/training-export-templates 原样下发）
3. 测试一致性检查（默认模板文件必须包含全部必填标记，防标记漂移）

约定：
- 标记一律写成 ``{中文名}``，与模板文件里的字面文本一致（试卷模板历史原因是双花括号
  ``{{培训内容}}``，保持不变）。
- ``required`` 的标记缺失时上传被拒绝；``optional`` 缺失只影响导出内容不拦截。
  结构性锚点（行克隆的模板行标记、页眉页码）一律 required/optional 按实际用途标注。
- ``notes`` 是给用户的模板修改注意事项，前端原样展示。
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TemplateMarker:
    name: str          # 标记字面文本，含花括号，如 "{姓名}"
    description: str   # 导出时填充的内容说明
    required: bool = True


@dataclass(frozen=True)
class TrainingTemplateDef:
    key: str                # 注册键，入库 template_key
    name: str               # 展示名
    description: str        # 用途说明
    default_file: str       # backend/assets/hr/ 下的默认模板文件名
    markers: list[TemplateMarker] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def required_markers(self) -> list[str]:
        return [m.name for m in self.markers if m.required]


def _m(name: str, description: str, required: bool = True) -> TemplateMarker:
    return TemplateMarker(name=name, description=description, required=required)


TEMPLATES: list[TrainingTemplateDef] = [
    TrainingTemplateDef(
        key="training_notification",
        name="培训通知书",
        description="培训通知导出（7.4），SOP 培训全套材料之一",
        default_file="7.4培训通知书.docx",
        markers=[
            _m("{培训内容}", "培训主题，有补充内容时以「—」连接"),
            _m("{实施日期}", "培训日期与时段（面授/自学，多时段以「；」连接）"),
            _m("{课时}", "按面授时段累计的课时（如 4小时）"),
            _m("{培训方式}", "面授/自学/面授+自学等"),
            _m("{授课单位_培训师}", "培训师姓名"),
            _m("{培训对象}", "「部门」全体成员及病产假除外说明"),
            _m("{培训地点}", "培训地点"),
            _m("{考核方式}", "问答/笔试/实操等"),
            _m("{体现部门}", "页眉「部门/Dept」行的签发部门"),
            _m("{签发日期}", "页眉的落款日期行"),
        ],
        notes=[
            "「注意事项」三条文案已写在模板里，直接改模板文字即可生效",
            "页眉里保留 {体现部门} 和 {签发日期} 标记，位置可移动但不要删除",
        ],
    ),
    TrainingTemplateDef(
        key="training_signin_sheet",
        name="培训签到表",
        description="培训签到表导出（7.5），SOP 培训全套材料之一；人数多时自动分页",
        default_file="7.5培训签到表.docx",
        markers=[
            _m("{培训内容}", "培训主题"),
            _m("{培训对象}", "「部门」全体成员及病产假除外说明"),
            _m("{培训方式}", "面授/自学/面授+自学等"),
            _m("{课时}", "按面授时段累计的课时"),
            _m("{考核方式}", "问答/笔试/实操等"),
            _m("{实施日期}", "培训日期与时段"),
            _m("{姓名}", "签到行模板标记：系统按参训人数克隆该行并逐行填入"),
            _m("{体现部门}", "签到行模板标记：参训人所属部门，与 {姓名} 同一行"),
            _m("{页码}", "页眉页码，导出时替换为 Word 自动页码域", required=False),
            _m("{总页数}", "页眉总页数，导出时替换为 Word 自动总页数域", required=False),
        ],
        notes=[
            "含 {姓名} 的签到行是模板行：每页 15 人由系统克隆生成，行内可调整样式但标记要保留",
            "页眉的 {页码} {总页数} 缺失时页码保持模板原样，不影响导出",
        ],
    ),
    TrainingTemplateDef(
        key="training_evaluation",
        name="培训效果评估表",
        description="培训效果评估导出（7.11），SOP 培训全套材料之一",
        default_file="7.11培训效果评估表.docx",
        markers=[
            _m("{培训内容}", "培训主题"),
            _m("{实施日期}", "培训日期（如 2026.12.15）"),
            _m("{课时}", "课时（如 4h）"),
            _m("{培训方式}", "培训方式"),
            _m("{授课单位_培训师}", "培训师"),
            _m("{培训对象}", "「部门」全体成员及人数（写在「部门/班组/人员」栏）"),
            _m("{考核方式}", "考核方式"),
            _m("{部门总人数}", "应到人数", required=False),
            _m("{参与人数}", "实到人数", required=False),
            _m("{事假}", "事假人数", required=False),
            _m("{病假}", "病假人数", required=False),
            _m("{产假}", "产假人数", required=False),
            _m("{参加考核人数}", "参加考核人数", required=False),
            _m("{优秀人数}", "考核优秀人数", required=False),
            _m("{合格人数}", "考核合格人数", required=False),
            _m("{不合格人数}", "考核不合格人数", required=False),
            _m("{答题参与率}", "参与率（写在「参训人员参与率…」句中）", required=False),
            _m("{答题及格率}", "合格率（写在「合格率…」处）", required=False),
        ],
        notes=[
            "统计类标记未填数据时写空，不会破坏导出",
            "参与率与合格率都为空时，整句「参训人员参与率…达到培训效果。」自动隐藏",
        ],
    ),
    TrainingTemplateDef(
        key="qa_record",
        name="现场问答/实操记录表",
        description="问答考核现场记录表导出，含考题区与受训人员区",
        default_file="现场问答，实操记录表-模板1.docx",
        markers=[
            _m("{培训内容}", "培训主题"),
            _m("{实施日期}", "培训日期"),
            _m("{培训方式}", "培训方式"),
            _m("{培训对象}", "培训部门/对象"),
            _m("{培训目的}", "培训目的"),
            _m("{$index+1}", "考题行模板标记：题号", required=False),
            _m("{文件编号}", "考题行模板标记：SOP 文件编号"),
            _m("{题目}", "考题行模板标记：考题内容，系统按题目数量克隆该行"),
            _m("{正确答案}", "考题行模板标记：正确答案"),
            _m("{分值}", "考题行模板标记：题目分值"),
            _m("{姓名}", "受训人行模板标记：姓名，系统按人数克隆该行"),
            _m("{答题结果}", "受训人行模板标记：答题/得分情况", required=False),
            _m("{考核日期}", "受训人行模板标记：考核日期", required=False),
            _m("{总分}", "受训人行模板标记：总分", required=False),
        ],
        notes=[
            "考题行以 {题目} 标记所在行为模板行；受训人行以 {姓名} 标记所在行为模板行",
            "无考题导出时考题区保留 5 个空白行供打印后手写",
        ],
    ),
    TrainingTemplateDef(
        key="score_report",
        name="培训成绩单",
        description="问答考核/考试成绩单导出，按人数自动追加行",
        default_file="成绩单模板.docx",
        markers=[
            _m("{序号}", "成绩行模板标记：序号", required=False),
            _m("{姓名}", "成绩行模板标记：姓名，系统按人数克隆该行"),
            _m("{部门}", "成绩行模板标记：部门", required=False),
            _m("{总分}", "成绩行模板标记：总分", required=False),
        ],
        notes=["表头之下含 {姓名} 的行是模板行，其样式决定全部成绩行样式"],
    ),
    TrainingTemplateDef(
        key="training_record",
        name="新员工培训记录",
        description="新员工入职培训记录（含员工概况与培训内容）",
        default_file="新员工培训记录-模板.docx",
        markers=[
            _m("{姓名}", "员工姓名"),
            _m("{性别}", "性别"),
            _m("{年龄}", "按出生年份推算的年龄"),
            _m("{体现部门}", "部门"),
            _m("{体现岗位}", "培训岗位（未指定时为实际岗位）"),
            _m("{入职日期}", "入职日期"),
            _m("{{入职日期}+3M-1day}", "试用期截止日（入职日期+3个月-1天，系统计算）"),
        ],
        notes=[
            "动态培训条目写入培训内容表格的固定行区域，请勿增删该区域的行",
            "试用期截止日标记 {{入职日期}+3M-1day} 是一个整体（三层花括号），请勿拆改",
        ],
    ),
    TrainingTemplateDef(
        key="work_permit",
        name="上岗证",
        description="新员工上岗证，培训清单从岗位培训表自动带出",
        default_file="上岗证模板.docx",
        markers=[
            _m("{姓名}", "员工姓名"),
            _m("{性别}", "性别"),
            _m("{学历}", "学历"),
            _m("{体现部门}", "部门"),
            _m("{培训起止日期}", "培训计划最早~最晚日期"),
            _m("{培训清单内容}", "岗位培训内容清单"),
            _m("{培训师}", "培训师（去重后顿号连接）"),
        ],
    ),
    TrainingTemplateDef(
        key="prejob_plan",
        name="岗前培训计划",
        description="新员工/异动人员岗前培训计划，培训内容按条目克隆行",
        default_file="新员工培训计划-模板.docx",
        markers=[
            _m("{姓名}", "员工姓名"),
            _m("{学历}", "学历"),
            _m("{毕业院校}", "毕业院校"),
            _m("{毕业时间}", "毕业时间"),
            _m("{体现部门}", "部门"),
            _m("{体现岗位}", "培训岗位（未指定时为实际岗位）"),
            _m("{入职日期}", "入职日期"),
            _m("{证书}", "人员分类/证书"),
            _m("{异动类别}", "新员工 或 岗位变动"),
            _m("{#培训内容}", "培训内容行循环开始标记（放模板行首格）"),
            _m("{/培训内容}", "培训内容行循环结束标记（放模板行末格）"),
            _m("{$index+1}", "培训内容行序号"),
            _m("{培训类别}", "培训内容行：培训类别"),
            _m("{培训师}", "培训内容行：培训师"),
            _m("{培训方式}", "培训内容行：培训方式"),
        ],
        notes=[
            "培训内容表是第二个表格：含 {#培训内容} 的行为模板行，克隆后整行替换；"
            "「计划完成期限」取培训类别与培训师之间的空白格",
            "循环标记 {#培训内容} {/培训内容} 必须成对出现在同一行",
        ],
    ),
    TrainingTemplateDef(
        key="training_registration",
        name="个人培训登记表",
        description="员工个人历年培训台账登记表，每人一页",
        default_file="个人培训登记表.docx",
        markers=[
            _m("{姓名}", "员工姓名"),
            _m("{性别}", "性别"),
            _m("{体现部门}", "部门"),
            _m("{体现岗位}", "岗位"),
            _m("{学历}", "学历"),
            _m("{毕业院校}", "毕业院校"),
            _m("{专业}", "专业"),
            _m("{证书}", "证书/人员分类"),
            _m("{毕业时间}", "毕业时间（可写 {毕业时间| customDate:'YYYY-MM-DD'}）"),
            _m("{入职日期}", "入职日期（可写 {入职日期| customDate:'YYYY-MM-DD'}）"),
            _m("{#台账}", "记录行循环开始标记（独立段落）"),
            _m("{/台账}", "记录行循环结束标记（独立段落）"),
        ],
        notes=[
            "{#台账} {/台账} 必须作为独立段落成对出现，系统按员工逐人克隆整页",
            "日期标记支持过滤器写法 {入职日期| customDate:'YYYY-MM-DD'}，不带过滤器则原样输出",
        ],
    ),
    TrainingTemplateDef(
        key="roster",
        name="培训花名册",
        description="培训口径人员花名册导出",
        default_file="roster_template.docx",
        markers=[
            _m("{$index+1}", "行序号"),
            _m("{体现部门}", "部门"),
            _m("{姓名}", "姓名"),
            _m("{性别}", "性别"),
            _m("{学历}", "学历"),
            _m("{人员状态}", "在职状态（未分类时写「在职」）", required=False),
            _m("{入职日期}", "入职日期（可写 {入职日期| customDate:'YYYY-MM-DD'}）"),
        ],
        notes=[
            "表格第一行数据行（表头之后）是模板行，系统按人数克隆",
            "页眉「第」「共」后会被改写为页码占位，措辞可调整但保持「第」「共」字样",
        ],
    ),
    TrainingTemplateDef(
        key="exam_paper",
        name="笔试试卷",
        description="笔试考核试卷导出，题型区块由系统按试卷内容自动生成",
        default_file="试卷模板.docx",
        markers=[
            _m("{{培训内容}}", "试卷标题：替换为「某某试题」（历史原因保留双花括号写法）"),
        ],
        notes=[
            "单选/判断/多选/填空四个题型区块由系统自动追加在模板内容之后，模板只需保留页面骨架与标题标记",
        ],
    ),
]

TEMPLATES_BY_KEY: dict[str, TrainingTemplateDef] = {t.key: t for t in TEMPLATES}


def get_template_def(key: str) -> TrainingTemplateDef | None:
    return TEMPLATES_BY_KEY.get(key)
