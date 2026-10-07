import uvicorn

from civis_brain.settings import Settings

settings = Settings()
uvicorn.run("civis_brain.app:create_app", factory=True, host=settings.brain_host,
            port=settings.brain_port)
