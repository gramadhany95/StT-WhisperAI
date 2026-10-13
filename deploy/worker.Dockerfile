FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models \
    HF_HUB_DISABLE_TELEMETRY=1 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# PyTorch 2.8 + CUDA 12.8 (membawa cuBLAS 12 + cuDNN 9 yang juga dipakai CTranslate2)
RUN printf "torch==2.8.0\ntorchaudio==2.8.0\ntorchvision==0.23.0\n" > /tmp/torch.txt \
 && pip install -r /tmp/torch.txt --index-url https://download.pytorch.org/whl/cu128

COPY requirements-app.txt requirements-web.txt ./
RUN pip install -c /tmp/torch.txt -r requirements-app.txt -r requirements-web.txt

ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib

COPY app ./app

RUN useradd --uid 1000 --create-home app \
 && mkdir -p /data/storage /data/work /models \
 && chown -R app:app /data /models
USER app

CMD ["python", "-m", "app.portal.worker"]
