"""The two steps small models miss most: "I'm done, how do I pay?" and "I paid".

Code recognises them and runs the tool itself before the LLM writes its reply (AI talks, code
decides). The executor still checks everything: request_payment refuses an incomplete cart.
"""

import difflib
import re

from app.models import MenuItem, Order, OrderStatus

_DONE_RE = re.compile(
    r"\b("
    r"(itu|tu|ini|tu je) ?(je|jer|ja|jek|sahaja|saja|shj|aje|ajer)"
    r"|(dah|sudah|da) cukup|cukup"
    r"|that'?s (all|it)|thats (all|it)|that is (all|it)|nothing else|all good|i'?m done|done"
    r"|(nak|mahu|mau|boleh|nk|ready to|want to|can i|how (do i|to)|where to|ready for) (bayar|pay)"
    r"|bayar (macam mana|camne|cmne|mcm mana)|checkout|check out"
    r"|qr|payment details?|account number|no akaun"
    r")\b",
    re.IGNORECASE,
)
# a whole message like "no" / "takde" / "ok" right after the AI asked "anything else?"
_SHORT_NO_RE = re.compile(
    r"^(no|nope|nah|tak|takde|tak de|tiada|no thanks?|nothing|x)[.!\s]*$", re.IGNORECASE
)
_SHORT_YES_RE = re.compile(
    r"^(yes|ya|yup|yea|yeah|ok|okay|okey|boleh|sure|confirm|betul|correct)[.!\s]*$", re.IGNORECASE
)
_ASKED_TO_FINISH_RE = re.compile(
    r"anything else|something else|apa(-apa)? lagi|nak (tambah|apa) lagi|lagi\?|ready|"
    r"confirm|pay|bayar|correct\?|betul\?|is that all|itu sahaja\?|itu je\?",
    re.IGNORECASE,
)
_PAID_RE = re.compile(
    r"\b("
    r"(dah|sudah|da|udah|siap|baru) ?(bayar|transfer|tf|bank in|banking)"
    r"|bayar (dah|sudah|siap)|transfer (dah|sudah|siap)"
    r"|(i |have |i have |i'?ve |already |just )?(paid|transferred)"
    r"|payment (done|made|sent|completed?)|sent (the )?(money|payment)"
    r"|done (paying|payment|transfer)"
    r")\b",
    re.IGNORECASE,
)
_ASKS_QR_RE = re.compile(
    r"\b(qr|payment details?|account number|no akaun|how (do i|to) pay|bayar (macam mana|mcm mana)"
    r"|(did ?n'?t|did not|not|tak|belum) (get|receive|send|sent|dapat|terima|hantar))\b",
    re.IGNORECASE,
)
_SHORT_DONE_RE = re.compile(r"^(done|dah|siap|settle|settled|sent)[.!\s]*$", re.IGNORECASE)
SCREENSHOT_TEXT_PREFIX = "[customer sent an image"


def wants_checkout(text: str, last_ai_reply: str | None) -> bool:
    if _DONE_RE.search(text):
        return True
    asked = bool(last_ai_reply and _ASKED_TO_FINISH_RE.search(last_ai_reply))
    return asked and bool(_SHORT_NO_RE.match(text.strip()) or _SHORT_YES_RE.match(text.strip()))


def says_paid(text: str) -> bool:
    if text.startswith(SCREENSHOT_TEXT_PREFIX):  # a screenshot while the QR is out
        return True
    return bool(_PAID_RE.search(text) or _SHORT_DONE_RE.match(text.strip()))


def asks_for_payment_details(text: str) -> bool:
    return bool(_ASKS_QR_RE.search(text))


def auto_action(
    order: Order | None, missing: list[str], text: str, last_ai_reply: str | None
) -> str | None:
    """What code does before the LLM replies: a tool name, "resend_payment", or None."""
    if order is None:
        return None
    if order.status == OrderStatus.chatting and not missing:
        return "request_payment" if wants_checkout(text, last_ai_reply) else None
    if order.status == OrderStatus.awaiting_payment:
        if says_paid(text):
            return "mark_paid_by_customer"
        if asks_for_payment_details(text):
            return "resend_payment"
    return None


# ---------------------------------------------------------------- items in the customer's words

_QTY_WORDS = {
    "a": 1, "an": 1, "one": 1, "satu": 1, "se": 1, "two": 2, "dua": 2, "three": 3, "tiga": 3,
    "four": 4, "empat": 4, "five": 5, "lima": 5, "six": 6, "enam": 6, "seven": 7, "tujuh": 7,
    "eight": 8, "lapan": 8, "nine": 9, "sembilan": 9, "ten": 10, "sepuluh": 10,
}  # fmt: skip
_WORD_RE = re.compile(r"[a-z0-9]+")
_TIMES_RE = re.compile(r"^(?:x(\d{1,2})|(\d{1,2})x)$")  # "x2", "2x"
FUZZY_MIN_LENGTH = 5  # short names must match exactly: "besh" is not "best"
FUZZY_RATIO = 0.8  # "mee gorend" -> "mee goreng"
MAX_QTY = 20


def _qty(word: str | None) -> int | None:
    if word is None:
        return None
    if word.isdigit():
        n = int(word)
        return n if 1 <= n <= MAX_QTY else None
    if m := _TIMES_RE.match(word):
        return int(m.group(1) or m.group(2))
    return _QTY_WORDS.get(word)


