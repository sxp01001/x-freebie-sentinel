#!/usr/bin/env python3
"""按 tweet_id 拉取单条推文详情（含展开 URL）。"""
import json, sys, urllib.request, urllib.error
sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import add_surrogate_to_request, read_json_response
url = "https://api.twitterapi.io/twitter/tweets?tweet_ids=" + sys.argv[1]
req = urllib.request.Request(url, headers={"Accept": "application/json"})
add_surrogate_to_request(req, "custom.twitterapi-io", allowed_hosts=["api.twitterapi.io"])
with urllib.request.urlopen(req, timeout=90) as r:
    d = read_json_response(r)
t = d["tweets"][0]
ents = t.get("entities") or {}
print(json.dumps({
    "id": t["id"], "createdAt": t["createdAt"], "author": t["author"]["userName"],
    "likeCount": t.get("likeCount"), "viewCount": t.get("viewCount"),
    "text": t.get("text"),
    "urls": [u.get("expanded_url") for u in ents.get("urls", [])],
}, ensure_ascii=False, indent=1))
