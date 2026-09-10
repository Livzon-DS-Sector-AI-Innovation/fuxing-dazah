"""法规数据源注册表。

新增数据源只需在此添加 RegulationSource 条目即可，无需修改爬虫代码。

数据源策略（2026-07 重构）：
- 每个数据源指向各部门的「最新发布/通知公告」页面，而非「全部法规目录」
- 目录页面包含所有现行法规（包括几十年前的老法律），不适合爬取
- 通知公告页面按时间倒序排列，天然只包含近期新发布/修订的法规
- NPC（国家法律法规数据库）是法律档案库而非新闻源，已移除
"""

from __future__ import annotations

from app.modules.safety.regulation_crawler.engine.base import RegulationSource

# ── 非工业类别负面关键词：标准目录来源（openstd/hbba）用于源头拦截 ──
# 这些类别的强制国标与原料药工厂的安全/环保无关，应在其进入 AI 判定前过滤。
# 与 extractors.check_industry_relevance 的否定类别保持一致（提示词强化）。
_NON_INDUSTRIAL_KW: list[str] = [
    # 农业/种植/林业
    "种子", "种苗", "菌种", "苗木", "造林", "粮食作物", "农作物", "果蔬", "花卉", "林业",
    # 畜牧/兽医/渔业/水产
    "畜禽", "兽医", "动物检疫", "检疫", "生猪", "羊毛", "山羊绒", "冷冻精液",
    "饲料", "兽药", "养殖", "水产", "渔业",
    # 医疗器械/医用
    "外科植入物", "植入物", "医疗器械", "医用", "齿科", "骨科", "体外诊断", "心血管", "人工器官",
    # 食品/饮料/烟草
    "食品", "饮料", "调味品", "乳制品", "罐头", "烟草",
    # 体育/健身/玩具/文体
    "运动服装", "体育", "健身", "玩具",
    # 养老/民生/社会服务
    "养老机构", "老年人", "社会福利",
    # 核电/军工/交通/水利等非工业安全行业
    "核电厂", "核电站", "核反应堆", "核设施", "核技术利用", "核安全", "研究堆",
    "放射性废物", "低水平放射性", "乏燃料", "铀矿", "军用", "武器", "舰船", "航空", "航天",
    "桥梁", "水利工程", "农业机械",
    # 2026-08-31 扩充：生态环境部环境标准源混入的非工业行业标准
    "船舶", "船用", "海洋", "海上", "锚地", "倾倒", "港口",
    "汽车", "摩托车", "机动车", "轻型汽车", "道路车辆", "车用", "内燃机",
    "转基因", "植物检疫", "植物保护", "野生近缘种", "生物多样性", "外来入侵",
    # 信息化/平台类（与工厂合规无直接关联的标准）
    "信息平台", "接口规范", "系统建设指南",
    # 行政公告类（非法规正文：征集/公示/名单等）
    "公开征求意见", "征求意见", "征集", "公示", "名单", "人选", "遴选",
    # 2026-09-01 扩充：其他行业专属/特定地域/无关检测对象的环境标准
    # （mee_std 等标准源反复混入，标题含"排放标准/污染控制"但与本厂无关）
    "纺织", "印染", "造纸",
    "废弃电器电子产品", "电器电子产品", "废光伏",
    "石油天然气开采", "油气开采", "矿区", "矿山", "矿业",
    "建筑垃圾",
    "微囊藻毒素", "藻毒素", "有机磷农药", "农药残留",
    "红外吸收仪", "pm2.5",
    # 特定流域/库区（本厂不在其流域，出现即拦）
    "赤水河", "丹江口", "太湖", "巢湖", "滇池", "洱海", "抚仙湖",
    "洞庭湖", "鄱阳湖", "三峡库区", "渭河", "松花江", "淮河", "海河", "黄河", "长江流域",
]

# ── 默认数据源列表 ──

