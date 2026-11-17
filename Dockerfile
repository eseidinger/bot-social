FROM node:22-alpine AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/bot_social ./bot_social
COPY backend/migrations ./migrations
RUN pip install --no-cache-dir . && groupadd --gid 10001 app && useradd --uid 10001 --gid 10001 app
COPY --from=web-build /app/web/dist /app/web/dist
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "bot_social.deployment", "serve"]
