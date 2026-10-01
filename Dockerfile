FROM ubuntu:22.04
ARG BLENDER_VER=5.1.2
ENV DEBIAN_FRONTEND=noninteractive \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=all \
    PYTHONUNBUFFERED=1
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl xz-utils python3 python3-pip \
      libx11-6 libxi6 libxxf86vm1 libxfixes3 libxrender1 libxext6 libxkbcommon0 libxkbcommon-x11-0 \
      libsm6 libice6 libgl1 libegl1 libglu1-mesa libgomp1 \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://download.blender.org/release/Blender${BLENDER_VER%.*}/blender-${BLENDER_VER}-linux-x64.tar.xz \
      | tar -xJ -C /opt && ln -s /opt/blender-${BLENDER_VER}-linux-x64/blender /usr/local/bin/blender
RUN pip3 install --no-cache-dir runpod==1.7.*
COPY handler.py setup_render.py /app/
WORKDIR /app
CMD ["python3", "-u", "handler.py"]
