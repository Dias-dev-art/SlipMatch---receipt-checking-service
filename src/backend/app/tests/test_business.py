"""Business settings, payment QR upload, Telegram shop code."""

import pytest
from sqlalchemy import inspect
from sqlmodel import SQLModel

from app.core.config import settings
from app.tests.conftest import auth_headers, register

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


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
    assert body["payment_qr_url"] is None and "whatsapp" not in body
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


def test_shop_code_and_telegram_link(client, owner, other):
    mine = client.get("/api/v1/business", headers=owner).json()
    assert mine["shop_code"] == "kak-ani-kitchen"
    assert mine["telegram_link"] == "https://t.me/TestShopBot?start=kak-ani-kitchen"
    theirs = client.get("/api/v1/business", headers=other).json()
    assert theirs["shop_code"] == "mak-teh-bakery"
    # same shop name again: the code gets a number
    register(client, "ani2@demo.my", "Kak Ani Kitchen")
    again = client.get("/api/v1/auth/me", headers=auth_headers(client, "ani2@demo.my")).json()
    assert again["business"]["shop_code"] == "kak-ani-kitchen-2"


def test_telegram_link_needs_bot_username(client, owner, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_USERNAME", "")
    assert client.get("/api/v1/business", headers=owner).json()["telegram_link"] is None


def test_change_shop_code(client, owner, other):
    url = "/api/v1/business"
    r = client.patch(url, headers=owner, json={"shop_code": "kakani"})
    assert r.status_code == 200 and r.json()["telegram_link"].endswith("?start=kakani")
    assert client.patch(url, headers=other, json={"shop_code": "kakani"}).status_code == 409
    assert client.patch(url, headers=owner, json={"shop_code": "Bad Code!"}).status_code == 422
    assert client.patch(url, headers=owner, json={"shop_code": None}).status_code == 422


def test_whatsapp_and_exclusion_endpoints_are_gone(client, owner):
    assert client.put("/api/v1/business/whatsapp", headers=owner, json={}).status_code in (404, 405)
    assert client.get("/api/v1/business/exclusions", headers=owner).status_code == 404


def test_business_requires_auth(client):
    assert client.get("/api/v1/business").status_code == 401
