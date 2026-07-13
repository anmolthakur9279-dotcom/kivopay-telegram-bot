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

PRIMARY_ADMINS = [
    "ak04756",
]
ALLOWED_ADMINS = ["ak04756", "kivo4259", "kivopaycarl"]

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


def _load_groups():
    """Load groups as dict {str(chat_id): {id, name}}. Migrates old list format."""
    raw = _load_json(GROUPS_FILE, {})
    if isinstance(raw, list):
        # Migrate from old set/list format
        return {str(cid): {"id": cid, "name": f"Group {cid}"} for cid in raw}
    return raw


blacklisted_users = set(_load_json(BLACKLIST_FILE, []))
tracked_groups = _load_groups()   # {str(chat_id): {"id": int, "name": str}}
tasks_data = _load_json(TASKS_FILE, {"counter": 0, "tasks": {}})
task_counter = tasks_data.get("counter", 0)
active_tasks = tasks_data.get("tasks", {})   # {str(task_id): task_dict}
task_stop_events = {}                         # {str(task_id): threading.Event}


def save_blacklist():
    _save_json(BLACKLIST_FILE, list(blacklisted_users))


def save_groups():
    _save_json(GROUPS_FILE, tracked_groups)


def save_tasks():
    _save_json(TASKS_FILE, {"counter": task_counter, "tasks": active_tasks})


def _add_group(chat_id, name):
    """Register or update a group in tracked_groups."""
    tracked_groups[str(chat_id)] = {
        "id": chat_id,
        "name": name or f"Group {chat_id}",
    }
    save_groups()


