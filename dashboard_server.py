#!/usr/bin/env python3
"""
Grammar Bot Dashboard Server
Run this alongside bot.py to serve the web dashboard.
Visit: http://localhost:5000
"""

import sqlite3
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timedelta

DB_PATH = os.environ.get("DB_PATH", "grammar_bot.db")
PORT = int(os.environ.get("DASHBOARD_PORT", 5000))

def get_all_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM corrections")
    total = c.fetchone()[0]

    today = datetime.now().strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM corrections WHERE timestamp LIKE ?", (f"{today}%",))
    today_count = c.fetchone()[0]

    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    c.execute("SELECT COUNT(*) FROM corrections WHERE timestamp >= ?", (week_ago,))
    week_count = c.fetchone()[0]

    c.execute("""SELECT DATE(timestamp) day, COUNT(*) cnt FROM corrections
                 WHERE timestamp >= ? GROUP BY day ORDER BY day DESC""", (week_ago,))
    daily = c.fetchall()

    c.execute("""SELECT mistake_type, COUNT(*) cnt FROM corrections
                 GROUP BY mistake_type ORDER BY cnt DESC LIMIT 5""")
    common = c.fetchall()

    c.execute("""SELECT k.username, COUNT(*) cnt FROM corrections co
                 LEFT JOIN known_users k ON co.user_id=k.user_id
                 GROUP BY co.user_id ORDER BY cnt DESC LIMIT 5""")
    top_users = c.fetchall()

    c.execute("""SELECT mistake_type, original FROM corrections
                 ORDER BY id DESC LIMIT 10""")
    recent = c.fetchall()

    c.execute("SELECT COUNT(*) FROM known_users")
    user_count = c.fetchone()[0]

    conn.close()
    return {
        "total": total,
        "today": today_count,
        "week": week_count,
        "daily": daily,
        "common": common,
        "top_users": top_users,
        "recent": recent,
        "user_count": user_count
    }

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logs

    def do_GET(self):
        if self.path == "/api/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                stats = get_all_stats()
                self.wfile.write(json.dumps(stats).encode())
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode())

        elif self.path == "/" or self.path == "/dashboard":
            dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
            try:
                with open(dashboard_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(content)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"dashboard.html not found")
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == "__main__":
    print(f"🌐 Dashboard running at http://localhost:{PORT}")
    print(f"📊 Stats API at http://localhost:{PORT}/api/stats")
    server = HTTPServer(("0.0.0.0", PORT), DashboardHandler)
    server.serve_forever()
