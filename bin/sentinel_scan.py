#!/usr/bin/env python3
"""X-Freebie-Sentinel 生产级增量扫描 V1。
3 组并行高信噪比 Query（串行执行，间隔>=6s）-> seen去重 -> 铁律粗筛（含分销/代充拦截器）
-> 72h冷却 -> verdict。SENTINEL_FORCE_ERROR=1 模拟 API 故障。
输出 JSON: {"status":"ok|error","scanned":N,"rejected":{"reason":n},"new_freebies":[...]}
"""
import hashlib, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

HERE = os.path.expanduser("~/workspace/x_freebie_sentinel/bin")
sys.path.insert(0, HERE)
from sentinel_db import seen, in_cooldown, push

LOGDIR = os.path.expanduser("~/workspace/x_freebie_sentinel/logs")
os.makedirs(LOGDIR, exist_ok=True)

QUERIES = {
 "A": ('("免费额度" OR "白嫖" OR "送额度" OR "免费 API" OR "免绑卡" OR "无限额度" OR "黑客松" OR "兑换码") '
       '(AI OR Claude OR GPT OR Cursor OR 模型 OR 算力 OR API OR Agent) -抽奖 -转发 -giveaway -filter:retweets'),
 "B": ('("free credits" OR "promo code" OR "free tier" OR "no credit card" OR "open beta" OR "free API" OR "startup credits") '
       '(AI OR LLM OR API OR GPU OR agent OR IDE OR cloud OR Anthropic OR OpenAI OR Cursor) '
       '-bet -casino -sportsbook -draftkings -fanduel -stake -crypto -airdrop -giveaway -raffle -filter:retweets'),
 "C": ('("giving away $" OR "free for everyone" OR "credits for all" OR "claim your free" OR "free access to") '
       '(AI OR API OR model OR agent OR developer) -giveaway -rt -follow -bet -filter:retweets'),
 "D": ('(from:xulijian1994 OR from:mjjwiki OR from:WeiYi88890 OR from:xmglab) -is:retweet'),
 "E": ('(Wise OR 美元户 OR 港卡 OR 美卡) (恢复 OR 可以开 OR 重新开放 OR 放宽) min_faves:20 -is:retweet'),
 "F": ('(Gemini OR "Google AI Pro" OR Claude OR ChatGPT OR Cursor OR "YouTube Premium" OR Grok) '
       '(学生 OR 叠加 OR SheerID OR 锁定 OR 续到 OR "下一次付款" OR "下次扣款" OR "剩余时长") -is:retweet'),
}

# 5 类硬否决 + 分销/代充拦截器
RSS_FEEDS = [
    ("linuxdo-welfare", "https://linux.do/c/welfare/36.rss"),
    ("v2ex-promotions", "https://www.v2ex.com/feed/promotions.xml"),
    ("v2ex-create", "https://www.v2ex.com/feed/create.xml"),
]
# NodeSeek 无分版块 RSS，读版块 HTML（免登录）
NODESEEK_BOARDS = [
    ("nodeseek-promotion", "https://www.nodeseek.com/categories/promotion"),
    ("nodeseek-info", "https://www.nodeseek.com/categories/info"),
]
RSS_POSITIVE = re.compile("免费|白嫖|送|兑换码|公益|0元|0刀|放水|吃码|秒过|二验|隐藏入口|叠加|内测|首发|上车|bug|漏洞|free", re.I)

