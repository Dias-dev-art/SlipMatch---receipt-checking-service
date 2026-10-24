"""
SlipMatch order checker.

  1. AI (Qwen on RunPod) READS the customer's message and lists what they want:
     which menu item, how many.
  2. Plain Python DECIDES: is each item on the menu? Is there enough stock?
     -> ACCEPT, PARTIAL (offer the items we have), DECLINE, or NEEDS_REVIEW.
  3. If the customer ASKS about a food instead of ordering, it answers (ANSWER):
     price + availability from our menu, description from the owner or Wikipedia.
  4. Greetings and small talk get a natural reply (CHAT). Anything it cannot answer
     (opening hours, delivery, cancelling...) goes to the owner (NEEDS_REVIEW).

The AI never sees the stock numbers, so it can't "decide" wrongly.

Env vars (Replit Secrets):
  RUNPOD_API_KEY, RUNPOD_ENDPOINT_ID
  MODEL_NAME=qwen/qwen2.5-vl-7b-instruct
  USE_FALLBACK=false      true = skip the AI, use the simple keyword reader
  AI_TIMEOUT_S=30
  PROMPT_VERSION=v5       which prompt to use (for tuning)
  GUIDED_JSON=true        force the AI to answer in our JSON shape
  LOW_CONFIDENCE=0.6      below this -> NEEDS_REVIEW
  MENU_CSV=data/menu.csv
  BUSINESS="a small Malaysian kuih and catering seller"   who the shop is (change for another menu)
  USE_WIKIPEDIA=true      look up general food descriptions on Wikipedia for questions
  TYPO_CUTOFF=0.78        how close a misspelled food name must be to count (higher = stricter)
  CONFIRM_REPEATS=true    'same again' asks "Just to confirm..." first (false = confirm right away)

Try it:  python order_ai.py "nak 10 karipap dengan 2 nasi lemak"
         python order_ai.py "what is seri muka?"
"""
import csv, difflib, json, os, re, sys, time

MODEL_NAME = os.environ.get("MODEL_NAME", "qwen/qwen2.5-vl-7b-instruct")
ENDPOINT_ID = os.environ.get("RUNPOD_ENDPOINT_ID", "")
TIMEOUT_S = float(os.environ.get("AI_TIMEOUT_S", "30"))
PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v5")
LOW_CONFIDENCE = float(os.environ.get("LOW_CONFIDENCE", "0.6"))
MENU_CSV = os.environ.get("MENU_CSV", "data/menu.csv")
_guided = os.environ.get("GUIDED_JSON", "true").lower() == "true"
BUSINESS = os.environ.get("BUSINESS", "a small Malaysian kuih and catering seller")
USE_WIKIPEDIA = os.environ.get("USE_WIKIPEDIA", "true").lower() == "true"
WIKI_CACHE = os.environ.get("WIKI_CACHE", "data/wiki_cache.json")


# ------------------------------------------------------------------ menu
def load_menu(path=MENU_CSV):
    menu = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            menu[r["item_id"]] = {
                "id": r["item_id"],
                "name": r["name"],
                "aliases": [a.strip() for a in r.get("aliases", "").split(";") if a.strip()],
                "price_myr": float(r["price_myr"]),
                "stock_qty": int(r["stock_qty"]),
                "description": (r.get("description") or "").strip(),   # optional, written by owner
            }
    return menu


def menu_for_prompt(menu):
    lines = []
    for m in menu.values():
        extra = f" (also called: {', '.join(m['aliases'])})" if m["aliases"] else ""
        lines.append(f"{m['id']}: {m['name']}{extra}")
    return "\n".join(lines)


# ------------------------------------------------------------------ prompts
SCHEMA = {
    "type": "object",
    "properties": {
        "is_order": {"type": "boolean"},
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "said": {"type": "string"},
                    "menu_id": {"type": ["string", "null"]},
                    "quantity": {"type": ["integer", "null"]},
                },
                "required": ["said", "menu_id", "quantity"],
            },
        },
        "confidence": {"type": "number"},
    },
    "required": ["is_order", "items", "confidence"],
}

PROMPTS = {
    "v1": (
        "You read food orders sent on WhatsApp to a small Malaysian kuih and catering "
        "seller. Messages may be in English, Malay, or a mix.\n\n"
        "MENU (id: name):\n{menu}\n\n"
        "Customer message:\n\"\"\"{message}\"\"\"\n\n"
        "List every food or drink the customer wants. For each one give:\n"
        "- said: the words the customer used for it\n"
        "- menu_id: the matching id from the MENU, or null if it is not on the menu\n"
        "- quantity: a whole number. Malay numbers: satu=1, dua=2, tiga=3, empat=4, lima=5, "
        "enam=6, tujuh=7, lapan=8, sembilan=9, sepuluh=10. Use null if no number is given.\n"
        "Set is_order to false if the message is not a new order (a greeting, a question, "
        "a thank-you, a cancellation or a change to an old order) and give an empty items list.\n"
        "confidence: 0 to 1, how sure you are that the items and quantities are right.\n"
        "Return ONE JSON object only: "
        "{{\"is_order\": true, \"items\": [{{\"said\": \"...\", \"menu_id\": \"K04\", \"quantity\": 10}}], "
        "\"confidence\": 0.9}}"
    ),
    "v2": (
        "You read food orders sent on WhatsApp to a small Malaysian kuih and catering "
        "seller. Messages may be in English, Malay, or a mix.\n\n"
        "MENU (id: name):\n{menu}\n\n"
        "Customer message:\n\"\"\"{message}\"\"\"\n\n"
        "List EVERY food or drink the customer asks for, INCLUDING things that are not on "
        "the menu. For each one give:\n"
        "- said: the words the customer used for it\n"
        "- menu_id: the matching id from the MENU, or null if it is not on the menu "
        "(for example burger or pizza)\n"
        "- quantity: the number the customer wrote for THIS item. The number can come before "
        "or after the name: '10 karipap', 'karipap 10' and 'karipap x10' all mean 10. "
        "Malay numbers: satu=1, dua=2, tiga=3, empat=4, lima=5, enam=6, tujuh=7, lapan=8, "
        "sembilan=9, sepuluh=10. If the customer wrote no number for this item, use null. "
        "Never invent a number.\n"
        "Set is_order to false ONLY if the message asks for no food or drink at all (a greeting, "
        "a question, a thank-you, a cancellation or a change to an old order); then items is empty. "
        "A message asking for things that are not on the menu is still an order.\n"
        "confidence: 0 to 1, how sure you are that the items and quantities are right.\n"
        "Return ONE JSON object only, in this shape: "
        "{{\"is_order\": true, \"items\": [{{\"said\": \"<words>\", \"menu_id\": \"<id or null>\", "
        "\"quantity\": <number or null>}}], \"confidence\": <0 to 1>}}"
    ),
    "v3": (
        "You read food orders sent on WhatsApp to {business}. "
        "Messages may be in English, Malay, or a mix.\n\n"
        "MENU (id: name):\n{menu}\n\n"
        "Customer message:\n\"\"\"{message}\"\"\"\n\n"
        "List EVERY food or drink the customer asks for, INCLUDING things that are not on "
        "the menu. For each one give:\n"
        "- said: the name of the food only, without numbers or units\n"
        "- menu_id: the matching id from the MENU, or null if it is not on the menu "
        "(for example burger, pizza, satay)\n"
        "- quantity: the number the customer wrote for THIS item. The number can come before "
        "or after the name: '10 karipap', 'karipap 10' and 'karipap x10' all mean 10. "
        "Words like bungkus, keping, biji, cucuk, pcs, pieces are units, not part of the name: "
        "'satay 20 cucuk' means said='satay', quantity=20. "
        "Malay numbers: satu=1, dua=2, tiga=3, empat=4, lima=5, enam=6, tujuh=7, lapan=8, "
        "sembilan=9, sepuluh=10. If the customer wrote no number for this item, use null. "
        "Never invent a number.\n"
        "is_order rules:\n"
        "- true when the customer asks to buy food or drink, EVEN IF none of it is on the menu "
        "(e.g. '1 pizza please' is an order: list pizza with menu_id null).\n"
        "- false when the customer wants to CANCEL, CHANGE or REMOVE something from an earlier "
        "order (words like cancel, batal, tukar, ubah, tak jadi), even if they name a food. "
        "Also false for greetings, questions and thank-yous. When false, items is empty.\n"
        "confidence: 0 to 1, how sure you are that the items and quantities are right.\n"
        "Return ONE JSON object only, in this shape: "
        "{{\"is_order\": true, \"items\": [{{\"said\": \"<food name>\", \"menu_id\": \"<id or null>\", "
        "\"quantity\": <number or null>}}], \"confidence\": <0 to 1>}}"
    ),
    "v4": (
        "You read food orders sent on WhatsApp to {business}. "
        "Messages may be in English, Malay, or a mix.\n\n"
        "MENU (id: name):\n{menu}\n\n"
        "Customer message:\n\"\"\"{message}\"\"\"\n\n"
        "List EVERY food or drink the customer asks for, INCLUDING things that are not on "
        "the menu. For each one give:\n"
        "- said: the name of the food only, without numbers or units\n"
        "Customers often write Manglish ('10 karipap can or not', 'tapau 2 mee goreng lah' = takeaway, "
        "'boss', la/lah/lor/meh/ah are just friendly words). "
        "Customers often make spelling mistakes or use short forms (karipp, nasi lemk, teh trik, "
        "nk = nak, n = and, pls = please). Match a misspelled name to the menu item it clearly means. "
        "Only use null when it is really a different food that is not on the menu.\n"
        "- menu_id: the matching id from the MENU, or null if it is not on the menu "
        "(for example burger, pizza, satay)\n"
        "- quantity: the number the customer wrote for THIS item. The number can come before "
        "or after the name: '10 karipap', 'karipap 10' and 'karipap x10' all mean 10. "
        "Words like bungkus, keping, biji, cucuk, pcs, pieces are units, not part of the name: "
        "'satay 20 cucuk' means said='satay', quantity=20. "
        "Malay numbers: satu=1, dua=2, tiga=3, empat=4, lima=5, enam=6, tujuh=7, lapan=8, "
        "sembilan=9, sepuluh=10. If the customer wrote no number for this item, use null. "
        "Never invent a number.\n"
        "is_order rules:\n"
        "- true when the customer asks to buy food or drink, EVEN IF none of it is on the menu "
        "(e.g. '1 pizza please' is an order: list pizza with menu_id null).\n"
        "- false when the customer wants to CANCEL, CHANGE or REMOVE something from an earlier "
        "order (words like cancel, batal, tukar, ubah, tak jadi), even if they name a food. "
        "Also false for greetings, questions and thank-yous. When false, items is empty.\n"
        "confidence: 0 to 1, how sure you are that the items and quantities are right.\n"
        "Return ONE JSON object only, in this shape: "
        "{{\"is_order\": true, \"items\": [{{\"said\": \"<food name>\", \"menu_id\": \"<id or null>\", "
        "\"quantity\": <number or null>}}], \"confidence\": <0 to 1>}}"
    ),
    "v5": (
        "You read food orders sent on WhatsApp to {business}. "
        "Messages may be in English, Malay, or a mix.\n\n"
        "MENU (id: name):\n{menu}\n\n"
        "Customer message:\n\"\"\"{message}\"\"\"\n\n"
        "List EVERY food or drink the customer asks for, INCLUDING things that are not on "
        "the menu. For each one give:\n"
        "- said: the name of the food only, without numbers or units\n"
        "Customers often write Manglish ('10 karipap can or not', 'tapau 2 mee goreng lah' = takeaway, "
        "'boss', la/lah/lor/meh/ah are just friendly words). "
        "Customers often make spelling mistakes or use short forms (karipp, nasi lemk, teh trik, "
        "nk = nak, n = and, pls = please). Match a misspelled name to the menu item it clearly means. "
        "Only use null when it is really a different food that is not on the menu.\n"
        "- menu_id: the matching id from the MENU, or null if it is not on the menu "
        "(for example burger, pizza, satay)\n"
        "- quantity: the number the customer wrote for THIS item. The number can come before "
        "or after the name: '10 karipap', 'karipap 10' and 'karipap x10' all mean 10. "
        "Words like bungkus, keping, biji, cucuk, pcs, pieces are units, not part of the name: "
        "'satay 20 cucuk' means said='satay', quantity=20. "
        "IMPORTANT: a number written right before or right after a food belongs to that food, even "
        "when the food is misspelled or the message is short. Examples with other foods: "
        "'nk 12 apm' -> apam quantity 12; '2 roti bkar n 3 teh o' -> roti bakar 2 and teh o 3; "
        "'kuih koci 6' -> 6; 'x4 donut' -> 4. Only use null when there is truly no number for it.\n"
        "Malay numbers: satu=1, dua=2, tiga=3, empat=4, lima=5, enam=6, tujuh=7, lapan=8, "
        "sembilan=9, sepuluh=10. If the customer wrote no number for this item, use null. "
        "Never invent a number.\n"
        "is_order rules:\n"
        "- true when the customer asks to buy food or drink, EVEN IF none of it is on the menu "
        "(e.g. '1 pizza please' is an order: list pizza with menu_id null).\n"
        "- false when the customer wants to CANCEL, CHANGE or REMOVE something from an earlier "
        "order (words like cancel, batal, tukar, ubah, tak jadi), even if they name a food. "
        "Also false for greetings, questions and thank-yous. When false, items is empty.\n"
        "confidence: 0 to 1, how sure you are that the items and quantities are right.\n"
        "Return ONE JSON object only, in this shape: "
        "{{\"is_order\": true, \"items\": [{{\"said\": \"<food name>\", \"menu_id\": \"<id or null>\", "
        "\"quantity\": <number or null>}}], \"confidence\": <0 to 1>}}"
    ),
}


