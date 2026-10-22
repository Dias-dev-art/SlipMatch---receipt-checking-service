"""Business settings, payment QR upload, WhatsApp connection, exclusion list."""

import pytest
from sqlalchemy import inspect
from sqlmodel import SQLModel, select

from app.core.config import settings
from app.core.security import decrypt_token
from app.models import WhatsAppAccount
from app.tests.conftest import auth_headers, register

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WHATSAPP = {
    "phone_number_id": "123456789012345",
    "display_phone": "+60 12-345 6789",
    "access_token": "EAAG-secret-token-value",
}


@pytest.fixture
def owner(client):
    register(client, "ani@demo.my")
    return auth_headers(client, "ani@demo.my")


@pytest.fixture
def other(client):
    register(client, "teh@demo.my", "Mak Teh Bakery")
    return auth_headers(client, "teh@demo.my")


def test_migrations_match_models_for_every_table(engine):
    inspector = inspect(engine)
    for table in SQLModel.metadata.sorted_tables:
        columns = {c["name"] for c in inspector.get_columns(table.name)}
        assert columns == set(table.columns.keys()), table.name


def test_get_business_defaults(client, owner):
    body = client.get("/api/v1/business", headers=owner).json()
    assert body["name"] == "Kak Ani Kitchen"
    assert body["payment_qr_url"] is None and body["whatsapp"] is None
    assert body["pickup_enabled"] is True and body["delivery_fee"] == "0.00"


def test_patch_business(client, owner):
    r = client.patch(
        "/api/v1/business",
        headers=owner,
        json={
            "delivery_enabled": True,
            "delivery_fee": "3.50",
            "payment_instructions": "DuitNow 0123",
            "payment_timeout_minutes": 15,
            "greeting": "  Salam!  ",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["delivery_fee"] == "3.50" and body["payment_timeout_minutes"] == 15
    assert body["greeting"] == "Salam!"
    assert (
        client.patch("/api/v1/business", headers=owner, json={"greeting": ""}).json()["greeting"]
        is None
    )
    # /auth/me shows the same business
    assert client.get("/api/v1/auth/me", headers=owner).json()["business"]["delivery_fee"] == (
        "3.50"
    )


@pytest.mark.parametrize(
    "body",
    [
        {"delivery_fee": "-1"},
        {"payment_timeout_minutes": 0},
        {"name": None},
        {"name": ""},
        {"slug": "x"},
        {"pickup_enabled": False},  # delivery is off by default: nothing left to offer
    ],
)
def test_patch_business_validation(client, owner, body):
    assert client.patch("/api/v1/business", headers=owner, json=body).status_code == 422
    assert client.get("/api/v1/business", headers=owner).json()["pickup_enabled"] is True


def test_upload_payment_qr_is_served_publicly(client, owner):
    r = client.post(
        "/api/v1/business/payment-qr",
        headers=owner,
        files={"file": ("qr.png", PNG, "image/png")},
    )
    assert r.status_code == 200, r.text
    url = r.json()["payment_qr_url"]
    assert url.startswith(f"{settings.PUBLIC_BASE_URL}/media/") and url.endswith(".png")
    served = client.get(url.removeprefix(settings.PUBLIC_BASE_URL))
    assert served.status_code == 200 and served.content == PNG


def test_upload_payment_qr_rejects_bad_files(client, owner):
    url = "/api/v1/business/payment-qr"
    r = client.post(url, headers=owner, files={"file": ("qr.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 415
    big = b"\x00" * (2 * 1024 * 1024 + 1)
    r = client.post(url, headers=owner, files={"file": ("qr.png", big, "image/png")})
    assert r.status_code == 413


def test_connect_whatsapp_never_returns_token(client, owner, session):
    r = client.put("/api/v1/business/whatsapp", headers=owner, json=WHATSAPP)
    assert r.status_code == 200, r.text
    assert r.json()["whatsapp"] == {
        "phone_number_id": "123456789012345",
        "display_phone": "+60 12-345 6789",
        "coexistence": False,
    }
    assert "EAAG" not in r.text
    assert "EAAG" not in client.get("/api/v1/auth/me", headers=owner).text
    account = session.exec(select(WhatsAppAccount)).one()
    assert account.access_token_encrypted != WHATSAPP["access_token"]
    assert decrypt_token(account.access_token_encrypted) == WHATSAPP["access_token"]
    # reconnecting replaces it
    client.put("/api/v1/business/whatsapp", headers=owner, json=WHATSAPP | {"coexistence": True})
    session.expire_all()
    assert session.exec(select(WhatsAppAccount)).one().coexistence is True


def test_same_number_cannot_join_two_businesses(client, owner, other):
    assert client.put("/api/v1/business/whatsapp", headers=owner, json=WHATSAPP).status_code == 200
    r = client.put("/api/v1/business/whatsapp", headers=other, json=WHATSAPP)
    assert r.status_code == 409


def test_connect_whatsapp_without_encryption_key(client, owner, monkeypatch):
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", "")
    assert client.put("/api/v1/business/whatsapp", headers=owner, json=WHATSAPP).status_code == 503


def test_exclusions_crud(client, owner):
    url = "/api/v1/business/exclusions"
    r = client.post(url, headers=owner, json={"wa_phone": "+60 12-111 2222", "label": " Mum "})
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["wa_phone"] == "60121112222" and created["label"] == "Mum"
    assert client.post(url, headers=owner, json={"wa_phone": "60121112222"}).status_code == 409
    assert client.post(url, headers=owner, json={"wa_phone": "12"}).status_code == 422
    assert [e["id"] for e in client.get(url, headers=owner).json()] == [created["id"]]
    assert client.delete(f"{url}/{created['id']}", headers=owner).status_code == 204
    assert client.get(url, headers=owner).json() == []


def test_exclusions_are_per_business(client, owner, other):
    url = "/api/v1/business/exclusions"
    mine = client.post(url, headers=owner, json={"wa_phone": "60121112222"}).json()
    assert client.get(url, headers=other).json() == []
    assert client.delete(f"{url}/{mine['id']}", headers=other).status_code == 404
    # the same number may be excluded by another business
    assert client.post(url, headers=other, json={"wa_phone": "60121112222"}).status_code == 201


def test_business_requires_auth(client):
    assert client.get("/api/v1/business").status_code == 401
    assert client.get("/api/v1/business/exclusions").status_code == 401
