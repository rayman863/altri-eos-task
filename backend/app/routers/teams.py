"""Teams, Scorecard, Issues, To-Dos and Rocks (docs/API_CONTRACTS.md sections 4 to 8)."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Response

from app.authz import IssueWrite, MeasurableIdPath, Now, SignedIn, TeamRead, TeamWrite, TodoWrite
from app.cache import ReadCache
from app.db import DbSession
from app.schemas import (
    Cell,
    Empty,
    IssueCreateIn,
    IssueOut,
    IssuePatchIn,
    IssueSolveIn,
    IssueTodoIn,
    MadeIssue,
    RockList,
    Scorecard,
    ScoreIn,
    TeamDetail,
    TeamListItem,
    TodoDoneIn,
    TodoList,
    TodoOut,
)
from app.services import issues, rocks, scorecard, teams, todos

router = APIRouter()

WeekPath = Annotated[date, Path(description="The week's Monday, e.g. 2026-11-02")]
SCORE_PATH = "/teams/{team_id}/measurables/{measurable_id}/scores/{week_start}"


# ---- teams ----------------------------------------------------------------------------------


@router.get("/teams", response_model=list[TeamListItem], tags=["Teams"])
async def list_teams(user: SignedIn, session: DbSession) -> list[dict]:
    return await teams.team_list(session, user)


@router.get("/teams/{team_id}", response_model=TeamDetail, tags=["Teams"])
async def get_team(access: TeamRead, session: DbSession, now: Now, cache: ReadCache) -> dict:
    return await teams.team_detail(session, access.team_id, now, cache)


# ---- scorecard ------------------------------------------------------------------------------


@router.get("/teams/{team_id}/scorecard", response_model=Scorecard, tags=["Scorecard"])
async def get_scorecard(access: TeamRead, session: DbSession, now: Now, cache: ReadCache) -> dict:
    return await scorecard.scorecard(session, access.team_id, now, cache)


@router.put(SCORE_PATH, response_model=Cell, tags=["Scorecard"], summary="Set a score")
async def put_score(
    access: TeamWrite,
    measurable_id: MeasurableIdPath,
    week_start: WeekPath,
    body: ScoreIn,
    session: DbSession,
    now: Now,
) -> dict:
    return await scorecard.put_score(session, access, measurable_id, week_start, body.value, now)


@router.delete(SCORE_PATH, status_code=204, tags=["Scorecard"], summary="Clear a score")
async def delete_score(
    access: TeamWrite,
    measurable_id: MeasurableIdPath,
    week_start: WeekPath,
    session: DbSession,
    now: Now,
) -> Response:
    await scorecard.clear_score(session, access, measurable_id, week_start, now)
    return Response(status_code=204)


@router.post(
    f"{SCORE_PATH}/issue",
    response_model=MadeIssue,
    status_code=201,
    responses={
        201: {"description": "A new Issue was created (`created: true`)"},
        200: {
            "model": MadeIssue,
            "description": "An open Issue already existed (`created: false`)",
        },
    },
    tags=["Scorecard"],
    summary="Make it an Issue (201 created, 200 existing)",
)
async def make_issue(
    access: TeamWrite,
    measurable_id: MeasurableIdPath,
    week_start: WeekPath,
    response: Response,
    session: DbSession,
    now: Now,
    body: Empty | None = None,
) -> dict:
    issue, created = await scorecard.make_issue(session, access, measurable_id, week_start, now)
    response.status_code = 201 if created else 200
    return {"created": created, "issue": issue}


# ---- issues ---------------------------------------------------------------------------------


@router.get("/teams/{team_id}/issues", response_model=list[IssueOut], tags=["Issues"])
async def list_issues(
    access: TeamRead,
    session: DbSession,
    now: Now,
    cache: ReadCache,
    status: Annotated[Literal["unsolved", "solved"], Query()] = "unsolved",
) -> list[dict]:
    return await issues.list_issues(session, access.team_id, status, now, cache)


@router.post("/teams/{team_id}/issues", response_model=IssueOut, status_code=201, tags=["Issues"])
async def create_issue(
    access: TeamWrite, body: IssueCreateIn, session: DbSession, now: Now
) -> dict:
    return await issues.create_issue(session, access, body.title, body.priority, now)


@router.patch("/issues/{issue_id}", response_model=IssueOut, tags=["Issues"])
async def patch_issue(access: IssueWrite, body: IssuePatchIn, session: DbSession) -> dict:
    return await issues.set_priority(session, access, body.priority)


@router.post("/issues/{issue_id}/solve", response_model=IssueOut, tags=["Issues"])
async def solve_issue(access: IssueWrite, body: IssueSolveIn, session: DbSession, now: Now) -> dict:
    return await issues.solve(session, access, body.resolution_note, now)


@router.post("/issues/{issue_id}/todos", response_model=TodoOut, status_code=201, tags=["Issues"])
async def add_issue_todo(
    access: IssueWrite, body: IssueTodoIn, session: DbSession, now: Now
) -> dict:
    todo_id = await issues.add_todo(session, access, access.user, body.title, body.owner_id, now)
    return await todos.get_todo(session, todo_id, now)


# ---- to-dos ---------------------------------------------------------------------------------


@router.get("/teams/{team_id}/todos", response_model=TodoList, tags=["To-Dos"])
async def list_todos(access: TeamRead, session: DbSession, now: Now, cache: ReadCache) -> dict:
    return await todos.list_todos(session, access.team_id, now, cache)


@router.put("/todos/{todo_id}/done", response_model=TodoOut, tags=["To-Dos"])
async def set_todo_done(access: TodoWrite, body: TodoDoneIn, session: DbSession, now: Now) -> dict:
    return await todos.set_done(session, access, body.done, now)


# ---- rocks ----------------------------------------------------------------------------------


@router.get("/teams/{team_id}/rocks", response_model=RockList, tags=["Rocks"])
async def list_rocks(access: TeamRead, session: DbSession, now: Now, cache: ReadCache) -> dict:
    return await rocks.list_rocks(session, access.team_id, now, cache)
