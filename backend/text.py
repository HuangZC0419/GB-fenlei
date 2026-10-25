# -*- coding: utf-8 -*-
"""标准号、标准名称的规范化和中文分词。"""

import re
import unicodedata
from typing import Any, List

CHINESE_RE = re.compile(r"[一-鿿]+")
ASCII_RE = re.compile(r"[a-z][a-z0-9._\-]*")
DASH_RE = re.compile(r"[—–－]")

SINGLE_CHAR_TOKENS = set("钢铝铜钛镁镍锌锡银金")

_NAME_PUNCTUATION_RE = re.compile(
    r"[，,。.;；、:：\-—_/\\()（）\[\]【】<>《》\"'“”‘’]"
)


def to_text(value: Any) -> str:
    """把单元格值安全转成去首尾空格的字符串。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def normalize_name(name: Any) -> str:
    """名称规范化：全半角统一、转小写、去空格与常见标点。"""
    text = unicodedata.normalize("NFKC", to_text(name)).lower()
    text = re.sub(r"\s+", "", text)
    return _NAME_PUNCTUATION_RE.sub("", text)


def normalize_code(code: Any) -> str:
    """标准号规范化：统一前缀写法、两位年份补全、去掉空格和连字符。"""
    text = unicodedata.normalize("NFKC", to_text(code)).upper()
    text = DASH_RE.sub("-", text)
    text = text.replace("／", "/")
    text = re.sub(r"\s+", "", text)
    text = text.replace("GJB/T", "GJBT").replace("GB/T", "GBT")

    match = re.search(r"-(\d{2})$", text)
    if match:
        year = int(match.group(1))
        full_year = 1900 + year if year >= 30 else 2000 + year
        text = text[: match.start()] + "-" + str(full_year)

    return re.sub(r"[-\s]", "", text)


def base_code(code: str) -> str:
    """去掉末尾四位年份，得到标准号主体。"""
    normalized = normalize_code(code)
    return re.sub(r"(?:19|20)\d{2}$", "", normalized)


def tokenize(text: Any) -> List[str]:
    """中文 2~3 元切分 + 金属单字 + 英文/数字 token。"""
    normalized = unicodedata.normalize("NFKC", to_text(text)).lower()
    tokens: List[str] = []

    for chunk in CHINESE_RE.findall(normalized):
        length = len(chunk)
        for index, char in enumerate(chunk):
            if char in SINGLE_CHAR_TOKENS:
                tokens.append(char)
            if index + 2 <= length:
                tokens.append(chunk[index : index + 2])
            if index + 3 <= length:
                tokens.append(chunk[index : index + 3])

    for word in ASCII_RE.findall(normalized):
        if len(word) >= 2 and not word.isdigit():
            tokens.append(word)

    return tokens
