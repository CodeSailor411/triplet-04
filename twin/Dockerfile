# Twin layer image. Build context: the twin/ folder.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/twin/src

WORKDIR /app/twin

# Exact versions from the lock file, so every machine builds the same image.
COPY requirements-lock.txt ./
RUN pip install -r requirements-lock.txt

# The code is not pip-installed. The Twin finds its config relative to this folder.
COPY src ./src
COPY config ./config
COPY mocks ./mocks
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# sed strips Windows line endings, which would break the script inside the container.
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && chmod +x /usr/local/bin/docker-entrypoint.sh && mkdir -p run-logs

EXPOSE 8000 8080
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "twin"]
