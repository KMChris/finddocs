# Serwer OCR PP-OCRv6_medium na GPU, wystawiony przez PaddleX jako HTTP.
#
# Obraz nie zawiera zadnych danych organizacji. Wagi modeli sa pobierane
# w trakcie budowania, wiec uruchomiony kontener nie potrzebuje dostepu do sieci.
#
# Budowanie idzie dwuetapowo. Kolo paddlepaddle-gpu laduje ``libcuda.so.1`` juz
# przy imporcie, a ta biblioteka pochodzi ze sterownika i nie jest widoczna
# w trakcie ``docker build``. Wagi sciaga wiec etap pomocniczy z kolem CPU,
# a etap docelowy tylko je kopiuje: pliki modeli sa te same dla obu wariantow.
#
# Sterowniki CUDA i cuDNN sa w kole paddlepaddle-gpu, wiec obraz bazowy to
# zwykly python, a nie warstwa nvidia/cuda. Kontener wymaga sterownika NVIDIA
# na hoscie (od 550.54.14) i uruchomienia z --gpus all.

ARG PADDLE_VERSION=3.3.0
ARG PADDLEOCR_VERSION=3.7.0

# --- etap pomocniczy: pobranie wag modeli --------------------------------------
FROM python:3.11-slim-bookworm AS weights

ARG PADDLE_VERSION
ARG PADDLEOCR_VERSION
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install "paddlepaddle==${PADDLE_VERSION}" \
        -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
RUN python -m pip install "paddleocr==${PADDLEOCR_VERSION}"

COPY pipeline.yaml /opt/finddocs-ocr/pipeline.yaml
COPY warmup.py /opt/finddocs-ocr/warmup.py
RUN python /opt/finddocs-ocr/warmup.py

# --- etap docelowy: serwer na GPU ----------------------------------------------
FROM python:3.11-slim-bookworm

ARG PADDLE_VERSION
ARG PADDLEOCR_VERSION
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libgl1 i libglib2.0-0 sa wymagane przez OpenCV, libgomp1 przez Paddle.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip install "paddlepaddle-gpu==${PADDLE_VERSION}" \
        -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
RUN python -m pip install "paddleocr==${PADDLEOCR_VERSION}"
RUN paddlex --install serving

COPY pipeline.yaml /opt/finddocs-ocr/pipeline.yaml
COPY --from=weights /root/.paddlex /root/.paddlex

EXPOSE 8868

HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8868/health || exit 1

CMD ["paddlex", "--serve", \
     "--pipeline", "/opt/finddocs-ocr/pipeline.yaml", \
     "--device", "gpu:0", \
     "--host", "0.0.0.0", \
     "--port", "8868"]
