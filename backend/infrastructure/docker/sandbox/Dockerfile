FROM python:3.12-slim

ARG HTTP_PROXY
ARG HTTPS_PROXY
ARG NO_PROXY
ARG http_proxy
ARG https_proxy
ARG no_proxy
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN groupadd --system --gid 10001 sandbox \
    && useradd --system --uid 10001 --gid sandbox --home-dir /sandbox sandbox \
    && install -d -o sandbox -g sandbox -m 0700 /exchange \
    && apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir Pillow==11.3.0 PyMuPDF==1.26.3 python-magic==0.4.27
WORKDIR /sandbox
COPY infrastructure/sandbox/validate_and_render.py /usr/local/bin/validate_and_render.py
COPY infrastructure/sandbox/daemon.py /usr/local/bin/daemon.py
USER sandbox
ENTRYPOINT ["python", "/usr/local/bin/daemon.py"]
