"""WhatsApp webhook end to end with a fake Graph API and a scripted LLM (no network)."""

import hashlib
import hmac
import json
from datetime import timedelta

import httpx
import pytest
from sqlmodel import select

from app.core.config import settings
from app.models import Conversation, Message, Order, ProcessedWebhook
from app.models.base import utcnow
from app.services import timers
from app.services.whatsapp import set_transport
from app.tests.conftest import auth_headers, register
from app.tests.fake_llm import call, say, tools
from app.webhook import parser

PHONE_NUMBER_ID = "111222333444555"
CUSTOMER = "60123456789"
IMAGE = b"\xff\xd8\xff\xe0" + b"\x00" * 64  # jpeg-ish bytes


class FakeGraph:
    """Records what we send to Meta and serves one downloadable image."""

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.auth: set[str] = set()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.auth.add(request.headers.get("Authorization", ""))
        if request.method == "POST" and request.url.path.endswith(f"/{PHONE_NUMBER_ID}/messages"):
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})
        if request.url.path.endswith("/media-1"):
            return httpx.Response(
                200, json={"url": "https://lookaside.test/img", "mime_type": "image/jpeg"}
            )
        if request.url.host == "lookaside.test":
            return httpx.Response(200, content=IMAGE, headers={"content-type": "image/jpeg"})
        return httpx.Response(404, json={"error": {"message": "not found"}})

    def texts(self) -> list[str]:
        return [m["text"]["body"] for m in self.sent if m["type"] == "text"]


@pytest.fixture
def graph():
    fake = FakeGraph()
    set_transport(httpx.MockTransport(fake))
    return fake


@pytest.fixture
def owner(client):
    register(client, "ani@demo.my")
    headers = auth_headers(client, "ani@demo.my")
    client.post("/api/v1/menu", headers=headers, json={"name": "Nasi Lemak", "price": "8.00"})
    r = client.put(
        "/api/v1/business/whatsapp",
        headers=headers,
        json={
            "phone_number_id": PHONE_NUMBER_ID,
            "display_phone": "+60 3-1234 5678",
            "access_token": "EAAG-test-token",
        },
    )
    assert r.status_code == 200, r.text
    return headers


def message_payload(msg: dict, *, phone_number_id: str = PHONE_NUMBER_ID) -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "60312345678",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [{"profile": {"name": "Ali"}, "wa_id": CUSTOMER}],
                            "messages": [{"from": CUSTOMER, "timestamp": "1760000000", **msg}],
                        },
                    }
                ],
            }
        ],
    }


def text(body: str, msg_id: str = "wamid.1") -> dict:
    return {"id": msg_id, "type": "text", "text": {"body": body}}


def post(client, payload: dict, *, secret: str | None = None):
    raw = json.dumps(payload).encode()
    key = (secret or settings.WHATSAPP_APP_SECRET).encode()
    sig = "sha256=" + hmac.new(key, raw, hashlib.sha256).hexdigest()
    return client.post(
        "/webhook",
        content=raw,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
    )


# ---------------------------------------------------------------- verification + signature


def test_verify_handshake(client):
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
        "hub.challenge": "1158201444",
    }
    r = client.get("/webhook", params=params)
    assert r.status_code == 200 and r.text == "1158201444"
    assert client.get("/webhook", params=params | {"hub.verify_token": "nope"}).status_code == 403
    assert client.get("/webhook", params=params | {"hub.mode": "unsubscribe"}).status_code == 403


def test_bad_or_missing_signature_is_rejected(client, owner, llm):
    assert post(client, message_payload(text("hi")), secret="wrong").status_code == 401
    r = client.post("/webhook", json=message_payload(text("hi")))
    assert r.status_code == 401
    assert llm.requests == []


# ---------------------------------------------------------------- messages


def test_text_message_is_answered_on_whatsapp(client, owner, llm, graph, session):
    llm.script(
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=2),
            call("set_order_type", type="pickup"),
        ),
        say("Ok boss, 2 nasi lemak tapau."),
    )
    r = post(client, message_payload(text("boss nak 2 nasi lemak tapau")))
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert graph.texts() == ["Ok boss, 2 nasi lemak tapau."]
    assert graph.sent[0]["to"] == CUSTOMER
    assert graph.auth == {"Bearer EAAG-test-token"}  # decrypted token used
    order = session.exec(select(Order)).one()
    assert order.total == 16 and order.status == "chatting"
    customer_msg = session.exec(select(Message).where(Message.sender == "customer")).one()
    assert customer_msg.wa_message_id == "wamid.1"


def test_duplicate_delivery_is_processed_once(client, owner, llm, graph, session):
    llm.script(say("Hi!"))
    post(client, message_payload(text("hello", "wamid.dup")))
    post(client, message_payload(text("hello", "wamid.dup")))  # Meta retry
    assert graph.texts() == ["Hi!"]
    assert len(llm.requests) == 1
    assert session.exec(select(ProcessedWebhook)).one().wa_message_id == "wamid.dup"


def test_old_webhook_ids_are_forgotten(session):
    session.add(ProcessedWebhook(wa_message_id="old", received_at=utcnow() - timedelta(days=8)))
    session.add(ProcessedWebhook(wa_message_id="new"))
    session.commit()
    assert timers.forget_old_webhooks() == 1
    assert [w.wa_message_id for w in session.exec(select(ProcessedWebhook)).all()] == ["new"]


