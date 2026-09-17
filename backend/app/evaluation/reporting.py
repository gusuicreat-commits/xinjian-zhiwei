"""Small human/machine summaries with separate, optional diagnostic artifacts."""

import gzip
import json
from collections import Counter
from pathlib import Path


def write_workflow_report(report: dict, output: Path, *, details: str = "failures") -> Path:
    if details not in {"failures", "all", "none"}:
        raise ValueError("invalid detail policy")
    output.parent.mkdir(parents=True, exist_ok=True)
    detail_path = output.with_suffix(".details.json.gz")
    summary_path = output.with_suffix(".md")
    selected = (
        [
            case
            for case in report["cases"]
            if details == "all" or (details == "failures" and case["status"] in {"failed", "error"})
        ]
        if details != "none"
        else []
    )
    compact = {key: value for key, value in report.items() if key != "cases"}
    compact.update(
        report_format="workflow-summary-v1",
        detail_policy=details,
        detail_artifact=detail_path.name if selected else None,
        cases=[],
    )
    for case in report["cases"]:
        item = {key: case[key] for key in ("id", "status", "reason", "error_type") if key in case}
        item["check_counts"] = dict(Counter(check["status"] for check in case.get("checks", [])))
        item["failed_requirements"] = [
            check["requirement"] for check in case.get("checks", []) if check["status"] != "passed"
        ]
        compact["cases"].append(item)
    if selected:
        artifact = {key: value for key, value in report.items() if key != "cases"}
        artifact["cases"] = selected
        with gzip.open(detail_path, "wt", encoding="utf-8") as handle:
            json.dump(artifact, handle, ensure_ascii=False, separators=(",", ":"))
    elif detail_path.exists():
        # Only this output's generated attachment; never delete sibling reports.
        detail_path.unlink()
    output.write_text(json.dumps(compact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path.write_text(render_summary(compact), encoding="utf-8")
    return summary_path


def render_summary(report: dict) -> str:
    titles = {
        "dht-missing": "DHT11 缺少读数",
        "led-legacy": "LED 旧 level 语义",
        "led-command": "LED 命令状态边界",
        "dht-ambiguous": "DHT11 故障原因不明确",
        "dht-valid": "DHT11 有效诊断流程",
        "dht-foreign_evidence": "拒绝其他诊断的证据",
        "dht-invalid_json": "模型返回无效 JSON",
        "dht-timeout": "模型超时降级",
        "dht-candidate-linkage": "候选与证据关联",
        "feedback-roundtrip": "学生反馈完整往返",
        "duplicate-feedback": "重复反馈幂等",
        "teacher-roundtrip": "教师审核完整往返",
        "foreign-session-read": "阻止跨会话读取",
        "foreign-session-feedback": "阻止跨会话反馈",
        "foreign-package-version": "阻止错误实验包版本",
        "postgres-restart": "数据库连接重建后恢复",
        "feedback-conflict-action": "重复请求动作冲突",
        "feedback-conflict-note": "重复请求说明冲突",
        "feedback-new-attempt": "新一轮反馈",
        "feedback-missing-session": "反馈缺少会话",
        "feedback-missing-request-id": "反馈缺少请求编号",
        "feedback-invalid-request-id": "反馈请求编号无效",
        "foreign-session-feedback-replay": "跨会话重放反馈",
        "postgres-restart-replay": "重建连接后重放反馈",
        "dht-unrelated-evidence": "拒绝无关证据",
    }
    labels = {
        "passed": "通过",
        "failed": "失败",
        "error": "执行错误",
        "not_run": "未执行",
        "blocked": "受阻",
        "incomplete": "未完成",
    }

    def cell(value):
        return str(value).replace("\n", " ").replace("|", "\\|")

    counts = Counter(case["status"] for case in report["cases"])
    lines = [
        "# 流程测试摘要",
        "",
        f"- 软件检查：{labels.get(report['status'], report['status'])}",
        f"- 场景：{len(report['cases'])}；通过 {counts['passed']}；失败/错误 "
        f"{counts['failed'] + counts['error']}；未执行 {counts['not_run']}",
        f"- 执行时间：{report.get('created_at', '未开始')}",
        f"- 环境：{report.get('database', '未启动')}",
        f"- 代码版本：{report.get('git_commit', '未记录')}；"
        f"工作区有未提交内容：{report.get('worktree_dirty', '未记录')}",
        "- 范围：合成数据的软件流程检查，不代表真实硬件、教师确认或 AI 语义验收。",
        "",
    ]
    if report.get("reason"):
        lines += [f"受阻原因：{cell(report['reason'])}", ""]
    lines += ["| 场景 | 结果 | 失败项或未执行原因 |", "| --- | --- | --- |"]
    for case in report["cases"]:
        reason = (
            ", ".join(case["failed_requirements"])
            or case.get("reason")
            or case.get("error_type")
            or "—"
        )
        lines.append(
            f"| {cell(titles.get(case['id'], case['id']))} | "
            f"{labels.get(case['status'], case['status'])} | "
            f"{cell(reason)} |"
        )
    lines += [
        "",
        "下一步："
        + (
            "处理失败或未执行项后重测。"
            if report["status"] != "passed"
            else "软件检查已通过；硬件验证和独立语义审阅仍需另行完成。"
        ),
    ]
    if report.get("detail_artifact"):
        lines += ["", f"排错附件：[{report['detail_artifact']}]({report['detail_artifact']})"]
    else:
        lines += ["", "本次未保存完整轨迹；简明 JSON 保留源码指纹及逐场景结果。"]
    return "\n".join(lines) + "\n"
