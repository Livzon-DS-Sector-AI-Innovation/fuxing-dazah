"""术语表加载与一致性校验。CSV 格式：中文术语,English Term（首行可为表头）。"""
from __future__ import annotations

import csv
from pathlib import Path

_HEADER_HINTS = {"中文", "english", "en", "zh", "原文", "译文", "chinese"}


class Glossary:
    def __init__(self, pairs: list[tuple[str, str]], source: str = ""):
        # 长词优先，提示模型先匹配更具体的术语
        self.pairs = sorted(pairs, key=lambda p: -len(p[0]))
        self.source = source

    def __bool__(self):
        return bool(self.pairs)

    def prompt_lines(self, source_lang: str) -> list[str]:
        """按翻译方向组织提示行：源语言词 → 目标语言固定译法。"""
        if source_lang == "zh":
            return [f"{zh}→{en}" for zh, en in self.pairs]
        return [f"{en}→{zh}" for zh, en in self.pairs]

    def check(self, source_text: str, target_text: str, source_lang: str) -> list[str]:
        """源文含术语而译文未按术语表翻译 → 返回不一致说明（仅作复核提示）。"""
        problems = []
        if source_lang == "zh":
            for zh, en in self.pairs:
                if zh in source_text and en.lower() not in target_text.lower():
                    problems.append(f"术语「{zh}」应译为「{en}」")
        else:
            for zh, en in self.pairs:
                if en.lower() in source_text.lower() and zh not in target_text:
                    problems.append(f"术语「{en}」应译为「{zh}」")
        return problems


def load_glossary(path: str | Path) -> Glossary:
    path = Path(path)
    pairs: list[tuple[str, str]] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if not row or len(row) < 2:
                continue
            zh, en = row[0].strip(), row[1].strip()
            if not zh or not en:
                continue
            if zh.lower() in _HEADER_HINTS or en.lower() in _HEADER_HINTS:
                continue
            pairs.append((zh, en))
    if not pairs:
        raise ValueError(f"术语表 {path} 中未读到有效条目（格式：中文术语,English Term）")
    return Glossary(pairs, source=str(path))
