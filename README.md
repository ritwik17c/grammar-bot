# 🤖 Grammar Correction Telegram Bot (Groq + Llama 3)

A Telegram bot powered by **Groq AI (Llama 3.3 70B)** that checks and corrects English grammar in real time — completely free!

---

## Features

- ✅ Instant grammar correction for any text
- 📝 Explains what was changed and why
- 🤗 Friendly, encouraging tone
- ⚡ Powered by Groq (ultra-fast, free tier)
- Supports `/start`, `/help`, and `/check <text>` commands

---

## Environment Variables Needed

| Variable | Where to get it |
|----------|----------------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather on Telegram |
| `GROQ_API_KEY` | From console.groq.com |

---

## Deploy on Railway (Free)

1. Push these 4 files to a GitHub repository
2. Go to [railway.app](https://railway.app) → sign up with GitHub
3. Click **New Project → Deploy from GitHub repo**
4. Select your repository
5. Go to **Variables** tab and add:
   - `TELEGRAM_BOT_TOKEN` = your token
   - `GROQ_API_KEY` = your Groq key
6. Railway auto-detects the Dockerfile and deploys ✅

---

## Run Locally

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="your_bot_token"
export GROQ_API_KEY="your_groq_key"

python bot.py
```

## Run with Docker

```bash
docker build -t grammar-bot .

docker run -d \
  -e TELEGRAM_BOT_TOKEN="your_bot_token" \
  -e GROQ_API_KEY="your_groq_key" \
  grammar-bot
```

---

## Usage

| Action | What to do |
|--------|-----------|
| Start the bot | Send `/start` |
| Get help | Send `/help` |
| Check inline text | `/check I goes to school` |
| Check any message | Just type and send it! |

---

## Example

**You send:**
> She dont like apples and her friend dont neither.

**Bot replies:**
> ✅ Corrected: She doesn't like apples and her friend doesn't either.
>
> 📝 Changes made:
> - "dont" → "doesn't" (third-person singular requires "doesn't")
> - "dont neither" → "doesn't either" ("either" is correct in this context)
