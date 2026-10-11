from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres in production; SQLite is supported for local development and tests.
    database_url: str = "sqlite+aiosqlite:///./dev.db"
    secret_key: str = "dev-secret-change-me-dev-secret-change-me"  # >= 32 bytes; set SECRET_KEY in .env
    cookie_secure: bool = False
    session_hours: int = 8

    # Seeded admin account (password must be changed on first login). The old TEACHER_* names still work.
    admin_username: str = Field("admin", validation_alias=AliasChoices("admin_username", "teacher_username"))
    admin_password: str = Field("changeme", validation_alias=AliasChoices("admin_password", "teacher_password"))

    # "judge0" in production. "local" runs Python in a subprocess with NO sandbox:
    # development only, never expose it to students.
    judge_backend: Literal["judge0", "local"] = "judge0"
    judge0_url: str = "http://judge0-server:2358"
    judge0_auth_token: str = ""
    judge0_rapidapi_key: str = ""
    judge0_rapidapi_host: str = ""
    judge0_python_id: int = 71  # "Python (3.8.1)" on Judge0 CE 1.13.1; check GET /languages
    judge_workers: int = 4
    # Run all of a submission's tests in one Judge0 submission (far less Judge0 overhead).
    judge0_pack_tests: bool = True

    # Problem of the week entries need an email at exactly this domain. Empty = any.
    school_email_domain: str = "stpaulsschool.org.uk"
    contact_email: str = "carriem@stpaulsschool.org.uk"  # shown when someone can't enter

    # Replying to people who submit problems. Empty SMTP_HOST = not set up: the admin's own
    # mail app opens instead (mailto). For Gmail: smtp.gmail.com, 587, the address, an App Password.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""  # defaults to smtp_username
    smtp_from_name: str = "CompSoc"
    smtp_ssl: bool = False  # True for port 465; otherwise STARTTLS

    media_dir: str = "./media"
    cors_origins: list[str] = []
    run_migrations: bool = True
    seed_sample_quiz: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
