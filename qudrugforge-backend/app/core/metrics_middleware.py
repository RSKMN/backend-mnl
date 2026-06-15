import time
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from app.core.metrics import REQUEST_COUNT, REQUEST_LATENCY

class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method
        path = request.url.path
        
        start_time = time.time()
        
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            status_code = 500
            raise
        finally:
            latency = time.time() - start_time
            
            # Record metrics
            REQUEST_COUNT.labels(method=method, endpoint=path, status_code=status_code).inc()
            REQUEST_LATENCY.labels(method=method, endpoint=path).observe(latency)
            
        return response
