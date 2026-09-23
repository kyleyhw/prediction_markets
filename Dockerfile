# One image for every platform process: `vp serve`, `vp worker`, `vp ingest`,
# `vp db migrate` (plan, task 34). The base is a build argument so a machine
# that cannot reach Docker Hub can use a mirror of the same image.
ARG BASE=python:3.14-slim
FROM ${BASE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# A machine behind a TLS-intercepting proxy passes its CA as a build secret
# (`--secret id=extra_ca,src=<bundle>`); it is used while installing and is
# never written into the image.
RUN --mount=type=secret,id=extra_ca \
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir "uv==0.12.18"
WORKDIR /app

# Dependencies first, from the lock, so a code change does not reinstall them.
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN --mount=type=secret,id=extra_ca \
    if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev --no-install-project
COPY vp ./vp
RUN --mount=type=secret,id=extra_ca \
    if [ -f /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --frozen --no-dev

RUN useradd --system --uid 10001 --home /data vp && mkdir -p /data && chown vp /data
USER vp
ENV PATH=/opt/venv/bin:$PATH \
    VP_DATA_ROOT=/data
EXPOSE 8000
ENTRYPOINT ["vp"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8000"]
