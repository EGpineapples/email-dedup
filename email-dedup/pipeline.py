"""Discord scrape + filter pipeline.

Exposes run_scrape(channel_id, token, on_progress=None) -> dict.
Writes webhook_history.csv, declined_profiles.csv, checked_profiles.csv
next to this file.
"""
import os
import csv
import asyncio
import threading
import time
import traceback

try:
    import discord
    HAS_DISCORD = True
except ImportError:
    HAS_DISCORD = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HISTORY_CSV  = os.path.join(BASE_DIR, "webhook_history.csv")
DECLINED_CSV = os.path.join(BASE_DIR, "declined_profiles.csv")
CHECKED_CSV  = os.path.join(BASE_DIR, "checked_profiles.csv")


# ---------------- message -> dict ----------------
def _flatten(msg):
    row = {
        "message_id":        msg.id,
        "timestamp":         msg.created_at.isoformat(),
        "webhook_name":      str(msg.author),
        "content":           msg.content,
        "embed_title":       "",
        "embed_description": "",
        "embed_url":         "",
        "embed_footer":      "",
    }
    for embed in msg.embeds:
        row["embed_title"]       = embed.title or row["embed_title"]
        row["embed_description"] = embed.description or row["embed_description"]
        row["embed_url"]         = embed.url or row["embed_url"]
        row["embed_footer"]      = embed.footer.text if embed.footer else row["embed_footer"]
        for field in embed.fields:
            row[f"field_{field.name}"] = field.value
    return row


# ---------------- writers ----------------
def _write_history(rows):
    fieldnames = []
    for r in rows:
        for k in r:
            if k not in fieldnames:
                fieldnames.append(k)
    with open(HISTORY_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _filter_and_write():
    declined, checked = [], []
    with open(HISTORY_CSV, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            title   = (row.get("embed_title") or "").lower()
            profile = (row.get("field_Profile") or "").replace("||", "").strip()
            site    = (row.get("field_Site") or row.get("field_site") or "").strip()
            ts      = row.get("timestamp", "")
            entry   = {"timestamp": ts, "profile": profile, "site": site}
            if "declined" in title or "decline" in title:
                declined.append(entry)
            elif "checked" in title or "checkout" in title:
                checked.append(entry)

    for path, data in [(DECLINED_CSV, declined), (CHECKED_CSV, checked)]:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp", "profile", "site"])
            w.writeheader()
            w.writerows(data)
    return len(declined), len(checked)


# ---------------- async scrape ----------------
async def _do_scrape(token, channel_id, on_progress):
    if not HAS_DISCORD:
        return {"ok": False, "error": "discord.py is not installed"}

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    out = {"ok": False}

    @client.event
    async def on_ready():
        try:
            channel = client.get_channel(channel_id) or await client.fetch_channel(channel_id)
            if channel is None:
                raise RuntimeError(f"Channel {channel_id} not found or bot lacks access")

            rows, count = [], 0
            async for msg in channel.history(limit=None):
                if msg.webhook_id:
                    rows.append(_flatten(msg))
                count += 1
                if on_progress and count % 200 == 0:
                    on_progress(f"scanned {count} messages, {len(rows)} webhook rows")

            if on_progress:
                on_progress(f"writing {len(rows)} rows -> CSV")
            _write_history(rows)
            declined_n, checked_n = _filter_and_write()

            out.update({
                "ok":         True,
                "channel":    getattr(channel, "name", str(channel_id)),
                "scanned":    count,
                "webhooks":   len(rows),
                "declined":   declined_n,
                "checked":    checked_n,
            })
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"
            traceback.print_exc()
        finally:
            await client.close()

    try:
        await client.start(token)
    except Exception as e:
        if not out.get("error"):
            out["error"] = f"{type(e).__name__}: {e}"
    return out


def run_scrape(channel_id, token, on_progress=None):
    """Synchronous wrapper. Runs a fresh event loop, disconnects when done."""
    return asyncio.run(_do_scrape(token, int(channel_id), on_progress))


# ---------------- background-job runner ----------------
class ScrapeJob:
    """Thread-safe container so Flask can kick a scrape and poll its status."""
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        with self.lock:
            self.running = False
            self.status  = "idle"
            self.started = None
            self.result  = None
            self.error   = None
            self.channel_id = None

    def snapshot(self):
        with self.lock:
            return {
                "running":    self.running,
                "status":     self.status,
                "started":    self.started,
                "result":     self.result,
                "error":      self.error,
                "channel_id": self.channel_id,
            }

    def start(self, channel_id, token):
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.status  = "connecting to Discord..."
            self.started = time.time()
            self.result  = None
            self.error   = None
            self.channel_id = str(channel_id)

        def _progress(msg):
            with self.lock:
                self.status = msg

        def _run():
            try:
                res = run_scrape(channel_id, token, on_progress=_progress)
                with self.lock:
                    if res.get("ok"):
                        self.result = res
                        self.status = (f"done - {res['webhooks']} webhook rows "
                                       f"({res['declined']} declined, {res['checked']} checked)")
                    else:
                        self.error  = res.get("error", "unknown error")
                        self.status = f"failed: {self.error}"
            except Exception as e:
                with self.lock:
                    self.error  = f"{type(e).__name__}: {e}"
                    self.status = f"failed: {self.error}"
            finally:
                with self.lock:
                    self.running = False

        threading.Thread(target=_run, daemon=True).start()
        return True


JOB = ScrapeJob()
