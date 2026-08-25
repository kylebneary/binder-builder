from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import GoalDetailOut, GoalIn, GoalOut
from app.models.enums import Condition, GoalType
from app.services import goals as goals_service
from app.services.collection import get_or_create_default_collection

router = APIRouter(prefix="/goals", tags=["goals"])


@router.get("", response_model=list[GoalOut])
def list_goals(db: Session = Depends(get_db)) -> list[GoalOut]:
    return [GoalOut.model_validate(g) for g in goals_service.list_goals(db)]


@router.post("", response_model=GoalOut, status_code=201)
def create_goal(body: GoalIn, db: Session = Depends(get_db)) -> GoalOut:
    try:
        goal_type = GoalType(body.goal_type)
        target_condition = Condition(body.target_condition)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    goal = goals_service.create_goal(
        db,
        name=body.name,
        goal_type=goal_type,
        set_id=body.set_id,
        filter_json=body.filter_json,
        target_condition=target_condition,
    )
    return GoalOut.model_validate(goal)


@router.get("/{goal_id}", response_model=GoalDetailOut)
def get_goal_detail(goal_id: int, db: Session = Depends(get_db)) -> GoalDetailOut:
    collection = get_or_create_default_collection(db)
    detail = goals_service.get_goal_need_list(db, goal_id, collection.id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    return GoalDetailOut.model_validate(detail)


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: int, db: Session = Depends(get_db)) -> None:
    deleted = goals_service.delete_goal(db, goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