DEFAULT_SOURCES: list[RegulationSource] = [
    # ── 国务院政策文件库 JSON API（权威来源，按发布时间排序 + 时间过滤）──
    RegulationSource(
        name="国务院政策文件库",
        base_url="https://sousuo.www.gov.cn/search-gov/data",
        source_type="gov_cn",
        strategy="api",
        puborg_whitelist=[
            # 核心监管机构
            "国务院", "应急", "卫生健康", "生态环境", "市场监管",
            "药监", "住房和城乡", "工业和信息化", "发展改革",
            "人力资源", "全国人大", "国家安全监管",
            # 扩展：标准/认证/运输
            "标准化", "认证认可", "交通运输", "公安部",
        ],
        title_blacklist=[
            "煤矿", "民航", "食品", "教育", "金融", "证券", "保险",
            "邮政", "铁路", "水利", "农业", "体育", "广电", "养老",
            "医疗器械", "驾驶员", "放射性", "粮食", "旅游", "银行",
            "航空", "矿山", "地震", "气象", "森林", "草原",
            "家庭病床", "长期护理", "中药饮片", "电子商务",
            *_NON_INDUSTRIAL_KW,
        ],
        api_params={
            "t": "zhengcelibrary_gw_bm_gb",
            "searchfield": "title:content:summary",
            "sort": "pubtime",
            "sortType": "2",
            "timetype": "timezd",
            "n": "50",
            "q": "安全生产 危险化学品 特种设备 消防 职业病防治 环境保护 排污许可 固废管理 废气治理 废水治理 大气污染 危废 环境影响评价 药品管理 应急预案 管理条例 管理办法 安全规程 技术规范 排放标准 清洁生产",
        },
        lookback_days=180,
        attachment_selector=(
            "a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], "
            "a[href*='附件'], a[href*='下载']"
        ),
        pagination_pattern="https://sousuo.www.gov.cn/search-gov/data?t=zhengcelibrary_gw_bm_gb&searchfield=title:content:summary&sort=pubtime&sortType=2&p={page}&n=50&timetype=timezd&q=安全生产+应急管理+职业健康+消防+危化品+特种设备+环保+药品管理",
        rate_limit_seconds=2.0,
        max_pages=5,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://sousuo.www.gov.cn/",
        },
    ),
    # ── 应急管理部 — 通知公告（按时间倒序，每页 20 条，真正的"最新发布"）──
    RegulationSource(
        name="应急管理部通知公告",
        base_url="https://www.mem.gov.cn/gk/tzgg/",
        source_type="mem",
        strategy="http_parse",
        title_blacklist=[
            "煤矿", "民航", "食品", "教育", "金融", "证券", "保险",
            "邮政", "铁路", "水利", "农业", "体育", "广电", "养老",
            "家庭病床", "中药饮片", "草原", "森林", "地震", "气象",
            *_NON_INDUSTRIAL_KW,
        ],
        # 页面结构：多个 div.cont，每个含 ul > li > a（标题）+ span（日期）
        # <div class="cont"><ul><li><a href="...">TITLE<span>DATE</span></a></li></ul></div>
        list_selector="div.cont ul li",
        title_selector="a",
        date_selector="span",
        detail_link_selector="a",
        attachment_selector="a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], a[href*='附件']",
        max_pages=1,  # 首页 20 条覆盖近期，无需翻页
        rate_limit_seconds=2.0,
    ),
    # ── 应急管理部 — 标准公告（新批准的行业标准）──
    RegulationSource(
        name="应急管理部标准公告",
        base_url="https://www.mem.gov.cn/fw/flfgbz/bz/bzgg/",
        source_type="mem_standards",
        strategy="http_parse",
        title_blacklist=[
            "煤矿", "民航", "食品", "教育", "金融", "证券", "保险",
            "邮政", "铁路", "水利", "农业", "体育", "广电", "养老",
            "家庭病床", "中药饮片", "草原", "森林", "地震", "气象",
            *_NON_INDUSTRIAL_KW,
        ],
        # 页面结构：多个 div.cont，每个含 ul > li > a（标题+日期合并文本，无独立 span）
        # <div class="cont"><ul><li><a href="...">TITLE_TEXT 2026-06-22 09:20</a></li></ul></div>
        # 日期从标题文本末尾提取（_STRIP_TRAILING_DATE_RE 剥离后即为干净标题）
        list_selector="div.cont ul li",
        title_selector="a",
        date_selector="",  # 日期嵌入标题文本末尾，无独立元素
        detail_link_selector="a",
        attachment_selector="a[href$='.pdf'], a[href$='.doc'], a[href$='.docx']",
        max_pages=1,
        rate_limit_seconds=2.0,
    ),
    # ── 国家标准化管理委员会 — 标准全文公开（需 Playwright JS 渲染）──
    RegulationSource(
        name="国家标准全文公开系统",
        base_url="https://openstd.samr.gov.cn/bzgk/gb/std_list",
        source_type="samr",
        strategy="playwright",
        list_selector="tr:has(td:first-child)",
        title_selector="td:nth-child(5)",
        date_selector="td:nth-child(7)",
        detail_link_selector="td:last-child a",
        attachment_selector="",
        title_blacklist=[
            "煤矿", "民航", "食品", "教育", "金融", "证券", "保险",
            "邮政", "铁路", "水利", "农业", "体育", "广电", "养老",
            "粮食", "旅游", "银行", "航空", "矿山", "地震", "气象",
            "森林", "草原",
            *_NON_INDUSTRIAL_KW,
        ],
        search_keywords="安全生产 危险化学品 特种设备 消防 职业健康 防爆 压力容器 锅炉 应急预案 应急救援 防护用品 防尘防毒 电气安全 化学品分类 储存 运输 坠落防护 安全带 安全帽 高处作业 劳动防护 防护装备 气体 粉尘 爆炸 有限空间 动火 吊装 脚手架 机械安全 防雷 防静电 应急照明 疏散 火灾 灭火 危险作业",
        max_pages=5,
        rate_limit_seconds=3.0,
    ),
    # ── 国家卫健委 — 法规文件目录（flfg，带日期；412 反爬由 PlaywrightCrawler 重载处理）──
    RegulationSource(
        name="国家卫健委法规",
        base_url="https://www.nhc.gov.cn/wjw/flfg/list.shtml",
        source_type="nhc",
        strategy="playwright",
        title_blacklist=[
            "煤矿", "民航", "金融", "证券", "保险", "邮政", "铁路",
            "水利", "农业", "体育", "广电",
            "家庭病床", "中药饮片",
            *_NON_INDUSTRIAL_KW,
        ],
        # 页面结构：<ul class="zxxx_list mt20"><li><a title="...">TITLE</a><span class="ml">2023-12-14</span></li>
        list_selector="ul.zxxx_list li",
        title_selector="a",
        date_selector="span.ml",
        detail_link_selector="a",
        attachment_selector="a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], a[href*='附件']",
        max_pages=1,  # 目录页首页 24 条即为最新，无需翻页
        rate_limit_seconds=2.0,
    ),
    # ── 国家药监局 — 药品法规文件（ypfgwj，带日期；412 反爬由 PlaywrightCrawler 重载处理）──
    RegulationSource(
        name="国家药监局法规",
        base_url="https://www.nmpa.gov.cn/yaopin/ypfgwj/index.html",
        source_type="nmpa",
        strategy="playwright",
        title_blacklist=[
            "煤矿", "民航", "金融", "证券", "保险", "邮政", "铁路",
            "水利", "农业", "体育", "广电",
            "家庭病床", "中药饮片",
            *_NON_INDUSTRIAL_KW,
        ],
        # 页面结构：<ul><li><a href="../../xxgk/fgwj/gzwj/gzwjyp/xxx.html">TITLE</a><span>(2026-06-25)</span></li>
        # 直选模式：选择器直接匹配法规 <a>（href 含 gzwjyp），日期从父级 li 的 span 提取
        list_selector="ul li a[href*='gzwjyp']",
        title_selector="",
        date_selector="span",
        detail_link_selector="",
        attachment_selector="a[href$='.pdf'], a[href$='.doc'], a[href$='.docx'], a[href*='附件']",
        max_pages=2,
        rate_limit_seconds=2.0,
    ),
    # ── 生态环境部 — 通知公告（环保法规标准发布，按时间倒序）──
    RegulationSource(
        name="生态环境部通知公告",
        base_url="https://www.mee.gov.cn/ywdt/gsgg/",
        source_type="mee",
        strategy="http_parse",
        title_blacklist=[
            "煤矿", "民航", "金融", "证券", "保险", "邮政", "铁路",
            "水利", "农业", "体育", "广电",
            "家庭病床", "中药饮片", "草原", "森林", "地震", "气象",
            "核安全", "核电", "核设施", "铀矿", "放射性废物",
            "海洋工程", "船舶", "渔业",
            *_NON_INDUSTRIAL_KW,
        ],
        # 第一段：div.mobile_list a[href*='shtml']（EIA公示）
        # 第二段：div.mobile_list a[href*='xxgk']（法规标准公告，.html 后缀）
        list_selector="div.mobile_list a[href*='xxgk'], div.mobile_list a[href*='gsgg']",
        title_selector="",  # 直选模式：选择器直接匹配 <a>
        date_selector="span",
        detail_link_selector="a",
        attachment_selector="a[href$='.pdf'], a[href$='.doc'], a[href$='.docx']",
        max_pages=3,
        rate_limit_seconds=2.0,
    ),
    # ── 生态环境部 — 环境标准文本（bzwb，官方全文 PDF；含 openstd 缺失全文的 GB/HJ 环保标准）──
    RegulationSource(
        name="生态环境部环境标准",
        base_url="https://www.mee.gov.cn/ywgz/fgbz/bz/bzwb/index.shtml",
        source_type="mee_std",
        strategy="http_parse",
        title_blacklist=[
            "煤矿", "矿山", "民航", "金融", "证券", "保险", "邮政", "铁路",
            "体育", "广电", "养老", "烟草",
            *_NON_INDUSTRIAL_KW,
        ],
        # 页面结构：<ul class="bgtIndexUl wbmainUl"><li><a href="...shtml">TITLE</a><span>2026-09-01 实施</span></li>
        list_selector="ul.bgtIndexUl li",
        title_selector="a",
        date_selector="span",
        detail_link_selector="a",
        attachment_selector="a[href$='.pdf'], a[href$='.doc'], a[href$='.docx']",
        max_pages=1,  # 索引页首页即近期标准（按时间倒序）
        rate_limit_seconds=2.0,
    ),
    # ── 全国标准信息公共服务平台 — 国家标准公告 ──
    # ── 全国标准信息公共服务平台 — 安全生产行业标准列表 ──
    RegulationSource(
        name="安全生产行业标准（hbba）",
        base_url="https://hbba.sacinfo.org.cn/stdList?key=&trade=%E5%AE%89%E5%85%A8%E7%94%9F%E4%BA%A7",
        source_type="samr_hbba",
        strategy="samr_list",
        title_blacklist=[
            "煤矿", "矿山", "烟花爆竹", "民用爆炸物品",
            *_NON_INDUSTRIAL_KW,
        ],
        list_selector="",
        detail_link_selector="",
        attachment_selector="",
        max_pages=8,  # 每页100条（脚本切换），8页覆盖~800条（约2年发布窗口）
        rate_limit_seconds=1.5,
    ),
    # ── 全国标准信息公共服务平台 — 强制性国家标准列表 ──
    RegulationSource(
        name="强制性国家标准（openstd）",
        base_url="https://openstd.samr.gov.cn/bzgk/std/std_list_type?p.p1=1&p.p90=circulation_date&p.p91=desc",
        source_type="samr_openstd",
        strategy="samr_list",
        title_blacklist=[
            "煤矿", "矿山", "食品", "航空", "船舶",
            "核安全", "放射性",
            *_NON_INDUSTRIAL_KW,
        ],
        list_selector="",
        detail_link_selector="",
        attachment_selector="",
        max_pages=8,
        rate_limit_seconds=1.5,
    ),
]
