FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps needed by opencv/ultralytics runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Python deps for current project scripts.
RUN pip install --no-cache-dir \
    pyserial==3.5 \
    ultralytics==8.2.103 \
    opencv-python-headless==4.11.0.86

# Copy project files.
COPY . /app

# Default command (can be overridden at docker run time).
CMD ["python3", "sts3215_test.py", "--help"]
