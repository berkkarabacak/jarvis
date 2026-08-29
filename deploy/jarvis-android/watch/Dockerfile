FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends android-tools-adb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /watch
COPY server.py /watch/server.py
EXPOSE 6081
CMD ["python", "-u", "/watch/server.py"]
