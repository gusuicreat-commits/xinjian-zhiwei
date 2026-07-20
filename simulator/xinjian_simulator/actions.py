from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class UploadAction:
    kind: Literal["log", "reading", "heartbeat"]
    payload: dict[str, Any]
