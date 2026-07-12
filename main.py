import os
import json
import time
import threading
import datetime
import telebot
from google import genai as genai_client
from http.server import BaseHTTPRequestHandler, HTTPServer

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")

PRIMARY_ADMIN = "ak04756"
ALLOWED_ADMINS = ["ak04756", "kivo4159"]

# Runtime toggles
public_access_enabled = True
translation_enabled = True
broadcast_enabled = True
schedule_enabled = True
repeat_enabled = True

# ─────────────────────────────────────────────
# PERSISTENT STORAGE
# ─────────────────────────────────────────────
BLACKLIST_FILE = "blacklisted_users.json"
GROUPS_FILE = "tracked_groups.json"
TASKS_FILE = "active_tasks.json"

def _load_json(path, default):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return default

def _save_json(path, data):
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[WARN] Could not save {path}: {e}")

blacklisted_users = set(_load_json(BLACKLIST_FILE, []))
tracked_groups = set(_load_json(GROUPS_FILE, []))
tasks_data = _load_json(TASKS_FILE, {"counter": 0, "tasks": {}})
task_counter = tasks_data.get("counter", 0)
active_tasks = tasks_data.get("tasks", {})  # {str(task_id): task_dict}
task_stop_events = {}  # {str(task_id): threading.Event}

def save_blacklist():
    _save_json(BLACKLIST_FILE, list(blacklisted_users))

def save_groups():
    _save_json(GROUPS_FILE, list(tracked_groups))

def save_tasks():
    _save_json(TASKS_FILE, {"counter": task_counter, "tasks": active_tasks})

# ─────────────────────────────────────────────
# GOOGLE GENAI
# ─────────────────────────────────────────────
try:
    gemini_client = genai_client.Client(api_key=GOOGLE_API_KEY)
except Exception as e:
    print(f"[WARN] Gemini init failed: {e}")
    gemini_client = None

def translate_text(text):
    if not gemini_client:
        return "❌ Translation service unavailable."
    try:
        prompt = (
            "Detect the language of the following text and translate it to English. "
            "If it is already in English, translate it to Arabic. "
            "Reply with ONLY the translated text, no explanations.\n\n"
            f"{text}"
        )
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash", contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        return f"❌ Translation error: {e}"

def translate_image(file_id, caption):
    if not gemini_client:
        return "❌ Translation service unavailable."
    try:
        import urllib.request
        import io
        from google.genai import types as genai_types
        bot_file = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{bot_file.file_path}"
        img_bytes = urllib.request.urlopen(file_url).read()
        prompt = (
            "Describe and translate any text visible in this image to English. "
            "If the caption is provided, also translate it. "
            f"Caption: {caption or 'None'}\n"
            "Reply with only the translation/description."
        )
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                prompt,
                genai_types.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
            ],
        )
        return response.text.strip()
    except Exception as e:
        return f"❌ Image translation error: {e}"

# ─────────────────────────────────────────────
# BOT INIT
# ─────────────────────────────────────────────
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ─────────────────────────────────────────────
# SECURITY INTERCEPTOR
# ─────────────────────────────────────────────
def security_check(message):
    """Returns True if the message should be processed, False if blocked."""
    username = (message.from_user.username or "").lower()
    if username in blacklisted_users:
        try:
            bot.reply_to(message, "❌ You have been banned from using this bot by the administrator.")
        except Exception:
            pass
        return False
    if not public_access_enabled and username not in ALLOWED_ADMINS:
        try:
            bot.reply_to(message, "🔒 This bot is currently locked by the administrator. Only authorized users can access it.")
        except Exception:
            pass
        return False
    return True

def is_admin(message):
    return (message.from_user.username or "").lower() in ALLOWED_ADMINS

def is_primary_admin(message):
    return (message.from_user.username or "").lower() == PRIMARY_ADMIN

# ─────────────────────────────────────────────
# GROUP TRACKING
# ─────────────────────────────────────────────
@bot.message_handler(content_types=["new_chat_members"])
def on_new_member(message):
    if message.new_chat_members:
        for member in message.new_chat_members:
            if member.id == bot.get_me().id:
                tracked_groups.add(message.chat.id)
                save_groups()

