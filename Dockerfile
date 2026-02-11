FROM rockylinux:8

ENV LANG=C.UTF-8

# Instalar dependencias del sistema y ffmpeg
RUN yum -y update && \
    yum -y install epel-release curl dnf-plugins-core && \
    # Enable CodeReady Builder (CRB) required by some EPEL/RPMFusion deps
    /usr/bin/crb enable || true && \
    # Enable RPM Fusion and install ffmpeg and build deps. Install SDL2 first to satisfy ffmpeg
    curl -sL -o /tmp/rpmfusion-free-release.rpm https://download1.rpmfusion.org/free/el/rpmfusion-free-release-8.noarch.rpm && \
    rpm -Uvh /tmp/rpmfusion-free-release.rpm || true && \
    yum -y install SDL2 || true && \
    yum -y install python39 python39-devel python39-pip gcc gcc-c++ make || true && \
    # Try installing ffmpeg; allow fallback options if dependencies require alternate candidates
    yum -y install ffmpeg || yum -y install --nobest ffmpeg || yum -y install ffmpeg --allowerasing || true && \
    python3.9 -m pip install --upgrade pip && \
    yum -y clean all && rm -f /tmp/rpmfusion-free-release.rpm

WORKDIR /app

COPY requirements.txt /app/
RUN python3.9 -m pip install --no-cache-dir -r requirements.txt

COPY . /app

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
