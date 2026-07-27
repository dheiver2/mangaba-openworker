# Mangaba em um container só: o servidor Python serve a própria GUI buildada.
# O navegador abre http://localhost:8765 — mesma origem, uma porta, zero Node em runtime.
#
# O token do sidecar existe para separar processos DA MESMA máquina; dentro do
# container ele é fixado por build-arg (a porta só é publicada em 127.0.0.1 pelo
# compose) e o gate humano continua sendo a senha local (mangaba/passcode.py).

# -- estágio 1: build da GUI ---------------------------------------------------------
FROM node:20-slim AS gui
WORKDIR /gui
COPY surfaces/gui/package.json surfaces/gui/package-lock.json ./
# `npm ci` respeitando o lockfile; os scripts de install (esbuild) precisam rodar.
RUN npm ci --ignore-scripts=false --no-audit --no-fund
COPY surfaces/gui/ ./
ARG MANGABA_TOKEN=mangaba-docker-local
ENV VITE_MANGABA_API_TOKEN=$MANGABA_TOKEN \
    VITE_MANGABA_HTTP= \
    VITE_MANGABA_WS=
# Sem VITE_MANGABA_HTTP/WS o api.ts cai no default 127.0.0.1:8765 — correto aqui,
# porque o compose publica exatamente nessa porta da máquina.
RUN npx vite build

# -- estágio 2: servidor Python ------------------------------------------------------
FROM python:3.12-slim AS server
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY mangaba/ ./mangaba/
RUN pip install --no-cache-dir .
COPY --from=gui /gui/dist /app/gui-dist

ARG MANGABA_TOKEN=mangaba-docker-local
ENV MANGABA_API_TOKEN=$MANGABA_TOKEN \
    MANGABA_GUI_DIST=/app/gui-dist \
    MANGABA_STATE_DIR=/data \
    PYTHONUNBUFFERED=1

# /data guarda tudo que persiste: senha, conversas, segredos de conectores.
VOLUME ["/data"]
EXPOSE 8765
CMD ["mangaba-server", "--host", "0.0.0.0", "--port", "8765"]
