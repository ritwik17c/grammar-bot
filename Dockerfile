FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY dashboard_server.py .
COPY dashboard.html .
COPY start.sh .
COPY vkv_logo.jpg .
RUN chmod +x start.sh

CMD ["bash", "start.sh"]
