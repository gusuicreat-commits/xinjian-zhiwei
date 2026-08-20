from pathlib import Path

from app import config


def test_project_env_loader_never_searches_parent(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_load_dotenv(path):
        captured["path"] = Path(path)

    monkeypatch.setattr(config, "load_dotenv", fake_load_dotenv)
    config.load_project_env()
    assert captured["path"] == config.PROJECT_ROOT / ".env"


def test_settings_ignore_generic_parent_database_variable(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://must-not-be-used")
    monkeypatch.delenv("KIP_DATABASE_URL", raising=False)
    assert "knowledge_ingestion" in config.Settings().database_url