def fetch_rss_candidates():
    """拉取 RSS 补充源，返回 [(feed名, 标题, 链接)]。失败只记日志不中断整轮。"""
    cands = []
    for name, url in RSS_FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            xml = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
            items = re.findall(r"<item>(.*?)</item>", xml, re.S) or re.findall(r"<entry>(.*?)</entry>", xml, re.S)
            hit = 0
            for it in items:
                t = re.search(r"<title>(.*?)</title>", it, re.S)
                title = re.sub(r"<!\[CDATA\[|\]\]>", "", t.group(1).strip()) if t else ""
                d = re.search(r"<description>(.*?)</description>", it, re.S)
                desc = re.sub(r"<!\[CDATA\[|\]\]>|<[^>]+>", "", d.group(1).strip()) if d else ""
                m = re.search(r'<link[^>]*href="([^"]+)"', it) or re.search(r"<link>(.*?)</link>", it)
                link = m.group(1).strip() if m else ""
                if title and link and RSS_POSITIVE.search(title + desc):
                    # LinuxDo/社区：标题+正文摘要先过中转站拦截器，减少 worker 无效核验
                    combo = title + " " + desc[:300]
                    if re.search(r"中转|倍率|官key|1[:：]1\s*充值|特价|限时降价|不降智", combo, re.I) \
                            and not re.search(r"公益", combo):
                        log(f"RSS[{name}] 脚本层拦截中转站广告: {title[:50]}")
                        continue
                    cands.append((name, title[:200], link)); hit += 1
            log(f"RSS[{name}] {len(items)} 篇，命中 {hit} 条")
        except Exception as e:
            log(f"RSS[{name}] 拉取失败: {e}")
    for name, url in NODESEEK_BOARDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            html = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
            seen_links = set(); hit = 0
            for m in re.finditer(r'href="(/post-(\d+)-1)"[^>]*>([^<]{4,80})</a>', html):
                path, title = m.group(1), m.group(3).strip()
                if path in seen_links or "NodeSeek" in title: continue
                seen_links.add(path)
                if RSS_POSITIVE.search(title):
                    cands.append((name, title[:200], "https://www.nodeseek.com" + path)); hit += 1
            log(f"HTML[{name}] 命中 {hit} 条")
        except Exception as e:
            log(f"HTML[{name}] 拉取失败: {e}")
    return cands

REJECT_PATTERNS = [
    ("抽奖画饼", r"抽奖|giveaway|raffle|lucky winner|转评赞|转发抽|抽\d+人"),
    ("骗互动锁私信", r"扣\s*1|留言\s*666|私信发你|私我领取|评论区.*领取"),
    ("传销式排队", r"invite friends to move up|拉人头|邀请.*加速|referral.*waitlist"),
    ("盗号钓鱼", r"connect wallet|连接钱包|签名.*领|开启.*写权限|curl.*\|\s*(sh|bash)"),
    ("博彩噪音", r"stake\.com|melbet|bet code|投注|博彩|\bodds\b"),
    ("分销拉新", r"\?(via|aff|ref|partner)="),
    ("代充合租黑卡", r"代充|合租|拼车|成品号|黑卡|共享账号|低价.*账号"),
    ("伪造欺诈", r"伪造.*(证件|身份证)|假.*身份证|ps.*证件|买卖账号|买号|卖号|账号交易"),
]

# 灰色内容：可收，但必须标风险推（deals 灰色规则，2026-10-17 用户亲定）
GRAY_PATTERNS = [
    ("U卡/新渠道", r"\bu\s*卡|U卡|虚拟卡|(visa|mastercard).*(申请|开卡)|(申请|开卡).*(visa|mastercard)|新渠道"),
    ("验证技巧", r"验证.*技巧|过验证|绕验证|防风控"),
    ("漏洞套利", r"0元|卡bug|漏洞|没修全|上车"),
]

def log(msg):
    ts = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    with open(os.path.join(LOGDIR, "sentinel.log"), "a") as f: f.write(line)

def classify(text, urls):
    # 中转站广告：API relay resellers（公益站除外，那是真免费）
    if re.search(r"中转|倍率|官key|1[:：]1\s*充值|特价|限时降价|不降智", text, re.I) and not re.search(r"公益", text):
        return ("reject", "中转站广告", "")
    if re.search(r"\baff\b", text, re.I):
        return ("reject", "分销拉新", "")
    for name, pat in REJECT_PATTERNS:
        if re.search(pat, text, re.I): return ("reject", name, "")
        if name == "分销拉新":
            for u in urls:
                if re.search(pat, u, re.I): return ("reject", name, "")
    for name, pat in GRAY_PATTERNS:
        if re.search(pat, text, re.I): return ("candidate", "", "灰色:" + name + "（可能封号/违反条款，标风险推）")
    return ("candidate", "", "")

