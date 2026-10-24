"""Tests run on a real Postgres DB `<DATABASE_URL db>_test`, built by the migrations."""

import os

from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

from app.core.config import settings

_base_url = make_url(os.environ.get("DATABASE_URL", settings.DATABASE_URL))
TEST_DATABASE_URL = _base_url.set(database=f"{_base_url.database}_test")
os.environ["DATABASE_URL"] = TEST_DATABASE_URL.render_as_string(hide_password=False)
settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.ENV = "test"
settings.JWT_SECRET = "test-secret-key-that-is-long-enough-for-hs256"
settings.PUBLIC_BASE_URL = "https://backend.test"
settings.TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
settings.WHATSAPP_APP_SECRET = "test-app-secret"
settings.WHATSAPP_VERIFY_TOKEN = "test-verify-token"

import httpx  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from app.agent.llm import set_llm_client  # noqa: E402
from app.core import db  # noqa: E402
from app.core.db import get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.services.whatsapp import set_transport  # noqa: E402
from app.tests.fake_llm import ScriptedLLM  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _create_test_database() -> None:
    admin = create_engine(_base_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DATABASE_URL.database}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{TEST_DATABASE_URL.database}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine():
    _create_test_database()
    eng = create_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL.render_as_string(hide_password=False)
    command.upgrade(cfg, "head")
    db.engine = eng
    yield eng
    eng.dispose()


@pytest.fixture(autouse=True)
def clean_tables(engine):
    yield
    tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture(autouse=True)
def llm():
    """Every test gets a scripted LLM; the real endpoint is never called from tests."""
    fake = ScriptedLLM()
    set_llm_client(fake)
    yield fake
    set_llm_client(None)


@pytest.fixture(autouse=True)
def no_real_whatsapp():
    """Graph API calls fail loudly unless a test installs its own fake transport."""

    def refuse(request):
        raise AssertionError(f"unexpected call to {request.url}")

    set_transport(httpx.MockTransport(refuse))
    yield
    set_transport(None)


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def client(engine):
    def _session():
        with Session(engine) as s:
            yield s

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def register(client: TestClient, email: str, business: str = "Kak Ani Kitchen") -> dict:
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "secret123",
            "full_name": "Ani",
            "business_name": business,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def auth_headers(client: TestClient, email: str, password: str = "secret123") -> dict[str, str]:
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
