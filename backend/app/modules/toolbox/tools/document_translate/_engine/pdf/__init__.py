"""PDF 大型法规文档翻译子包：结构化抽取 → 领域预读 → 复用主流水线翻译 → 重排式 DOCX 输出。"""

import re

# XML 1.0 不允许的字符：部分 PDF 内嵌字体的 ToUnicode 破损，连字 fi/fl/ffi 被映射成
# 0x01~0x04 等控制码。抽取层统一清洗为 U+FFFD（保留"此处丢字"信号，译文阶段由模型
# 按上下文还原），生成端仍用它做终局守卫，防未来路径漏网被 lxml 拒绝。
XML_BAD_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffe\uffff]")