def _remove_group(chat_id):
    tracked_groups.pop(str(chat_id), None)
    save_groups()


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
            "Reply with ONLY the translated English text, no explanations, no language labels.\n\n"
            f"{text}"
        )
        response = gemini_client.models.generate_content(
            model="gemini-3.1-flash-lite", contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        return f"❌ Translation error: {e}"


def translate_image(file_id, caption):
    if not gemini_client:
        return "❌ Translation service unavailable."
    try:
        import urllib.request
        from google.genai import types as genai_types

        bot_file = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{bot_file.file_path}"
        img_bytes = urllib.request.urlopen(file_url).read()
        prompt = (
            "Detect the language of any text visible in this image and translate it to English. "
            "If a caption is provided, also translate the caption to English. "
            f"Caption: {caption or 'None'}\n"
            "Reply with ONLY the translated English text, no explanations, no language labels."
        )
        response = gemini_client.models.generate_content(
            model="gemini-3.1-flash-lite",
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
    return (message.from_user.username or "").lower() in PRIMARY_ADMINS


# ─────────────────────────────────────────────
# GROUP TRACKING
# ─────────────────────────────────────────────
@bot.message_handler(content_types=["new_chat_members"])
def on_new_member(message):
    if message.new_chat_members:
        for member in message.new_chat_members:
            if member.id == bot.get_me().id:
                name = message.chat.title or message.chat.username or f"Group {message.chat.id}"
                _add_group(message.chat.id, name)


# ─────────────────────────────────────────────
# BROADCAST DELIVERY
# ─────────────────────────────────────────────
def deliver_to_groups(text=None, photo_file_id=None, caption=None, targeted_group_ids=None, photo_path=None):
    """Send to specified groups, or all tracked groups if targeted_group_ids is None/empty.
    Auto-removes stale groups (403 Forbidden / 400 group-upgraded errors)."""
    if targeted_group_ids:
        target_ids = [
            info["id"]
            for cid, info in tracked_groups.items()
            if cid in [str(g) for g in targeted_group_ids]
        ]
    else:
        target_ids = [info["id"] for info in tracked_groups.values()]

    stale_ids = []
    for chat_id in target_ids:
        try:
            if photo_path and os.path.exists(photo_path):
                with open(photo_path, "rb") as f:
                    bot.send_photo(chat_id, f, caption=caption or text)
            elif photo_file_id:
                bot.send_photo(chat_id, photo_file_id, caption=caption)
            else:
                bot.send_message(chat_id, text)
        except Exception as e:
            err = str(e)
            if "Error code: 403" in err or (
                "Error code: 400" in err and any(kw in err for kw in ["kicked", "upgraded", "deleted", "deactivated"])
            ):
                print(f"[INFO] Auto-removing stale group {chat_id}: {err[:80]}")
                stale_ids.append(chat_id)
            else:
                print(f"[WARN] Failed to deliver to {chat_id}: {e}")

    for chat_id in stale_ids:
        _remove_group(chat_id)


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
@bot.message_handler(commands=["start"])
def cmd_start(message):
    if not security_check(message):
        return
    if message.chat.type in ("group", "supergroup"):
        name = message.chat.title or f"Group {message.chat.id}"
        _add_group(message.chat.id, name)
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
        "/stop\\_task <ID> — Stop any task by ID\n"
        "/task\\_list — List all active tasks\n"
        "/clear\\_tasks — Clear all tasks\n"
        "/groups — List tracked groups\n"
        "/remove\\_group <id> — Remove a group from tracking\n"
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

    if username in PRIMARY_ADMINS:
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

    if message.reply_to_message and message.reply_to_message.photo:
        photo = message.reply_to_message.photo[-1]
        cap = message.reply_to_message.caption or ""
        result = translate_image(photo.file_id, cap)
        bot.reply_to(message, result)
        return

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
        name = message.chat.title or f"Group {message.chat.id}"
        _add_group(message.chat.id, name)
        bot.reply_to(message, f"✅ This group ({name}, ID: {message.chat.id}) is now being tracked.")
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
    for idx, (cid, info) in enumerate(tracked_groups.items(), start=1):
        name = info.get("name", "Unknown")
        lines.append(f"{idx}. {name}\n   `{cid}`")
    bot.reply_to(message, "\n".join(lines), parse_mode="Markdown")


# ─────────────────────────────────────────────
# /remove_group
# ─────────────────────────────────────────────
@bot.message_handler(commands=["remove_group"])
def cmd_remove_group(message):
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /remove_group <group_id>\nUse /groups to see all IDs.")
        return
    try:
        chat_id = int(parts[1].strip())
    except ValueError:
        bot.reply_to(message, "❌ Invalid group ID. Must be a number (e.g. -1001234567890).")
        return
    if str(chat_id) in tracked_groups:
        name = tracked_groups[str(chat_id)].get("name", str(chat_id))
        _remove_group(chat_id)
        bot.reply_to(message, f"✅ Group *{name}* (`{chat_id}`) removed from tracking list.", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"❌ Group `{chat_id}` is not in the tracking list.", parse_mode="Markdown")


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
        parse_mode="Markdown",
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
    if not security_check(message):
        return
    if not _primary_only(message):
        return
    translation_enabled = not translation_enabled
    bot.reply_to(message, f"Translation is now {'✅ enabled' if translation_enabled else '❌ disabled'}.")


@bot.message_handler(commands=["toggle_broadcast"])
def cmd_toggle_broadcast(message):
    global broadcast_enabled
    if not security_check(message):
        return
    if not _primary_only(message):
        return
    broadcast_enabled = not broadcast_enabled
    bot.reply_to(message, f"Broadcast is now {'✅ enabled' if broadcast_enabled else '❌ disabled'}.")


@bot.message_handler(commands=["toggle_schedule"])
def cmd_toggle_schedule(message):
    global schedule_enabled
    if not security_check(message):
        return
    if not _primary_only(message):
        return
    schedule_enabled = not schedule_enabled
    bot.reply_to(message, f"Scheduling is now {'✅ enabled' if schedule_enabled else '❌ disabled'}.")


@bot.message_handler(commands=["toggle_repeat"])
def cmd_toggle_repeat(message):
    global repeat_enabled
    if not security_check(message):
        return
    if not _primary_only(message):
        return
    repeat_enabled = not repeat_enabled
    bot.reply_to(message, f"Repeat is now {'✅ enabled' if repeat_enabled else '❌ disabled'}.")


@bot.message_handler(commands=["toggle_public"])
def cmd_toggle_public(message):
    global public_access_enabled
    if not security_check(message):
        return
    if not _primary_only(message):
        return
    public_access_enabled = not public_access_enabled
    bot.reply_to(message, f"Public access is now {'✅ enabled' if public_access_enabled else '🔒 disabled'}.")


@bot.message_handler(commands=["lock"])
def cmd_lock(message):
    global public_access_enabled
    if not security_check(message):
        return
    if not _primary_only(message):
        return
    public_access_enabled = False
    bot.reply_to(message, "🔒 Bot locked to admins only.")


@bot.message_handler(commands=["unlock"])
def cmd_unlock(message):
    global public_access_enabled
    if not security_check(message):
        return
    if not _primary_only(message):
        return
    public_access_enabled = True
    bot.reply_to(message, "🔓 Bot unlocked for everyone.")


@bot.message_handler(commands=["block"])
def cmd_block(message):
    if not security_check(message):
        return
    if not _primary_only(message):
        return
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
    if not security_check(message):
        return
    if not _primary_only(message):
        return
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


def _register_task(
    task_id,
    task_type,
    interval_hours=None,
    scheduled_time=None,
    text=None,
    photo_file_id=None,
    caption=None,
    targeted_groups=None,
    photo_path=None,
):
    tid = str(task_id)
    active_tasks[tid] = {
        "id": task_id,
        "type": task_type,
        "interval_hours": interval_hours,
        "scheduled_time": scheduled_time,
        "text": text,
        "photo_file_id": photo_file_id,
        "photo_path": photo_path,
        "caption": caption,
        "targeted_groups": targeted_groups or [],  # [] = broadcast to ALL groups
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
def _run_repeat(task_id, interval_hours, text, photo_file_id, caption, photo_path=None):
    stop_event = _stop_event_for(task_id)
    while not stop_event.is_set():
        task = active_tasks.get(str(task_id), {})
        tg = task.get("targeted_groups") or []
        pp = task.get("photo_path") or photo_path
        deliver_to_groups(
            text=text,
            photo_file_id=photo_file_id,
            photo_path=pp,
            caption=caption,
            targeted_group_ids=tg if tg else None,
        )
        stop_event.wait(timeout=interval_hours * 3600)
    # Only clean up if we're still the owner — a PUT edit may have replaced us
    tid = str(task_id)
    if task_stop_events.get(tid) is stop_event:
        _unregister_task(task_id)
        task_stop_events.pop(tid, None)


@bot.message_handler(commands=["repeat"])
def cmd_repeat(message):
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    if not repeat_enabled:
        bot.reply_to(message, "❌ Repeat is currently disabled.")
        return
    if not tracked_groups:
        bot.reply_to(message, "⚠️ No groups are being tracked yet.")
        return

    photo_file_id = None
    caption = None
    text = None

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
    _register_task(tid, "repeat", interval_hours=interval_hours, text=text, photo_file_id=photo_file_id, caption=caption)
    t = threading.Thread(target=_run_repeat, args=(tid, interval_hours, text, photo_file_id, caption), daemon=True)
    t.start()
    bot.reply_to(message, f"✅ Repeat task #{tid} started — every {interval_hours}h to {len(tracked_groups)} group(s).\nUse /stop_task {tid} to stop it.")


# ─────────────────────────────────────────────
# SCHEDULE TASK
# ─────────────────────────────────────────────
def _run_schedule(task_id, scheduled_time_str, text, photo_file_id, caption, photo_path=None):
    stop_event = _stop_event_for(task_id)
    while not stop_event.is_set():
        now = datetime.datetime.now()
        try:
            target = datetime.datetime.strptime(scheduled_time_str, "%I:%M %p").replace(
                year=now.year, month=now.month, day=now.day
            )
        except ValueError:
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
        task = active_tasks.get(str(task_id), {})
        tg = task.get("targeted_groups") or []
        pp = task.get("photo_path") or photo_path
        deliver_to_groups(
            text=text,
            photo_file_id=photo_file_id,
            photo_path=pp,
            caption=caption,
            targeted_group_ids=tg if tg else None,
        )
    # Only clean up if we're still the owner — a PUT edit may have replaced us
    tid = str(task_id)
    if task_stop_events.get(tid) is stop_event:
        _unregister_task(task_id)
        task_stop_events.pop(tid, None)


@bot.message_handler(commands=["schedule"])
def cmd_schedule(message):
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    if not schedule_enabled:
        bot.reply_to(message, "❌ Scheduling is currently disabled.")
        return
    if not tracked_groups:
        bot.reply_to(message, "⚠️ No groups are being tracked yet.")
        return

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
    _register_task(tid, "schedule", scheduled_time=scheduled_time_str, text=text, photo_file_id=photo_file_id, caption=caption)
    t = threading.Thread(target=_run_schedule, args=(tid, scheduled_time_str, text, photo_file_id, caption), daemon=True)
    t.start()
    bot.reply_to(message, f"✅ Schedule task #{tid} created — daily at {scheduled_time_str} to {len(tracked_groups)} group(s).\nUse /stop_task {tid} to stop it.")


# ─────────────────────────────────────────────
# /broadcast
# ─────────────────────────────────────────────
@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if not security_check(message):
        return
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

    threading.Thread(target=deliver_to_groups, kwargs={"text": text, "photo_file_id": photo_file_id, "caption": caption}, daemon=True).start()
    bot.reply_to(message, f"📢 Broadcasting to {len(tracked_groups)} group(s)...")


# ─────────────────────────────────────────────
# /stop_task (unified stop for repeat + schedule)
# ─────────────────────────────────────────────
@bot.message_handler(commands=["stop_task", "stop_rpt", "stop_schdl"])
def cmd_stop_task(message):
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    parts = message.text.split(None, 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /stop_task <task_id>")
        return
    tid = parts[1].strip()
    if tid not in active_tasks:
        bot.reply_to(message, f"❌ Task #{tid} not found. Use /task_list to see active tasks.")
        return
    task_type = active_tasks[tid].get("type", "task")
    if tid in task_stop_events:
        task_stop_events[tid].set()
    _unregister_task(int(tid))
    bot.reply_to(message, f"🛑 {task_type.capitalize()} task #{tid} stopped.")


# ─────────────────────────────────────────────
# /task_list
# ─────────────────────────────────────────────
@bot.message_handler(commands=["task_list", "tasks"])
def cmd_task_list(message):
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    if not active_tasks:
        bot.reply_to(message, "📋 No active tasks.")
        return

    lines = [f"📋 Active Tasks ({len(active_tasks)}):"]
    for tid, task in sorted(active_tasks.items(), key=lambda x: int(x[0])):
        try:
            ttype = task.get("type", "?")
            emoji = "🔁" if ttype == "repeat" else "⏰"

            if ttype == "repeat":
                detail = f"every {task.get('interval_hours')}h"
            else:
                detail = f"daily at {task.get('scheduled_time', '?')}"

            content = "📷 photo" if task.get("photo_file_id") else f"💬 {str(task.get('text', ''))[:40]}"

            tg = task.get("targeted_groups") or []
            if tg:
                group_names = []
                for g in tg:
                    info = tracked_groups.get(str(g))
                    group_names.append(info["name"] if info else str(g))
                groups_str = f"🎯 {', '.join(group_names)}"
            else:
                groups_str = f"📡 All {len(tracked_groups)} group(s)"

            lines.append(f"\n{emoji} Task #{tid} — {detail}\n   {content}\n   {groups_str}\n   Stop: /stop_task {tid}")
        except Exception as e:
            lines.append(f"\n⚠️ Task #{tid} (error reading: {e})")

    bot.reply_to(message, "\n".join(lines))


# ─────────────────────────────────────────────
# /clear_tasks
# ─────────────────────────────────────────────
@bot.message_handler(commands=["clear_tasks"])
def cmd_clear_tasks(message):
    if not security_check(message):
        return
    if not is_admin(message):
        bot.reply_to(message, "⛔ Admin only.")
        return
    for ev in list(task_stop_events.values()):
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
        photo_path = task.get("photo_path")
        caption = task.get("caption")
        task_id = task.get("id")
        if ttype == "repeat":
            interval_hours = task.get("interval_hours", 1)
            t = threading.Thread(target=_run_repeat, args=(task_id, interval_hours, text, photo_file_id, caption), kwargs={"photo_path": photo_path}, daemon=True)
            t.start()
            print(f"[INFO] Restored repeat task #{task_id} (every {interval_hours}h)")
        elif ttype == "schedule":
            scheduled_time = task.get("scheduled_time")
            t = threading.Thread(target=_run_schedule, args=(task_id, scheduled_time, text, photo_file_id, caption), kwargs={"photo_path": photo_path}, daemon=True)
            t.start()
            print(f"[INFO] Restored schedule task #{task_id} (daily at {scheduled_time})")


# ─────────────────────────────────────────────
# INTERNAL HTTP API (port 8001 — localhost only)
# Used by the Express admin dashboard
# ─────────────────────────────────────────────
class InternalAPIHandler(BaseHTTPRequestHandler):
    def _send(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length:
            return json.loads(self.rfile.read(length))
        return {}

    def do_GET(self):
        if self.path == "/status":
            self._send(200, {
                "tracked_groups": len(tracked_groups),
                "active_tasks": len(active_tasks),
                "public_access": public_access_enabled,
                "translation": translation_enabled,
                "broadcast": broadcast_enabled,
                "schedule": schedule_enabled,
                "repeat": repeat_enabled,
            })
        elif self.path == "/groups":
            self._send(200, list(tracked_groups.values()))
        elif self.path == "/tasks":
            self._send(200, list(active_tasks.values()))
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/broadcast":
            body = self._read_body()
            if not broadcast_enabled:
                self._send(403, {"error": "Broadcast is currently disabled"})
                return
            text = body.get("text")
            photo_file_id = body.get("photo_file_id")
            photo_path = body.get("photo_path")
            caption = body.get("caption")
            tg = body.get("targeted_groups") or None
            threading.Thread(
                target=deliver_to_groups,
                kwargs={"text": text, "photo_file_id": photo_file_id, "photo_path": photo_path,
                        "caption": caption, "targeted_group_ids": tg},
                daemon=True,
            ).start()
            self._send(200, {"ok": True, "targets": len(tg) if tg else len(tracked_groups)})

        elif self.path == "/tasks":
            body = self._read_body()
            task_type = body.get("type")
            if task_type not in ("repeat", "schedule"):
                self._send(400, {"error": "type must be 'repeat' or 'schedule'"})
                return
            text = body.get("text", "").strip()
            photo_path = body.get("photo_path")
            interval_hours = body.get("interval_hours")
            scheduled_time = body.get("scheduled_time")

            if task_type == "repeat" and not interval_hours:
                self._send(400, {"error": "interval_hours required for repeat tasks"})
                return
            if task_type == "schedule" and not scheduled_time:
                self._send(400, {"error": "scheduled_time required for schedule tasks"})
                return
            if not text and not photo_path:
                self._send(400, {"error": "text or photo_path required"})
                return

            tid = _new_task_id()
            _register_task(
                tid, task_type,
                interval_hours=float(interval_hours) if interval_hours else None,
                scheduled_time=scheduled_time,
                text=text or None,
                photo_path=photo_path,
            )
            if task_type == "repeat":
                t = threading.Thread(
                    target=_run_repeat,
                    args=(tid, float(interval_hours), text or None, None, None),
                    kwargs={"photo_path": photo_path},
                    daemon=True,
                )
            else:
                t = threading.Thread(
                    target=_run_schedule,
                    args=(tid, scheduled_time, text or None, None, None),
                    kwargs={"photo_path": photo_path},
                    daemon=True,
                )
            t.start()
            self._send(200, {"ok": True, "task_id": tid})

        else:
            self._send(404, {"error": "not found"})

    def do_PATCH(self):
        if self.path.startswith("/tasks/"):
            tid = self.path.split("/tasks/")[1]
            body = self._read_body()
            if tid in active_tasks:
                active_tasks[tid]["targeted_groups"] = body.get("targeted_groups", [])
                save_tasks()
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "task not found"})
        else:
            self._send(404, {"error": "not found"})

    def do_PUT(self):
        """Hot-reload a task: stop the running thread, update data, restart thread."""
        if self.path.startswith("/tasks/"):
            tid = self.path.split("/tasks/")[1]
            if tid not in active_tasks:
                self._send(404, {"error": "task not found"})
                return
            body = self._read_body()
            task = active_tasks[tid]

            # Stop the currently-running thread (it will NOT unregister because
            # we remove the event from task_stop_events first — ownership check)
            old_event = task_stop_events.pop(tid, None)
            if old_event:
                old_event.set()

            # Apply updates to the stored task record
            if "text" in body:
                task["text"] = body["text"] or None
            if "photo_path" in body:
                task["photo_path"] = body["photo_path"] or None
            if "interval_hours" in body and body["interval_hours"] is not None:
                task["interval_hours"] = float(body["interval_hours"])
            if "scheduled_time" in body and body["scheduled_time"]:
                task["scheduled_time"] = body["scheduled_time"]
            if "targeted_groups" in body:
                task["targeted_groups"] = body["targeted_groups"] or []
            save_tasks()

            # Restart background thread with updated data
            task_id = task["id"]
            ttype = task["type"]
            text = task.get("text")
            photo_file_id = task.get("photo_file_id")
            photo_path = task.get("photo_path")
            caption = task.get("caption")

            if ttype == "repeat":
                interval_hours = task.get("interval_hours", 1)
                t = threading.Thread(
                    target=_run_repeat,
                    args=(task_id, interval_hours, text, photo_file_id, caption),
                    kwargs={"photo_path": photo_path},
                    daemon=True,
                )
            elif ttype == "schedule":
                scheduled_time = task.get("scheduled_time")
                t = threading.Thread(
                    target=_run_schedule,
                    args=(task_id, scheduled_time, text, photo_file_id, caption),
                    kwargs={"photo_path": photo_path},
                    daemon=True,
                )
            else:
                self._send(400, {"error": "unknown task type"})
                return
            t.start()
            self._send(200, {"ok": True, "task_id": task_id})
        else:
            self._send(404, {"error": "not found"})

    def do_DELETE(self):
        if self.path.startswith("/tasks/"):
            tid = self.path.split("/tasks/")[1]
            if tid in active_tasks:
                if tid in task_stop_events:
                    task_stop_events[tid].set()
                _unregister_task(int(tid))
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "task not found"})
        else:
            self._send(404, {"error": "not found"})

    def log_message(self, format, *args):
        pass  # Suppress access logs


def start_internal_api():
    server = HTTPServer(("127.0.0.1", 8001), InternalAPIHandler)
    server.serve_forever()


# ─────────────────────────────────────────────
# HEALTH CHECK WEB SERVER (port 8000)
# ─────────────────────────────────────────────
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

    def log_message(self, format, *args):
        pass


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

    # Start health-check HTTP server on port 8000
    threading.Thread(target=start_health_server, daemon=True).start()
    print("✅ Health check server started on port 8000")

    # Start internal API server on port 8001 (localhost only, for admin dashboard)
    threading.Thread(target=start_internal_api, daemon=True).start()
    print("✅ Internal API server started on port 8001")

    replit_domains = os.environ.get("REPLIT_DOMAINS", "")
    if replit_domains:
        domain = replit_domains.split(",")[0].strip()
        print(f"\n🌐 Admin Dashboard: https://{domain}/admin")
        print(f"🌐 UptimeRobot URL: https://{domain}/\n")
    else:
        print("\n🌐 Admin Dashboard: http://localhost:8080/admin\n")

    restore_tasks()
    print(f"[INFO] Restored {len(active_tasks)} task(s) from disk.")
    print(f"[INFO] Tracking {len(tracked_groups)} group(s).")

    print("🤖 Bot is running. Polling for updates...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        except Exception as e:
            print(f"[ERROR] Polling crashed: {e}. Restarting in 5s...")
            time.sleep(5)
