"""Single-container entrypoint (Hugging Face Spaces): API under /api + built React SPA."""
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from main import app as api

STATIC_DIR = os.getenv("STATIC_DIR", "/app/static")


class SPAFiles(StaticFiles):
    """Serve index.html for unknown paths so client-side routes survive refresh."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code == 404:
                return await super().get_response("index.html", scope)
            raise


app = FastAPI()
app.mount("/api", api)
app.mount("/", SPAFiles(directory=STATIC_DIR, html=True), name="spa")
