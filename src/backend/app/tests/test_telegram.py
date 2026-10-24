"""Telegram webhook end to end with a fake Bot API and a scripted LLM (no network)."""

import json
from datetime import timedelta

import httpx
import pytest
from sqlmodel import select

from app.core.config import settings
from app.models import (
    Business,
    Conversation,
    Customer,
    Message,
    Order,
    ProcessedWebhook,
    TelegramChat,
)
from app.models.base import utcnow
from app.services import templates, timers
from app.telegram import parser, setup
from app.telegram.client import set_transport
from app.tests.conftest import auth_headers, register
from app.tests.fake_llm import call, say, tools

TOKEN = "123456:test-bot-token"
CHAT = 987654321
IMAGE = b"\xff\xd8\xff\xe0" + b"\x00" * 64  # jpeg-ish bytes
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class FakeBotAPI:
    """Records Bot API calls and serves one downloadable photo."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | bytes]] = []
        self.fail: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.startswith(f"/file/bot{TOKEN}/"):
            return httpx.Response(200, content=IMAGE)
        assert path.startswith(f"/bot{TOKEN}/"), path
        method = path.rsplit("/", 1)[-1]
        is_json = request.headers.get("content-type", "").startswith("application/json")
        self.calls.append((method, json.loads(request.content) if is_json else request.content))
        if method in self.fail:
            return httpx.Response(403, json={"ok": False, "description": "bot was blocked"})
        if method == "getFile":
            result = {"file_id": "photo-big", "file_path": "photos/file_1.jpg", "file_size": 68}
            return httpx.Response(200, json={"ok": True, "result": result})
        if method in ("sendMessage", "sendPhoto"):
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        return httpx.Response(200, json={"ok": True, "result": True})

    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]

    def texts(self) -> list[str]:
        return [body["text"] for m, body in self.calls if m == "sendMessage"]

    def photos(self) -> list[bytes]:
        return [body for m, body in self.calls if m == "sendPhoto"]


@pytest.fixture
def bot_api(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", TOKEN)
    fake = FakeBotAPI()
    set_transport(httpx.MockTransport(fake))
    return fake


@pytest.fixture
def owner(client):
    register(client, "ani@demo.my")
    headers = auth_headers(client, "ani@demo.my")
    client.post("/api/v1/menu", headers=headers, json={"name": "Nasi Lemak", "price": "8.00"})
    return headers


_next_update = iter(range(1, 10_000))


def update(message: dict, *, update_id: int | None = None, chat: int = CHAT) -> dict:
    uid = update_id if update_id is not None else next(_next_update)
    return {
        "update_id": uid,
        "message": {
            "message_id": 100 + uid,
            "date": 1760000000,
            "chat": {"id": chat, "type": "private", "first_name": "Ali"},
            "from": {
                "id": chat,
                "is_bot": False,
                "first_name": "Ali",
                "last_name": "Bakar",
                "username": "ali_b",
            },
            **message,
        },
    }


def text(body: str, **kw) -> dict:
    return update({"text": body}, **kw)


def post(client, payload: dict, *, secret: str | None = None):
    headers = {"X-Telegram-Bot-Api-Secret-Token": secret or settings.TELEGRAM_WEBHOOK_SECRET}
    return client.post("/telegram/webhook", json=payload, headers=headers)


def start(client, code: str = "kak-ani-kitchen", **kw):
    return post(client, text(f"/start {code}", **kw))


def share_phone(client, *, user_id: int = CHAT):
    """The customer taps "Share phone number" (Telegram sends their own contact card)."""
    card = {"phone_number": "+60123456789", "first_name": "Ali", "user_id": user_id}
    return post(client, update({"contact": card}))


def keyboards(bot_api) -> list[dict]:
    return [
        body["reply_markup"]
        for m, body in bot_api.calls
        if m == "sendMessage" and "reply_markup" in body
    ]


# ---------------------------------------------------------------- secret + dedupe


def test_bad_or_missing_secret_is_rejected(client, owner, llm, bot_api):
    assert post(client, text("hi"), secret="wrong").status_code == 401
    assert client.post("/telegram/webhook", json=text("hi")).status_code == 401
    assert llm.requests == [] and bot_api.calls == []


def test_duplicate_delivery_is_processed_once(client, owner, llm, bot_api, session):
    start(client)
    llm.script(say("Hi boss!"))
    post(client, text("hello", update_id=5000))
    post(client, text("hello", update_id=5000))  # Telegram retry
    assert bot_api.texts()[1:] == ["Hi boss!"]
    assert len(llm.requests) == 1
    assert session.get(ProcessedWebhook, "tg:5000") is not None


def test_old_update_ids_are_forgotten(session):
    session.add(ProcessedWebhook(update_key="tg:1", received_at=utcnow() - timedelta(days=8)))
    session.add(ProcessedWebhook(update_key="tg:2"))
    session.commit()
    assert timers.forget_old_webhooks() == 1
    assert [w.update_key for w in session.exec(select(ProcessedWebhook)).all()] == ["tg:2"]


# ---------------------------------------------------------------- shops


def test_start_with_shop_code_binds_chat_and_welcomes(client, owner, llm, bot_api, session):
    assert start(client).status_code == 200
    # one bot serves many shops: the welcome says which shop this is and shows its menu
    assert bot_api.texts() == [
        "Hi Ali! You're ordering from Kak Ani Kitchen 😊\n\nMenu:\n• Nasi Lemak – RM8.00\n\n"
        "Pickup only.\n\nWhat would you like today?"
    ]
    chat = session.get(TelegramChat, str(CHAT))
    customer = session.exec(select(Customer)).one()
    assert chat.business_id == customer.business_id
    assert customer.tg_chat_id == str(CHAT) and customer.display_name == "Ali Bakar"
    assert customer.tg_username == "ali_b" and customer.phone is None
    assert llm.requests == []  # the welcome is a template
    welcome = session.exec(select(Message)).one()
    assert welcome.sender == "system" and welcome.body == bot_api.texts()[0]


def test_custom_greeting_is_the_welcome(client, owner, bot_api):
    client.patch("/api/v1/business", headers=owner, json={"greeting": "Selamat datang!"})
    start(client)
    (welcome,) = bot_api.texts()
    assert welcome.startswith("Hi Ali! You're ordering from Kak Ani Kitchen")
    assert welcome.endswith("\n\nSelamat datang!")


def test_chat_without_shop_is_asked_to_open_a_link(client, owner, llm, bot_api, session):
    post(client, text("nak 1 nasi lemak"))
    start(client, "no-such-shop")
    assert bot_api.texts() == [templates.OPEN_SHOP_LINK, templates.OPEN_SHOP_LINK]
    assert llm.requests == []
    assert session.exec(select(Customer)).all() == []


def test_default_shop_serves_chats_without_a_link(client, owner, llm, bot_api, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_DEFAULT_SHOP", "kak-ani-kitchen")
    llm.script(say("Hi! Nasi lemak today?"))
    post(client, text("hi"))
    assert bot_api.texts() == ["Hi! Nasi lemak today?"]


def test_another_shop_link_switches_the_chat(client, owner, llm, bot_api, session):
    register(client, "teh@demo.my", "Mak Teh Bakery")
    start(client)
    start(client, "mak-teh-bakery")
    assert bot_api.texts()[-1].startswith("Hi Ali! You're ordering from Mak Teh Bakery")
    teh = session.exec(select(Business).where(Business.shop_code == "mak-teh-bakery")).one()
    assert session.get(TelegramChat, str(CHAT)).business_id == teh.id
    assert len(session.exec(select(Customer)).all()) == 2  # one customer row per shop


# ---------------------------------------------------------------- orders


def test_text_message_is_answered_with_typing_first(client, owner, llm, bot_api, session):
    start(client)
    llm.script(
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=2),
            call("set_order_type", type="pickup"),
        ),
        say("Boleh boss, 2 nasi lemak tapau 👍"),
    )
    post(client, text("boss nak 2 nasi lemak tapau", update_id=7000))
    assert bot_api.methods()[1:] == ["sendChatAction", "sendMessage"]
    _, body = bot_api.calls[-1]
    # the AI's opener + the real cart and next question, written by code
    assert body == {
        "chat_id": str(CHAT),
        "text": "Boleh boss, 2 nasi lemak tapau 👍\n\nYour order:\n• 2× Nasi Lemak – RM16.00\n"
        "Total: RM16.00\n\nAnything else, or shall I send the payment details?",
        "link_preview_options": {"is_disabled": True},
    }
    order = session.exec(select(Order)).one()
    assert order.total == 16 and order.status == "chatting"
    customer_msg = session.exec(select(Message).where(Message.sender == "customer")).one()
    assert customer_msg.tg_message_id == "7100"


def test_payment_flow_uploads_qr_and_owner_approves_on_dashboard(
    client, owner, llm, bot_api, session
):
    client.post(
        "/api/v1/business/payment-qr", headers=owner, files={"file": ("qr.png", PNG, "image/png")}
    )
    start(client)
    llm.script(
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=1),
            call("set_order_type", type="pickup"),
            call("request_payment"),
        )
    )
    post(client, text("1 nasi lemak tapau, itu je"))
    # no phone yet: the cart + the "Share phone number" button, and no QR
    assert bot_api.photos() == []
    assert bot_api.texts()[-1].startswith("Your order:\n• 1× Nasi Lemak – RM8.00")
    assert keyboards(bot_api)[-1]["keyboard"][0][0]["request_contact"] is True
    order = session.exec(select(Order)).one()
    assert order.status == "chatting"

    # the customer taps the button: phone saved, keyboard removed, QR + payment details sent
    bot_api.calls.clear()
    share_phone(client)
    assert keyboards(bot_api)[0] == {"remove_keyboard": True}
    (photo,) = bot_api.photos()  # the QR goes up as bytes: Telegram never has to reach /media
    assert PNG in photo and str(CHAT).encode() in photo
    session.refresh(order)
    assert order.status == "awaiting_payment"
    assert bot_api.texts()[-1].startswith(f"Pay RM8.00, reference {order.code}")
    assert len(llm.requests) == 1  # the checkout after the phone is code only

    # the customer sends the transfer screenshot; it is downloaded and attached as a hint
    llm.script(tools(call("mark_paid_by_customer")), say("Thanks, the owner will check it."))
    photo_sizes = [{"file_id": "photo-small", "width": 90}, {"file_id": "photo-big", "width": 1280}]
    post(client, update({"photo": photo_sizes, "caption": "dah bayar"}))
    assert ("getFile", {"file_id": "photo-big"}) in bot_api.calls
    session.refresh(order)
    assert order.status == "payment_check"
    assert order.payment_proof_media_url.startswith("/media/")
    assert client.get(order.payment_proof_media_url).content == IMAGE

    # the owner approves on the website: the confirmation goes out through the bot
    bot_api.calls.clear()
    r = client.post(f"/api/v1/orders/{order.id}/approve", headers=owner)
    assert r.json()["status"] == "approved"
    assert r.json()["customer"] == {
        "id": r.json()["customer"]["id"],
        "display_name": "Ali Bakar",
        "username": "ali_b",
        "phone": "60123456789",
    }
    assert bot_api.texts() == [
        f"Payment received, thank you! Order {order.code} is confirmed. "
        "We will tell you when it is ready for pickup."
    ]


def test_location_is_stored_by_code(client, owner, llm, bot_api, session):
    start(client)
    llm.script(say("Got your location. What would you like?"))
    post(client, update({"location": {"latitude": 3.139, "longitude": 101.6869}}))
    order = session.exec(select(Order)).one()
    assert str(order.location_lat) == "3.139000" and str(order.location_lng) == "101.686900"


def test_voice_gets_text_only_reply(client, owner, llm, bot_api):
    start(client)
    post(client, update({"voice": {"file_id": "v", "duration": 3}}))
    assert bot_api.texts()[-1] == templates.TEXT_ONLY
    assert llm.requests == []


def test_blocked_bot_does_not_break_the_order(client, owner, llm, bot_api, session):
    bot_api.fail = {"sendMessage", "sendChatAction"}
    start(client)
    llm.script(tools(call("add_item", menu_item_id="nasi_lemak", qty=1)), say("Ok!"))
    assert post(client, text("1 nasi lemak")).status_code == 200
    assert session.exec(select(Order)).one().total == 8


# ---------------------------------------------------------------- startup


def test_webhook_is_registered_with_the_secret(bot_api, monkeypatch, client, owner):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://abc.ngrok-free.app/")
    assert setup.register_webhook() is True
    assert bot_api.calls == [
        (
            "setWebhook",
            {
                "url": "https://abc.ngrok-free.app/telegram/webhook",
                "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
                "allowed_updates": ["message"],
            },
        )
    ]
    setup.log_shop_links()  # reads the DB, no Bot API call
    assert len(bot_api.calls) == 1


def test_webhook_needs_https_and_a_token(bot_api, monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://localhost:8000")
    assert setup.register_webhook() is False
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    assert setup.register_webhook() is False
    assert bot_api.calls == []


# ---------------------------------------------------------------- parser


def test_parser_reads_start_codes_photos_and_files():
    assert parser.parse(text("/start Kak-Ani-Kitchen")).start_code == "kak-ani-kitchen"
    assert parser.parse(text("/start")).start_code == ""
    assert parser.parse(text("nak 2 nasi lemak")).start_code is None
    doc = {"document": {"file_id": "doc-1", "mime_type": "image/png"}, "caption": "resit"}
    parsed = parser.parse(update(doc))
    assert (parsed.type, parsed.file_id, parsed.text) == ("image", "doc-1", "resit")
    pdf = parser.parse(update({"document": {"file_id": "d", "mime_type": "application/pdf"}}))
    assert pdf.type == "other"


def test_parser_skips_groups_bots_edits_and_garbage():
    group = text("hi")
    group["message"]["chat"]["type"] = "group"
    from_bot = text("hi")
    from_bot["message"]["from"]["is_bot"] = True
    edited = {"update_id": 9, "edited_message": text("hi")["message"]}
    for payload in (group, from_bot, edited, None, {"update_id": "x"}, {"update_id": 1}):
        assert parser.parse(payload) is None


def test_start_begins_a_fresh_conversation_for_the_ai(client, owner, llm, bot_api, session):
    start(client)
    llm.script(say("Sure thing! Adding one Nasi Lemak."), say("Which items would you like?"))
    post(client, text("one nasi lemak"))
    start(client)  # the customer taps Start again
    llm.script(say("Hi! What would you like?"))
    post(client, text("hello"))
    conversations = session.exec(select(Conversation)).all()
    assert len(conversations) == 2
    # the AI only saw the new chat: the welcome and "hello", not the old replies
    history = [m["content"] for m in llm.requests[-1][1:]]
    assert history[-1] == "hello" and not any("Adding one" in h for h in history)


def test_start_keeps_the_conversation_while_a_payment_is_pending(
    client, owner, llm, bot_api, session
):
    start(client)
    llm.script(
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=1),
            call("set_order_type", type="pickup"),
            call("request_payment"),
        )
    )
    post(client, text("1 nasi lemak tapau, itu je"))
    share_phone(client)
    start(client)
    assert len(session.exec(select(Conversation)).all()) == 1
    assert session.exec(select(Order)).one().status == "awaiting_payment"


def test_someone_elses_contact_card_is_not_saved(client, owner, llm, bot_api, session):
    start(client)
    share_phone(client, user_id=555)  # a forwarded contact, not the customer's own number
    assert session.exec(select(Customer)).one().phone is None
    assert llm.requests == []


def test_start_brings_the_bot_back_after_the_owner_replied(client, owner, llm, bot_api, session):
    """The customer pressed Start while the owner's pause was on: the bot answers again."""
    start(client)
    conv = session.exec(select(Conversation)).one()
    conv.ai_paused_until = utcnow() + timedelta(minutes=10)  # the owner just replied
    session.add(conv)
    session.commit()
    start(client)
    llm.script(say("Hi! What would you like?"))
    post(client, text("hello"))
    assert bot_api.texts()[-1] == "Hi! What would you like?"