# ─────────────────────────────────────────────
# BROADCAST DELIVERY
# ─────────────────────────────────────────────
def deliver_to_groups(text=None, photo_file_id=None, caption=None):
    for chat_id in list(tracked_groups):
        try:
            if photo_file_id:
                bot.send_photo(chat_id, photo_file_id, caption=caption)
            else:
                bot.send_message(chat_id, text)
        except Exception as e:
            print(f"[WARN] Failed to deliver to {chat_id}: {e}")

# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(message):
    if not security_check(message):
        return
    if message.chat.type in ("group", "supergroup"):
        tracked_groups.add(message.chat.id)
        save_groups()
    bot.reply_to(message, "👋 Hello! I'm online and ready. Use /help to see available commands.")

# ─────────────────────────────────────────────
# /help
# ─────────────────────────────────────────────
@bot.message_handler(commands=["help"])
def cmd_help(message):
    if not security_check(message):
        return
    username = (message.from_user.username or "").lower()

    general = (
        "📖 *General Commands:*\n"
        "/start — Start the bot\n"
        "/trans <text> — Translate text\n"
        "/tr <text> — Translate text (shortcut)\n"
        "/translate — Reply to a photo+caption to translate\n"
        "/help — Show this help\n"
    )

    admin_cmds = (
        "\n🛠 *Admin Commands:*\n"
        "/stop\\_bot — Lock public access\n"
        "/start\\_bot — Unlock public access\n"
        "/quota\\_status — Show quota info\n"
        "/broadcast <msg> — Send message to all groups\n"
        "/repeat <hours> <msg> — Repeat message every N hours\n"
        "/schedule <HH:MM AM/PM> <msg> — Schedule daily message\n"
        "/stop\\_rpt <ID> — Stop a repeat task\n"
        "/stop\\_schdl <ID> — Stop a schedule task\n"
        "/task\\_list — List all active tasks\n"
        "/clear\\_tasks — Clear all tasks\n"
        "/start\\_tracking — Add this group to tracking list\n"
    )

    primary_cmds = (
        "\n👑 *Primary Admin Only:*\n"
        "/toggle\\_trans — Toggle translation on/off\n"
        "/toggle\\_broadcast — Toggle broadcast on/off\n"
        "/toggle\\_schedule — Toggle scheduling on/off\n"
        "/toggle\\_repeat — Toggle repeat on/off\n"
        "/toggle\\_public — Toggle public access on/off\n"
        "/lock — Lock bot to admins only\n"
        "/unlock — Unlock bot for everyone\n"
        "/block <username> — Block a user\n"
        "/unblock <username> — Unblock a user\n"
    )

    if username == PRIMARY_ADMIN:
        text = general + admin_cmds + primary_cmds
    elif username in ALLOWED_ADMINS:
        text = general + admin_cmds
    else:
        text = (
            "📖 *Available Commands:*\n"
            "/start — Start the bot\n"
            "/trans <text> — Translate text to/from English\n"
            "/tr <text> — Shortcut for /trans\n"
            "/translate — Reply to a photo to translate its content\n"
            "/help — Show this help\n"
        )
    bot.reply_to(message, text, parse_mode="Markdown")

# ─────────────────────────────────────────────
# TRANSLATION COMMANDS
# ─────────────────────────────────────────────
@bot.message_handler(commands=["trans", "tr", "translate"])
def cmd_translate(message):
    if not security_check(message):
        return
    if not translation_enabled:
        bot.reply_to(message, "🔇 Translation is currently disabled by the administrator.")
        return

    # Handle reply to photo
    if message.reply_to_message and message.reply_to_message.photo:
        photo = message.reply_to_message.photo[-1]
        cap = message.reply_to_message.caption or ""
        result = translate_image(photo.file_id, cap)
        bot.reply_to(message, result)
        return

    # Handle text argument
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /trans <text>  or reply to a photo with /translate")
        return
    result = translate_text(parts[1])
    bot.reply_to(message, result)

