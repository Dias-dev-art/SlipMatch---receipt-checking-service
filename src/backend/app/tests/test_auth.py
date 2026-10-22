import uuid

from sqlalchemy import inspect

from app.models import Business, Owner
from app.tests.conftest import auth_headers, register


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_migrations_match_models(engine):
    columns = {c["name"] for c in inspect(engine).get_columns("businesses")}
    assert columns == set(Business.model_fields)
    columns = {c["name"] for c in inspect(engine).get_columns("owners")}
    assert columns == set(Owner.model_fields)


def test_register_creates_owner_and_business(client, session):
    body = register(client, "Ani@Demo.my")
    assert body["owner"]["email"] == "ani@demo.my"
    assert body["business"]["name"] == "Kak Ani Kitchen"
    assert body["business"]["payment_timeout_minutes"] == 10
    assert "hashed_password" not in body["owner"]
    owner = session.get(Owner, uuid.UUID(body["owner"]["id"]))
    assert owner.hashed_password.startswith("$argon2")


def test_register_duplicate_email(client):
    register(client, "ani@demo.my")
    r = client.post(
        "/api/v1/auth/register",
        json={
            "email": "ANI@demo.my",
            "password": "secret123",
            "full_name": "X",
            "business_name": "Y",
        },
    )
    assert r.status_code == 409


def test_register_validates_input(client):
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "short", "full_name": "", "business_name": ""},
    )
    assert r.status_code == 422


def test_login_and_me(client):
    register(client, "ani@demo.my")
    headers = auth_headers(client, "ani@demo.my")
    me = client.get("/api/v1/auth/me", headers=headers).json()
    assert me["owner"]["email"] == "ani@demo.my"
    assert me["business"]["name"] == "Kak Ani Kitchen"


def test_login_wrong_password(client):
    register(client, "ani@demo.my")
    r = client.post("/api/v1/auth/login", data={"username": "ani@demo.my", "password": "nope1234"})
    assert r.status_code == 400


def test_me_requires_valid_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_each_owner_sees_only_own_business(client):
    a = register(client, "a@demo.my", "Kak Ani Kitchen")
    b = register(client, "b@demo.my", "Mak Teh Bakery")
    me_a = client.get("/api/v1/auth/me", headers=auth_headers(client, "a@demo.my")).json()
    me_b = client.get("/api/v1/auth/me", headers=auth_headers(client, "b@demo.my")).json()
    assert me_a["business"]["id"] == a["business"]["id"]
    assert me_b["business"]["id"] == b["business"]["id"]
    assert me_a["business"]["id"] != me_b["business"]["id"]


def test_inactive_owner_rejected(client, session):
    body = register(client, "ani@demo.my")
    headers = auth_headers(client, "ani@demo.my")
    owner = session.get(Owner, uuid.UUID(body["owner"]["id"]))
    owner.is_active = False
    session.add(owner)
    session.commit()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
