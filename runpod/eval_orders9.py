"""
Tests the order AI on data/test_orders.csv and gives you a score.

  python eval_orders.py --split dev     # use while you are tuning
  python eval_orders.py --split test    # hidden test (already used for v2 -> now a 2nd practice set)
  python eval_orders.py --split test2   # fresh hidden test for the final numbers (run once)
  python eval_orders.py --split qa      # food questions (should be ANSWER)
  python eval_orders.py --split typo    # orders with spelling mistakes
  python eval_orders.py --orders data/train/generated_orders.csv --split gen --limit 100
                                        # 100 of the generated examples

IMPORTANT: the expected answers depend on the stock in data/menu.csv.
Don't change menu.csv stock numbers, or the expected decisions become wrong.

expected_items format: K04:10;K06:2   (NONE:1 = an item that is not on the menu)
"""
import argparse, csv, statistics, time
from collections import Counter
from pathlib import Path

import order_ai


def parse_expected(s):
    c = Counter()
    for part in filter(None, (s or "").split(";")):
        mid, qty = part.split(":")
        c[mid.strip()] += int(qty)
    return c


def got_items(lines):
    c = Counter()
    for l in lines:
        c[l["menu_id"] or "NONE"] += l["quantity"]
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--orders", default="data/test_orders.csv")
    ap.add_argument("--split", choices=["dev", "test", "test2", "qa", "typo", "manglish", "gen", "all"], default="dev")
    ap.add_argument("--limit", type=int, help="test only N random messages (saves time and credit)")
    a = ap.parse_args()

    menu = order_ai.load_menu()
    rows = list(csv.DictReader(open(a.orders, newline="", encoding="utf-8")))
    if a.split != "all":
        rows = [r for r in rows if r["split"] == a.split]
    if a.limit and a.limit < len(rows):
        import random
        rows = random.Random(7).sample(rows, a.limit)

    items_ok = decision_ok = fallback = 0
    dangerous = []            # we accepted/offered food when we shouldn't have
    latencies, records = [], []

    for i, r in enumerate(rows, 1):
        res = order_ai.check_order(r["order_text"], menu)
        want_items, have_items = parse_expected(r["expected_items"]), got_items(res["items"])
        ok_i = want_items == have_items
        menu_ok = {k: v for k, v in want_items.items() if k != "NONE"} == \
                  {k: v for k, v in have_items.items() if k != "NONE"}   # what we would actually sell
        ok_d = res["decision"] == r["expected_decision"]
        items_ok += ok_i
        decision_ok += ok_d
        fallback += res["read_by"] == "fallback"
        if res["read_by"] != "fallback":
            latencies.append(res["latency_s"])
        got, want = res["decision"], r["expected_decision"]
        if (got == "ACCEPT" and want != "ACCEPT") or (got == "PARTIAL" and want == "NEEDS_REVIEW") \
                or (got in ("ACCEPT", "PARTIAL") and not menu_ok):
            dangerous.append(r["order_text"])   # would sell the wrong menu items or amounts
        print(f"[{i}/{len(rows)}] {'OK ' if ok_i and ok_d else 'ERR'} "
              f"{res['decision']:<12} (want {r['expected_decision']:<12}) "
              f"{res['latency_s']:>5}s  {r['order_text'][:45]}")
        records.append({
            "order_text": r["order_text"],
            "want_items": dict(want_items), "got_items": dict(have_items), "items_ok": ok_i,
            "want_decision": r["expected_decision"], "got_decision": res["decision"],
            "decision_ok": ok_d, "reasons": " | ".join(res["reasons"]),
            "confidence": res["confidence"], "read_by": res["read_by"],
            "latency_s": res["latency_s"], "reply": res["reply_draft"],
            "sources": " | ".join(res.get("sources", [])), "raw": res["raw"],
        })

    n = len(rows)
    out = Path("data/eval"); out.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%m%d-%H%M")
    path = out / f"orders_{order_ai.PROMPT_VERSION}_{a.split}_{stamp}.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(records[0].keys()))
        w.writeheader(); w.writerows(records)

    print(f"\n=== SUMMARY  prompt {order_ai.PROMPT_VERSION} | split {a.split} | {n} orders ===")
    print(f"  items read correctly      {items_ok}/{n}  ({items_ok/n:.0%})")
    print(f"  correct decision          {decision_ok}/{n}  ({decision_ok/n:.0%})")
    print(f"  DANGEROUS wrong accepts   {len(dangerous)}  {dangerous}")
    print(f"  AI unavailable (fallback) {fallback}/{n}")
    if latencies:
        print(f"  seconds per order: median {statistics.median(latencies):.2f}, max {max(latencies):.2f}")
    print(f"  details -> {path}")

    log = out / "orders_tuning_log.csv"
    new = not log.exists()
    with open(log, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["time", "prompt", "split", "n", "items_ok", "decision_ok", "dangerous",
                        "fallback", "median_s"])
        w.writerow([stamp, order_ai.PROMPT_VERSION, a.split, n, items_ok, decision_ok,
                    len(dangerous), fallback, round(statistics.median(latencies), 2) if latencies else ""])


if __name__ == "__main__":
    main()
