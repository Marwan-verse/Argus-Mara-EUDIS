FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 ARGUS_SOC_DB=/data/accounts.sqlite3
WORKDIR /app
COPY soc/requirements.txt /app/soc/requirements.txt
RUN python -m pip install --no-cache-dir -r soc/requirements.txt \
    && groupadd --gid 10001 argus && useradd --uid 10001 --gid 10001 --no-create-home argus \
    && mkdir /data && chown argus:argus /data
COPY argus/ /app/argus/
COPY ui/admin/ /app/ui/admin/
COPY ui/styles.css /app/ui/styles.css
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "argus.collab_server"]