# ------------------------------------------------------------------ AI call
def _call_ai(prompt, schema=None, max_tokens=500, temperature=0.0):
    """Send one prompt to Qwen on RunPod and return its text answer."""
    global _guided
    from openai import OpenAI, BadRequestError
    client = OpenAI(api_key=os.environ["RUNPOD_API_KEY"],
                    base_url=f"https://api.runpod.ai/v2/{ENDPOINT_ID}/openai/v1",
                    timeout=TIMEOUT_S, max_retries=0)
    kwargs = dict(model=MODEL_NAME, temperature=temperature, max_tokens=max_tokens,
                  messages=[{"role": "user", "content": prompt}])
    if schema and _guided:                  # force the exact JSON shape (standard OpenAI format)
        kwargs["response_format"] = {"type": "json_schema",
                                     "json_schema": {"name": "answer", "schema": schema}}
    try:
        r = client.chat.completions.create(**kwargs)
    except Exception as e:
        if not (schema and _guided) or "Timeout" in type(e).__name__ or "Connection" in type(e).__name__:
            raise
        _guided = False                     # worker doesn't support it -> plain JSON from the prompt
        kwargs.pop("response_format", None)
        r = client.chat.completions.create(**kwargs)
    return r.choices[0].message.content


def _ask_ai(message, menu, history=None):
    prompt = PROMPTS[PROMPT_VERSION].format(menu=menu_for_prompt(menu), message=message,
                                            business=BUSINESS)
    if history:                             # earlier messages, only to understand 'same', 'more', 'lagi'...
        earlier = "\n".join(f"{'Customer' if w == 'customer' else 'Shop'}: {t}" for w, t in history[-6:])
        prompt = prompt.replace(
            "Customer message:",
            "Earlier in this chat (for context only):\n" + earlier + "\n\n"
            "List ONLY what the NEW message below asks for. Do NOT repeat items from earlier messages, "
            "unless the new message clearly refers to them (for example 'same again', '2 more', "
            "'tambah 2 lagi'); then use the earlier messages to know which food is meant. "
            "'Same again' / 'sama macam tadi' means repeat EVERYTHING the customer ordered earlier "
            "in this chat.\n\n"
            "NEW customer message:", 1)
    return _call_ai(prompt, SCHEMA)


def _parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no JSON in AI answer")
    return json.loads(m.group(0))


# ------------------------------------------------------------------ cleanup
TYPO_CUTOFF = float(os.environ.get("TYPO_CUTOFF", "0.78"))   # how close a misspelling must be (0-1)


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def _similar(a, b):
    """0..1 how alike two spellings are ('karipp' vs 'karipap' = 0.92). Spaces ignored."""
    a, b = a.replace(" ", ""), b.replace(" ", "")
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _similar_length(a, b):
    """A misspelling is about as long as the real word ('goreng' is too short to be 'mee goreng')."""
    la, lb = len(a.replace(" ", "")), len(b.replace(" ", ""))
    return la and lb and min(la, lb) / max(la, lb) >= 0.75


def _ngrams(text, n_max=3):
    w = _norm(text).split()
    w = ["mee" if t == "me" and i + 1 < len(w) and w[i + 1] in ("goreng", "rebus", "hoon", "kari", "bandung",
                                                                   "siam", "jawa", "sup", "soup", "kuah", "mamak")
         else t for i, t in enumerate(w)]
    return {" ".join(w[i:i + n]) for n in range(1, n_max + 1) for i in range(len(w) - n + 1)}


def _fuzzy_menu_match(said, menu):
    """Best menu item for a possibly misspelled name. Returns (item_id, score) or (None, 0)."""
    s = _norm(said)
    if len(s.replace(" ", "")) < 4:          # too short to guess safely
        return None, 0.0
    best, best_score = None, 0.0
    for m in menu.values():
        for n in [m["name"]] + m["aliases"]:
            if not _similar_length(s, _norm(n)):
                continue
            score = _similar(s, _norm(n))
            if score > best_score:
                best, best_score = m["id"], score
    return (best, best_score) if best_score >= TYPO_CUTOFF else (None, 0.0)


def _find_menu_id(said, menu):
    """Match the customer's words to a menu item by name/alias, allowing small spelling mistakes."""
    s = _norm(said)
    if not s:
        return None
    for m in menu.values():
        for n in [m["name"]] + m["aliases"]:
            nn = _norm(n)
            if nn and (re.search(r"\b" + re.escape(nn) + r"\b", s) or re.search(r"\b" + re.escape(s) + r"\b", nn)):
                return m["id"]
    return _fuzzy_menu_match(s, menu)[0]


def _fits(said, item):
    """Do the customer's words look like this menu item (name or alias, small typos allowed)?"""
    s = _norm(said)
    for n in [item["name"]] + item["aliases"]:
        nn = _norm(n)
        if nn and (nn in s or s in nn or _similar(s, nn) >= TYPO_CUTOFF):
            return True
    return False


def clean_items(raw_items, menu):
    """Fix ids, fill missing quantities, merge duplicates."""
    out, notes = {}, []
    for it in raw_items or []:
        said = str(it.get("said") or "").strip()
        mid = it.get("menu_id")
        if mid not in menu:                 # AI gave a wrong/unknown id -> check by name (typos allowed)
            mid = _find_menu_id(said, menu)
            if mid and _norm(said) not in [_norm(n) for n in [menu[mid]["name"]] + menu[mid]["aliases"]]:
                notes.append(f"Read '{said}' as {menu[mid]['name']} (spelling)")
        else:                               # AI chose an item: does it fit the words the customer used?
            by_words = _find_menu_id(said, menu)
            if by_words and by_words != mid:
                notes.append(f"AI matched '{said}' to {menu[mid]['name']}, corrected to {menu[by_words]['name']}")
                mid = by_words
            elif not by_words and said and not _fits(said, menu[mid]):
                notes.append(f"AI matched '{said}' to {menu[mid]['name']}, but the words don't match — "
                             f"treated as not on the menu")
                mid = None
        try:
            qty = int(it.get("quantity")) if it.get("quantity") is not None else None
        except (TypeError, ValueError):
            qty = None
        ai_qty = qty is not None
        if qty is None:
            qty = 1
            notes.append(f"No quantity given for '{said}', assumed 1")
        if qty <= 0:
            notes.append(f"Odd quantity for '{said}' ({qty})")
            continue
        key = mid or f"NONE:{said.lower()}"
        if key in out:
            out[key]["quantity"] += qty
            out[key]["ai_qty"] = out[key]["ai_qty"] and ai_qty
        else:
            out[key] = {"menu_id": mid, "said": said, "quantity": qty, "ai_qty": ai_qty}
    return list(out.values()), notes


