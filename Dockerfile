# Digital Twin Gradio app — bind 0.0.0.0; use --env-file .env at run time for secrets.
FROM python:3.12-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY me/ ./me/

EXPOSE 7860

CMD ["python", "app.py"]
