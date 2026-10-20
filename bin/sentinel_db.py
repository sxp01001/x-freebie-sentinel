#!/usr/bin/env python3
"""X-Freebie-Sentinel 持久化：seen_tweets + pushed_freebies（72h 冷却）+ pending_vault（待解锁金库）。"""
import sqlite3, sys, os, time

DB = os.path.expanduser("~/workspace/x_freebie_sentinel/sentinel.db")
COOLDOWN_PUSHED = 72 * 3600      # 真正推送过的：主域名 72h 冷却
COOLDOWN_HELD = 6 * 3600         # 核验存疑挂起的：域名只冷却 6h，tweet_id 照常去重

def conn():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS seen_tweets(
        tweet_id TEXT PRIMARY KEY, author TEXT, seen_at INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS pushed_freebies(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, domain TEXT,
        promo_code TEXT, status TEXT, pushed_at INTEGER)""")
    c.execute("""CREATE TABLE IF NOT EXISTS pending_vault(
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, value_usd TEXT,
        claim_url TEXT, requirement TEXT, found_at INTEGER, note TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS hunter_candidates(
        handle TEXT PRIMARY KEY, first_seen INTEGER, hits INTEGER DEFAULT 1,
        last_freebie TEXT)""")
    return c

def seen(tweet_id, author=""):
    c = conn(); now = int(time.time())
    row = c.execute("SELECT 1 FROM seen_tweets WHERE tweet_id=?", (tweet_id,)).fetchone()
    if row: c.close(); return True
    c.execute("INSERT INTO seen_tweets VALUES(?,?,?)", (tweet_id, author, now))
    c.commit(); c.close(); return False

def in_cooldown(domain, promo_code=""):
    """双层冷却：status=pushed -> 72h；status=held_unverified -> 6h。True = 拦截。"""
    c = conn(); now = int(time.time())
    row = c.execute(
        "SELECT pushed_at, status FROM pushed_freebies WHERE domain=? AND COALESCE(promo_code,'')=COALESCE(?, '') ORDER BY pushed_at DESC LIMIT 1",
        (domain, promo_code)).fetchone()
    c.close()
    if not row: return False
    pushed_at, status = row
    cd = COOLDOWN_PUSHED if status == "pushed" else COOLDOWN_HELD
    return (now - pushed_at) < cd

def push(name, domain, promo_code="", status="pushed"):
    c = conn()
    c.execute("INSERT INTO pushed_freebies(name,domain,promo_code,status,pushed_at) VALUES(?,?,?,?,?)",
              (name, domain, promo_code, status, int(time.time())))
    c.commit(); c.close()

def vault_add(name, value_usd, claim_url, requirement, note=""):
    c = conn()
    c.execute("INSERT INTO pending_vault(name,value_usd,claim_url,requirement,found_at,note) VALUES(?,?,?,?,?,?)",
              (name, value_usd, claim_url, requirement, int(time.time()), note))
    c.commit(); c.close()

def vault_list():
    c = conn()
    rows = c.execute("SELECT name,value_usd,claim_url,requirement,note,datetime(found_at,'unixepoch','+8 hours') FROM pending_vault ORDER BY id").fetchall()
    c.close(); return rows

def note_hunter(handle, freebie_name=""):
    """D 组野生猎手攒人：推送成功的推文作者记一笔，供每周挑高命中率新人。"""
    if not handle: return
    c = conn(); now = int(time.time())
    row = c.execute("SELECT hits FROM hunter_candidates WHERE handle=?", (handle,)).fetchone()
    if row:
        c.execute("UPDATE hunter_candidates SET hits=hits+1,last_freebie=? WHERE handle=?", (freebie_name, handle))
    else:
        c.execute("INSERT INTO hunter_candidates(handle,first_seen,hits,last_freebie) VALUES(?,?,1,?)",
                  (handle, now, freebie_name))
    c.commit(); c.close()

def hunter_list(min_hits=1):
    c = conn()
    rows = c.execute("SELECT handle,hits,last_freebie,datetime(first_seen,'unixepoch','+8 hours') FROM hunter_candidates WHERE hits>=? ORDER BY hits DESC", (min_hits,)).fetchall()
    c.close(); return rows
