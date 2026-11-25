# Sandbox local de execução da Korda (K08). Ver services/execution/README.md.
# O contexto de build é só infra/sandbox/: nada do repositório (fontes, evaluation/) entra na imagem.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt /opt/korda/requirements.txt
RUN pip install -r /opt/korda/requirements.txt

COPY consulta.py /opt/korda/consulta.py

# Usuário sem root. Em execução o worker passa --user <uid>:<gid> do host para casar com as montagens.
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin korda
USER korda

# dbt grava estado e logs só em /work/saida (montagem com escrita).
ENV DBT_PROFILES_DIR=/work/projeto \
    DBT_TARGET_PATH=/work/saida/target \
    DBT_LOG_PATH=/work/saida/logs \
    DBT_SEND_ANONYMOUS_USAGE_STATS=false \
    HOME=/tmp

WORKDIR /work/projeto
# O contêiner fica parado esperando `docker exec`; o worker o destrói no fim.
CMD ["sleep", "infinity"]
