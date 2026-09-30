from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres in production; SQLite is supported for local development and tests.
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    secret_key: str = "dev-secret-change-me-dev-secret-change-me"  # >= 32 bytes; set SECRET_KEY in .env
    cookie_secure: bool = False
    session_hours: int = 8

    # Seeded teacher account (password must be changed on first login).
    teacher_username: str = "teacher"
    teacher_password: str = "changeme"

    # "judge0" in production. "local" runs Python in a subprocess with NO sandbox:
    # development only, never expose it to students.
    judge_backend: Literal["judge0", "local"] = "judge0"
    judge0_url: str = "http://judge0-server:2358"
    judge0_auth_token: str = ""
    judge0_rapidapi_key: str = ""
    judge0_rapidapi_host: str = ""
    judge0_python_id: int = 71  # "Python (3.8.1)" on Judge0 CE 1.13.1; check GET /languages
    judge_workers: int = 4

    media_dir: str = "./media"
    cors_origins: list[str] = []
    run_migrations: bool = True
    seed_sample_quiz: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
