FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/brain/src:/app/brain/mocks \
    BRAIN_HOST=0.0.0.0 \
    PEER_MODE=live \
    LLM_MODE=gemini \
    BRAIN_DEBUG_ENABLED=false

WORKDIR /app/brain
COPY requirements-lock.txt ./
RUN python -m pip install -r requirements-lock.txt

COPY src ./src
COPY config ./config
# Brain imports the shared fixture helpers. Do not package fixture case data.
COPY mocks/civis_mock_peers ./mocks/civis_mock_peers
COPY scripts/compose_tls.py scripts/compose_timeline.py ./scripts/
RUN mkdir -p logs

EXPOSE 8001
CMD ["python", "-m", "civis_brain"]
