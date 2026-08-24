FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY fastbot ./fastbot
COPY static ./static
RUN pip install --no-cache-dir . && mkdir -p /app/.data
ENV FASTBOT_HOST=0.0.0.0 FASTBOT_PORT=5012 FASTBOT_DATABASE=/app/.data/fastbot.db
EXPOSE 5012
CMD ["python", "-m", "fastbot.main"]
