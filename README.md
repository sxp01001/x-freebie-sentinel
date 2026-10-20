# X-Freebie-Sentinel

2 小时高频真羊毛哨兵：扫描 X + 中文社区（LinuxDo / V2EX / NodeSeek），抓"免费额度 / 兑换码 / 限时免费窗 / 开发者包 / 数字赠品"类真福利，见肉才推，平时静默。

## 架构

```
bin/sentinel_scan.py 主扫描脚本：6 组 X Query + RSS/版块补充源 → 分类 → 去重 → JSON 输出
bin/sentinel_db.py 持久化：seen_tweets / pushed_freebies（双层冷却）/ pending_vault（待解锁金库）/ hunter_candidates（猎手攒人）
bin/tweet_detail.py 推文详情抓取（实操路径核验用）
bin/sentinel_search.py 高频词增量抓取（含 t.co 还原）
bin/balance_watch.py 额度台账辅助（当前无 cron 调用，被动告警替代）
```

## 情报源

- **X（6 组查询）**：A 中文池 / B 英文技术池 / C 破圈动作词 / D 爆料账号定点 / E 政策反转 / F 套利快线
- **社区（免费免登录）**：LinuxDo 福利羊毛 RSS、V2EX 推广/创造 RSS、NodeSeek 推广/情报版块

## 双 API 容灾

- 主：`twitterapis.com`（$0.0008/次，无平台限流；加 `fields` 参数拿 entities 展开链接）
- 备：`twitterapi.io`（~$0.003/次）
- 主家 402 → 抛 `CREDIT_EXHAUSTED` 告警换 key；两家全挂 → 同样告警

## 过滤体系

- **5 类硬否决**：抽奖画饼 / 骗互动锁私信 / 传销式排队 / 反撸陷阱 / 钓鱼
- **拦截器**：分销拉新（aff）、代充合租黑卡、中转站广告（中转/倍率/官key/不降智，公益站除外）、伪造欺诈
- **灰色标风险推**：U 卡/新渠道、验证技巧、漏洞套利

## 核验双标准（V1.1）

- **标准 A（官方明面福利）**：打开官网核验"当前有效 + 确实可撸"，无口径则挂起
- **标准 B（漏洞套利/隐藏入口/政策反转）**：豁免官网公告核验；验"原帖实操步骤/成功截图/隐藏直链"或"评论区实测反馈"，有具体路径立即推，标题加 `⚡[漏洞/风控窗口期·速测]`

## 去重与冷却

- `seen_tweets`：tweet_id / RSS 链接 MD5 去重
- 已推送域名 **72h** 冷却；核验存疑（held_unverified）域名仅 **6h** 冷却
- `pending_vault`：真肉但暂缺资格（如需 edu 邮箱）入库待解锁
- `hunter_candidates`：推送成功作者自动记录，每周复盘挑高命中率猎手并入 D 组

## 输出

4 行：🎁 内容 / ⚡ 3步领法 / 🪪 门槛 / ⏰ 时效防坑

## 运行

生产环境由 12 个 cron 班次驱动（每 2 小时一班，全天 24h，每班扫过去 2.5h）。
手动跑一轮：

```bash
python3 bin/sentinel_scan.py 2.5 18 # window_h=2.5, 每组 18 条
```

## 本地状态（不入库）

`sentinel.db`、`logs/`、`usage.jsonl`、`credits.json`、`__pycache__/` 均为本机运行态，见 `.gitignore`。
