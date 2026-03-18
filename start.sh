#!/bin/bash
# Start both the Grammar Bot and Dashboard Server together

echo "🤖 Starting Grammar Assistant Bot + Dashboard..."

# Start dashboard server in background
python dashboard_server.py &
DASHBOARD_PID=$!
echo "📊 Dashboard started (PID: $DASHBOARD_PID)"

# Start the main bot
python bot.py

# If bot stops, also stop dashboard
kill $DASHBOARD_PID
