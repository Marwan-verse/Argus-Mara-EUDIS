FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ARGUS_AIS_DIR=/data/ais ARGUS_REQUIRE_VOLUME=1
WORKDIR /app
COPY live/requirements.txt /app/live/requirements.txt
RUN python -m pip install --no-cache-dir -r live/requirements.txt
# Explicit copies exclude the recorder key, real recordings and desktop packages.
COPY argus/__init__.py argus/live_server.py argus/live_state.py argus/live_archive.py /app/argus/
COPY recorder/recorder.py /app/recorder/recorder.py
COPY ui/live/ /app/ui/live/
COPY ui/assets/world_land.json ui/assets/world_ports.json ui/assets/mark.svg /app/ui/assets/
EXPOSE 8080
CMD ["python", "-m", "argus.live_server"]
