# GPU-enabled image. Requires nvidia-container-toolkit on the host.
# CPU-only fallback: change FROM to python:3.12-slim and remove the
# CuPy/CUDA libraries from requirements (or skip the install step).
FROM nvidia/cuda:12.6.3-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data

WORKDIR /app

# System dependencies
#  - python 3.12, pip, build tools
#  - GDAL + PROJ for rasterio / pyproj
#  - libGL + libglib for OpenCV
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
        ca-certificates \
        curl \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
        gcc g++ \
        gdal-bin libgdal-dev \
        proj-bin libproj-dev \
        libgl1 libglib2.0-0 \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir opencv-python-headless \
 && pip install --no-cache-dir cupy-cuda12x \
        nvidia-cuda-runtime-cu12 nvidia-cuda-nvrtc-cu12 \
        nvidia-cublas-cu12 nvidia-cusolver-cu12 nvidia-cusparse-cu12 \
        nvidia-cufft-cu12 nvidia-curand-cu12 nvidia-nvjitlink-cu12

COPY app/ ./app/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