# ------------------------------------------------------------------ decision (no AI here)
def decide(items, menu, is_order=True, confidence=1.0):
    """Rules that turn the list of items into ACCEPT / PARTIAL / DECLINE / NEEDS_REVIEW.

    ACCEPT        everything is on the menu and in stock
    PARTIAL       some items are fine, some are not -> offer the customer the fine ones
    DECLINE       nothing in the order can be supplied
    NEEDS_REVIEW  not an order, nothing understood, or the AI was unsure
    """
    reasons, lines, total = [], [], 0.0
    if not is_order:
        return "NEEDS_REVIEW", ["Message is not a new order — owner should reply"], [], 0.0
    if not items:
        return "NEEDS_REVIEW", ["Could not find any menu items in the message"], [], 0.0

    for it in items:
        m = menu.get(it["menu_id"]) if it["menu_id"] else None
        if m is None:
            reasons.append(f"'{it['said']}' is not on the menu")
            lines.append({**it, "name": None, "ok": False, "problem": "not_on_menu"})
            continue
        if m["stock_qty"] <= 0:
            reasons.append(f"{m['name']} is out of stock")
            ok, problem = False, "out_of_stock"
        elif m["stock_qty"] < it["quantity"]:
            reasons.append(f"{m['name']}: asked {it['quantity']}, only {m['stock_qty']} left")
            ok, problem = False, "not_enough"
        else:
            ok, problem = True, None
            total += m["price_myr"] * it["quantity"]
            reasons.append(f"{m['name']} × {it['quantity']} in stock")
        lines.append({**it, "name": m["name"], "price_myr": m["price_myr"], "ok": ok, "problem": problem})

    n_ok = sum(l["ok"] for l in lines)
    if n_ok == 0:
        return "DECLINE", reasons, lines, 0.0
    decision = "ACCEPT" if n_ok == len(lines) else "PARTIAL"
    if confidence < LOW_CONFIDENCE:
        return "NEEDS_REVIEW", reasons + [f"AI not sure it read the order right ({confidence:.2f})"], lines, round(total, 2)
    return decision, reasons, lines, round(total, 2)


# ------------------------------------------------------------------ customer reply (template, not AI)
MALAY_WORDS = {"nak", "boleh", "dan", "dengan", "kak", "bungkus", "saya", "ada", "tak", "untuk",
               "utk", "tolong", "terima", "kasih", "satu", "dua", "tiga", "empat", "lima", "enam",
               "tujuh", "lapan", "sembilan", "sepuluh", "keping", "biji", "pagi", "petang", "je",
               "sahaja", "order", "tempah", "lagi", "ya", "nk", "sy", "dgn", "pun", "apa", "tu", "itu",
               "ini", "inti", "hari", "harini", "berapa", "mana", "macam", "manis", "pedas", "sedap", "habis",
               "nanti", "esok", "tadi", "kat", "dekat", "ke", "kah", "tak", "x", "jugak", "juga", "bang", "dik",
               "dah", "cukup", "takde", "saja", "sudah", "selamat", "datang", "pesan", "boleh"}
ENGLISH_WORDS = {"i", "want", "please", "can", "get", "and", "the", "for", "like", "would",
                 "hi", "hello", "thanks", "give", "me", "some"}


MANGLISH_MARKERS = {"la", "lah", "lor", "loh", "leh", "meh", "mah", "wor", "liao", "ah", "aiyo", "aiya",
                    "alamak", "boss", "bro", "tapau", "dabao", "walao", "one", "cannot", "can"}
MANGLISH_PHRASES = ["can or not", "got or not", "or not", "got what", "what got", "can ah", "can la"]
PARTICLES = {"la", "lah", "lor", "loh", "leh", "meh", "mah", "wor", "liao", "ah", "ar", "eh", "yo", "ya",
             "boss", "bro", "sis", "kak", "abang", "bang", "dik", "aunty", "uncle", "k", "ok", "okay"}


def is_manglish(message):
    t = " " + _norm(message) + " "
    words = set(t.split())
    return bool(words & (MANGLISH_MARKERS - {"one", "can"})) or any(" " + p + " " in t for p in MANGLISH_PHRASES)


def reply_language(message):
    """'ms' if the customer wrote mostly Malay, else 'en' (Manglish counts as English)."""
    if is_manglish(message):                    # 'aiyo ... habis meh?' is Manglish -> English reply
        return "en"
    words = re.findall(r"[a-z]+", message.lower())
    ms = sum(w in MALAY_WORDS - {"order"} for w in words)
    en = sum(w in ENGLISH_WORDS for w in words)
    return "ms" if ms > en else "en"


def _problem_text(l, menu, lang, mine=0):
    """Why an item can't be supplied. 'mine' = how many this customer already ordered in this chat."""
    left = menu[l["menu_id"]]["stock_qty"] if l["menu_id"] in menu else 0
    had = left + mine                            # what the shop had before this customer's orders
    if lang == "ms":
        if l["problem"] == "not_on_menu":
            return f"'{l['said']}' tiada dalam menu kami"
        if l["problem"] == "out_of_stock":
            if mine:
                return (f"{l['name']} sudah habis — hari ini kami ada {had} sahaja dan pesanan anda "
                        f"telah mengambil kesemua {mine}")
            return f"{l['name']} sudah habis"
        if mine:
            return f"{l['name']} tinggal {left} sahaja (anda sudah pesan {mine}, diminta lagi {l['quantity']})"
        return f"{l['name']} tinggal {left} sahaja (diminta {l['quantity']})"
    if l["problem"] == "not_on_menu":
        return f"'{l['said']}' is not on our menu"
    if l["problem"] == "out_of_stock":
        if mine:
            return f"{l['name']} is now sold out — we had {had} today and your order took all {mine}"
        return f"{l['name']} is sold out"
    if mine:
        return f"we only have {left} {l['name']} left — you already have {mine} in your order"
    return f"we only have {left} {l['name']} left (you asked for {l['quantity']})"


def _already_ordered(past_orders):
    mine = {}
    for o in past_orders or []:
        for it in o["items"]:
            if it.get("menu_id"):
                mine[it["menu_id"]] = mine.get(it["menu_id"], 0) + it["quantity"]
    return mine


def reply_draft(decision, lines, total, menu, lang="ms", past_orders=None):
    """Message to send the customer. Owner can still edit it before sending."""
    good = [l for l in lines if l["ok"]]
    bad = [l for l in lines if not l["ok"]]
    good_txt = ", ".join(f"{l['name']} × {l['quantity']}" for l in good)
    mine = _already_ordered(past_orders)
    bad_txt = "; ".join(_problem_text(l, menu, lang, mine.get(l.get("menu_id"), 0)) for l in bad)

    if decision == "ACCEPT":
        if lang == "ms":
            return f"Terima kasih! Order diterima: {good_txt}. Jumlah RM {total:.2f}."
        return f"Thank you! Your order is confirmed: {good_txt}. Total RM {total:.2f}."
    if decision == "PARTIAL":
        if lang == "ms":
            return (f"{good_txt} ada dan sudah dimasukkan (RM {total:.2f}). Maaf, {bad_txt}. "
                    f"Nak teruskan dengan {good_txt} sahaja? Balas YA untuk sahkan.")
        return (f"{good_txt} is available and added to your order (RM {total:.2f}). Sorry, {bad_txt}. "
                f"Would you like to continue with {good_txt} only? Reply YES to confirm.")
    if decision == "CONFIRM":
        extra = ""
        if bad:
            extra = (f" (Maaf, {bad_txt}.)" if lang == "ms" else f" (Sorry, {bad_txt}.)")
        if lang == "ms":
            return f"Nak pastikan: {good_txt} (RM {total:.2f})?{extra} Balas YA untuk sahkan."
        return f"Just to confirm, you'd like: {good_txt} (RM {total:.2f})?{extra} Reply YES to confirm."
    if decision == "DECLINE":
        if lang == "ms":
            return f"Maaf, {bad_txt}. Nak tukar order?"
        return f"Sorry, {bad_txt}. Would you like to order something else?"
    return ""


def added_reply(lines, total, past_orders, lang):
    """Order added to earlier orders in this chat: say what was added AND the new running total."""
    good = [l for l in lines if l.get("ok")]
    added = ", ".join(f"{l['name']} × {l['quantity']}" for l in good)
    so_far = {}
    for o in past_orders or []:
        for it in o["items"]:
            so_far[it["name"]] = so_far.get(it["name"], 0) + it["quantity"]
    for l in good:
        so_far[l["name"]] = so_far.get(l["name"], 0) + l["quantity"]
    grand = round(sum(o["total_myr"] for o in past_orders or []) + total, 2)
    body = ", ".join(f"{n} × {q}" for n, q in so_far.items())
    if lang == "ms":
        return f"Baik, {added} ditambah (RM {total:.2f}). Order anda setakat ini: {body}. Jumlah RM {grand:.2f}."
    return f"Ok, added {added} (RM {total:.2f}). Your order so far: {body}. Total RM {grand:.2f}."


def confirm_partial(result, menu=None, past_orders=None):
    """Customer replied YES to a PARTIAL or CONFIRM question -> keep the available items, ACCEPT.
    past_orders: earlier confirmed orders in this chat, to show the running total.
    The backend calls this; the AI is not involved."""
    menu = menu or load_menu()
    if result["decision"] not in ("PARTIAL", "CONFIRM"):
        return result
    good = [l for l in result["items"] if l["ok"]]
    total = round(sum(l["price_myr"] * l["quantity"] for l in good), 2)
    lang = result.get("language", "ms")
    reply = added_reply(good, total, past_orders, lang) if past_orders else reply_draft("ACCEPT", good, total, menu, lang)
    return {**result, "decision": "ACCEPT", "items": good, "total_myr": total,
            "reasons": [f"{l['name']} × {l['quantity']} in stock" for l in good] + ["Customer confirmed"],
            "reply_draft": reply}


# ------------------------------------------------------------------ fallback (no AI)
_MALAY = {"satu": 1, "dua": 2, "tiga": 3, "empat": 4, "lima": 5, "enam": 6, "tujuh": 7,
          "lapan": 8, "sembilan": 9, "sepuluh": 10, "sebungkus": 1, "sebiji": 1}