# ─────────────────────────────────────────────
# /start_tracking
# ─────────────────────────────────────────────
@bot.message_handler(commands=["start_tracking"])
def cmd_start_tracking(message):
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    if message.chat.type in ("group", "supergroup"):
        tracked_groups.add(message.chat.id)
        save_groups()
        bot.reply_to(message, f"✅ This group (ID: {message.chat.id}) is now being tracked.")
    else:
        bot.reply_to(message, "ℹ️ This command must be used in a group chat.")

# ─────────────────────────────────────────────
# /groups
# ─────────────────────────────────────────────
@bot.message_handler(commands=["groups"])
def cmd_groups(message):
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    if not tracked_groups:
        bot.reply_to(message, "📭 No groups are currently being tracked.")
        return
    lines = [f"📋 *Tracked Groups ({len(tracked_groups)}):*\n"]
    for idx, chat_id in enumerate(tracked_groups, start=1):
        try:
            chat = bot.get_chat(chat_id)
            name = chat.title or chat.username or "Unknown"
        except Exception:
            name = "Unknown / Bot removed"
        lines.append(f"{idx}. {name}\n   `{chat_id}`")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────
# /quota_status
# ─────────────────────────────────────────────
@bot.message_handler(commands=["quota_status"])
def cmd_quota_status(message):
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    bot.reply_to(
        message,
        f"📊 *Quota / Status:*\n"
        f"Tracked groups: {len(tracked_groups)}\n"
        f"Active tasks: {len(active_tasks)}\n"
        f"Blacklisted users: {len(blacklisted_users)}\n"
        f"Public access: {'✅' if public_access_enabled else '🔒'}\n"
        f"Translation: {'✅' if translation_enabled else '❌'}\n"
        f"Broadcast: {'✅' if broadcast_enabled else '❌'}\n"
        f"Schedule: {'✅' if schedule_enabled else '❌'}\n"
        f"Repeat: {'✅' if repeat_enabled else '❌'}",
        parse_mode="Markdown"
    )

# ─────────────────────────────────────────────
# /stop_bot / /start_bot
# ─────────────────────────────────────────────
@bot.message_handler(commands=["stop_bot"])
def cmd_stop_bot(message):
    global public_access_enabled
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    public_access_enabled = False
    bot.reply_to(message, "🔒 Bot locked. Only admins can use it now.")

@bot.message_handler(commands=["start_bot"])
def cmd_start_bot(message):
    global public_access_enabled
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    public_access_enabled = True
    bot.reply_to(message, "✅ Bot unlocked. Public access enabled.")

# ─────────────────────────────────────────────
# TOGGLE COMMANDS (primary admin only)
# ─────────────────────────────────────────────
def _primary_only(message):
    if not is_primary_admin(message):
        bot.reply_to(message, "⛔ This command is for the primary admin only.")
        return False
    return True

@bot.message_handler(commands=["toggle_trans"])
def cmd_toggle_trans(message):
    global translation_enabled
    if not security_check(message): return
    if not _primary_only(message): return
    translation_enabled = not translation_enabled
    bot.reply_to(message, f"Translation is now {'✅ enabled' if translation_enabled else '❌ disabled'}.")

@bot.message_handler(commands=["toggle_broadcast"])
def cmd_toggle_broadcast(message):
    global broadcast_enabled
    if not security_check(message): return
    if not _primary_only(message): return
    broadcast_enabled = not broadcast_enabled
    bot.reply_to(message, f"Broadcast is now {'✅ enabled' if broadcast_enabled else '❌ disabled'}.")

@bot.message_handler(commands=["toggle_schedule"])
def cmd_toggle_schedule(message):
    global schedule_enabled
    if not security_check(message): return
    if not _primary_only(message): return
    schedule_enabled = not schedule_enabled
    bot.reply_to(message, f"Scheduling is now {'✅ enabled' if schedule_enabled else '❌ disabled'}.")

@bot.message_handler(commands=["toggle_repeat"])
def cmd_toggle_repeat(message):
    global repeat_enabled
    if not security_check(message): return
    if not _primary_only(message): return
    repeat_enabled = not repeat_enabled
    bot.reply_to(message, f"Repeat is now {'✅ enabled' if repeat_enabled else '❌ disabled'}.")

