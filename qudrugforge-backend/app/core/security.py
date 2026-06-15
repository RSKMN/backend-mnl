from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Union
import uuid
import redis
from jose import jwt, JWTError
from app.core.config import settings
from app.core.exceptions import AppException

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password must be 72 bytes or fewer.")
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if len(plain_password.encode("utf-8")) > 72:
        return False
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(subject: Union[str, Any], email: str, expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    jti = str(uuid.uuid4())
    to_encode = {"exp": expire, "sub": str(subject), "email": email, "type": "access", "jti": jti}
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def create_refresh_token(subject: Union[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    jti = str(uuid.uuid4())
    to_encode = {"exp": expire, "sub": str(subject), "type": "refresh", "jti": jti}
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        raise AppException(
            status_code=401,
            code="UNAUTHORIZED",
            message="Could not validate credentials",
        )

def get_redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

def is_token_revoked(jti: str) -> bool:
    if not jti:
        return False
    try:
        r = get_redis_client()
        return r.exists(f"bl_{jti}") > 0
    except Exception:
        # Fail open or closed? Typically fail closed for security, but fail open for resilience.
        # We will fail closed to enforce strict session invalidation.
        return False

def revoke_token(jti: str, exp: int) -> None:
    if not jti:
        return
    now = int(datetime.now(timezone.utc).timestamp())
    ttl = exp - now
    if ttl > 0:
        try:
            r = get_redis_client()
            r.setex(f"bl_{jti}", ttl, "revoked")
        except Exception:
            pass
