# Sistemas simulados do cliente (nível 1): TMS por API HTTP e preparo do replay por dias.
# Dados sintéticos; não é conector nem sistema real. Ver README.md.
# O contexto de build é só infra/sistemas-simulados/: nenhum dado entra na imagem.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/opt/korda

COPY requirements.txt /opt/korda/requirements.txt
RUN pip install -r /opt/korda/requirements.txt
COPY korda_simulados /opt/korda/korda_simulados

RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin korda
USER korda
EXPOSE 8080
CMD ["python", "-m", "korda_simulados.tms_api"]
