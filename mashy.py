#!/usr/bin/env python3
"""
mashy - Instagram auto-poster and DM updater (official Graph API).

Setup:
  pip install requests schedule python-dotenv
  Create a .env file next to this script:
      IG_USER_ID=1784xxxxxxxxxxxx
      IG_ACCESS_TOKEN=IGAAxxxxxxxx
  Requires an Instagram Business/Creator account with the
  instagram_business_content_publish and instagram_business_manage_messages
  permissions (set up in a Meta developer app).

Files:
  posts.json  - queue of posts: [{"image_url": "https://...", "caption": "..."}]
                image_url must be a public JPEG URL.
  update.txt  - the RB update text to DM out.

Usage:
  python mashy.py run          # start the scheduler
  python mashy.py post         # publish next queued post now
  python mashy.py dm           # send the update DM now
"""
import json
import os
import random
import sys
import time
from pathlib import Path

import requests
import schedule
from dotenv import load_dotenv

load_dotenv()

# ---------------- CONFIG ----------------
IG_USER_ID = os.getenv("IG_USER_ID")
TOKEN = os.getenv("IG_ACCESS_TOKEN")
BASE = "https://graph.instagram.com/v21.0"

POST_TIMES = ["10:00", "18:00"]   # daily post times (24h, local time)
DM_TIMES = ["12:00"]              # daily DM run times
MAX_DMS_PER_RUN = 25              # keep this low to avoid spam flags
DM_DELAY_RANGE = (20, 60)         # random seconds between DMs

HERE = Path(__file__).parent
POSTS_FILE = HERE / "posts.json"
UPDATE_FILE = HERE / "update.txt"
SENT_LOG = HERE / "dm_log.json"   # {user_id: last_sent_timestamp}
# ----------------------------------------


def api(method, path, **kwargs):
    params = kwargs.pop("params", {})
    params["access_token"] = TOKEN
    r = requests.request(method, f"{BASE}/{path}", params=params, timeout=60, **kwargs)
    data = r.json()
    if r.status_code >= 400:
        raise RuntimeError(f"API error {r.status_code}: {data}")
    return data


def log(msg):
    print(f"[mashy {time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# ---------------- POSTING ----------------
def publish_next_post():
    if not POSTS_FILE.exists():
        log("No posts.json found.")
        return
    queue = json.loads(POSTS_FILE.read_text())
    if not queue:
        log("Post queue is empty.")
        return

    post = queue[0]
    try:
        container = api("POST", f"{IG_USER_ID}/media", params={
            "image_url": post["image_url"],
            "caption": post.get("caption", ""),
        })
        # Give Instagram a moment to process the image
        time.sleep(10)
        api("POST", f"{IG_USER_ID}/media_publish",
            params={"creation_id": container["id"]})
        queue.pop(0)
        POSTS_FILE.write_text(json.dumps(queue, indent=2))
        log(f"Posted. {len(queue)} left in queue.")
    except Exception as e:
        log(f"Post failed: {e}")


# ---------------- DMs ----------------
def send_update_dms():
    if not UPDATE_FILE.exists():
        log("No update.txt found.")
        return
    text = UPDATE_FILE.read_text().strip()
    if not text:
        log("update.txt is empty.")
        return

    sent_log = json.loads(SENT_LOG.read_text()) if SENT_LOG.exists() else {}
    try:
        convos = api("GET", f"{IG_USER_ID}/conversations", params={
            "platform": "instagram",
            "fields": "participants,updated_time",
        }).get("data", [])
    except Exception as e:
        log(f"Could not fetch conversations: {e}")
        return

    sent = 0
    for c in convos:
        if sent >= MAX_DMS_PER_RUN:
            break
        for p in c.get("participants", {}).get("data", []):
            uid = p["id"]
            if uid == IG_USER_ID:
                continue
            # Don't send the same update text twice to the same person
            if sent_log.get(uid, {}).get("text") == text:
                continue
            try:
                api("POST", f"{IG_USER_ID}/messages", json={
                    "recipient": {"id": uid},
                    "message": {"text": text},
                })
                sent_log[uid] = {"text": text, "time": time.time()}
                sent += 1
                log(f"DM sent to {p.get('username', uid)}")
                time.sleep(random.uniform(*DM_DELAY_RANGE))
            except Exception as e:
                # Usually: outside the 24h messaging window
                log(f"Skipped {p.get('username', uid)}: {e}")
            SENT_LOG.write_text(json.dumps(sent_log, indent=2))
    log(f"DM run finished. Sent {sent}.")


# ---------------- SCHEDULER ----------------
def run():
    for t in POST_TIMES:
        schedule.every().day.at(t).do(publish_next_post)
    for t in DM_TIMES:
        schedule.every().day.at(t).do(send_update_dms)
    log(f"Running. Posts at {POST_TIMES}, DMs at {DM_TIMES}. Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


def main():
    if not IG_USER_ID or not TOKEN:
        sys.exit("Set IG_USER_ID and IG_ACCESS_TOKEN in your .env file.")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    {"run": run, "post": publish_next_post, "dm": send_update_dms}.get(
        cmd, lambda: sys.exit(__doc__))()


if __name__ == "__main__":
    main()
