"""
Chat with the shop's bot like a customer on WhatsApp. The chat is saved, so it continues next time.

  python chat.py                 # chat as "guest"
  python chat.py --as ali        # chat as another customer (each has their own saved history)

It waits for you to text first. Commands:
  /history   show the saved conversation and orders
  /new       forget this customer's chat and start fresh
  /menu      show today's stock      /debug   show why the bot answered that way
  /reset     put stock back to menu.csv
  /quit      stop (the chat stays saved)
Stock only goes down inside this program; menu.csv is never changed.
"""
import argparse

import order_ai
import sessions

YES = {"yes", "y", "ya", "yaa", "ok", "okay", "boleh", "jadi", "setuju", "sure", "yup", "yep", "ok jadi"}
NO = {"no", "n", "tak", "tidak", "takpe", "tak nak", "x", "nope", "tak jadi"}


def show_menu(menu):
    print()
    for m in menu.values():
        stock = f"{m['stock_qty']} left" if m["stock_qty"] > 0 else "SOLD OUT"
        print(f"   {m['name']:<20} RM {m['price_myr']:>5.2f}   {stock}")
    print()


def show_history(s):
    print(f"\n   --- saved chat for '{s['customer']}' (since {s.get('started', '?')}) ---")
    for m in s["messages"][-30:]:
        who = "You" if m["who"] == "customer" else "Bot"
        print(f"   [{m['time']}] {who}: {m['text']}")
    if s["orders"]:
        print("   --- confirmed orders ---")
        for o in s["orders"]:
            items = ", ".join(f"{i['name']} × {i['quantity']}" for i in o["items"])
            print(f"   [{o['time']}] {items} — RM {o['total_myr']:.2f}")
    print()


def take_stock(menu, result):
    for l in result["items"]:
        if l.get("ok") and l.get("menu_id") in menu:
            menu[l["menu_id"]]["stock_qty"] -= l["quantity"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--as", dest="customer", default="guest", help="customer name / phone number")
    args = ap.parse_args()

    menu = order_ai.load_menu()
    s = sessions.load(args.customer)
    debug = False

    if s["messages"]:
        print(f"(continuing chat as '{s['customer']}' — {len(s['messages'])} saved messages, "
              f"{len(s['orders'])} orders. /history to see them, /new to start fresh)\n")
    else:
        print(f"(new chat as '{s['customer']}' — type /quit to stop)\n")

    def say(text, r=None):
        print(f"Bot: {text}\n")
        sessions.add_message(s, "bot", text)
        sessions.save(s)
        if debug and r:
            print(f"   [{r['decision']} | {r['latency_s']}s | {r['read_by']}]")
            for reason in r["reasons"]:
                print(f"    - {reason}")
            for src in r.get("sources", []):
                print(f"    source: {src}")
            print()

    while True:
        try:
            msg = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        cmd = msg.lower()
        if cmd in ("/quit", "/exit", "/stop", "/q"):
            break
        if cmd == "/menu":
            show_menu(menu); continue
        if cmd == "/history":
            show_history(s); continue
        if cmd == "/new":
            sessions.clear(s); sessions.save(s)
            print("   (chat history cleared)\n"); continue
        if cmd == "/debug":
            debug = not debug
            print(f"   (details {'on' if debug else 'off'})\n"); continue
        if cmd == "/reset":
            menu = order_ai.load_menu()
            print("   (stock reset from menu.csv)\n"); continue

        earlier = sessions.history(s, 10)         # before adding this message
        sessions.add_message(s, "customer", msg)
        sessions.save(s)

        waiting = s.get("waiting")
        if waiting:                               # reply to "continue with only X?"
            word = cmd.strip("!.? ")
            if word in YES:
                r = order_ai.confirm_partial(waiting, menu, s["orders"])
                take_stock(menu, r)
                sessions.add_order(s, r)
                s["waiting"] = None
                say(r["reply_draft"], r); continue
            if word in NO:
                ms = waiting.get("language") == "ms"
                s["waiting"] = None
                say("Baik, tak apa. Ada apa-apa lagi yang nak dipesan?" if ms
                    else "No problem! Anything else you'd like?"); continue
            s["waiting"] = None

        r = order_ai.check_order(msg, menu, earlier, s["orders"], s.get("lang"))
        if r.get("set_language"):
            s["lang"] = r["set_language"]
        if r["decision"] == "ACCEPT":
            take_stock(menu, r)
            sessions.add_order(s, r)
        elif r["decision"] in ("PARTIAL", "CONFIRM"):
            r.pop("raw", None)
            s["waiting"] = r
        say(r["reply_draft"] or order_ai.owner_handoff(r.get("language", "en")), r)

    sessions.save(s)
    print("(chat saved — run python chat.py again to continue)")


if __name__ == "__main__":
    main()
