#!/usr/bin/env python3
"""API 额度监控：根据用量台账估算两家 provider 剩余额度，低于阈值则告警。
用量单价：twitterapi.io 约 $0.003/次，twitterapis.com $0.0008/次。
credits.json 记录每家的起算额度和起算时间（换 key 后由人工更新）。
输出 JSON: {"alert": bool, "details": {...}}
"""
import json, os, sys
from datetime import datetime, timezone

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COST = {"twitterapi.io": 0.003, "twitterapis.com": 0.0008}
ALERT_RATIO = 0.25

def main():
    cfg = json.load(open(os.path.join(BASE, "credits.json")))
    usage_path = os.path.join(BASE, "usage.jsonl")
    spent = {p: 0.0 for p in COST}
    calls = {p: 0 for p in COST}
    if os.path.exists(usage_path):
        for line in open(usage_path):
            line = line.strip()
            if not line: continue
            try: entry = json.loads(line)
            except Exception: continue
            for p, n in (entry.get("providers") or {}).items():
                if p in COST:
                    calls[p] += n
                    spent[p] += n * COST[p]
    details, alert = {}, False
    for p, info in cfg["providers"].items():
        start, seed = info["starting_usd"], info.get("seed_spent_usd", 0)
        total_spent = round(seed + spent.get(p, 0), 4)
        remaining = round(start - total_spent, 4)
        ratio = remaining / start if start > 0 else 0
        low = ratio < ALERT_RATIO or remaining <= 0
        alert = alert or low
        details[p] = {"starting_usd": start, "seed_spent_usd": seed,
                      "tracked_calls": calls.get(p, 0), "est_spent_usd": total_spent,
                      "est_remaining_usd": remaining, "remaining_ratio": round(ratio, 3),
                      "low": low, "since": info.get("since")}
    print(json.dumps({"alert": alert, "details": details,
                      "note": "估算值，seed 为启用台账前的粗估消耗"}, ensure_ascii=False, indent=1))

main()
