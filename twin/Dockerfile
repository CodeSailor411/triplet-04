# Twin layer and local dashboard image. Build context: twin/.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/twin/src

WORKDIR /app/twin

COPY requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY src ./src
COPY config ./config
COPY mocks ./mocks
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh \
    && mkdir -p run-logs

EXPOSE 8000 8080
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "twin"]
