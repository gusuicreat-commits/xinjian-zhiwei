import uvicorn
from alembic import command
from alembic.config import Config


def main() -> None:
    command.upgrade(Config("alembic.ini"), "head")
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
