from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.classroom import Classroom, User
from app.models.knowledge import KnowledgeDocument
from app.schemas.readiness import ReadinessItem, ReadinessResponse

router = APIRouter(prefix="/readiness", tags=["readiness"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.get("/status", response_model=ReadinessResponse)
def readiness_status(db: DatabaseSession) -> ReadinessResponse:
    settings = get_settings()
    db.execute(text("SELECT 1"))
    formal_approved = int(
        db.scalar(
            select(func.count(KnowledgeDocument.id)).where(
                KnowledgeDocument.review_status == "approved",
                KnowledgeDocument.is_test_data.is_(False),
            )
        )
        or 0
    )
    users = int(db.scalar(select(func.count(User.id)).where(User.is_test_data.is_(False))) or 0)
    classes = int(
        db.scalar(select(func.count(Classroom.id)).where(Classroom.is_test_data.is_(False))) or 0
    )
    ai_configured = bool(settings.ai_enabled and settings.ai_api_key)
    software_ready = True
    demo_ready = True
    hardware_ready = False
    knowledge_ready = formal_approved > 0
    organization_ready = users > 0 and classes > 0
    production_ready = software_ready and hardware_ready and knowledge_ready and organization_ready
    items = [
        ReadinessItem(
            key="database",
            label="数据库与迁移",
            status="ready",
            evidence="数据库连接成功；具体迁移 Head 由部署验收命令核查。",
        ),
        ReadinessItem(
            key="device_protocol",
            label="设备协议 V1",
            status="ready",
            evidence="协议、幂等、批量、乱序和时间质量测试已建立。",
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
            status="blocked",
            evidence="仓库中没有真实设备上传数据或正式固件。",
            required_input="硬件型号、传感器、接线/GPIO、电压、字段、单位和采样策略",
        ),
        ReadinessItem(
            key="formal_knowledge",
            label="正式知识",
            status="ready" if knowledge_ready else "blocked",
            evidence=f"已批准非测试文档数：{formal_approved}",
            required_input=None if formal_approved else "可授权资料与双角色审核结论",
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
            status="ready" if organization_ready else "blocked",
            evidence=f"用户数：{users}；班级数：{classes}",
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
