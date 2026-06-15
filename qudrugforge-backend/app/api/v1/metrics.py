from fastapi import APIRouter, Depends, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from app.core.dependencies import require_global_admin

router = APIRouter()

@router.get("/", dependencies=[Depends(require_global_admin)])
def get_metrics():
    """
    Expose prometheus metrics.
    Protected to global admins only.
    """
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
