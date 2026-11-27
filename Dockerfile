# Runner HTTP do Radar Legislativo (SPEC V3 seção 14). Construído na própria VPS (nó único do Swarm,
# sem registro de imagens): docker build -t radar-runner:<versão> .
FROM python:3.12-slim

# git + ssh: publicação do site no branch gh-pages (deploy key montada como secret do Swarm)
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

ARG UID=1000
ARG GID=1000
RUN groupadd -g ${GID} radar && useradd -m -u ${UID} -g ${GID} radar

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY sql/ sql/
COPY config/ config/
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo

# data/ e site/ chegam por volume (Landing, logs e o site gerado ficam fora da imagem)
RUN mkdir -p data site && chown radar:radar data site
USER radar
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["uvicorn", "radar.runner.app:app", "--host", "0.0.0.0", "--port", "8000"]
