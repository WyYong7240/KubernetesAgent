from app.core.config import Settings


def test_dotenv_is_read_independent_of_working_directory(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=development\n"
        "DATABASE_URL=postgresql+asyncpg://file-user:pass@localhost/file-db\n"
        "DAGGER_WEBHOOK_SECRET=file-secret\n",
        encoding="utf-8",
    )
    for key in ("APP_ENV", "DATABASE_URL", "DAGGER_WEBHOOK_SECRET"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path.parent)

    settings = Settings.from_environment(env_file)
    assert settings.database_url.endswith("/file-db")
    assert settings.dagger_webhook_secret == "file-secret"

    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://override/db")
    monkeypatch.setenv("DAGGER_WEBHOOK_SECRET", "")
    overridden = Settings.from_environment(env_file)
    assert overridden.database_url == "postgresql+asyncpg://override/db"
    assert overridden.dagger_webhook_secret is None
