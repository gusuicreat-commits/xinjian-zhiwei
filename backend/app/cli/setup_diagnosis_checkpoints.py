"""Create or upgrade LangGraph checkpoint tables as an explicit deployment step."""

from langgraph.checkpoint.postgres import PostgresSaver

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    if settings.diagnosis_checkpoint_backend != "postgres":
        raise SystemExit("DIAGNOSIS_CHECKPOINT_BACKEND must be postgres")
    if not settings.diagnosis_checkpoint_dsn:
        raise SystemExit("DIAGNOSIS_CHECKPOINT_DSN is required")
    with PostgresSaver.from_conn_string(settings.diagnosis_checkpoint_dsn) as saver:
        saver.setup()
    print("LangGraph checkpoint schema is ready")


if __name__ == "__main__":
    main()
