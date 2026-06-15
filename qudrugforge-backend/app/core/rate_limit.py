from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

def get_user_id_or_ip(request: Request) -> str:
    """
    Extracts the user identifier for rate limiting.
    Prefers the authenticated user sub (from JWT), falls back to IP address.
    """
    # If the user is attached to the request state via auth middleware/deps
    if hasattr(request.state, "user_id") and request.state.user_id:
        return str(request.state.user_id)
    if hasattr(request.state, "user") and hasattr(request.state.user, "id"):
        return str(request.state.user.id)
    
    # Check if we injected it manually in deps
    user_id = request.scope.get("user_id")
    if user_id:
        return str(user_id)

    # Fallback to IP
    return get_remote_address(request)

# Instantiate the global limiter
limiter = Limiter(key_func=get_user_id_or_ip)
