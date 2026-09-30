"""slowapi rate limits. Keyed by team token where there is one: a whole school sits behind
one NAT address, so per-IP limits on /runs and /submissions would lump every team together."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def client_key(request: Request) -> str:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return "t:" + auth[7:][:64]
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else get_remote_address(request)


limiter = Limiter(key_func=client_key)
