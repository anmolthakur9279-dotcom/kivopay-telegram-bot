# Telegram Admin Bot

A fully-featured Python Telegram bot with admin access control, persistent task storage, AI-powered translation, and media-aware broadcast/scheduling.

## Run & Operate

- `python main.py` — run the bot (workflow: "Telegram Bot")
- Health check server: port 8000
- Bot polls Telegram for updates indefinitely, auto-restarts on crash

## Stack

- Python 3.11
- pyTelegramBotAPI 4.x — Telegram bot framework
- google-genai — Gemini 1.5 Flash for translation
- Python threading — background tasks (repeat/schedule/broadcast)
- http.server — built-in health check endpoint

## Where things live

- `main.py` — entire bot (single file)
- `blacklisted_users.json` — blocked usernames (auto-created)
- `tracked_groups.json` — group chat IDs (auto-created)
- `active_tasks.json` — persisted repeat/schedule tasks + counter (auto-created)

## Architecture decisions

- All three JSON files are loaded at startup and saved on every mutation — tasks survive restarts.
- On startup, `restore_tasks()` re-spawns background threads for every saved repeat/schedule task.
- Security interceptor runs at the top of every command handler — blacklist and public lock checked first.
- Health server runs on port 8000 on a daemon thread; bot polling loop is in the main thread with auto-retry.
- Switched from deprecated `google.generativeai` to `google.genai` (Client API).

## Product

- **General users**: `/trans`, `/tr`, `/translate` (text and photo translation via Gemini)
- **Allowed admins**: broadcast, repeat (interval), daily schedule, task management, group tracking
- **Primary admin (ak04756)**: toggle all features, lock/unlock, block/unblock users

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Port 8080 is taken by existing workspace services — health server uses port 8000 instead
- UptimeRobot ping URL: use `https://<your-replit-domain>/` (hitting port 8000 via proxy)
- `google-generativeai` is deprecated — always use `google-genai` (`from google import genai`)
- Do not add the bot to a group before `/start_tracking` — or send `/start` in the group so the bot auto-registers it

## Required Secrets

- `TELEGRAM_BOT_TOKEN` — from @BotFather on Telegram
- `GOOGLE_API_KEY` — from https://aistudio.google.com/app/apikey

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
