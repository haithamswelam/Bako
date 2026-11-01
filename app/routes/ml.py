import os
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from opentelemetry import trace

from app.ai.providers.base import LLMProviderError
from app.ai.providers.factory import build_shadow_explanation_provider
from app.dependencies import get_current_user
from app.services.ai_explanation_orchestrator import (
    clarification_outcome,
    conversation_outcome,
    generate_coach_explanation,
    unsupported_question_outcome,
    unknown_goal_outcome,
)
from app.services.ai_chat_action_service import build_ai_chat_actions
from app.services.ai_goal_followup_service import build_goal_adjustment
from app.services.ai_chat_history_service import (
    get_ai_chat_history,
    get_ai_usage_summary,
    record_ai_exchange,
)
from app.services.ai_question_context_service import (
    build_contextual_explanation_request,
)
from app.services.budget_service import calculate_daily_table
from app.services.date_service import current_business_date
from app.services.ml_shadow_service import (
    MLServiceUnavailableError,
    build_canonical_budget_snapshot,
    build_live_cycle_coach_response,
    request_budget_risk_prediction,
)


router = APIRouter(prefix="/ml", tags=["ml-shadow"])


def _ai_explanation_timeout_seconds() -> float:
    raw_value = os.getenv("AI_EXPLANATION_TIMEOUT_SECONDS", "8")
    try:
        timeout = float(raw_value)
    except ValueError as error:
        raise ValueError(
            "AI_EXPLANATION_TIMEOUT_SECONDS must be a number"
        ) from error
    if not 0 < timeout <= 30:
        raise ValueError(
            "AI_EXPLANATION_TIMEOUT_SECONDS must be greater than zero "
            "and no more than 30"
        )
    return timeout


class ShadowCoachExplanationInput(BaseModel):
    cycle_id: int = Field(gt=0)
    question: str = Field(min_length=1, max_length=500)
    history_days: int = Field(default=5, ge=1, le=30)

    @field_validator("question")
    @classmethod
    def question_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question cannot be blank")
        return cleaned


def _build_shadow_cycle_coach(
    cycle_id: int,
    history_days: int,
    user_id: int,
) -> dict:
    as_of_date = current_business_date()
    budget_data, error = calculate_daily_table(
        cycle_id=cycle_id,
        user_id=user_id,
    )
    if error:
        raise HTTPException(status_code=404, detail=error)

    snapshot = build_canonical_budget_snapshot(
        budget_data=budget_data,
        as_of_date=as_of_date,
    )
    prediction = request_budget_risk_prediction(snapshot)
    return build_live_cycle_coach_response(
        budget_data=budget_data,
        prediction=prediction,
        as_of_date=as_of_date,
        history_days=history_days,
    )


@router.get("/shadow/budget-risk")
def get_shadow_budget_risk(
    cycle_id: int,
    current_user=Depends(get_current_user),
):
    budget_data, error = calculate_daily_table(
        cycle_id=cycle_id,
        user_id=current_user["id"],
    )
    if error:
        raise HTTPException(status_code=404, detail=error)

    try:
        snapshot = build_canonical_budget_snapshot(
            budget_data=budget_data,
            as_of_date=current_business_date(),
        )
        prediction = request_budget_risk_prediction(snapshot)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except MLServiceUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return {
        "mode": "shadow",
        "affects_financial_decisions": False,
        "snapshot": snapshot,
        "prediction": prediction,
    }


