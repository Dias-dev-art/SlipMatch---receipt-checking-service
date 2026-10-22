import pytest
from sqlmodel import Session

from app.seed import MENU, seed
from app.services.menu import slugify
from app.tests.conftest import auth_headers, register


@pytest.fixture
def owner(client):
    register(client, "ani@demo.my", "Kak Ani Kitchen")
    return auth_headers(client, "ani@demo.my")


@pytest.fixture
def other(client):
    register(client, "teh@demo.my", "Mak Teh Bakery")
    return auth_headers(client, "teh@demo.my")


def create(client, headers, **overrides):
    body = {"name": "Mee Goreng", "price": "7.00", "description": "Chicken, egg", "tags": []}
    r = client.post("/api/v1/menu", headers=headers, json=body | overrides)
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Mee Goreng", "mee_goreng"),
        ("  Nasi  Lemak (Special)! ", "nasi_lemak_special"),
        ("Kuih Café", "kuih_cafe"),
        ("!!!", "item"),
    ],
)
def test_slugify(name, slug):
    assert slugify(name) == slug


def test_create_and_list(client, owner):
    item = create(client, owner, tags=["Spicy", " halal ", "spicy"], category="Noodles")
    assert item["slug"] == "mee_goreng"
    assert item["price"] == "7.00"
    assert item["tags"] == ["spicy", "halal"]
    assert item["is_available"] is True
    create(client, owner, name="Teh Tarik", price="3")
    items = client.get("/api/v1/menu", headers=owner).json()
    assert [i["slug"] for i in items] == ["mee_goreng", "teh_tarik"]
    assert [i["sort_order"] for i in items] == [1, 2]


def test_same_name_gets_unique_slug(client, owner):
    assert create(client, owner)["slug"] == "mee_goreng"
    assert create(client, owner)["slug"] == "mee_goreng_2"
    assert create(client, owner)["slug"] == "mee_goreng_3"


def test_same_slug_allowed_in_other_business(client, owner, other):
    assert create(client, owner)["slug"] == "mee_goreng"
    assert create(client, other)["slug"] == "mee_goreng"


@pytest.mark.parametrize(
    "body",
    [
        {"name": "", "price": "7.00"},
        {"name": "X", "price": "0"},
        {"name": "X", "price": "-1"},
        {"name": "X", "price": "7.005"},
        {"name": "X"},
    ],
)
def test_create_validation(client, owner, body):
    assert client.post("/api/v1/menu", headers=owner, json=body).status_code == 422


def test_update_keeps_slug(client, owner):
    item = create(client, owner)
    r = client.patch(
        f"/api/v1/menu/{item['id']}",
        headers=owner,
        json={"name": "Mee Goreng Mamak", "price": "8.50"},
    )
    assert r.status_code == 200
    assert r.json()["name"] == "Mee Goreng Mamak"
    assert r.json()["price"] == "8.50"
    assert r.json()["slug"] == "mee_goreng"


def test_update_rejects_slug_and_nulls(client, owner):
    item = create(client, owner)
    url = f"/api/v1/menu/{item['id']}"
    assert client.patch(url, headers=owner, json={"slug": "x"}).status_code == 422
    assert client.patch(url, headers=owner, json={"price": None}).status_code == 422
    assert client.patch(url, headers=owner, json={"category": None}).status_code == 200


def test_availability_toggle(client, owner):
    item = create(client, owner)
    url = f"/api/v1/menu/{item['id']}/availability"
    assert (
        client.patch(url, headers=owner, json={"is_available": False}).json()["is_available"]
        is False
    )
    assert client.get("/api/v1/menu", headers=owner).json()[0]["is_available"] is False


def test_delete(client, owner):
    item = create(client, owner)
    assert client.delete(f"/api/v1/menu/{item['id']}", headers=owner).status_code == 204
    assert client.get("/api/v1/menu", headers=owner).json() == []
    assert client.delete(f"/api/v1/menu/{item['id']}", headers=owner).status_code == 404


def test_owner_cannot_touch_other_business_menu(client, owner, other):
    item = create(client, owner)
    base = f"/api/v1/menu/{item['id']}"
    assert client.get("/api/v1/menu", headers=other).json() == []
    assert client.patch(base, headers=other, json={"price": "1.00"}).status_code == 404
    r = client.patch(f"{base}/availability", headers=other, json={"is_available": False})
    assert r.status_code == 404
    assert client.delete(base, headers=other).status_code == 404
    assert client.get("/api/v1/menu", headers=owner).json()[0]["price"] == "7.00"


def test_menu_requires_auth(client):
    assert client.get("/api/v1/menu").status_code == 401


def test_seed_is_idempotent(engine):
    with Session(engine) as s:
        seed(s)
        seed(s)
    with Session(engine) as s:
        from sqlmodel import select

        from app.models import MenuItem

        items = s.exec(select(MenuItem)).all()
    assert sorted(i.slug for i in items) == sorted(m[0] for m in MENU)
    prices = {i.slug: str(i.price) for i in items}
    assert prices == {
        "nasi_lemak": "8.00",
        "mee_goreng": "7.00",
        "roti_canai": "2.00",
        "teh_tarik": "3.00",
    }
