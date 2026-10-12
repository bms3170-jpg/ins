FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ./
COPY templates ./templates
ENV PORT=8000 COOKIE_SECURE=1
EXPOSE 8000
CMD ["sh", "-c", "gunicorn -w 1 -b 0.0.0.0:${PORT:-8000} app:app"]
