import feedparser
import requests
import json
import os
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

# ── 配置 ──────────────────────────────────────────────────────────────────────

APP_TOKEN = os.environ.get("WXPUSHER_APP_TOKEN", "AT_Zggv7IzCIq80UqLJFCfhvuTVECDwMyef")
UIDS = ["UID_qUv6CjARHEUD7jUGdGqu75bHRaWA"]
WXPUSHER_URL = "https://wxpusher.zjiecode.com/api/send/message"

RSS_FEEDS = [
    "https://news.google.com/rss/search?q=21世纪经济报道+保险&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=中证网+保险&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=第一财经+保险&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=财联社+保险&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=保险&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://coverager.com/feed/",
    "https://www.insurancejournal.com/feed/",
    "https://www.insurancebusinessmag.com/asia/rss",
    "https://news.google.com/rss/search?q=保险+OR+医疗+OR+养老+site:cnstock.com&hl=zh-CN&gl=CN",
    "https://www.reinsurancene.ws/feed/",
    "https://news.google.com/rss/search?q=格隆汇+保险&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=界面新闻+保险&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://news.google.com/rss/search?q=国家金融监督管理总局+保险&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
    "https://www.fiercehealthcare.com/rss/xml",
    "https://news.google.com/rss/search?q=保险+site:iyiou.com&hl=zh-CN&gl=CN",
]

SENT_GUIDS_FILE = Path("sent_guids.json")
MAX_GUIDS = 500
CUTOFF_HOURS = 24

# ── 已推送 GUID 管理 ──────────────────────────────────────────────────────────

def load_sent_guids() -> list:
    if SENT_GUIDS_FILE.exists():
        with open(SENT_GUIDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []

def save_sent_guids(guids: list):
    with open(SENT_GUIDS_FILE, "w", encoding="utf-8") as f:
        json.dump(guids[-MAX_GUIDS:], f, ensure_ascii=False, indent=2)

# ── RSS 抓取与过滤 ────────────────────────────────────────────────────────────

def parse_pub_date(entry) -> float:
    """解析发布时间，返回 Unix 时间戳；无法解析则返回 0"""
    if hasattr(entry, "published"):
        try:
            return parsedate_to_datetime(entry.published).timestamp()
        except Exception:
            pass
    if hasattr(entry, "updated"):
        try:
            return parsedate_to_datetime(entry.updated).timestamp()
        except Exception:
            pass
    return 0.0

def clean_title(title: str) -> str:
    """移除控制字符，保持标题整洁"""
    return re.sub(r'[\x00-\x1F\x7F"\\]', ' ', title).strip()

def fetch_new_items(sent_guids: list) -> list:
    cutoff = time.time() - CUTOFF_HOURS * 3600
    new_items = []

    for url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                guid = getattr(entry, "id", None) or getattr(entry, "link", None)
                if not guid:
                    continue
                pub_time = parse_pub_date(entry)
                if pub_time < cutoff:
                    continue
                if guid in sent_guids:
                    continue
                new_items.append({
                    "title": clean_title(getattr(entry, "title", "（无标题）")),
                    "link": getattr(entry, "link", ""),
                    "guid": guid,
                    "pub_time": pub_time,
                })
        except Exception as e:
            print(f"[ERROR] 抓取失败: {url}\n  原因: {e}")

    # 按发布时间倒序排列（最新的先推送）
    new_items.sort(key=lambda x: x["pub_time"], reverse=True)
    return new_items

# ── WxPusher 推送 ─────────────────────────────────────────────────────────────

def send_to_wxpusher(item: dict) -> bool:
    content = f"{item['title']}\n{item['link']}"
    payload = {
        "appToken": APP_TOKEN,
        "content": content,
        "contentType": 1,
        "uids": UIDS,
    }
    try:
        resp = requests.post(WXPUSHER_URL, json=payload, timeout=10)
        data = resp.json()
        if data.get("code") == 1000:
            print(f"[OK] 已推送: {item['title'][:40]}")
            return True
        else:
            print(f"[WARN] 推送失败: {data.get('msg')} | {item['title'][:40]}")
            return False
    except Exception as e:
        print(f"[ERROR] 推送异常: {e} | {item['title'][:40]}")
        return False

# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    print(f"[START] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 开始抓取...")

    sent_guids = load_sent_guids()
    new_items = fetch_new_items(sent_guids)

    print(f"[INFO] 发现 {len(new_items)} 条新内容")

    if not new_items:
        print("[INFO] 无新内容，退出")
        return

    pushed_guids = []
    for item in new_items:
        success = send_to_wxpusher(item)
        if success:
            pushed_guids.append(item["guid"])
        time.sleep(0.5)  # 避免频率过高

    # 更新并保存 GUID 列表
    updated_guids = sent_guids + pushed_guids
    save_sent_guids(updated_guids)

    print(f"[DONE] 成功推送 {len(pushed_guids)} 条，跳过 {len(new_items) - len(pushed_guids)} 条")

if __name__ == "__main__":
    main()