READER_STOP = {"nak", "nk", "n", "and", "dan", "dgn", "dengan", "pls", "please", "plz", "is", "itu", "tu",
               "ada", "my", "order", "the", "a", "i", "want", "get", "can", "for", "of", "some", "kak", "bang",
               "saya", "sy", "me", "boleh", "dapat", "to", "x", "also", "lagi", "tak", "what", "apa", "jadi",
               "with", "plus", "je", "sahaja", "only", "you", "we", "it", "this", "that", "like", "id", "d",
               "la", "lah", "lor", "leh", "meh", "mah", "ah", "boss", "bro", "tapau", "dabao", "can", "or",
               "not", "got", "one", "ok", "k"}
UNIT_WORDS = {"bungkus", "keping", "biji", "cucuk", "pcs", "pc", "pieces", "piece", "cawan", "cup", "cups",
              "packs", "pack", "box", "kotak", "set", "dozen"}
NEGATION = ["tak nak", "taknak", "tidak", "jangan", "dont", "don t", "do not", "no ", "without", "tanpa",
            "except", "kecuali", "not "]


def _as_number(tok):
    t = tok[1:] if tok.startswith("x") and tok[1:].isdigit() else tok
    if t.isdigit():
        return int(t)
    return _MALAY.get(t)


def _qty_before(tokens, s):
    k = s - 1
    if k >= 0 and tokens[k] in UNIT_WORDS:
        k -= 1
    return _as_number(tokens[k]) if k >= 0 else None


def _qty_after(tokens, e):
    k = e
    if k < len(tokens) and tokens[k] in UNIT_WORDS and k + 1 < len(tokens) and _as_number(tokens[k + 1]) is not None:
        return _as_number(tokens[k + 1])          # 'nasi lemak bungkus dua'
    if k < len(tokens) and _as_number(tokens[k]) is not None:
        return _as_number(tokens[k])
    return None


def _num_index_before(tokens, s):
    k = s - 1
    if k >= 0 and tokens[k] in UNIT_WORDS:
        k -= 1
    return k if k >= 0 and _as_number(tokens[k]) is not None else None


def _num_index_after(tokens, e):
    k = e
    if k < len(tokens) and tokens[k] in UNIT_WORDS and k + 1 < len(tokens) and _as_number(tokens[k + 1]) is not None:
        return k + 1
    return k if k < len(tokens) and _as_number(tokens[k]) is not None else None


NOODLE_WORDS = {"goreng", "rebus", "hoon", "kari", "bandung", "siam", "jawa", "sup", "soup", "kuah", "mamak"}


def _fix_spelling(tokens):
    """Common Malaysian spellings: 'me goreng' -> 'mee goreng'."""
    return ["mee" if t == "me" and i + 1 < len(tokens) and tokens[i + 1] in NOODLE_WORDS else t
            for i, t in enumerate(tokens)]


def code_read(message, menu):
    """Plain-code reader: finds menu items in the message, allowing spelling mistakes.
    Used to double-check the AI, and on its own when the AI is down."""
    tokens = _fix_spelling(_norm(message).split())
    names = [(_norm(n), m["id"]) for m in menu.values() for n in [m["name"]] + m["aliases"] if _norm(n)]

    exact_names = {n for n, _ in names}

    def usable(span):
        first, last = tokens[span[0]], tokens[span[-1]]
        words = " ".join(tokens[k] for k in span)
        if any(_as_number(tokens[k]) is not None for k in span):
            return False
        if any(tokens[k] in UNIT_WORDS for k in span) and words not in exact_names:   # 'Nasi Lemak Bungkus' ok
            return False
        return first not in READER_STOP and last not in READER_STOP

    taken, hits = set(), []
    for exact in (True, False):                 # exact names first, then spelling mistakes
        for size in (3, 2, 1):
            for s in range(len(tokens) - size + 1):
                span = list(range(s, s + size))
                if any(k in taken for k in span) or not usable(span):
                    continue
                words = " ".join(tokens[s:s + size])
                if exact:
                    mid = next((m_ for n, m_ in names if words == n), None)
                else:
                    if len(words.replace(" ", "")) < 5:
                        continue
                    best, score = None, 0.0
                    for n, m_ in names:
                        if not _similar_length(words, n):   # 'goreng' alone is not 'mee goreng'
                            continue
                        sc = _similar(words, n)
                        if sc > score:
                            best, score = m_, sc
                    mid = best if score >= TYPO_CUTOFF else None
                if mid:
                    taken.update(span)
                    hits.append((s, s + size, words, mid))
    hits.sort()
    if not hits:
        return []
    # Do customers write the number before ("10 karipap") or after ("karipap 10")?
    # Look at where the first number in the whole message is, compared with the first food.
    nums = [k for k, t in enumerate(tokens) if _as_number(t) is not None]
    before_style = bool(nums) and nums[0] < hits[0][0]
    claimed, picks = set(), []
    for s, e, words, mid in hits:                # 1st choice: 'karipap x10' binds tightly; else the style
        k_after, k_before = _num_index_after(tokens, e), _num_index_before(tokens, s)
        if k_after is not None and tokens[k_after].startswith("x"):
            k = k_after
        else:
            k = k_before if before_style else k_after
        if k is not None and k in claimed:
            k = None
        if k is not None:
            claimed.add(k)
        picks.append(k)
    found = []
    for (s, e, words, mid), k in zip(hits, picks):
        if k is None:                            # 2nd choice: the other side, if no other food owns it
            for alt in (_num_index_after(tokens, e), _num_index_before(tokens, s)):
                if alt is not None and alt not in claimed:
                    k = alt
                    claimed.add(alt)
                    break
        found.append({"said": words, "menu_id": mid, "quantity": _as_number(tokens[k]) if k is not None else None})
    return found


def _qty_for_words(message, said):
    """Number written next to some words in the message ('2 nasi goreng', 'satay x15')."""
    tokens, target = _norm(message).split(), _norm(said).split()
    if not target:
        return None
    for s in range(len(tokens) - len(target) + 1):
        if tokens[s:s + len(target)] == target:
            e = s + len(target)
            k_after = _num_index_after(tokens, e)
            if k_after is not None and tokens[k_after].startswith("x"):
                return _as_number(tokens[k_after])
            k = _num_index_before(tokens, s)
            if k is None:
                k = k_after
            return _as_number(tokens[k]) if k is not None else None
    return None


ORDER_PHRASES = ["can i get", "can i have", "can get", "i want", "i d like", "id like", "i would like",
                 "give me", "nak", "nk", "mau", "order", "bagi", "tapau", "dabao", "tolong", "want", "get me",
                 "please", "pls", "boleh dapat", "saya nak", "one more", "add"]


def order_attempt(message):
    """A number + an order phrase ('2 me rebus please') — someone is trying to order something."""
    t = " " + _norm(message) + " "
    has_number = any(_as_number(w) is not None for w in _norm(message).split())
    return has_number and any(" " + p + " " in t for p in ORDER_PHRASES)


def follow_up_item(message, menu, history):
    """'8 then', 'ok 5 je', 'can i get 8?' with no food named, right after ONE food was discussed."""
    if not history:
        return None
    words = _norm(message).split()
    numbers = [n for n in (_as_number(w) for w in words) if n is not None]
    if len(numbers) != 1 or code_read(message, menu) or len(words) > 7:
        return None
    if mentions_change(message) or needs_owner_topic(message) or has_negation(message) \
            or repeat_multiplier(message) or refers_to_last_order(message):
        return None
    for who, text in reversed(history[-6:]):    # the CUSTOMER's most recent message that names food
        if who != "customer":                    # never the bot's lists or examples ('10 karipap')
            continue
        found = {c["menu_id"] for c in code_read(text, menu)}
        if found:
            if len(found) != 1:
                return None                      # several foods -> which one? let the owner check
            return {"menu_id": found.pop(), "said": "(from earlier)", "quantity": numbers[0]}
    return None


def looks_like_order(message, menu):
    """An order phrase + a number + a menu food = an order, whatever the AI said."""
    t = " " + _norm(message) + " "
    if mentions_change(message) or needs_owner_topic(message) or has_negation(message):
        return False
    found = code_read(message, menu)
    return bool(found) and any(c["quantity"] for c in found) and any(" " + p + " " in t for p in ORDER_PHRASES)


def has_negation(message):
    t = " " + _norm(message).replace("or not", " ") + " "     # 'can or not?' is not a negation
    return any(w in t for w in NEGATION)


def fallback_read(message, menu):
    """Reader used when the AI is down. Always labelled 'fallback' and never auto-accepted."""
    return code_read(message, menu)


# ------------------------------------------------------------------ safety guardrail (no AI)
CHANGE_WORDS = ["cancel", "batal", "tukar", "ubah", "tak jadi", "change my order",
                "change order", "refund", "make it", "make that", "change it", "change to", "jadikan",
                "tukar jadi", "kurangkan", "reduce", "instead of"]


def mentions_change(message):
    """True if the customer seems to be changing/cancelling an old order (typos like 'cancle' too)."""
    t = message.lower()
    if any(re.search(r"\b" + re.escape(w) + r"\b", t) for w in CHANGE_WORDS):
        return True
    words = _norm(message).split()
    return any(len(w) >= 4 and _similar(w, key) >= 0.8
               for w in words for key in ("cancel", "batal", "refund", "tukar"))


QUESTION_WORDS = ["lagi tak", "ada tak", "ada lagi", "masih ada", "still have", "still got",
                  "available", "do you have", "got any", "or not", " meh", "got ", "still got"]


def is_stock_question(message, notes):
    """'ada nasi lemak lagi tak?' asks IF there is stock; it is not an order.
    Caught when the message is a question AND the customer gave no quantity."""
    t = message.lower()
    asked = "?" in t or any(w in t for w in QUESTION_WORDS) or bool(
        re.search(r"\b(apa|what|how|is|are|does|do|ke|kah)\b", t) and not re.search(r"\b(nak|want|order|get)\b", t))
    no_number = not any(_as_number(w) is not None for w in _norm(message).split())
    return asked and no_number


# ------------------------------------------------------------------ food questions
QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "is_food_question": {"type": "boolean"},
        "foods": {"type": "array", "items": {
            "type": "object",
            "properties": {"said": {"type": "string"}, "menu_id": {"type": ["string", "null"]}},
            "required": ["said", "menu_id"]}},
    },
    "required": ["is_food_question", "foods"],
}

