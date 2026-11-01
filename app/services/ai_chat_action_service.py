from collections.abc import Iterable

from app.ai.question_router import resolve_goal_reference
from app.services.ai_insights_service import generate_ai_insights


def build_ai_chat_actions(
    cycle_id: int,
    user_id: int,
    topics: Iterable[str],
    question: str,
) -> list[dict]:
    """Return backend-calculated actions; never derive actions from LLM text."""

    if "goals" not in topics:
        return []

    insight_data, error = generate_ai_insights(
        cycle_id=cycle_id,
        user_id=user_id,
    )
    if error or not insight_data:
        return []

    goal_names = {
        int(goal["id"]): goal["name"]
        for goal in insight_data.get("goal_forecasts", [])
        if goal.get("id") is not None
    }
    goal_reference = resolve_goal_reference(question, goal_names.values())
    if goal_reference.status == "not_found":
        return []

    normalized_question = question.casefold()
    named_goal_ids = {
        goal_id
        for goal_id, goal_name in goal_names.items()
        if goal_name.casefold() in normalized_question
    }

    actions = []
    seen_goal_ids = set()
    forecasts = {
        int(goal["id"]): goal
        for goal in insight_data.get("goal_forecasts", [])
        if goal.get("id") is not None
    }
    for insight in insight_data.get("structured_insights", []):
        goal_id = insight.get("goal_id")
        amount = round(float(insight.get("amount") or 0), 2)
        if (
            insight.get("type") != "goal"
            or goal_id is None
            or amount <= 0
        ):
            continue

        goal_id = int(goal_id)
        forecast = forecasts.get(goal_id, {})
        daily_saving = forecast.get("required_daily_saving")
        # Prefer the daily target over a larger carryover allocation.
        if daily_saving is not None and float(daily_saving) > 0:
            amount = round(min(amount, float(daily_saving)), 2)
        if amount <= 0:
            continue
        if named_goal_ids and goal_id not in named_goal_ids:
            continue
        if goal_id in seen_goal_ids:
            continue

        goal_name = goal_names.get(goal_id, insight.get("title", "Goal"))
        actions.append(
            {
                "action_id": f"goal-contribution:{goal_id}:{amount:.2f}",
                "type": "goal_contribution",
                "goal_id": goal_id,
                "goal_name": goal_name,
                "amount": amount,
                "label": f"Add EGP {amount:.2f} to {goal_name}",
                "calculated_by": "backend_goal_rules",
                "requires_user_confirmation": True,
            }
        )
        seen_goal_ids.add(goal_id)

        if len(actions) == 3:
            break

    return actions
