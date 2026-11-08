# Guardian API and Twin event-feed bridge. Build context: guardian/.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/guardian/src:/app/guardian

WORKDIR /app/guardian

COPY src/requirements.txt ./src/requirements.txt
RUN pip install --no-cache-dir -r src/requirements.txt

COPY src ./src
COPY mocks ./mocks
RUN mkdir -p run-logs

EXPOSE 5000
CMD ["uvicorn", "unified_api:app", "--host", "0.0.0.0", "--port", "5000"]
