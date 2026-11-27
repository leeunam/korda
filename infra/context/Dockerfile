FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir uv==0.13.10 \
    && groupadd --gid 10001 korda \
    && useradd --uid 10001 --gid 10001 --no-create-home korda \
    && mkdir -p /app /var/lib/korda/media \
    && chown -R 10001:10001 /var/lib/korda \
    && chmod 0700 /var/lib/korda/media

WORKDIR /app
# Copy only this service: no source datasets, test answers or repository credentials.
COPY services/context/pyproject.toml services/context/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY services/context/korda_context ./korda_context
COPY services/context/migrations ./migrations
COPY services/context/alembic.ini ./alembic.ini
RUN uv sync --frozen --no-dev && rm -rf /root/.cache/uv

USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "korda_context.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
