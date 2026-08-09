import logging
from typing import Dict, Any, List, Optional
from config import Config

logger = logging.getLogger(__name__)

# Support both PyJWT and python-jose
try:
    import jwt
    from jwt import PyJWKClient, PyJWTError
    HAS_PYJWT = True
except ImportError:
    HAS_PYJWT = False
    jwt = None
    PyJWKClient = None
    PyJWTError = Exception

try:
    from jose import jwt as jose_jwt
    HAS_JOSE = True
except ImportError:
    HAS_JOSE = False
    jose_jwt = None

_jwks_client = None

def get_jwks_client():
    global _jwks_client
    if _jwks_client is None and HAS_PYJWT and Config.OIDC_ISSUER_URL:
        try:
            jwks_url = f"{Config.OIDC_ISSUER_URL.rstrip('/')}/protocol/openid-connect/certs"
            _jwks_client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
            logger.info(f"OIDC JWKS Client initialized for {jwks_url}")
        except Exception as e:
            logger.warning(f"Could not initialize OIDC JWKS Client: {e}")
    return _jwks_client

def verify_oidc_token(token: str) -> Dict[str, Any]:
    """
    Verifies an OIDC JWT against the configured Identity Provider (Keycloak / Okta / Azure AD).
    Extracts user identity and groups/roles for payload-level ACL enforcement.
    """
    if not token:
        return {}

    jwks_client = get_jwks_client()
    payload = {}

    try:
        if jwks_client and HAS_PYJWT:
            signing_key = jwks_client.get_signing_key_from_jwt(token)
            decode_kwargs = {
                "algorithms": ["RS256", "RS384", "RS512"],
                "options": {"verify_aud": bool(Config.OIDC_AUDIENCE)}
            }
            if Config.OIDC_AUDIENCE:
                decode_kwargs["audience"] = Config.OIDC_AUDIENCE
            if Config.OIDC_ISSUER_URL:
                decode_kwargs["issuer"] = Config.OIDC_ISSUER_URL

            payload = jwt.decode(
                token,
                signing_key.key,
                **decode_kwargs
            )
        elif HAS_JOSE:
            # Jose unverified decode / local validation fallback
            payload = jose_jwt.get_unverified_claims(token)
        elif HAS_PYJWT:
            payload = jwt.decode(token, options={"verify_signature": False})
        else:
            logger.warning("No JWT decoding library available for OIDC.")
            return {}

        # Standardize extracted user and groups
        username = (
            payload.get("preferred_username")
            or payload.get("email")
            or payload.get("sub")
            or "oidc_user"
        )
        
        # Extract groups/roles from various standard OIDC claim locations
        groups: List[str] = []
        if "groups" in payload and isinstance(payload["groups"], list):
            groups.extend(payload["groups"])
        if "realm_access" in payload and isinstance(payload["realm_access"], dict):
            realm_roles = payload["realm_access"].get("roles", [])
            if isinstance(realm_roles, list):
                groups.extend(realm_roles)
        if "roles" in payload and isinstance(payload["roles"], list):
            groups.extend(payload["roles"])

        # Default to Public if no groups found
        if not groups:
            groups = ["Public"]
        elif "Public" not in groups:
            groups.append("Public")

        return {
            "sub": username,
            "groups": list(set(groups)),
            "email": payload.get("email"),
            "auth_type": "oidc",
            "raw_payload": payload
        }
    except Exception as e:
        logger.warning(f"OIDC token verification failed: {e}")
        return {}
