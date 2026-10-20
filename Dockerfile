FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY spambot ./spambot
ENV DB_PATH=/data/spambot.sqlite
EXPOSE 8080
CMD ["python", "-m", "spambot", "serve", "--port", "8080"]
