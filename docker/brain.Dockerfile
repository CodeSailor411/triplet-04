# CIVIS Brain service image. Kept in the root integration layer so Brain's
# source ownership files remain with the Brain team.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/brain/src

WORKDIR /app/brain

COPY brain/requirements-lock.txt ./requirements-lock.txt
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY brain/src ./src
COPY brain/config ./config
COPY brain/mocks ./mocks
RUN mkdir -p run-logs

EXPOSE 8001
CMD ["python", "-m", "civis_brain"]
