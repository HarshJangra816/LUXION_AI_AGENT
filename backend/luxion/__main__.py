"""Run the Luxion backend: ``python -m luxion``."""

from __future__ import annotations

import uvicorn

from luxion.config.settings import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "luxion.api.app:app",
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.server.reload,
        log_config=None,
    )


if __name__ == "__main__":
    main()