def parse_items(text: str, menu: list[MenuItem]) -> list[tuple[str, int]]:
    """Menu items the customer named, with quantities: "one mee goreng and 2 teh tarik".

    Used only when the model claims it added items but called no tool. A quantity is the
    number or word right before the name ("2", "dua", "one") or "x2" right after; default 1.
    """
    words = _WORD_RE.findall(text.lower())
    used: set[int] = set()
    found: dict[str, int] = {}
    # longer names first, so "nasi lemak ayam" wins over "nasi lemak"
    for item in sorted(menu, key=lambda i: -len(_WORD_RE.findall(i.name.lower()))):
        name = " ".join(_WORD_RE.findall(item.name.lower()))
        size = len(name.split())
        if not size:
            continue
        for start in range(len(words) - size + 1):
            span = range(start, start + size)
            if used.intersection(span):
                continue
            said = " ".join(words[start : start + size])
            close = len(name) >= FUZZY_MIN_LENGTH and (
                difflib.SequenceMatcher(None, said, name).ratio() >= FUZZY_RATIO
            )
            if said != name and not close:
                continue
            used.update(span)
            # "2 bungkus nasi lemak", "3 cup teh tarik": the number sits before the unit word
            at = start - 1
            if at >= 0 and words[at] in UNIT_WORDS:
                at -= 1
            before = words[at] if at >= 0 else None
            if _negated(words, at if _qty(before) else at + 1):
                continue  # "tak nak teh tarik", "no fries"
            after = words[start + size] if start + size < len(words) else None
            qty = _qty(before) or (_qty(after) if after and _TIMES_RE.match(after) else None) or 1
            found[item.slug] = found.get(item.slug, 0) + qty
    return list(found.items())


# from the ML teammate's order reader (runpod/order_ai25.py): units and "don't want" words
UNIT_WORDS = {
    "bungkus", "keping", "biji", "cucuk", "pcs", "pc", "pieces", "piece", "cawan", "cup", "cups",
    "gelas", "glass", "glasses", "pinggan", "plate", "plates", "set", "sets", "box", "boxes",
}  # fmt: skip
_NEGATIONS = (
    ("tak", "nak"), ("taknak",), ("x", "nak"), ("tidak",), ("jangan",), ("tanpa",), ("no",),
    ("not",), ("without",), ("dont",), ("don", "t"), ("cancel",), ("buang",),
)  # fmt: skip


def _negated(words: list[str], start: int) -> bool:
    """True if the words right before `start` say the customer does NOT want this item."""
    window = words[max(0, start - 2) : start]
    return any(
        tuple(window[i : i + len(neg)]) == neg
        for neg in _NEGATIONS
        for i in range(len(window) - len(neg) + 1)
    )


# ---------------------------------------------------------------- did the customer really say it?

_ORDER_TYPE_RE = re.compile(
    r"\b(tapau|bungkus|take ?away|pick ?up|self[- ]?pick ?up|ambil|collect|dine[- ]?in"
    r"|deliver(y)?|hantar|antar|alamat|address)\b",
    re.IGNORECASE,
)


def premature_tool(name: str, text: str, last_ai_reply: str | None) -> dict | None:
    """A tool result for a call the customer did not ask for, or None to run the tool.

    Seen live: after "one nasi lemak" the model chose pickup by itself and sent the payment QR.
    """
    if name == "set_order_type" and not _ORDER_TYPE_RE.search(text):
        return {
            "error": "customer_did_not_choose",
            "note": "The customer has not said pickup or delivery yet. Ask them.",
        }
    if name == "request_payment" and not wants_checkout(text, last_ai_reply):
        return {
            "error": "customer_not_done",
            "note": "The customer has not said they are finished. Ask if they want anything else.",
        }
    return None


# ---------------------------------------------------------------- steps code answers by itself

_MENU_RE = re.compile(
    r"\b(menu|what do you (have|sell|got)|what('?s| is) (there|available|on offer)"
    r"|what can i (order|get)|ada apa|apa (yang )?ada|jual apa|senarai"
    r"|show me (the )?(food|list))\b",
    re.IGNORECASE,
)
_OWNER_RE = re.compile(
    r"\b((talk|speak|chat) (to|with) (the |a |your )?"
    r"(owner|human|person|someone|staff|seller|manager|admin)"
    r"|(real|actual) (person|human)|(pass|transfer|connect|hand) (me|this)( over)? to"
    r"|(owner|manager|human) (please|pls|plz)|call (the )?owner|nak (cakap|bercakap|chat) dengan"
    r"|tuan kedai|pemilik|panggil (owner|tuan))\b",
    re.IGNORECASE,
)
_PICKUP_RE = re.compile(
    r"\b(tapau|bungkus|take ?away|pick ?up|self[- ]?pick ?up|ambil sendiri|collect|dine[- ]?in)\b",
    re.IGNORECASE,
)
_DELIVERY_RE = re.compile(r"\b(deliver(y|ed)?|hantar|antar|send (it )?to)\b", re.IGNORECASE)


def asks_for_menu(text: str) -> bool:
    return bool(_MENU_RE.search(text))


def wants_owner(text: str) -> bool:
    """The customer asks for a person ("can you pass me to the owner") - seen live unanswered."""
    return bool(_OWNER_RE.search(text))


def order_type_said(text: str) -> str | None:
    """ "pickup" or "delivery" when the customer clearly chose one; None if neither or both."""
    pickup, delivery = bool(_PICKUP_RE.search(text)), bool(_DELIVERY_RE.search(text))
    if pickup == delivery:
        return None
    return "pickup" if pickup else "delivery"
