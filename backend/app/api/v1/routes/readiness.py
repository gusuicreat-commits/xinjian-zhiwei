from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.classroom import Classroom, User
from app.models.experiment import Experiment, ExperimentVersion
from app.models.knowledge import KnowledgeCase
from app.schemas.readiness import ReadinessItem, ReadinessResponse
from app.services.experiment_packages import (
    ExperimentPackageLoadError,
    load_experiment_package_runtime,
)

router = APIRouter(prefix="/readiness", tags=["readiness"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("/status", response_model=ReadinessResponse)
def readiness_status(db: DatabaseSession) -> ReadinessResponse:
    settings = get_settings()
    db.execute(text("SELECT 1"))
    formal_cases = int(
        db.scalar(
            select(func.count(KnowledgeCase.id)).where(
                KnowledgeCase.review_status == "approved",
                KnowledgeCase.root_cause_status == "confirmed",
                KnowledgeCase.facts_locked.is_(True),
                KnowledgeCase.quality_check_passed.is_(True),
                KnowledgeCase.is_test_data.is_(False),
            )
        )
        or 0
    )
    packages = []
    invalid_packages = 0
    for version in db.scalars(
        select(ExperimentVersion)
        .join(Experiment)
        .where(
            ExperimentVersion.status == "published",
            ExperimentVersion.is_test_data.is_(False),
            Experiment.status == "active",
            Experiment.is_test_data.is_(False),
        )
    ).all():
        try:
            runtime = load_experiment_package_runtime(db, version.id)
        except ExperimentPackageLoadError:
            invalid_packages += 1
            continue
        eligible = sum(
            case.review_status == "approved"
            and case.root_cause_status == "confirmed"
            and case.facts_locked
            and case.quality_check_passed
            and not case.is_test_data
            for case in runtime.bundle.cases.cases
        )
        packages.append(f"{runtime.experiment.code}@{version.version}：{eligible} 个合格案例")
    users = int(
        db.scalar(
            select(func.count(User.id)).where(
                User.is_test_data.is_(False), User.is_active.is_(True)
            )
        )
        or 0
    )
    classes = int(
        db.scalar(
            select(func.count(Classroom.id)).where(
                Classroom.is_test_data.is_(False), Classroom.is_active.is_(True)
            )
        )
        or 0
    )
    ai_configured = bool(settings.ai_enabled and settings.ai_api_key)
    # Runtime presence is not release acceptance; no signed acceptance source exists yet.
    software_ready = False
    demo_ready = False
    hardware_ready = False
    knowledge_ready = bool(packages)
    organization_ready = False  # Counts alone do not prove classroom bindings are complete.
    production_ready = False
    items = [
        ReadinessItem(
            key="database",
            label="数据库连接",
            status="ready",
            evidence="数据库连接成功；具体迁移 Head 由部署验收命令核查。",
        ),
        ReadinessItem(
            key="device_protocol",
            label="设备协议 V1",
            status="unverified",
            evidence="已有协议实现和测试；此接口不读取当前构建的验收报告，软件和演示验收待核实。",
        ),
        ReadinessItem(
            key="virtual_lab",
            label="虚拟实验室",
            status="test_only",
            evidence="十个版本化合成场景可用，只产生测试数据。",
        ),
        ReadinessItem(
            key="real_hardware",
            label="真实硬件接入",
            status="unverified",
            evidence="已有固件候选；此接口没有可核验的实物验收记录，不能由上传数据推断硬件通过。",
            required_input="硬件型号、传感器、接线/GPIO、电压、字段、单位和采样策略",
        ),
        ReadinessItem(
            key="formal_knowledge",
            label="可加载的正式实验资料包",
            status="ready" if knowledge_ready else "blocked",
            evidence=f"可加载非测试发布包：{len(packages)}；加载失败：{invalid_packages}。"
            + "；".join(packages),
            required_input=None if packages else "与教学任务相匹配、经过审核并发布的非测试资料包",
        ),
        ReadinessItem(
            key="formal_cases",
            label="兼容知识库正式案例",
            status="ready" if formal_cases else "not_required",
            evidence=f"满足审核、根因确认、事实锁定及质量检查的非测试案例：{formal_cases}。匹配仍需校验实验及异常类型；不要求每包都有真实案例。",
        ),
        ReadinessItem(
            key="ai",
            label="AI 增强",
            status="ready" if ai_configured else "not_required",
            evidence=(
                "AI 已启用且服务端密钥存在。"
                if ai_configured
                else "AI 默认关闭；确定性诊断不依赖 AI。"
            ),
        ),
        ReadinessItem(
            key="classroom_data",
            label="课堂身份数据",
            status="unverified",
            evidence=f"有效非测试用户数：{users}；有效非测试班级数：{classes}；任务和绑定完整性待验收。",
            required_input=None if users and classes else "正式用户、课程、班级与绑定清单",
        ),
        ReadinessItem(
            key="production",
            label="生产部署",
            status="blocked",
            evidence="本路线未执行云部署，也未确认生产网络、域名、备份责任和保留策略。",
            required_input="生产网络、安全、备份、监控、验收指标与责任人确认",
        ),
    ]
    blocking = any(item.status == "blocked" for item in items)
    return ReadinessResponse(
        overall="blocked" if blocking else "ready",
        version=settings.app_version,
        software_ready=software_ready,
        demo_ready=demo_ready,
        hardware_ready=hardware_ready,
        knowledge_ready=knowledge_ready,
        organization_ready=organization_ready,
        production_ready=production_ready,
        items=items,
    )
