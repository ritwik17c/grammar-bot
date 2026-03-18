# 🎓 VKV Grammar Assistant Bot v2

A smart Telegram group grammar assistant that privately corrects users' English messages — powered by Groq AI (Llama 3.3 70B).

---

## Features

- 👁️ Monitors group messages silently
- 📩 Sends private grammar corrections (never publicly)
- 🌐 Detects English language automatically
- 🧠 AI-powered grammar, punctuation & vocabulary suggestions
- 🎓 Formal writing tips for teachers
- 👋 Onboards new users with a welcome message
- ⚙️ Admin controls (enable/disable, sensitivity, explanations)
- 📊 Statistics & logging with SQLite

---

## Commands

| Command | Who | Description |
|---------|-----|-------------|
| `/start` | Any user | Register to receive private corrections |
| `/enable` | Admin only | Enable bot in the group |
| `/disable` | Admin only | Disable bot in the group |
| `/settings` | Admin only | Adjust sensitivity and explanations |
| `/stats` | Anyone | View correction statistics |

---

## Setup

### Step 1 — Disable Bot Privacy Mode (IMPORTANT)

By default, Telegram bots can't read group messages. You must disable privacy mode:

1. Open @BotFather on Telegram
2. Send `/mybots` → select your bot
3. Click **Bot Settings → Group Privacy → Turn Off**
4. Confirm — the bot can now read group messages ✅

### Step 2 — Environment Variables

| Variable | Value |
|----------|-------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `GROQ_API_KEY` | From console.groq.com |
| `WEBHOOK_URL` | Your Railway public URL (optional) |

### Step 3 — Deploy on Railway

1. Push all 4 files to your GitHub repo (replace old files)
2. Go to Railway → your project → Variables tab
3. Add `TELEGRAM_BOT_TOKEN` and `GROQ_API_KEY`
4. Optionally add `WEBHOOK_URL` = your Railway public domain
5. Redeploy ✅

### Step 4 — Add Bot to Your Group

1. Open your Telegram group
2. Click group name → Edit → Administrators → Add Admin
3. Search for your bot → add it
4. Give it permission to **read messages**
5. Send `/enable` in the group

### Step 5 — Users Register

Each group member must start the bot once:
1. They search for your bot on Telegram
2. Click **Start**
3. Bot registers them for private corrections ✅

---

## How It Works

```
User sends message in group
        ↓
Bot checks: Is the group enabled?
        ↓
Bot checks: Is user registered?
  → No: Send onboarding message
        ↓
Bot sends message to Groq AI
        ↓
AI checks: English? Has errors? Too short?
        ↓
If errors found → Send private correction to user
        ↓
Log correction to SQLite database
```

---

## Example Private Message Sent to User

```
✏️ Grammar Suggestion

Original Message:
She don't likes to come in school everyday.

Suggested Correction:
She doesn't like to come to school every day.

💡 Tip: Use "doesn't" for third-person singular. "Every day" is two words when used as an adverb.

📚 Vocabulary: Consider "attend school" instead of "come in school".

🎓 Formal Writing: "She does not attend school every day" is more appropriate in formal reports.

Keep writing! Every correction helps you improve. 🌟
```
