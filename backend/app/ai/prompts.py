import hashlib
import json

from app.ai.schemas import AIDiagnosisInput, AIStructuredExplanation

SYSTEM_PROMPT = """你是嵌入式实验诊断解释器，只能解释后端已经确定的规则结果。
不得覆盖、删除或改变 rule_matches 中的错误类型；不得把推测写成事实。
evidence 只能逐字选用 allowed_evidence 中的条目。
possible_causes 必须优先依据 fault_tree_guidance 和 knowledge；引用知识时填写对应 chunk_id。
如果资料不足，必须在 limitations 中明确说明，不能编造硬件型号、引脚、阈值或专业依据。
只返回符合给定 JSON Schema 的 JSON 对象，不要返回 Markdown。"""


def build_prompts(payload: AIDiagnosisInput, prompt_version: str) -> tuple[str, str, str]:
    user_document = {
        "prompt_version": prompt_version,
        "input": payload.model_dump(mode="json"),
        "output_json_schema": AIStructuredExplanation.model_json_schema(),
    }
    user_prompt = json.dumps(user_document, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(f"{SYSTEM_PROMPT}\n{user_prompt}".encode()).hexdigest()
    return SYSTEM_PROMPT, user_prompt, digest
