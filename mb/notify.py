"""
Optional daily push notification. Does nothing unless you set a secret:
  NTFY_TOPIC                       -> free, no signup: install the ntfy app, subscribe to your topic
  TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID -> Telegram bot message
PAGES_URL can override the link (default is derived from GITHUB_REPOSITORY).
"""
import os

import requests


def pages_url(env):
    if env.get("PAGES_URL"):
        return env["PAGES_URL"]
    repo = env.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return ""


def build_message(result, url=""):
    p = result.get("pick")
    if not p:
        why = "Top candidates failed AI due diligence." if result.get("dd_blocked") else "No candidate passed the filters."
        return f"Multibagger scan {result['generated']}: no pick today. {why}" + (f"\n{url}" if url else "")
    dd = p.get("diligence") or {}
    tag = {"green": "DD green", "yellow": "DD yellow, read the risks", "red": "DD red"}.get(dd.get("verdict"), "DD not run")
    streak = f" (day {p['streak']} on top)" if p.get("streak", 1) > 1 else " (new)"
    lines = [f"{p['name']} ({p['ticker']}) scored {p['score']:.0f}/100{streak}",
             f"Price Rs {p['price']:,.2f}. {tag}."]
    hi = [f for f in p.get("flags", []) if f.get("sev") == "high"]
    if hi:
        lines.append(f"{len(hi)} red flag(s): " + hi[0]["text"])
    if url:
        lines.append(url)
    return "\n".join(lines)


def send(result, env=None):
    env = os.environ if env is None else env
    url = pages_url(env)
    text = build_message(result, url)
    sent = []
    if env.get("NTFY_TOPIC"):
        try:
            h = {"Title": "Daily multibagger candidate"}
            if url:
                h["Click"] = url
            requests.post(f"https://ntfy.sh/{env['NTFY_TOPIC']}", data=text.encode("utf-8"), headers=h, timeout=20).raise_for_status()
            sent.append("ntfy")
        except Exception as e:
            print(f"ntfy failed: {str(e)[:100]}")
    if env.get("TELEGRAM_BOT_TOKEN") and env.get("TELEGRAM_CHAT_ID"):
        try:
            requests.post(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage",
                          json={"chat_id": env["TELEGRAM_CHAT_ID"], "text": text, "disable_web_page_preview": True},
                          timeout=20).raise_for_status()
            sent.append("telegram")
        except Exception as e:
            print("telegram failed: " + str(e).replace(env["TELEGRAM_BOT_TOKEN"], "***")[:100])
    return sent
