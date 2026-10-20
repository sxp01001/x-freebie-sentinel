#!/usr/bin/env python3
"""X-Freebie-Sentinel 高频羊毛词增量抓取：展示原始核心字段 + t.co 还原。
Usage: sentinel_search.py "<query>" [max_results=10]
"""
import json, sys, urllib.parse, urllib.request, urllib.error

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response

CONNECTION = "custom.twitterapi-io"
HOST = "api.twitterapi.io"
BASE = "https://{}/twitter".format(HOST)

def main():
    query = sys.argv[1]
    maxn = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    params = urllib.parse.urlencode({"query": query, "queryType": "Latest"})
    url = "{}/tweet/advanced_search?{}".format(BASE, params)
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    add_surrogate_to_request(request, CONNECTION, allowed_hosts=[HOST])
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = read_json_response(response)
    except urllib.error.HTTPError as e:
        print(json.dumps({"api_status": "ERROR", "http_error": e.code,
                          "body": e.read().decode("utf-8", "replace")[:300]},
                         ensure_ascii=False))
        sys.exit(2)
    tweets = data.get("tweets", [])
    out = {"api_status": "OK", "query": query, "returned": len(tweets),
           "showing": min(maxn, len(tweets)), "tweets": []}
    for t in tweets[:maxn]:
        entities = t.get("entities") or {}
        urls = [u.get("expanded_url") for u in (entities.get("urls") or []) if u.get("expanded_url")]
        out["tweets"].append({
            "id": t.get("id"),
            "createdAt": t.get("createdAt"),
            "author": (t.get("author") or {}).get("userName"),
            "bookmarkCount": t.get("bookmarkCount"),
            "viewCount": t.get("viewCount"),
            "likeCount": t.get("likeCount"),
            "retweetCount": t.get("retweetCount"),
            "text": (t.get("text") or "")[:280],
            "expanded_urls": urls,
        })
    print(json.dumps(out, ensure_ascii=False, indent=1))

main()