def test_unknown_number_is_ignored(client, owner, llm, graph):
    r = post(client, message_payload(text("hi"), phone_number_id="999"))
    assert r.status_code == 200
    assert llm.requests == [] and graph.sent == []


def test_status_updates_are_ignored(client, owner, llm):
    payload = message_payload(text("x"))
    value = payload["entry"][0]["changes"][0]["value"]
    del value["messages"]
    value["statuses"] = [{"id": "wamid.out", "status": "delivered"}]
    assert post(client, payload).status_code == 200
    assert llm.requests == []


def test_payment_flow_sends_qr_and_owner_approval(client, owner, llm, graph, session):
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    client.post(
        "/api/v1/business/payment-qr", headers=owner, files={"file": ("qr.png", png, "image/png")}
    )
    llm.script(
        tools(
            call("add_item", menu_item_id="nasi_lemak", qty=1),
            call("set_order_type", type="pickup"),
            call("request_payment"),
        ),
        say("Thank you!"),
    )
    post(client, message_payload(text("1 nasi lemak tapau, itu je")))
    image = next(m for m in graph.sent if m["type"] == "image")
    assert image["image"]["link"].startswith(f"{settings.PUBLIC_BASE_URL}/media/")
    order = session.exec(select(Order)).one()
    assert graph.texts()[0].startswith(f"Pay RM8.00, reference {order.code}")

    # customer sends the transfer screenshot; it is downloaded and attached as a hint
    llm.script(tools(call("mark_paid_by_customer")), say("Thanks, we are checking."))
    post(
        client,
        message_payload({"id": "wamid.2", "type": "image", "image": {"id": "media-1"}}),
    )
    session.refresh(order)
    assert order.status == "payment_check"
    assert order.payment_proof_media_url.startswith("/media/")
    proof = client.get(f"/api/v1/orders/{order.id}", headers=owner).json()
    assert proof["payment_proof_media_url"].startswith(settings.PUBLIC_BASE_URL)
    assert client.get(order.payment_proof_media_url).content == IMAGE

    # owner approves on the dashboard: the confirmation goes out through WhatsApp
    graph.sent.clear()
    r = client.post(f"/api/v1/orders/{order.id}/approve", headers=owner)
    assert r.json()["status"] == "approved"
    assert graph.texts() == [
        f"Payment received, thank you! Order {order.code} is confirmed. "
        "We will tell you when it is ready for pickup."
    ]


def test_location_message_is_stored_by_code(client, owner, llm, graph, session):
    llm.script(say("Got your location. What would you like?"))
    post(
        client,
        message_payload(
            {
                "id": "wamid.loc",
                "type": "location",
                "location": {"latitude": 3.1390, "longitude": 101.6869},
            }
        ),
    )
    order = session.exec(select(Order)).one()
    assert str(order.location_lat) == "3.139000" and str(order.location_lng) == "101.686900"


def test_audio_gets_text_only_reply(client, owner, llm, graph):
    post(client, message_payload({"id": "wamid.a", "type": "audio", "audio": {"id": "m"}}))
    assert graph.texts() == ["Sorry, I can only read text messages. Please type your order."]
    assert llm.requests == []


# ---------------------------------------------------------------- owner echoes (coexistence)


def echo_payload(body: str, msg_id: str = "wamid.echo") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "smb_message_echoes",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "60312345678",
                                "phone_number_id": PHONE_NUMBER_ID,
                            },
                            "message_echoes": [
                                {
                                    "from": "60312345678",
                                    "to": CUSTOMER,
                                    "id": msg_id,
                                    "timestamp": "1760000000",
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def test_owner_echo_pauses_ai(client, owner, llm, graph, session):
    llm.script(tools(call("handoff_to_owner", reason="complaint")))
    post(client, message_payload(text("makanan basi!")))
    assert post(client, echo_payload("Sorry boss, I will refund.")).status_code == 200
    conv = session.exec(select(Conversation)).one()
    assert conv.needs_owner is False and conv.ai_paused_until is not None
    assert session.exec(select(Message).where(Message.sender == "owner")).one().body == (
        "Sorry boss, I will refund."
    )
    n = len(llm.requests)
    post(client, message_payload(text("ok thanks", "wamid.3")))
    assert len(llm.requests) == n  # AI silent while the owner handles it


# ---------------------------------------------------------------- parser


def test_parser_skips_broken_parts():
    payload = message_payload({"id": "x", "type": "text", "text": {"body": "hi"}})
    payload["entry"].append({"changes": [{"field": "messages", "value": {}}]})  # no metadata
    payload["entry"].append("garbage")
    payload["entry"][0]["changes"][0]["value"]["messages"].append({"type": "text"})  # no id
    messages, echoes = parser.parse(payload)
    assert [(m.wa_message_id, m.text, m.display_name) for m in messages] == [("x", "hi", "Ali")]
    assert echoes == []
    assert parser.parse(None) == ([], [])
    assert parser.parse({"entry": None}) == ([], [])


def test_parser_button_replies_read_as_text():
    msg = {
        "id": "b",
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": "1", "title": "Pickup"}},
    }
    (parsed,), _ = parser.parse(message_payload(msg))
    assert parsed.type == "text" and parsed.text == "Pickup"