@bot.message_handler(commands=["toggle_public"])
def cmd_toggle_public(message):
    global public_access_enabled
    if not security_check(message): return
    if not _primary_only(message): return
    public_access_enabled = not public_access_enabled
    bot.reply_to(message, f"Public access is now {'✅ enabled' if public_access_enabled else '🔒 disabled'}.")

@bot.message_handler(commands=["lock"])
def cmd_lock(message):
    global public_access_enabled
    if not security_check(message): return
    if not _primary_only(message): return
    public_access_enabled = False
    bot.reply_to(message, "🔒 Bot locked to admins only.")

@bot.message_handler(commands=["unlock"])
def cmd_unlock(message):
    global public_access_enabled
    if not security_check(message): return
    if not _primary_only(message): return
    public_access_enabled = True
    bot.reply_to(message, "🔓 Bot unlocked for everyone.")

@bot.message_handler(commands=["block"])
def cmd_block(message):
    if not security_check(message): return
    if not _primary_only(message): return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /block <username>")
        return
    target = parts[1].lstrip("@").lower()
    blacklisted_users.add(target)
    save_blacklist()
    bot.reply_to(message, f"✅ @{target} has been blocked.")

@bot.message_handler(commands=["unblock"])
def cmd_unblock(message):
    if not security_check(message): return
    if not _primary_only(message): return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /unblock <username>")
        return
    target = parts[1].lstrip("@").lower()
    blacklisted_users.discard(target)
    save_blacklist()
    bot.reply_to(message, f"✅ @{target} has been unblocked.")

# ─────────────────────────────────────────────
# TASK MANAGEMENT HELPERS
# ─────────────────────────────────────────────
def _new_task_id():
    global task_counter
    task_counter += 1
    return task_counter

def _register_task(task_id, task_type, interval_hours=None, scheduled_time=None,
                   text=None, photo_file_id=None, caption=None):
    tid = str(task_id)
    active_tasks[tid] = {
        "id": task_id,
        "type": task_type,
        "interval_hours": interval_hours,
        "scheduled_time": scheduled_time,
        "text": text,
        "photo_file_id": photo_file_id,
        "caption": caption,
    }
    save_tasks()

def _unregister_task(task_id):
    tid = str(task_id)
    active_tasks.pop(tid, None)
    save_tasks()

def _stop_event_for(task_id):
    tid = str(task_id)
    if tid not in task_stop_events:
        task_stop_events[tid] = threading.Event()
    return task_stop_events[tid]

# ─────────────────────────────────────────────
# REPEAT TASK
# ─────────────────────────────────────────────
def _run_repeat(task_id, interval_hours, text, photo_file_id, caption):
    stop_event = _stop_event_for(task_id)
    while not stop_event.is_set():
        deliver_to_groups(text=text, photo_file_id=photo_file_id, caption=caption)
        stop_event.wait(timeout=interval_hours * 3600)
    _unregister_task(task_id)
    task_stop_events.pop(str(task_id), None)

