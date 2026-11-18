# Third-Party Open Source Software Notice

This Microsoft internal IP asset incorporates unmodified open-source libraries installed via standard package registries (`PyPI` and `npm`) at build/runtime. No open-source source code is vendored or modified in this repository.

## Runtime Dependencies

### Python (`pyproject.toml`)
- **defusedxml** — Python Software Foundation License 2.0
- **fastapi** — MIT License
- **pydantic** — MIT License
- **pyjwt[crypto]** (`PyJWT`, `cryptography`) — MIT License / Apache-2.0 OR BSD-3-Clause
- **python-dotenv** — BSD-3-Clause License
- **python-multipart** — Apache License 2.0
- **typer** — MIT License
- **uvicorn** — BSD-3-Clause License

### Web UI (`apps/web/package.json`)
- **react** / **react-dom** — MIT License
- **vite** / **@vitejs/plugin-react** — MIT License

Refer to `uv.lock` and `apps/web/package-lock.json` for transitive dependency versions and to `https://aka.ms/ospo` for Microsoft Open Source Programs Office guidance.
