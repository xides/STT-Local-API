FROM rockylinux:10

ENV LANG=C.UTF-8 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# Rocky Linux 10.1 base dependencies + ffmpeg
RUN dnf -y update && \
    dnf -y install dnf-plugins-core curl ca-certificates && \
    dnf config-manager --set-enabled crb || true && \
    dnf -y install epel-release && \
    curl -fsSL -o /tmp/rpmfusion-free-release.rpm https://download1.rpmfusion.org/free/el/rpmfusion-free-release-10.noarch.rpm && \
    rpm -Uvh /tmp/rpmfusion-free-release.rpm && \
    dnf -y install python3 python3-pip python3-devel gcc gcc-c++ make && \
    dnf -y install ffmpeg || dnf -y install --nobest ffmpeg && \
    dnf clean all && \
    rm -rf /var/cache/dnf /tmp/rpmfusion-free-release.rpm

WORKDIR /app

COPY requirements.txt /app/
RUN python3 -m pip install --upgrade pip setuptools wheel && \
    python3 -m pip install -r requirements.txt

COPY . /app

EXPOSE 8000

CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
