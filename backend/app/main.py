from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes.encounters import router as encounters_router
from app.routes.messages import router as messages_router


def create_app() -> FastAPI:
    app = FastAPI(title="Mini Hospital Demo API")

    # Dev-friendly CORS for local frontend.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(encounters_router)
    app.include_router(messages_router)
    return app


app = create_app()

