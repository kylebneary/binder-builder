from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.schemas import (
    GoalDetailOut,
    GoalIn,
    GoalOut,
    RankedStrategyOut,
    SensitivityIn,
    SensitivityOut,
    SimResultOut,
    SimulateIn,
    SimulateResponseOut,
    StrategyOut,
    UnsimulatableProductOut,
)
from app.models.enums import Condition, GoalType
from app.services import goals as goals_service
from app.services.collection import get_or_create_default_collection
from app.services.simulation_runs import run_search_and_cache, run_sensitivity
from app.sim.optimizer import Objective
from app.sim.types import CostParams, Strategy

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


@router.post("/{goal_id}/simulate", response_model=SimulateResponseOut)
def simulate_goal(
    goal_id: int, body: SimulateIn, db: Session = Depends(get_db)
) -> SimulateResponseOut:
    try:
        objective = Objective(body.objective)
    except ValueError as exc:
        detail = f"Unknown objective {body.objective!r}"
        raise HTTPException(status_code=422, detail=detail) from exc

    overrides = body.model_dump(
        exclude={"objective", "n_trials", "seed", "sealed_product_ids"}, exclude_none=True
    )
    params = replace(CostParams(), **overrides)
    sealed_product_ids = set(body.sealed_product_ids) if body.sealed_product_ids else None

    try:
        result = run_search_and_cache(
            db,
            goal_id,
            objective,
            params,
            n_trials=body.n_trials,
            seed=body.seed,
            sealed_product_ids=sealed_product_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    ranked = [
        RankedStrategyOut(
            simulation_run_id=run.id,
            strategy=StrategyOut(units=run.strategy_json),
            result=SimResultOut(
                **{k: v for k, v in run.results_json.items() if k in SimResultOut.model_fields}
            ),
        )
        for run in result.runs
    ]
    return SimulateResponseOut(
        goal_id=goal_id,
        objective=objective.value,
        ranked=ranked,
        unsimulatable=[UnsimulatableProductOut(**u) for u in result.unsimulatable],
        uncovered_needed_price_sum=result.uncovered_needed_price_sum,
    )


@router.post("/{goal_id}/sensitivity", response_model=SensitivityOut)
def sensitivity_goal(
    goal_id: int, body: SensitivityIn, db: Session = Depends(get_db)
) -> SensitivityOut:
    overrides = body.model_dump(
        exclude={"sealed_product_ids", "n_trials", "seed"}, exclude_none=True
    )
    params = replace(CostParams(), **overrides)
    strategy = Strategy(units=body.sealed_product_ids)

    try:
        result = run_sensitivity(
            db, goal_id, strategy, params, n_trials=body.n_trials, seed=body.seed
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SensitivityOut(**result)


@router.get("/{goal_id}/export/mass-entry", response_class=PlainTextResponse)
def export_goal_mass_entry(goal_id: int, db: Session = Depends(get_db)) -> str:
    """Still-needed cards in TCGplayer Mass Entry format (one '<qty> <name>' line per card)."""
    collection = get_or_create_default_collection(db)
    detail = goals_service.get_goal_need_list(db, goal_id, collection.id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id} not found")
    return goals_service.mass_entry_text(detail)