@bot.message_handler(commands=["repeat"])
def cmd_repeat(message):
    if not security_check(message): return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    if not repeat_enabled:
        bot.reply_to(message, "❌ Repeat is currently disabled.")
        return
    if not tracked_groups:
        bot.reply_to(message, "⚠️ No groups are being tracked yet.")
        return

    # Parse: /repeat <hours> <message>  or reply to photo
    photo_file_id = None
    caption = None
    text = None
    interval_hours = None

    parts = message.text.split(None, 2)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /repeat <hours> <message>  (or reply to a photo)")
        return
    try:
        interval_hours = float(parts[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid hours value.")
        return

    if message.reply_to_message and message.reply_to_message.photo:
        photo_file_id = message.reply_to_message.photo[-1].file_id
        caption = message.reply_to_message.caption or (parts[2] if len(parts) > 2 else "")
    elif len(parts) > 2:
        text = parts[2]
    else:
        bot.reply_to(message, "Usage: /repeat <hours> <message>")
        return

    tid = _new_task_id()
    _register_task(tid, "repeat", interval_hours=interval_hours,
                   text=text, photo_file_id=photo_file_id, caption=caption)
    t = threading.Thread(target=_run_repeat, args=(tid, interval_hours, text, photo_file_id, caption), daemon=True)
    t.start()
    bot.reply_to(message, f"✅ Repeat task #{tid} started — every {interval_hours}h to {len(tracked_groups)} group(s).")

# ─────────────────────────────────────────────
# SCHEDULE TASK
# ─────────────────────────────────────────────
def _run_schedule(task_id, scheduled_time_str, text, photo_file_id, caption):
    """scheduled_time_str: 'HH:MM AM/PM' e.g. '09:30 AM'"""
    stop_event = _stop_event_for(task_id)
    while not stop_event.is_set():
        now = datetime.datetime.now()
        try:
            target = datetime.datetime.strptime(scheduled_time_str, "%I:%M %p").replace(
                year=now.year, month=now.month, day=now.day
            )
        except ValueError:
            # Try 24h format fallback
            try:
                target = datetime.datetime.strptime(scheduled_time_str, "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
            except ValueError:
                break
        if target <= now:
            target += datetime.timedelta(days=1)
        wait_secs = (target - now).total_seconds()
        stop_event.wait(timeout=wait_secs)
        if stop_event.is_set():
            break
        deliver_to_groups(text=text, photo_file_id=photo_file_id, caption=caption)
    _unregister_task(task_id)
    task_stop_events.pop(str(task_id), None)

@bot.message_handler(commands=["schedule"])
def cmd_schedule(message):
    if not security_check(message): return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    if not schedule_enabled:
        bot.reply_to(message, "❌ Scheduling is currently disabled.")
        return
    if not tracked_groups:
        bot.reply_to(message, "⚠️ No groups are being tracked yet.")
        return

    # /schedule HH:MM AM/PM message
    # Consume first 3 tokens as time (e.g. "09:30 AM")
    parts = message.text.split(None, 3)
    if len(parts) < 3:
        bot.reply_to(message, "Usage: /schedule <HH:MM> <AM/PM> <message>")
        return

    scheduled_time_str = f"{parts[1]} {parts[2]}"
    photo_file_id = None
    caption = None
    text = None

    if message.reply_to_message and message.reply_to_message.photo:
        photo_file_id = message.reply_to_message.photo[-1].file_id
        caption = message.reply_to_message.caption or (parts[3] if len(parts) > 3 else "")
    elif len(parts) > 3:
        text = parts[3]
    else:
        bot.reply_to(message, "Usage: /schedule <HH:MM> <AM/PM> <message>")
        return

    tid = _new_task_id()
    _register_task(tid, "schedule", scheduled_time=scheduled_time_str,
                   text=text, photo_file_id=photo_file_id, caption=caption)
    t = threading.Thread(target=_run_schedule, args=(tid, scheduled_time_str, text, photo_file_id, caption), daemon=True)
    t.start()
    bot.reply_to(message, f"✅ Schedule task #{tid} created — daily at {scheduled_time_str} to {len(tracked_groups)} group(s).")

# ─────────────────────────────────────────────
# /broadcast
# ─────────────────────────────────────────────
@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if not security_check(message): return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    if not broadcast_enabled:
        bot.reply_to(message, "❌ Broadcast is currently disabled.")
        return
    if not tracked_groups:
        bot.reply_to(message, "⚠️ No groups are being tracked yet.")
        return

    photo_file_id = None
    caption = None
    text = None

    if message.reply_to_message and message.reply_to_message.photo:
        photo_file_id = message.reply_to_message.photo[-1].file_id
        caption = message.reply_to_message.caption or ""
    else:
        parts = message.text.split(None, 1)
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /broadcast <message>  or reply to a photo")
            return
        text = parts[1]

    def _do_broadcast():
        deliver_to_groups(text=text, photo_file_id=photo_file_id, caption=caption)

    threading.Thread(target=_do_broadcast, daemon=True).start()
    bot.reply_to(message, f"📢 Broadcasting to {len(tracked_groups)} group(s)...")

# ─────────────────────────────────────────────
# STOP REPEAT / SCHEDULE
# ─────────────────────────────────────────────
@bot.message_handler(commands=["stop_rpt"])
def cmd_stop_rpt(message):
    if not security_check(message): return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /stop_rpt <task_id>")
        return
    tid = parts[1].strip()
    if tid not in active_tasks:
        bot.reply_to(message, f"❌ Task #{tid} not found.")
        return
    if tid in task_stop_events:
        task_stop_events[tid].set()
    _unregister_task(int(tid))
    bot.reply_to(message, f"🛑 Repeat task #{tid} stopped.")

@bot.message_handler(commands=["stop_schdl"])
def cmd_stop_schdl(message):
    if not security_check(message): return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /stop_schdl <task_id>")
        return
    tid = parts[1].strip()
    if tid not in active_tasks:
        bot.reply_to(message, f"❌ Task #{tid} not found.")
        return
    if tid in task_stop_events:
        task_stop_events[tid].set()
    _unregister_task(int(tid))
    bot.reply_to(message, f"🛑 Schedule task #{tid} stopped.")

# ─────────────────────────────────────────────
# /task_list
# ─────────────────────────────────────────────
@bot.message_handler(commands=["task_list"])
def cmd_task_list(message):
    if not security_check(message): return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    if not active_tasks:
        bot.reply_to(message, "📋 No active tasks.")
        return
    lines = ["📋 *Active Tasks:*"]
    for tid, task in active_tasks.items():
        ttype = task.get("type", "?")
        if ttype == "repeat":
            detail = f"every {task.get('interval_hours')}h"
        else:
            detail = f"daily at {task.get('scheduled_time')}"
        content = "📷 photo" if task.get("photo_file_id") else f"💬 {str(task.get('text',''))[:30]}..."
        lines.append(f"#{tid} [{ttype}] {detail} — {content}")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")

# ─────────────────────────────────────────────
# /clear_tasks
# ─────────────────────────────────────────────
@bot.message_handler(commands=["clear_tasks"])
def cmd_clear_tasks(message):
    if not security_check(message): return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    for tid, ev in list(task_stop_events.items()):
        ev.set()
    task_stop_events.clear()
    active_tasks.clear()
    save_tasks()
    bot.reply_to(message, "🗑 All tasks cleared.")

# ─────────────────────────────────────────────
# RESTORE TASKS ON STARTUP
# ─────────────────────────────────────────────
def restore_tasks():
    for tid, task in list(active_tasks.items()):
        ttype = task.get("type")
        text = task.get("text")
        photo_file_id = task.get("photo_file_id")
        caption = task.get("caption")
        task_id = task.get("id")
        if ttype == "repeat":
            interval_hours = task.get("interval_hours", 1)
            t = threading.Thread(target=_run_repeat, args=(task_id, interval_hours, text, photo_file_id, caption), daemon=True)
            t.start()
            print(f"[INFO] Restored repeat task #{task_id} (every {interval_hours}h)")
        elif ttype == "schedule":
            scheduled_time = task.get("scheduled_time")
            t = threading.Thread(target=_run_schedule, args=(task_id, scheduled_time, text, photo_file_id, caption), daemon=True)
            t.start()
            print(f"[INFO] Restored schedule task #{task_id} (daily at {scheduled_time})")

# ─────────────────────────────────────────────
# HEALTH CHECK WEB SERVER
# ─────────────────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        pass  # Suppress access logs

def start_health_server():
    server = HTTPServer(("0.0.0.0", 8000), HealthHandler)
    server.serve_forever()

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is not set. Exiting.")
        exit(1)

    # Start health-check HTTP server
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    print("✅ Health check server started on port 8080")

    # Print uptime URL hint
    import os as _os
    replit_domains = _os.environ.get("REPLIT_DOMAINS", "")
    if replit_domains:
        domain = replit_domains.split(",")[0].strip()
        print(f"\n🌐 Uptime URL (plug into UptimeRobot / Cron-Job.org):")
        print(f"   https://{domain}/api/health\n")
    else:
        print("\n🌐 Health endpoint available at: http://localhost:8080\n")

    # Restore persisted tasks from previous run
    restore_tasks()
    print(f"[INFO] Restored {len(active_tasks)} task(s) from disk.")
    print(f"[INFO] Tracking {len(tracked_groups)} group(s).")

    # Start polling
    print("🤖 Bot is running. Polling for updates...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        except Exception as e:
            print(f"[ERROR] Polling crashed: {e}. Restarting in 5s...")
            time.sleep(5)
