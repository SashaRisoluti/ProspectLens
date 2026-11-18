from fastapi import FastAPI, Response
from sqlalchemy import text

from prospectlens.db.session import get_engine

app = FastAPI(title="ProspectLens API", version="0.1.0")


@app.get("/healthz")
def healthz(response: Response) -> dict[str, str]:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
    except Exception:
        response.status_code = 503
        return {"status": "error", "db": "non raggiungibile"}
    return {"status": "ok", "db": "ok"}
