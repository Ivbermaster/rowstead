FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
WORKDIR /srv/batchflow
COPY requirements.lock ./
RUN pip install -r requirements.lock && python -m playwright install --with-deps chromium \
    && groupadd --gid 10001 batchflow && useradd --uid 10001 --gid batchflow --create-home batchflow \
    && mkdir -p /srv/batchflow/data && chown -R batchflow:batchflow /srv/batchflow /opt/browsers
COPY pyproject.toml ./
COPY README.md LICENSE ./
COPY app ./app
COPY demo ./demo
RUN pip install --no-deps .
COPY alembic.ini ./
COPY migrations ./migrations
USER batchflow
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
