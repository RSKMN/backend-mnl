from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        
        # Phase 7C Security Headers
        # HSTS, frame protection, content-type sniff protection
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # NOTE: Content-Security-Policy is intentionally NOT set here.
        # The backend is a pure API server (no HTML served).
        # Setting CSP on API responses was incorrectly blocking browser fetch()
        # consumption of JSON responses from cross-origin Vercel/Cloudflare contexts.
        # CSP should only be set on HTML-serving frontends.
        
        return response