def _search_tio(query, since, maxn):
    """主 provider: twitterapi.io。返回归一化 tweet 列表。"""
    sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
    from dynamic_credentials import add_surrogate_to_request, read_json_response
    import urllib.request, urllib.error
    q = query + f" since:{since}_UTC -is:retweet"
    url = "https://api.twitterapi.io/twitter/tweet/advanced_search?" + urllib.parse.urlencode({"query": q, "queryType": "Latest"})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    add_surrogate_to_request(req, "custom.twitterapi-io", allowed_hosts=["api.twitterapi.io"])
    with urllib.request.urlopen(req, timeout=90) as r:
        return read_json_response(r).get("tweets", [])[:maxn]

def _search_tapis(query, since, maxn):
    """主 provider: twitterapis.com（$0.0008/次，无平台限流）。fields 要到 entities 展开链接，数据与 tio 对等。"""
    sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
    from dynamic_credentials import add_surrogate_to_request, read_json_response
    import urllib.request, urllib.error
    q = query + f" since:{since}_UTC -is:retweet"
    url = "https://api.twitterapis.com/twitter/tweet/advanced_search?" + urllib.parse.urlencode({
        "query": q, "product": "Latest",
        "fields": "id,text,created_at,entities,author.username,url"})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    add_surrogate_to_request(req, "custom.twitterapis", allowed_hosts=["api.twitterapis.com"])
    with urllib.request.urlopen(req, timeout=90) as r:
        data = read_json_response(r)
    tweets = data.get("tweets") or data.get("data") or []
    out = []
    for t in tweets[:maxn]:
        a = t.get("author")
        username = (a.get("username") if isinstance(a, dict) else a) if a else ""
        tid, text = t.get("id"), t.get("text") or ""
        tweet_url = t.get("url") or (f"https://x.com/{username}/status/{tid}" if tid else "")
        expanded = [u.get("expanded_url") or u.get("url")
                    for u in ((t.get("entities") or {}).get("urls") or [])]
        expanded = [u for u in expanded if u]
        link_list = expanded or ([tweet_url] if tweet_url else [])
        out.append({"id": tid, "author": {"userName": username}, "text": text,
                    "entities": {"urls": [{"expanded_url": u} for u in link_list]}})
    return out

def search_once(query, window_h, maxn):
    """双 provider：主 twitterapis.com（便宜 4 倍、无限流），备 twitterapi.io。402 = 主家额度用完。"""
    since = (datetime.now(timezone.utc) - timedelta(hours=window_h)).strftime("%Y-%m-%d_%H:%M:%S")
    try:
        return ("twitterapis.com", _search_tapis(query, since, maxn))
    except Exception as e:
        import urllib.error
        if isinstance(e, urllib.error.HTTPError) and e.code == 402:
            raise RuntimeError("CREDIT_EXHAUSTED twitterapis.com 额度用完（402）")
        log(f"主 provider twitterapis.com 失败({type(e).__name__}: {str(e)[:80]})，切换备选 twitterapi.io")
        return ("twitterapi.io", _search_tio(query, since, maxn))

