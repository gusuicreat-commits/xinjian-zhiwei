"""Strict parser for the three lines emitted by the current SHT31 firmware."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
_READING = re.compile(rf"^温度:\s*({_NUMBER})\s*℃\s*\|\s*湿度:\s*({_NUMBER})\s*%RH$")
_BOOT = "SHT31 传感器启动!"
_FAILURE = "读取失败！检查接线或者把地址改成0x45"


@dataclass(frozen=True)
class ParsedLine:
    kind: str
    text: str
    temperature: Optional[float] = None
    humidity: Optional[float] = None


def parse_line(raw_line: str) -> Optional[ParsedLine]:
    """Parse one complete decoded serial line; unknown text returns ``None``."""
    text = raw_line.rstrip("\r\n").strip()
    if text == _BOOT:
        return ParsedLine("boot", text)
    if text == _FAILURE:
        return ParsedLine("failure", text)
    match = _READING.fullmatch(text)
    if not match:
        return None
    temperature = float(match.group(1))
    humidity = float(match.group(2))
    if not (math.isfinite(temperature) and math.isfinite(humidity)):
        return None
    return ParsedLine("reading", text, temperature, humidity)