QUESTION_PROMPT = (
    "A customer sent this WhatsApp message to {business}:\n\"\"\"{message}\"\"\"\n\n"
    "MENU (id: name):\n{menu}\n\n"
    "Is the customer asking ABOUT a food or drink (what it is, what is in it, how it tastes, "
    "whether it is available, whether we sell it, its price)? Greetings, thank-yous, opening hours, "
    "delivery and payment questions are NOT food questions.\n"
    "List each food or drink they ask about: said = the name they used, menu_id = the matching "
    "id from the MENU or null if we do not sell it.\n"
    "Return ONE JSON object only: "
    "{{\"is_food_question\": true, \"foods\": [{{\"said\": \"<name>\", \"menu_id\": \"<id or null>\"}}]}}"
)

DESCRIBE_PROMPT = (
    "A customer of {business} asked:\n\"\"\"{message}\"\"\"\n\n"
    "Describe {name} for them in {language}, in 1 or 2 short, simple sentences.\n"
    "Use ONLY this information: {desc}\n"
    "{rule}\n"
    "Do NOT mention price, stock, availability, halal status or allergens. "
    "Write only the sentences, nothing else."
)
RULE_GENERAL = ("This information is about this kind of food in general, not our own recipe, "
                "so describe it with 'usually' (English) or 'biasanya' (Malay).")
RULE_OWNER = "This is the owner's own description of our product, so you may state it directly."