def run(window_h=2.5, per_query_n=18):
    if os.environ.get("SENTINEL_FORCE_ERROR") == "1":
        raise RuntimeError("twitterapi.io 调用失败: HTTP 429 余额/限流（模拟）")
    scanned, rejected, new_freebies = 0, {}, []
    per_query, providers = {}, {}
    fails = {"twitterapi.io": 0, "twitterapis.com": 0}
    for name, q in QUERIES.items():
        try:
            provider, tweets = search_once(q, window_h, per_query_n)
        except RuntimeError as e:
            if "CREDIT_EXHAUSTED" in str(e):
                raise
            fails["twitterapi.io"] += 1; fails["twitterapis.com"] += 1
            log(f"查询[{name}] 两家全失败: {str(e)[:80]}")
            time.sleep(12); continue
        except Exception as e:
            fails["twitterapi.io"] += 1; fails["twitterapis.com"] += 1
            log(f"查询[{name}] 两家全失败: {type(e).__name__} {str(e)[:80]}")
            time.sleep(12); continue
        providers[provider] = providers.get(provider, 0) + 1
        per_query[name] = len(tweets)
        for t in tweets:
            scanned += 1
            tid, author = t.get("id"), (t.get("author") or {}).get("userName", "")
            text = t.get("text") or ""
            urls = [u.get("expanded_url") for u in ((t.get("entities") or {}).get("urls") or []) if u.get("expanded_url")]
            if seen(tid, author):
                rejected["已处理过"] = rejected.get("已处理过", 0) + 1; continue
            verdict, reason, risk = classify(text, urls)
            if verdict == "reject":
                rejected[reason] = rejected.get(reason, 0) + 1
                log(f"否决[{name}] @{author}: {reason}"); continue
            domain = urllib.parse.urlparse(urls[0]).netloc if urls else ""
            if domain and in_cooldown(domain):
                rejected["72h冷却"] = rejected.get("72h冷却", 0) + 1
                log(f"冷却拦截[{name}] @{author} {domain}"); continue
            new_freebies.append({"query": name, "tweet_id": tid, "author": author,
                                 "text": text[:280], "urls": urls, "domain": domain, "risk": risk})
            log(f"候选[{name}] @{author} {domain} {tid}")
        # 主家无限流短间隔；备选 tio 免费层 5 秒 1 次，保持 12 秒
        time.sleep(3 if provider == "twitterapis.com" else 12)
    for feed_name, title, link in fetch_rss_candidates():
        tid = "rss:" + hashlib.md5(link.encode()).hexdigest()[:16]
        if seen(tid, feed_name):
            rejected["已处理过"] = rejected.get("已处理过", 0) + 1; continue
        verdict, reason, risk = classify(title, [link])
        if verdict == "reject":
            rejected[reason] = rejected.get(reason, 0) + 1
            log(f"否决[RSS-{feed_name}] {reason}: {title[:50]}"); continue
        domain = urllib.parse.urlparse(link).netloc or ""
        new_freebies.append({"query": "RSS-" + feed_name, "tweet_id": tid, "author": feed_name,
                             "text": title[:280], "urls": [link], "domain": domain, "risk": risk})
        log(f"候选[RSS-{feed_name}] {title[:60]}")
    # 额度耗尽判定（用户要求：真没额度才提醒）
    warnings = []
    if fails["twitterapi.io"] == len(QUERIES) and fails["twitterapis.com"] == len(QUERIES):
        raise RuntimeError("CREDIT_EXHAUSTED 两家 X API 6 组查询全失败，疑似额度/配额耗尽，请换 key")
    if providers.get("twitterapis.com", 0) == 0 and providers.get("twitterapi.io", 0) > 0:
        warnings.append("twitterapis.com 本轮 6 组查询全部失败，已全切备选 twitterapi.io；如持续请换 key")
        log("WARNING: " + warnings[-1])
    # 用量台账：每班记各 provider 调用次数，供用量统计
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "usage.jsonl"), "a") as f:
            f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "providers": providers}) + "\n")
    except Exception:
        pass
    return {"status": "ok", "window_h": window_h, "per_query": per_query, "providers": providers,
            "warnings": warnings, "scanned": scanned, "rejected": rejected, "new_freebies": new_freebies}

if __name__ == "__main__":
    try:
        res = run(window_h=float(sys.argv[1]) if len(sys.argv) > 1 else 2.5,
                  per_query_n=int(sys.argv[2]) if len(sys.argv) > 2 else 18)
        log(f"扫描完成: {res['scanned']} 条, 否决 {res['rejected']}, 候选 {len(res['new_freebies'])}")
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        log(f"扫描异常: {e}")
        print(json.dumps({"status": "error", "error": str(e), "new_freebies": []}, ensure_ascii=False))
        sys.exit(3)
