import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from jose import jwt, JWTError
from config import Config

# JWT configuration
SECRET_KEY = Config.JWT_SECRET
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours for development convenience

def verify_password(plain_password: str, hashed_password: str) -> bool:
    passwd = plain_password.encode('utf-8')
    hashed = hashed_password.encode('utf-8')
    return bcrypt.checkpw(passwd, hashed)

def get_password_hash(password: str) -> str:
    passwd = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(passwd, salt)
    return hashed.decode('utf-8')

def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes the access token and returns the payload dictionary if valid.
    Raises JWTError if invalid.
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return {}