def _wiki_cache():
    try:
        return json.load(open(WIKI_CACHE, encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def wiki_lookup(name):
    """Short general description of a food from Wikipedia. Returns (text, url) or (None, None).
    Results are cached in data/wiki_cache.json so the demo works offline after the first time."""
    if not USE_WIKIPEDIA:
        return None, None
    cache = _wiki_cache()
    if name.lower() in cache:
        c = cache[name.lower()]
        return c.get("text"), c.get("url")
    import urllib.parse, urllib.request
    headers = {"User-Agent": "SlipMatch-hackathon/1.0 (student project)"}
    try:
        q = urllib.parse.urlencode({"action": "query", "list": "search", "format": "json",
                                    "srlimit": 1, "srsearch": f"{name} Malaysian food"})
        req = urllib.request.Request(f"https://en.wikipedia.org/w/api.php?{q}", headers=headers)
        hits = json.load(urllib.request.urlopen(req, timeout=8))["query"]["search"]
        if not hits:
            text, url = None, None
        else:
            title = urllib.parse.quote(hits[0]["title"].replace(" ", "_"))
            req = urllib.request.Request(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}", headers=headers)
            page = json.load(urllib.request.urlopen(req, timeout=8))
            text = (page.get("extract") or "").strip()[:700] or None
            url = page.get("content_urls", {}).get("desktop", {}).get("page")
    except Exception:
        return None, None                   # no internet / Wikipedia down -> just skip it
    cache[name.lower()] = {"text": text, "url": url}
    try:
        os.makedirs(os.path.dirname(WIKI_CACHE) or ".", exist_ok=True)
        json.dump(cache, open(WIKI_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except OSError:
        pass
    return text, url


def _description_for(m):
    """(description text, written_by_owner, sources). Owner's own words always win."""
    if m["description"]:
        return m["description"], True, ["owner description (menu.csv)"]
    text, url = wiki_lookup(m["name"])
    if text:
        return text, False, [f"wikipedia: {url}"]
    return None, False, []


def _price_stock_line(m, lang):
    """Price and availability are written by code, never by the AI, so they are always exact."""
    p, left = m["price_myr"], m["stock_qty"]
    if lang == "ms":
        return (f"{m['name']} RM {p:.2f} setiap satu, ada {left} lagi hari ini." if left > 0 else
                f"{m['name']} RM {p:.2f} setiap satu, tapi maaf, sudah habis hari ini.")
    return (f"{m['name']} is RM {p:.2f} each, and we have {left} left today." if left > 0 else
            f"{m['name']} is RM {p:.2f} each, but sorry, it's sold out today.")


GENERIC_WORDS = {"today", "now", "menu", "food", "foods", "drink", "drinks", "anything", "something",
                 "everything", "item", "items", "stuff", "dish", "dishes", "kuih", "makanan", "minuman",
                 "hari ini", "harini", "sekarang", "apa", "apa apa", "semua", "you", "we", "it", "this",
                 "that", "what", "hello", "hi", "available", "special", "specials", "recommendation"}


def _is_generic(said):
    """'today', 'menu', 'food'... are not the name of a dish."""
    return re.sub(r"[^a-z ]", " ", (said or "").lower()).strip() in GENERIC_WORDS


QUESTION_FILLER = {"do", "does", "have", "has", "sell", "got", "serve", "any", "are", "is", "there", "today",
                   "hari", "ini", "harini", "tomorrow", "esok", "now", "you", "u", "we", "what", "whats", "which",
                   "anything", "else", "else?", "kau", "awak", "korang", "jual", "ada", "apa", "boleh", "can"}


def _content_words(said):
    """Words left after removing question/filler words ('what do you have today' -> nothing)."""
    return [w for w in _norm(said).split()
            if w not in QUESTION_FILLER and w not in READER_STOP and w not in GENERIC_WORDS]


def _mentioned(food, message, menu):
    """Grounding check: the food must really appear in the customer's message
    (by the words the AI quoted, or by the menu item's name/alias), allowing small typos."""
    grams = _ngrams(message)
    said = _norm(food.get("said"))
    if said and (said in grams or any(_similar(said, g) >= TYPO_CUTOFF for g in grams)):
        return True
    m = menu.get(food.get("menu_id"))
    if m:
        for n in [m["name"]] + m["aliases"]:
            nn = _norm(n)
            if nn and (nn in grams or any(_similar(nn, g) >= TYPO_CUTOFF for g in grams)):
                return True
    return False


FOOD_QUESTION_WORDS = ["sell", "have", "got", "serve", "menu", "what is", "what's", "whats",
                       "ada", "jual", "apa itu", "apa tu", "buat", "available", "do you make"]


def _asks_about_food(message):
    """Only reply 'we don't have X' if the customer really asked about having/selling food.
    Stops 'hello, are you open today?' from becoming "we don't have 'hello'"."""
    t = " " + re.sub(r"[^a-z' ]", " ", message.lower()) + " "
    return any(" " + w + " " in t for w in FOOD_QUESTION_WORDS)


def answer_question(message, menu, lang):
    """If the message asks about food, return (reply, foods, sources). Otherwise None."""
    raw = _call_ai(QUESTION_PROMPT.format(business=BUSINESS, message=message,
                                          menu=menu_for_prompt(menu)), QUESTION_SCHEMA, max_tokens=200)
    q = _parse_json(raw)
    if not q.get("is_food_question") or not q.get("foods"):
        # AI said no, but the customer clearly named a menu food in a question ('fried noodles habis meh?')
        named = code_read(message, menu)
        if named and is_stock_question(message, []):
            q = {"is_food_question": True, "foods": [{"said": c["said"], "menu_id": c["menu_id"]} for c in named]}
        else:
            return None

    on_menu, not_on_menu, seen = [], [], set()
    for f in q["foods"]:
        if not _mentioned(f, message, menu):   # AI named a food the customer never wrote -> ignore it
            continue
        if _is_generic(f.get("said")) or not _content_words(f.get("said")):   # 'today', 'you have'... not dishes
            continue
        mid = f.get("menu_id") if f.get("menu_id") in menu else _find_menu_id(f.get("said"), menu)
        if mid and mid not in seen:
            seen.add(mid)
            on_menu.append(menu[mid])
        elif not mid and f.get("said") and _asks_about_food(message):
            not_on_menu.append(str(f["said"]).strip())

    if not on_menu and not not_on_menu:          # AI's foods didn't check out -> use what code finds
        named = code_read(message, menu) if is_stock_question(message, []) or "?" in message else []
        for c in named:
            if c["menu_id"] not in seen:
                seen.add(c["menu_id"])
                on_menu.append(menu[c["menu_id"]])
        if not on_menu:                          # nothing real left -> not a food question
            return None

    parts, sources = [], []
    language = "Malay (Bahasa Melayu)" if lang == "ms" else "English"
    for m in on_menu:
        desc, by_owner, src_ = _description_for(m)
        if desc:
            try:
                text = _call_ai(DESCRIBE_PROMPT.format(
                    business=BUSINESS, message=message, name=m["name"], language=language,
                    desc=desc, rule=RULE_OWNER if by_owner else RULE_GENERAL),
                    max_tokens=120, temperature=0.2).strip().strip('"')
                if text:
                    parts.append(text)
                    sources += src_
            except Exception:
                pass                        # no description is fine; price/stock still answered
        parts.append(_price_stock_line(m, lang))
    if any(m["stock_qty"] > 0 for m in on_menu):
        parts.append("Nak order?" if lang == "ms" else "Would you like to order some?")
    if not_on_menu:
        names = ", ".join(f"'{n}'" for n in not_on_menu)
        some = ", ".join(m["name"] for m in list(menu.values())[:5])
        parts.append(f"Maaf, kami tiada {names} dalam menu. Antara menu kami: {some}."
                     if lang == "ms" else
                     f"Sorry, we don't have {names} on our menu. Some of what we offer: {some}.")
    return " ".join(parts), [m["name"] for m in on_menu] + not_on_menu, sources


# ------------------------------------------------------------------ conversation (greetings, small talk)
CHAT_SCHEMA = {
    "type": "object",
    "properties": {"reply": {"type": "string"}, "needs_owner": {"type": "boolean"}},
    "required": ["reply", "needs_owner"],
}

CHAT_PROMPT = (
    "You are the friendly WhatsApp assistant of {business}.\n\n"
    "TODAY'S MENU (the only facts you may use):\n{menu_facts}\n\n"
    "Conversation so far:\n{history}\n\n"
    "Customer's new message:\n\"\"\"{message}\"\"\"\n\n"
    "Customers often write Manglish (Malaysian English: la, lah, lor, meh, 'can or not', 'got or not', "
    "'tapau' = takeaway, 'boss') — that is normal friendly talk, not a problem.\n"
    "Reply in {language}, in 1 to 3 short friendly sentences, like a real person texting.\n"
    "You MAY: greet, thank, chat briefly, tell them what is on the menu with the prices and "
    "availability above, and explain how to order (for example 'nak 10 karipap').\n"
    "You must NEVER: say an order is confirmed, added or cancelled; invent dishes, prices, "
    "opening hours, delivery, location or payment details.\n"
    "If they say yes/ok but nothing is waiting for an answer, ask what they would like to order.\n"
    "Do not list the whole menu unless they ask what you have.\n"
    "If they ask something these facts cannot answer (opening hours, delivery, payment, location, "
    "complaints, changing or cancelling an order), say politely that the owner will reply soon "
    "and set needs_owner to true. Otherwise needs_owner is false.\n"
    "Return JSON only: {{\"reply\": \"<your message>\", \"needs_owner\": false}}"
)


def _menu_facts(menu):
    return "\n".join(f"- {m['name']}: RM {m['price_myr']:.2f} each, "
                     f"{str(m['stock_qty']) + ' left today' if m['stock_qty'] > 0 else 'SOLD OUT today'}"
                     for m in menu.values())


def _history_text(history):
    if not history:
        return "(this is the first message)"
    return "\n".join(f"{'Customer' if who == 'customer' else 'You'}: {text}" for who, text in history[-6:])


OWNER_TOPICS = ["open", "opening", "close", "closing", "hours", "buka", "tutup", "deliver", "delivery",
                "hantar", "penghantaran", "grab", "foodpanda", "location", "address", "alamat", "where are you",
                "where is", "where s", "your shop", "kedai kat", "lokasi",
                "kat mana", "dekat mana", "pay", "payment", "bayar", "bank", "transfer", "duitnow", "qr",
                "refund", "halal", "allergy", "allergic", "alergi", "complain", "complaint", "aduan", "discount",
                "diskaun", "promo", "booking", "reserve", "tempah meja"]


def needs_owner_topic(message):
    """Topics the bot has no facts about. The owner must answer these, whatever the AI says."""
    t = " " + re.sub(r"[^a-z ]", " ", message.lower()) + " "
    return any(" " + w + " " in t for w in OWNER_TOPICS)


MENU_QUESTIONS = ["what do you have", "what you have", "what do u have", "what have you got", "whats on the menu",
                  "what s on the menu", "what is on the menu", "show me the menu", "the menu", "your menu", "menu",
                  "what do you sell", "what you sell", "what s available", "whats available", "what is available",
                  "apa ada", "ada apa", "menu apa", "jual apa", "apa yang ada", "senarai menu",
                  "got what", "what got", "today got what", "got anything", "sell what", "ada jual apa"]


def is_menu_question(message):
    t = " " + _norm(message) + " "
    return any(" " + q + " " in t for q in MENU_QUESTIONS)


def menu_reply(menu, lang, manglish=False):
    """The real menu, written by code (always exact)."""
    avail = [f"{m['name']} (RM {m['price_myr']:.2f})" for m in menu.values() if m["stock_qty"] > 0]
    sold = [m["name"] for m in menu.values() if m["stock_qty"] <= 0]
    if manglish and lang != "ms":
        txt = "Today got: " + ", ".join(avail) + "."
        if sold:
            txt += " " + ", ".join(sold) + " habis already."
        return txt + ' What you want ah? Can type like "10 karipap".'
    if lang == "ms":
        txt = "Hari ini kami ada: " + ", ".join(avail) + "."
        if sold:
            txt += " Maaf, " + ", ".join(sold) + " sudah habis."
        return txt + " Nak order apa? Contoh: \"nak 10 karipap\"."
    txt = "Today we have: " + ", ".join(avail) + "."
    if sold:
        txt += " Sorry, " + ", ".join(sold) + (" is" if len(sold) == 1 else " are") + " sold out."
    return txt + ' What would you like? For example: "10 karipap".'


def owner_handoff(lang):
    return ("Terima kasih! Saya dah sampaikan kepada pemilik, dia akan balas sekejap lagi."
            if lang == "ms" else "Thanks! I've passed this to the owner, they'll reply to you shortly.")


def chat_reply(message, menu, lang, history=None):
    """Natural reply for greetings/small talk. Returns (reply, needs_owner)."""
    language = "Malay (Bahasa Melayu)" if lang == "ms" else "English"
    if is_manglish(message) and lang != "ms":
        language = ("friendly Malaysian English (Manglish) like a local shop assistant — a little lah/ah "
                    "is fine, use your own words, stay easy to understand")
    raw = _call_ai(CHAT_PROMPT.format(business=BUSINESS, menu_facts=_menu_facts(menu),
                                      history=_history_text(history), message=message,
                                      language=language),
                   CHAT_SCHEMA, max_tokens=200, temperature=0.4)
    d = _parse_json(raw)
    reply = str(d.get("reply") or "").strip()
    if claims_order(reply):                     # only the order checker may confirm orders
        reply = not_sure_reply(lang, message)
    return (reply or owner_handoff(lang)), bool(d.get("needs_owner", not reply))


ORDER_CLAIMS = ["confirmed", "coming up", "added to your order", "order placed", "on the way", "diterima",
                "dah masuk", "dimasukkan", "processing your order", "preparing your", "got your order",
                "noted your order", "your order is", "order anda", "sudah diorder", "will be ready"]


def claims_order(reply):
    r = reply.lower()
    return "×" in reply or any(w in r for w in ORDER_CLAIMS)


def not_sure_reply(lang, message=""):
    if lang == "ms":
        return 'Maaf, saya kurang faham. Boleh tulis macam ni: "nak 10 karipap", atau tanya "menu".'
    if is_manglish(message):
        return 'Sorry boss, not so sure what you mean. Can type like "10 karipap", or ask "today got what?"'
    return 'Sorry, I\'m not sure what you mean. You can order like "10 karipap", or ask "what do you have today?"'



GREETING_WORDS = {"hi", "hii", "hiii", "hello", "helo", "hellooo", "hey", "hai", "hye", "yo", "morning",
                  "good", "afternoon", "evening", "night", "pagi", "petang", "malam", "selamat", "assalamualaikum",
                  "salam", "thanks", "thank", "you", "tq", "ty", "tqvm", "terima", "kasih", "noted", "nice",
                  "great", "sure", "alright", "orait", "baik", "okey", "okk", "oki", "cool", "sip", "mantap",
                  "best", "there"} | PARTICLES


def is_greeting(message):
    """'hello la', 'hai boss', 'tq lor', 'ok noted kak' -> just friendly talk."""
    words = _norm(message).split()
    return bool(words) and all(w in GREETING_WORDS for w in words)


def greeting_reply(message, lang):
    words = _norm(message).split()
    thanks = any(w in words for w in ("thanks", "thank", "tq", "ty", "tqvm", "kasih"))
    ack = any(w in words for w in ("ok", "okay", "okey", "okk", "oki", "noted", "good", "great", "nice", "baik",
                                   "sip", "cool", "alright", "orait", "sure", "mantap", "best"))
    if lang == "ms":
        if thanks:
            return "Sama-sama! Ada apa-apa lagi yang ingin dipesan?"
        if ack:
            return "Baik! Ada apa-apa lagi yang ingin dipesan?"
        return "Hai, selamat datang! Apa yang ingin anda pesan hari ini?"
    if thanks:
        return "You're welcome! Is there anything else you would like to order?"
    if ack:
        return "Great! Is there anything else you would like to order?"
    return "Hello, welcome! What would you like to order today?"


CLOSING_PHRASES = ["that s all", "thats all", "that is all", "that s it", "thats it", "that will be all",
                   "that ll be all", "nothing else", "no more", "no thanks", "no thank you", "all done", "done",
                   "i m done", "im done", "itu sahaja", "itu je", "tu je", "tu sahaja", "dah cukup", "cukup",
                   "takde", "tak ada", "tak ada lagi", "takde lagi", "nope", "nothing", "no", "dah", "tu saja",
                   "that s enough", "enough"]


def is_closing(message):
    """'no that's all', 'nothing else', 'dah cukup' -> the customer is finished."""
    t = " " + _norm(message) + " "
    if any(_as_number(w) is not None for w in t.split()):
        return False
    return any(" " + p + " " in t for p in CLOSING_PHRASES) and \
        all(w in GREETING_WORDS or w in {"no", "nope", "that", "s", "thats", "is", "it", "all", "nothing",
                                            "else", "more", "done", "i", "m", "im", "will", "be", "ll", "itu",
                                            "tu", "sahaja", "saja", "je", "dah", "cukup", "takde", "tak", "ada",
                                            "lagi", "enough", "for", "now", "today", "already", "liao", "lah",
                                            "la", "thx", "thanks", "thank", "you", "so", "much"}
            for w in t.split())


def closing_reply(past_orders, lang):
    """Friendly goodbye with the exact order summary (written by code)."""
    if past_orders:
        so_far = {}
        for o in past_orders:
            for it in o["items"]:
                so_far[it["name"]] = so_far.get(it["name"], 0) + it["quantity"]
        body = ", ".join(f"{n} × {q}" for n, q in so_far.items())
        total = round(sum(o["total_myr"] for o in past_orders), 2)
        if lang == "ms":
            return f"Terima kasih atas pesanan anda! {body}. Jumlah RM {total:.2f}. Semoga hari anda indah!"
        return f"Thank you for your order! {body}. Total RM {total:.2f}. Have a nice day!"
    if lang == "ms":
        return "Baik, terima kasih! Mesej kami bila-bila masa jika ingin memesan."
    return "Alright, thank you! Message us anytime you would like to order."


LANG_QUESTION = ("Hello, welcome! \U0001F44B Which language would you prefer?\n"
                 "Reply 1 for English, 2 for Bahasa Melayu.\n"
                 "Hai, selamat datang! Pilih bahasa: balas 1 untuk English, 2 untuk Bahasa Melayu.")
LANG_QUESTION_MARK = "Which language would you prefer"
LANG_CHOICES = {"en": {"1", "one", "satu", "english", "eng", "en", "inggeris", "bahasa inggeris"},
                "ms": {"2", "two", "dua", "bm", "melayu", "malay", "bahasa melayu", "bahasa malaysia", "ms"}}


def greeting_kind(message):
    words = _norm(message).split()
    if any(w in words for w in ("thanks", "thank", "tq", "ty", "tqvm", "kasih")):
        return "thanks"
    if any(w in words for w in ("ok", "okay", "okey", "okk", "oki", "noted", "good", "great", "nice", "baik",
                                "sip", "cool", "alright", "orait", "sure", "mantap", "best")):
        return "ack"
    return "hello"


def language_choice(message, history):
    """Answer to the 'Which language would you prefer?' question -> 'en' / 'ms'."""
    if not history or not any(w == "bot" and LANG_QUESTION_MARK in t for w, t in history[-2:]):
        return None
    t = " ".join(w for w in _norm(message).split() if w not in PARTICLES and w not in {"please", "pls"})
    for lang, choices in LANG_CHOICES.items():
        if t in choices:
            return lang
    return None


# ------------------------------------------------------------------ conversation memory helpers
REFERENCE_WORDS = ["same", "again", "that", "those", "it", "more", "another", "extra", "also", "too",
                   "lagi", "tambah", "sama", "tu", "itu", "juga", "jugak", "macam tadi", "semalam", "tadi"]
MY_ORDER_QUESTIONS = ["what did i order", "what i ordered", "what have i ordered", "my order", "my orders",
                      "how much in total", "how much altogether", "how much is my", "total", "order saya",
                      "apa saya order", "saya order apa", "berapa semua", "berapa jumlah", "jumlah semua",
                      "berapa total"]


def refers_back(message):
    """Does the customer point at something said earlier ('same again', '2 more', 'tambah lagi')?"""
    t = " " + _norm(message) + " "
    return any(" " + w + " " in t for w in REFERENCE_WORDS)


LANG_REQUESTS = {
    "en": {"english", "in english", "speak english", "english please", "english pls", "eng", "reply in english",
           "can english", "english can", "use english", "english la", "english lah"},
    "ms": {"malay", "melayu", "bahasa melayu", "bm", "cakap melayu", "bahasa malaysia", "in malay",
           "malay please", "guna bm", "cakap bm", "bm boleh"},
}


def language_request(message):
    """'english' / 'bahasa melayu' on its own -> 'en' / 'ms'."""
    t = " ".join(w for w in _norm(message).split() if w not in {"please", "pls", "la", "lah", "boss", "can", "ok"}) \
        or _norm(message)
    for lang, phrases in LANG_REQUESTS.items():
        if t in phrases or _norm(message) in phrases:
            return lang
    return None


def is_my_order_question(message):
    t = " " + _norm(message) + " "
    return any(" " + q + " " in t for q in MY_ORDER_QUESTIONS)


def order_summary(past_orders, lang):
    """Exact list of what this customer confirmed in this chat, written by code."""
    lines, total = {}, 0.0
    for o in past_orders or []:
        for it in o["items"]:
            key = it["name"]
            lines[key] = lines.get(key, 0) + it["quantity"]
        total += o["total_myr"]
    if not lines:
        return ("Belum ada order lagi dalam chat ini. Nak order apa?" if lang == "ms"
                else "You haven't ordered anything in this chat yet. What would you like?")
    body = ", ".join(f"{n} × {q}" for n, q in lines.items())
    return (f"Order anda setakat ini: {body}. Jumlah RM {total:.2f}." if lang == "ms"
            else f"So far you've ordered: {body}. Total RM {total:.2f}.")


REPEAT_PHRASES = ["same again", "same as before", "same as last time", "same order", "the same", "repeat",
                  "repeat my order", "one more time", "again", "sama macam tadi", "sama macam semalam",
                  "macam tadi", "order sama", "sama", "ulang", "ulang order"]
CONFIRM_REPEATS = os.environ.get("CONFIRM_REPEATS", "true").lower() == "true"


def is_repeat_request(message):
    t = " " + _norm(message) + " "
    return any(" " + p + " " in t for p in REPEAT_PHRASES)


LAST_ORDER_PHRASES = ["this order", "that order", "last order", "previous order", "my last order", "the order",
                      "order tadi", "order ni", "order td", "order yang tadi", "order sebelum ni", "order itu"]


def refers_to_last_order(message):
    t = " " + _norm(message) + " "
    return any(" " + p + " " in t for p in LAST_ORDER_PHRASES)


def repeat_multiplier(message):
    """'twice', 'double', 'x2', '3 times', 'dua kali' -> 2/2/2/3/2. None if no multiplier."""
    t = _norm(message)
    if re.search(r"\b(twice|double)\b", t):
        return 2
    m = re.search(r"\bx\s?(\d+)\b", t) or re.search(r"\b(\d+)\s*(?:times|kali)\b", t)
    if m:
        return max(1, min(int(m.group(1)), 20))
    m = re.search(r"\b(" + "|".join(_MALAY) + r")\s+kali\b", t)
    if m:
        return _MALAY[m.group(1)]
    return None


def repeat_items(past_orders):
    """Everything this customer confirmed before, added up per item (built by code, not the AI)."""
    total = {}
    for o in past_orders or []:
        for it in o["items"]:
            if it.get("menu_id"):
                total[it["menu_id"]] = total.get(it["menu_id"], 0) + it["quantity"]
    return [{"menu_id": mid, "said": mid, "quantity": q} for mid, q in total.items()]


# ------------------------------------------------------------------ main entry
def check_order(message, menu=None, history=None, past_orders=None, lang_pref=None):
    """history: optional list of ("customer"|"bot", text) earlier in this chat.
    past_orders: optional list of orders this customer already confirmed (see sessions.py).
    lang_pref: 'en' or 'ms' if the customer asked for a reply language (result["set_language"])."""
    """Returns dict: decision (ACCEPT / PARTIAL / DECLINE / ANSWER / CHAT / NEEDS_REVIEW), reasons, items,
    total_myr, reply_draft, sources, language, read_by, latency_s, confidence, raw."""
    menu = menu or load_menu()
    t0, raw, err = time.time(), None, None

    def quick(decision, reply, reasons, lines=(), total=0.0, lang=None, extra=None):
        out = {"decision": decision, "reasons": reasons, "items": list(lines), "total_myr": total,
               "reply_draft": reply, "sources": [], "language": lang or lang_pref or reply_language(message),
               "read_by": "code", "latency_s": round(time.time() - t0, 2), "confidence": 1.0,
               "prompt_version": PROMPT_VERSION, "raw": None}
        out.update(extra or {})
        return out

    if is_closing(message):                     # 'no that's all' -> goodbye with the order summary
        lang = lang_pref or reply_language(message)
        return quick("CHAT", closing_reply(past_orders, lang), ["Customer is finished"], lang=lang)

    chosen = language_choice(message, history)   # '1' / '2' after the language question
    if chosen:
        reply = ("Baik! Apa yang ingin anda pesan hari ini?" if chosen == "ms"
                 else "Great! What would you like to order today?")
        return quick("CHAT", reply, [f"Customer chose {chosen}"], lang=chosen, extra={"set_language": chosen})

    if is_greeting(message) and not code_read(message, menu):     # 'hello la', 'tq boss' -> quick reply
        if not lang_pref and greeting_kind(message) == "hello":
            # first hello and no language chosen yet -> ask which language they prefer
            return quick("CHAT", LANG_QUESTION, ["Greeting — asked for language"], extra={"ask_language": True})
        lang = lang_pref or reply_language(message)
        return quick("CHAT", greeting_reply(message, lang), ["Greeting"], lang=lang)

    wanted = language_request(message)          # 'english' / 'bahasa melayu' -> switch reply language
    if wanted:
        reply = ("Baik! Saya akan balas dalam Bahasa Melayu. Nak order apa?" if wanted == "ms"
                 else "Sure! I'll reply in English from now on. What would you like to order?")
        return quick("CHAT", reply, [f"Customer asked for replies in {wanted}"], lang=wanted,
                     extra={"set_language": wanted})
    follow = follow_up_item(message, menu, history)
    if follow:
        # 'can i get 8 then?' right after talking about one food -> that food × 8 (ask to confirm)
        lang = lang_pref or reply_language(message)
        decision, reasons, lines, total = decide([follow], menu)
        if decision == "ACCEPT":
            decision = "CONFIRM"
        reply = reply_draft(decision, lines, total, menu, lang, past_orders)
        have = _already_ordered(past_orders).get(follow["menu_id"], 0)
        if decision == "CONFIRM" and have:      # '2 more' of something already ordered -> show the new total
            name, add = menu[follow["menu_id"]]["name"], follow["quantity"]
            reply = (f"Jadi jumlahnya {have + add} {name} (tambah {add}, +RM {total:.2f})? Balas YA untuk sahkan."
                     if lang == "ms" else
                     f"So in total you'd like {have + add} {name} ({add} more, +RM {total:.2f})? Reply YES to confirm.")
        return {"decision": decision,
                "reasons": [f"Number linked to {menu[follow['menu_id']]['name']} from the previous messages"] + reasons,
                "items": lines, "total_myr": total, "reply_draft": reply,
                "sources": [], "language": lang, "read_by": "code", "latency_s": round(time.time() - t0, 2),
                "confidence": 1.0, "prompt_version": PROMPT_VERSION, "raw": None}

    times = repeat_multiplier(message)
    last_only = refers_to_last_order(message)
    if past_orders and (is_repeat_request(message) or last_only or times) \
            and not code_read(message, menu) and not mentions_change(message):
        # 'same again' -> everything ordered before; 'this order x2' -> the last order × 2 (built by code)
        lang = lang_pref or reply_language(message)
        base = past_orders[-1:] if (last_only or (times and not is_repeat_request(message))) else past_orders
        items = repeat_items(base)
        for it in items:
            it["quantity"] *= (times or 1)
        decision, reasons, lines, total = decide(items, menu)
        if decision in ("ACCEPT", "PARTIAL") and CONFIRM_REPEATS:
            decision = "CONFIRM"
        return {"decision": decision, "reasons": ["Repeat of earlier orders (built from saved orders)"] + reasons,
                "items": lines, "total_myr": total,
                "reply_draft": reply_draft(decision, lines, total, menu, lang, past_orders),
                "sources": [], "language": lang, "read_by": "code", "latency_s": round(time.time() - t0, 2),
                "confidence": 1.0, "prompt_version": PROMPT_VERSION, "raw": None}
    if past_orders is not None and is_my_order_question(message) and not code_read(message, menu):
        lang = lang_pref or reply_language(message)
        return {"decision": "CHAT", "reasons": ["Answered from this customer's saved orders"],
                "items": [], "total_myr": 0.0, "reply_draft": order_summary(past_orders, lang),
                "sources": [], "language": lang, "read_by": "code", "latency_s": round(time.time() - t0, 2),
                "confidence": 1.0, "prompt_version": PROMPT_VERSION, "raw": None}
    data = None

    if os.environ.get("USE_FALLBACK", "false").lower() != "true":
        for _ in range(2):                          # one retry if the JSON is broken
            if time.time() - t0 > TIMEOUT_S - 3:
                break
            try:
                raw = _ask_ai(message, menu, history)
                data = _parse_json(raw)
                break
            except (ValueError, json.JSONDecodeError) as e:
                err = f"AI answer was not valid JSON: {e}"
            except Exception as e:                  # timeout, connection, anything
                err = f"AI unavailable: {type(e).__name__}"
                break

    if data is not None and is_greeting(message) and not code_read(message, menu):
        data = {**data, "is_order": False, "items": []}      # 'helo' is never an order
    ai_missed_order = False
    if data is not None and not data.get("is_order", True) and looks_like_order(message, menu):
        # 'can i get 10 me goreng?' is an order even if the AI thought it was a question
        data = {**data, "is_order": True,
                "items": [{"said": c["said"], "menu_id": c["menu_id"], "quantity": c["quantity"]}
                          for c in code_read(message, menu)]}
        ai_missed_order = True
    if data is not None:
        read_by = f"runpod:{ENDPOINT_ID}"
        items, notes = clean_items(data.get("items"), menu)
        grams = _ngrams(message)
        keep_from_history = bool(history and refers_back(message) and not code_read(message, menu))
        grounded = []
        for it in items:                        # the AI may only list food the customer actually wrote
            said = _norm(it["said"])
            in_text = said and (said in grams or any(_similar(said, g) >= TYPO_CUTOFF for g in grams))
            if it["menu_id"] is None:
                if not _content_words(it["said"]) or _is_generic(it["said"]) or not in_text:
                    notes.append(f"Ignored '{it['said']}': not a food the customer wrote")
                    continue
            elif not in_text and not _mentioned({"said": it["said"], "menu_id": it["menu_id"]}, message, menu):
                said_before = keep_from_history and any(
                    it["menu_id"] in {c["menu_id"] for c in code_read(t, menu)}
                    for w, t in (history or [])[-6:] if w == "customer")
                if not said_before:              # only food the CUSTOMER wrote, now or earlier
                    notes.append(f"Ignored {menu[it['menu_id']]['name']}: the customer never asked for it")
                    continue
            grounded.append(it)
        items = grounded
        for it in items:                        # off-menu food: read its number from the message too
            if it["menu_id"] is None and not it.get("ai_qty"):
                q = _qty_for_words(message, it["said"])
                if q:
                    it["quantity"] = q
        added, disagree, from_history = False, [], False
        if data.get("is_order", True):          # double-check the AI with the code reader
            code_items = code_read(message, menu)
            in_msg = {c["menu_id"] for c in code_items}
            # With history, the AI must not copy items from earlier messages. Keep an item that is
            # not written in this message only if the message names no food AND points back
            # ('same again', '2 more', 'tambah lagi').
            from_history = bool(history and not in_msg and refers_back(message)
                                and any(it["menu_id"] in menu for it in items))
            if history and (in_msg or not refers_back(message)):
                kept = []
                for it in items:
                    if it["menu_id"] in menu and it["menu_id"] not in in_msg:
                        notes.append(f"Removed {menu[it['menu_id']]['name']}: not in this message "
                                     f"(only mentioned earlier)")
                    else:
                        kept.append(it)
                items = kept
            have = {i["menu_id"] for i in items}
            for c in code_items:                # same item: do the quantities agree?
                for it in items:
                    if it["menu_id"] == c["menu_id"] and c["quantity"] is not None \
                            and c["quantity"] != it["quantity"]:
                        name = menu[c["menu_id"]]["name"]
                        n_numbers = sum(_as_number(t) is not None for t in _norm(message).split())
                        simple = len(code_items) == 1 and len(items) == 1 and n_numbers == 1
                        if not it.get("ai_qty") or simple:   # one food + one number: nothing to confuse
                            notes.append(f"Quantity for {name} taken from the message: {c['quantity']}")
                            it["quantity"] = c["quantity"]
                        else:
                            disagree.append(f"{name}: AI read {it['quantity']}, spelling check read {c['quantity']}")
            for c in code_items:
                if c["menu_id"] not in have:
                    q = c["quantity"] or 1
                    items.append({"menu_id": c["menu_id"], "said": c["said"], "quantity": q})
                    have.add(c["menu_id"])
                    added = True
                    notes.append(f"AI missed '{c['said']}', added by spelling check as "
                                 f"{menu[c['menu_id']]['name']} × {q}")
        try:
            conf = max(0.0, min(1.0, float(data.get("confidence", 0))))
        except (TypeError, ValueError):
            conf = 0.0
        decision, reasons, lines, total = decide(items, menu, bool(data.get("is_order", True)), conf)
        if ai_missed_order:
            reasons = ["AI did not see an order here — read by the spelling check"] + reasons
            if decision == "ACCEPT":
                decision = "CONFIRM"            # we read it ourselves -> ask the customer first
        if from_history and decision in ("ACCEPT", "PARTIAL"):
            decision = "CONFIRM"                # built from earlier messages -> ask before confirming
            reasons = ["Order rebuilt from earlier messages — asking the customer to confirm"] + reasons
        if disagree and decision in ("ACCEPT", "PARTIAL", "CONFIRM"):
            decision = "NEEDS_REVIEW"           # two readers disagree on an amount -> don't guess
            reasons = ["Quantities unclear — owner should check: " + "; ".join(disagree)] + reasons
        if added and has_negation(message) and decision in ("ACCEPT", "PARTIAL"):
            decision = "NEEDS_REVIEW"           # 'tak nak karipap, 2 teh tarik' -> don't guess, ask the owner
            reasons = ["Order mentions something the customer may NOT want — owner should check"] + reasons
    else:
        read_by, conf = "fallback", 0.0
        items, notes = clean_items(fallback_read(message, menu), menu)
        decision, reasons, lines, total = decide(items, menu)
        if decision in ("ACCEPT", "PARTIAL"):       # never auto-accept without the AI
            decision = "NEEDS_REVIEW"
        reasons = ["AI not used — read by simple keyword matcher"] + ([err] if err else []) + reasons

    if mentions_change(message):                # safety net, whatever the AI said
        if decision != "NEEDS_REVIEW":
            reasons = ["Message talks about cancelling or changing an order — owner should check"] + reasons
        decision, lines, total = "NEEDS_REVIEW", [], 0.0
    stock_question = False
    if decision in ("ACCEPT", "PARTIAL", "DECLINE") and is_stock_question(message, notes):   # safety net 2
        decision, stock_question = "NEEDS_REVIEW", True
        reasons = ["Customer seems to be asking about stock, not ordering — owner should reply"] + reasons

    lang = lang_pref or reply_language(message)
    reply = reply_draft(decision, lines, total, menu, lang, past_orders)
    if decision == "ACCEPT" and past_orders:    # adding to earlier orders -> show the running total
        reply = added_reply(lines, total, past_orders, lang)
    sources = []

    # Not an order (or a stock question)? Maybe they are asking about a food -> answer it.
    not_an_order = data is not None and (not data.get("is_order", True) or stock_question)
    if not_an_order and not mentions_change(message) and not needs_owner_topic(message):
        try:
            ans = answer_question(message, menu, lang)
        except Exception as e:
            ans = None
            reasons.append(f"Could not answer the question automatically: {type(e).__name__}")
        if ans:
            reply, foods, sources = ans
            decision, lines, total = "ANSWER", [], 0.0
            reasons = [f"Customer asked about: {', '.join(foods)}"] + (
                [f"Description source: {s}" for s in sources] or ["No outside description used"])
            notes = []

    # Still nobody answered? Chat naturally, or tell the customer the owner will reply.
    if is_menu_question(message) and not code_read(message, menu) \
            and not mentions_change(message) and not needs_owner_topic(message):
        # 'what do you have today?' names no dish -> answer with the real menu, whatever the AI thought
        reply, decision = menu_reply(menu, lang, is_manglish(message)), "CHAT"
        lines, total, sources = [], 0.0, []
        reasons, notes = ["Menu question answered from the menu"], []
    short_number = len(_norm(message).split()) <= 4 and any(_as_number(w) is not None
                                                             for w in _norm(message).split())
    if decision == "NEEDS_REVIEW" and not reply and (any(c["quantity"] for c in code_read(message, menu))
                                                       or order_attempt(message) or short_number):
        reply = owner_handoff(lang)             # an amount of food is never small talk
        reasons = ["Message names an amount of food but was not understood — owner should check"] + reasons
    if decision == "NEEDS_REVIEW" and not reply:
        if data is not None and not lines and not mentions_change(message) and not needs_owner_topic(message):
            try:
                reply, needs_owner = chat_reply(message, menu, lang, history)
                if is_greeting(message):        # 'hello la' is never a job for the owner
                    needs_owner = False
                    if not reply or "owner" in reply.lower() or "pemilik" in reply.lower():
                        reply = greeting_reply(message, lang)
                if not needs_owner and not lines:
                    decision = "CHAT"
                    reasons = ["Small talk answered automatically"]
                    notes = []
                else:
                    reasons = ["Customer needs the owner: " + message[:60]] + reasons
            except Exception as e:
                if is_greeting(message):
                    reply, decision, reasons = greeting_reply(message, lang), "CHAT", ["Greeting (template reply)"]
                else:
                    reply = owner_handoff(lang)
                    reasons.append(f"Chat reply failed: {type(e).__name__}")
        else:
            reply = owner_handoff(lang)
            if needs_owner_topic(message):
                reasons = ["Question only the owner can answer (hours, delivery, payment...)"] + reasons

    return {
        "decision": decision,
        "reasons": reasons + notes,
        "items": lines,
        "total_myr": total,
        "reply_draft": reply,
        "sources": sources,
        "language": lang,
        "read_by": read_by,
        "latency_s": round(time.time() - t0, 2),
        "confidence": conf,
        "prompt_version": PROMPT_VERSION,
        "raw": raw,
    }


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]) or "nak 10 karipap dengan 2 nasi lemak"
    r = check_order(msg)
    r.pop("raw", None)
    print(json.dumps(r, indent=2, ensure_ascii=False))
