from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext

# Secret key for JWT
SECRET_KEY = "super-secret-key-change-later"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

# Password hashing engine
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

from opentelemetry import trace as _trace

_tracer = _trace.get_tracer("bako.security")      # does nothing when tracing is off

# Hash password
def hash_password(password: str):
    with _tracer.start_as_current_span("password.hash"):
        return pwd_context.hash(password)

# Verify password
def verify_password(
    plain_password: str,
    hashed_password: str
):
    with _tracer.start_as_current_span("password.verify"):
        return pwd_context.verify(
            plain_password,
            hashed_password
        )

# Create JWT token
def create_access_token(data: dict):
    to_encode = data.copy()

    expire = datetime.utcnow() + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    to_encode.update({
        "exp": expire
    })

    encoded_jwt = jwt.encode(
        to_encode,
        SECRET_KEY,
        algorithm=ALGORITHM
    )

    return encoded_jwt