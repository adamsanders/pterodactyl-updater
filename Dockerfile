FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ARG GIT_COMMIT=""
ENV GIT_COMMIT=${GIT_COMMIT}

COPY app/ ./app/

# Create directory for persisted configuration
RUN mkdir -p /data
#ENV CONFIG_PATH=/data/config.json

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
