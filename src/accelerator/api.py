"""Top-level ASGI entrypoint (`uvicorn accelerator.api:app`)."""

from accelerator.server.api import app as app
from accelerator.server.api import application as application
from accelerator.server.api import run_service as run_service
from accelerator.server.api import target_registry as target_registry
