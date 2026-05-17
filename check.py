"""
Japan Toreca オリパ 売り切れ通知システム

監視対象は watches.json で設定します。
このファイル(check.py)を編集する必要はありません。

【誤検知対策】
1. ガチャカードが描画されるまで待つ
2. ガチャ0件の取得は失敗とみなしてスキップ
3. 2回連続で見つからなかったら売り切れと判定(瞬間ミス許容)

【通知】
複数の通知は1通にまとめて送信(LINE通数節約 + 見やすさ向上)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

CONFIG_FILE = Path("watches.json")

DEFAULT_CONFIG = {
    "watches": [
        {"label": "ワンピース", "url": "https://japan-toreca.com/oripa/onepiece", "prices": [933]},
        {"label": "ホビー", "url": "https://japan-toreca.com/oripa/hobby", "prices": [1020, 1030, 1040]},
    ],
    "options": {"notify_on_new": False, "stale_days": 14, "miss_threshold": 2},
}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        print(f"[WARN] {CONFIG_FILE} が見つかりません。デフォルト設定で動作します。")
        return DEFAULT_CONFIG
    try:
        raw = CONFIG_FILE.read_text(encoding="utf-8")
        cfg = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[ERROR] {CONFIG_FILE} のJSON構文エラー: {e}")
        return DEFAULT_CONFIG

    if "watches" not in cfg or not isinstance(cfg["watches"], list):
        print(f"[ERROR] {CONFIG_FILE} に 'watches' (配列) がありません。")
        return DEFAULT_CONFIG
    for i, w in enumerate(cfg["watches"]):
        if not all(k in w for k in ("label", "url", "prices")):
            print(f"[ERROR] watches[{i}] に必須キー (label/url/prices) が不足。")
            return DEFAULT_CONFIG
        if not isinstance(w["prices"], list) or not all(isinstance(p, int) for p in w["prices"]):
            print(f"[ERROR] watches[{i}].prices は整数の配列で指定してください。")
            return DEFAULT_CONFIG

    return cfg


_CFG = load_config()
WATCHES = _CFG["watches"]
NOTIFY_ON_NEW = _CFG.get("options", {}).get("notify_on_new", False)
STALE_DAYS = _CFG.get("options", {}).get("stale_days", 14)
MISS_THRESHOLD = _CFG.get("options", {}).get("miss_threshold", 2)

STATE_FILE = Path("state.json")
DEBUG_HTML_DIR = Path("debug")

LINE_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


def fetch_html(url: str) -> str:
    print(f"[INFO] Playwrightで取得: {url}")
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=USER_AGENT, locale="ja-JP",
            viewport={"width": 1280, "height": 900},
        )
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        try:
            page.wait_for_selector("a[href*='/oripa/']", timeout=15_000)
        except Exception as e:
            print(f"[WARN] ガチャカードの待機タイムアウト: {e}")
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()
        return html


HREF_RE = re.compile(r'^(?:https?://japan-toreca\.com)?/oripa/(?P<cat>[\w-]+)/(?P<id>\d+)')
PRICE_RE = re.compile(r'(\d{1,3}(?:,\d{3})*|\d+)/1回')
STOCK_RE = re.compile(r'残り([\d,]+)\s*/\s*([\d,]+)')


def parse_gachas(html: str, expected_category: str | None = None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    gachas = []
    seen_keys = set()
    for a in soup.find_all("a", href=HREF_RE):
        m = HREF_RE.match(a["href"])
        if not m:
            continue
        category = m.group("cat")
        gacha_id = m.group("id")
        if expected_category and category != expected_category:
            continue
        key = f"{category}:{gacha_id}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        text = a.get_text(separator="", strip=True)
        price_m = PRICE_RE.search(text)
        stock_m = STOCK_RE.search(text)
        if not price_m:
            continue
        title = ""
        img = a.find("img")
        if img and img.get("alt"):
            title = img["alt"].split("|")[0].strip()
        price = int(price_m.group(1).replace(",", ""))
        remaining = int(stock_m.group(1).replace(",", "")) if stock_m else None
        total = int(stock_m.group(2).replace(",", "")) if stock_m else None
        gachas.append({
            "key": key, "category": category, "id": gacha_id, "href": a["href"],
            "title": title, "price": price, "remaining": remaining, "total": total,
        })
    return gachas


def filter_target_price(gachas: list[dict], target_prices: set[int]) -> list[dict]:
    return [g for g in gachas if g["price"] in target_prices]


def category_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            print("[WARN] state.json 破損、初期化します")
    return {"tracked_gachas": {}, "first_run": True, "last_check": None}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def send_line(text: str) -> None:
    if not LINE_TOKEN:
        print("[WARN] LINE_CHANNEL_ACCESS_TOKEN 未設定、通知スキップ")
        return
    r = requests.post(
        LINE_BROADCAST_URL,
        headers={"Authorization": f"Bearer {LINE_TOKEN}", "Content-Type": "application/json"},
        json={"messages": [{"type": "text", "text": text[:5000]}]},
        timeout=30,
    )
    if r.status_code != 200:
        print(f"[ERROR] LINE API {r.status_code}: {r.text}")
        r.raise_for_status()
    print("[INFO] LINE通知送信完了")


def format_sold_out(prev: dict, watch_label: str, watch_url: str, now_iso: str) -> str:
    title = prev.get("title") or "(タイトル不明)"
    gid = prev.get("id", "?")
    price = prev.get("price", "?")
    total = prev.get("last_total")
    remaining = prev.get("last_remaining")
    miss_count = prev.get("miss_count", 1)
    return (
        f"🎴 [{watch_label}] {price}コイン/1回 売り切れ\n"
        f"「{title}」(id={gid})\n"
        f"一覧から消失(直前: 残り{remaining}/{total}、{miss_count}回連続未検出)\n"
        f"{watch_url}"
    )


def format_new(g: dict, watch_label: str, now_iso: str) -> str:
    return (
        f"🆕 [{watch_label}] {g['price']}コイン/1回 新規出品\n"
        f"「{g['title'] or '(タイトル不明)'}」(id={g['id']})\n"
        f"残り {g['remaining']}/{g['total']}\n"
        f"https://japan-toreca.com/oripa/{g['category']}/{g['id']}"
    )


def process_watch(watch: dict, now_iso: str, state: dict,
                  *, is_first_run: bool) -> list[str]:
    label = watch["label"]
    url = watch["url"]
    target_prices = set(watch["prices"])
    expected_cat = category_from_url(url)

    print(f"\n--- [{label}] {url} ---")
    print(f"[INFO] 監視対象価格: {sorted(target_prices)}")

    html = fetch_html(url)
    DEBUG_HTML_DIR.mkdir(exist_ok=True)
    (DEBUG_HTML_DIR / f"{expected_cat}.html").write_text(html, encoding="utf-8")
    print(f"[INFO] HTML取得: {len(html):,} bytes")

    all_gachas = parse_gachas(html, expected_category=expected_cat)

    if len(all_gachas) == 0:
        print(f"[WARN] {label}: ガチャ0件 → ページ取得失敗の可能性、スキップ")
        return []

    target_gachas = filter_target_price(all_gachas, target_prices)
    print(f"[INFO] ガチャ一覧: {len(all_gachas)}件 / うち対象価格: {len(target_gachas)}件")
    for g in target_gachas:
        print(f"       - {g['price']:>5}コイン id={g['id']} "
              f"残り{g['remaining']}/{g['total']} | {g['title'][:50]}")

    tracked = state.setdefault("tracked_gachas", {})
    notifications: list[str] = []
    current_keys = {g["key"] for g in target_gachas}

    for g in target_gachas:
        key = g["key"]
        if key in tracked:
            prev = tracked[key]
            prev["last_seen"] = now_iso
            prev["last_remaining"] = g["remaining"]
            prev["last_total"] = g["total"]
            prev["title"] = g["title"] or prev.get("title", "")
            prev["price"] = g["price"]
            prev["disappeared_at"] = None
            prev["miss_count"] = 0
            prev["is_sold_out"] = False
        else:
            entry = {
                "category": g["category"], "id": g["id"], "price": g["price"],
                "title": g["title"],
                "first_seen": now_iso, "last_seen": now_iso,
                "last_remaining": g["remaining"], "last_total": g["total"],
                "is_sold_out": False, "sold_out_at": None,
                "disappeared_at": None, "miss_count": 0,
                "watch_label": label,
            }
            tracked[key] = entry
            if NOTIFY_ON_NEW and not is_first_run:
                notifications.append(format_new(g, label, now_iso))
                print(f"[NOTIFY] 新規出品: {key} {g['title'][:40]}")
            else:
                print(f"[INFO] 新規記録(通知なし): {key} {g['title'][:40]}")

    for key, prev in list(tracked.items()):
        if prev.get("watch_label") != label:
            continue
        if key in current_keys:
            continue
        was_sold_out = prev.get("is_sold_out", False)

        prev["miss_count"] = prev.get("miss_count", 0) + 1
        miss_count = prev["miss_count"]

        if miss_count < MISS_THRESHOLD:
            print(f"[INFO] 未検出 ({miss_count}/{MISS_THRESHOLD}): {key} {prev.get('title', '')[:40]} ※まだ通知しない")
            continue

        if not was_sold_out and not is_first_run:
            prev["is_sold_out"] = True
            prev["sold_out_at"] = now_iso
            prev["disappeared_at"] = now_iso
            notifications.append(format_sold_out(prev, label, url, now_iso))
            print(f"[NOTIFY] 売り切れ: {key} {prev.get('title', '')[:40]}")
        else:
            if not prev.get("disappeared_at"):
                prev["disappeared_at"] = now_iso
                prev["is_sold_out"] = True
            print(f"[INFO] 既知の消失: {key} (was_sold_out={was_sold_out})")

    return notifications


def cleanup_stale(state: dict) -> int:
    tracked = state.get("tracked_gachas", {})
    cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
    removed = 0
    for key in list(tracked.keys()):
        d = tracked[key].get("disappeared_at")
        if not d:
            continue
        try:
            if datetime.fromisoformat(d) < cutoff:
                del tracked[key]
                removed += 1
        except Exception:
            pass
    if removed:
        print(f"[INFO] 古いエントリ {removed} 件を削除")
    return removed


def send_combined(notifications: list[str], now_iso: str) -> None:
    """複数の通知を1通にまとめてLINEに送信。"""
    if not notifications:
        return
    if len(notifications) == 1:
        body = notifications[0] + f"\n\n検知: {now_iso}"
        send_line(body)
        return
    header = f"🔔 オリパ更新 {len(notifications)}件\n"
    body = header + "\n\n────────\n\n".join(notifications) + f"\n\n検知: {now_iso}"
    # 5000文字制限の保険
    if len(body) > 4900:
        body = body[:4900] + "\n…(省略)"
    send_line(body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--notify", action="store_true")
    args = parser.parse_args()

    if args.notify:
        send_line(f"✅ LINE疎通テスト\n{datetime.now(timezone.utc).isoformat()}")
        return 0

    now_iso = datetime.now(timezone.utc).isoformat()
    print(f"[INFO] 実行時刻: {now_iso}")
    print(f"[INFO] 監視数: {len(WATCHES)}, NOTIFY_ON_NEW={NOTIFY_ON_NEW}, MISS_THRESHOLD={MISS_THRESHOLD}")

    state = load_state()
    is_first_run = state.get("first_run", False)

    all_notifications: list[str] = []
    for watch in WATCHES:
        notes = process_watch(watch, now_iso, state, is_first_run=is_first_run)
        all_notifications.extend(notes)

    cleanup_stale(state)

    state["last_check"] = now_iso
    if is_first_run:
        state["first_run"] = False
        print("\n[INFO] 初回実行のため、すべて状態記録のみ・通知ゼロ")
        all_notifications = []

    if args.test:
        print(f"\n[INFO] テストモード: 通知予定 {len(all_notifications)} 件")
        for n in all_notifications:
            print("--- 通知 ---")
            print(n)
        return 0

    save_state(state)
    send_combined(all_notifications, now_iso)
    print(f"\n[INFO] 処理完了(通知対象 {len(all_notifications)} 件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
