"""config.json 配置加载与校验：所有可配置项集中于此。

优先级：run.py 的 OVERRIDES > config.json > 默认值。
API Key 只从 config.json（或 OVERRIDES）读取，不读环境变量；未配置直接报错。
相对路径一律相对 config.json 所在目录解析，与运行时 CWD 无关。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from pathlib import Path

VALID_MODES = ("bilingual", "replace")
VALID_DIRECTIONS = ("auto", "zh2en", "en2zh")


@dataclass
class Settings:
    input: str                       # 要翻译的 docx / pdf（必填）
    output: str = ""                 # 留空自动按模式命名
    report: str = ""                 # 校验报告路径，留空自动命名
    mode: str = "bilingual"          # bilingual=对照 / replace=替换
    direction: str = "auto"          # auto / zh2en / en2zh
    doc_type: str = "GMP 文件（批记录/工艺验证报告）"
    glossary: str = "glossaries/gmp_glossary.csv"   # 置空字符串禁用
    api_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    model: str = "glm-4.7"
    api_key: str = ""                # 留空则读环境变量
    batch_size: int = 30
    max_retries: int = 3
    concurrency: int = 4             # 并发翻译请求数；限流(429)时调小，1=顺序
    thinking_level: str = ""         # 思考等级 low/high/max；空=服务端默认
    date_format: str = "keep"        # 译文行日期格式 keep/iso/en/zh（仅日期，程序化转换）
    profile_pages: int = 5           # （仅 PDF）翻译前读前 N 页生成领域档案；0=关闭
    pages: str = ""                  # （仅 PDF）只翻指定页 "1-20"/"6"；空=全部
    mock: bool = True


def load_config(config_path, overrides: dict | None = None) -> Settings:
    """读取 config.json，合并 OVERRIDES，校验并解析路径。"""
    p = Path(config_path)
    raw: dict = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if overrides:
        raw.update({k: v for k, v in overrides.items() if v not in (None, "")})

    known = {f.name for f in fields(Settings)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"配置中存在未知字段: {sorted(unknown)}。可用字段：{sorted(known)}")
    if not raw.get("input"):
        raise ValueError("配置中必须设置 input（要翻译的 docx / pdf 文件路径）")

    s = Settings(**raw)

    # JSON 手改常见错误：布尔写成字符串、数字写成字符串
    if not isinstance(s.mock, bool):
        raise ValueError("mock 需要 true / false（布尔值，不要加引号）")
    for int_field in ("batch_size", "max_retries", "concurrency"):
        v = getattr(s, int_field)
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            raise ValueError(f"{int_field} 需要正整数")
    if s.concurrency > 16:
        raise ValueError("concurrency 最大 16（并发过高会被 API 限流）")
    if s.thinking_level not in ("", "low", "high", "max"):
        raise ValueError('thinking_level 只能是 ""（默认）/ "low" / "high" / "max"')
    if s.date_format not in ("keep", "iso", "en", "zh"):
        raise ValueError('date_format 只能是 "keep"（原样）/ "iso" / "en" / "zh"')
    if not isinstance(s.profile_pages, int) or isinstance(s.profile_pages, bool) or not (0 <= s.profile_pages <= 50):
        raise ValueError("profile_pages 需要 0~50 的整数（0=关闭 PDF 领域预读）")
    if s.pages and not re.fullmatch(r"\d+(-\d+)?", s.pages.strip()):
        raise ValueError('pages 只能是页码范围，如 "1-20" 或 "6"；留空=全部页')
    if s.mode not in VALID_MODES:
        raise ValueError(f"mode 只能是 {VALID_MODES}")
    if s.direction not in VALID_DIRECTIONS:
        raise ValueError(f"direction 只能是 {VALID_DIRECTIONS}")

    # 相对路径基于 config.json 所在目录，CWD 无关（VSCode 里怎么运行都一致）
    base = p.resolve().parent
    for attr in ("input", "glossary", "output", "report"):
        v = getattr(s, attr)
        if v and not Path(v).is_absolute():
            setattr(s, attr, str((base / v)))
    return s
