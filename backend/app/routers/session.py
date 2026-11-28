"""Session: the seeded user switcher, login, logout and /me (decision 4, plan 3.15)."""

from fastapi import APIRouter, Request, Response
from sqlalchemy import update

from app import models as m
from app.authz import Now, SignedIn, load_user
from app.cache import ReadCache
from app.db import DbSession
from app.errors import AppError
from app.realtime import close_user_streams
from app.schemas import Empty, LoginIn, Me, SeedUser
from app.security import COOKIE_NAME, sign_session
from app.services import teams as svc

router = APIRouter(tags=["Session"])


@router.get("/auth/users", response_model=list[SeedUser], summary="Seeded users (switcher)")
async def users(session: DbSession, cache: ReadCache) -> list[dict]:
    return await svc.seed_users(session, cache)


@router.post("/auth/login", response_model=Me, summary="Sign in as a seeded user")
async def login(
    body: LoginIn, request: Request, response: Response, session: DbSession, now: Now
) -> dict:
    user = await load_user(session, body.user_id)
    if user is None:
        raise AppError(401, "invalid_login", "Unknown user.")
    settings = request.app.state.settings
    response.set_cookie(
        COOKIE_NAME,
        sign_session(settings.session_secret, user.id, user.session_epoch),
        max_age=settings.session_max_age_s,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    request.state.user_id = user.id
    return await svc.me(session, user, now)


@router.post(
    "/auth/logout",
    status_code=204,
    summary="Sign out (ends every session of this user, in every browser)",
)
async def logout(
    user: SignedIn,
    request: Request,
    response: Response,
    session: DbSession,
    body: Empty | None = None,
) -> Response:
    settings = request.app.state.settings
    # The signed cookie can't be revoked by itself, so bump the user's epoch: every token
    # issued before this point stops working (not a team write, so no team bump).
    await session.execute(
        update(m.User).where(m.User.id == user.id).values(session_epoch=m.User.session_epoch + 1)
    )
    # Open live streams were authorized at connect: end them on every worker too.
    await close_user_streams(session, user.id)
    response.status_code = 204
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True, samesite="lax", secure=settings.cookie_secure
    )
    return response


@router.get("/me", response_model=Me, summary="The signed-in user, teams and server clock")
async def me(user: SignedIn, session: DbSession, now: Now) -> dict:
    return await svc.me(session, user, now)