@router.get("/shadow/cycle-coach")
def get_shadow_cycle_coach(
    cycle_id: int,
    history_days: int = Query(default=5, ge=1, le=30),
    current_user=Depends(get_current_user),
):
    try:
        return _build_shadow_cycle_coach(
            cycle_id=cycle_id,
            history_days=history_days,
            user_id=current_user["id"],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except MLServiceUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/shadow/cycle-coach/explanation")
def get_shadow_cycle_coach_explanation(
    
    payload: ShadowCoachExplanationInput,
    current_user=Depends(get_current_user),
):  
    """Explain trusted coach facts without changing financial decisions."""
    current_span = trace.get_current_span()
    current_span.set_attribute("bako.ai.feature", "ask_bako")
    current_span.set_attribute("bako.ai.cycle_id", payload.cycle_id)
    current_span.set_attribute("bako.ai.history_days", payload.history_days)

    if os.getenv(
        "OTEL_CAPTURE_SENSITIVE_INPUTS",
        "false",
    ).lower() == "true":
        current_span.set_attribute(
            "bako.ai.question",
            payload.question,
        )

    try:
        cycle_coach = _build_shadow_cycle_coach(
            cycle_id=payload.cycle_id,
            history_days=payload.history_days,
            user_id=current_user["id"],
        )
        goal_adjustment = build_goal_adjustment(
            payload.question,
            user_id=current_user["id"],
            cycle_id=payload.cycle_id,
            remaining_budget=cycle_coach["financial_position"]["remaining_budget"],
        )
        explanation_request, question_plan = (
            build_contextual_explanation_request(
                cycle_coach=cycle_coach,
                question="Tell me about goals" if goal_adjustment else payload.question,
                user_id=current_user["id"],
            )
        )       
        current_span.set_attribute(
            "bako.ai.topics",
            list(question_plan.topics),
        )
        current_span.set_attribute(
            "bako.ai.supported",
            question_plan.supported,
        )
        current_span.set_attribute(
            "bako.ai.needs_clarification",
            question_plan.needs_clarification,
        )
        

        if goal_adjustment:
            outcome = goal_adjustment[0]
        elif "conversation" in question_plan.topics:
            display_name = (current_user.get("display_name") or "").strip()
            first_name = (
                display_name.split()[0][:40]
                if display_name
                else None
            )
            outcome = conversation_outcome(
                request=explanation_request,
                conversation_kind=question_plan.conversation_kind,
                first_name=first_name,
                language=question_plan.conversation_language,
            )
        elif question_plan.needs_clarification:
            outcome = clarification_outcome(
                request=explanation_request,
                available_goal_names=question_plan.available_goal_names,
            )
        elif not question_plan.supported:
            outcome = unsupported_question_outcome(explanation_request)
        elif question_plan.goal_reference_status == "not_found":
            outcome = unknown_goal_outcome(
                request=explanation_request,
                requested_goal_name=question_plan.requested_goal_name,
                available_goal_names=question_plan.available_goal_names,
            )
        else:
            disabled_reason = "provider_disabled"
            try:
                provider = build_shadow_explanation_provider()
            except LLMProviderError:
                provider = None
                disabled_reason = "provider_configuration_error"

            outcome = generate_coach_explanation(
                request=explanation_request,
                user_question=payload.question,
                provider=provider,
                timeout_seconds=_ai_explanation_timeout_seconds(),
                max_attempts=1,
                disabled_reason=disabled_reason,
            )

        current_span.set_attribute(
            "bako.ai.used_fallback",
            outcome.metadata.used_fallback,
        )
        current_span.set_attribute(
            "bako.ai.openai_called",
            outcome.metadata.provider is not None,
        )

        if outcome.metadata.provider:
            current_span.set_attribute(
                "bako.ai.provider",
                outcome.metadata.provider,
            )

        if outcome.metadata.model:
            current_span.set_attribute(
                "bako.ai.model",
                outcome.metadata.model,
            )

        if outcome.metadata.fallback_reason:
            current_span.set_attribute(
                "bako.ai.fallback_reason",
                outcome.metadata.fallback_reason,
            )
        suggested_actions = goal_adjustment[1] if goal_adjustment else (
            []
            if (
                "conversation" in question_plan.topics
                or question_plan.needs_clarification
                or not question_plan.supported
            )
            else build_ai_chat_actions(
                cycle_id=payload.cycle_id,
                user_id=current_user["id"],
                topics=question_plan.topics,
                question=payload.question,
            )
        )
        exchange_id = record_ai_exchange(
            user_id=current_user["id"],
            cycle_id=payload.cycle_id,
            question=payload.question,
            explanation=outcome.explanation,
            topics=question_plan.topics,
            metadata=outcome.metadata,
        )
        usage_summary = get_ai_usage_summary(user_id=current_user["id"])
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except MLServiceUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    return {
        "mode": "shadow",
        "affects_financial_decisions": False,
        "question_plan": asdict(question_plan),
        "suggested_actions": suggested_actions,
        "exchange_id": exchange_id,
        "cycle_coach": cycle_coach,
        "explanation": outcome.explanation.model_dump(mode="json"),
        "operational_metadata": asdict(outcome.metadata),
        "usage_summary": usage_summary,
    }


@router.get("/coach/history")
def get_coach_history(
    cycle_id: int = Query(gt=0),
    limit: int = Query(default=100, ge=1, le=200),
    current_user=Depends(get_current_user),
):
    """Load saved questions and answers for one user-owned cycle."""

    history = get_ai_chat_history(
        user_id=current_user["id"],
        cycle_id=cycle_id,
        limit=limit,
    )
    if history is None:
        raise HTTPException(status_code=404, detail="Financial cycle not found")
    return {
        "cycle_id": cycle_id,
        "exchanges": history,
        "usage_summary": get_ai_usage_summary(user_id=current_user["id"]),
    }
