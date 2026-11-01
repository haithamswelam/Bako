"""Read-only contribution proposals; never execute a chat instruction."""

import re
from decimal import Decimal, InvalidOperation

from app.ai.contracts import CoachExplanation
from app.ai.question_router import resolve_goal_reference
from app.services.ai_chat_history_service import get_ai_chat_history
from app.services.ai_explanation_orchestrator import _local_outcome
from app.services.goals_service import get_user_goals


def is_goal_adjustment(question: str) -> bool:
    return bool(
        re.search(r"\b(adjust|change|update|set|instead|make)\b", question, re.I)
        and re.search(r"\b(button|contribution|save|saving|goal)\b", question, re.I)
    )


def _mentioned_goals(text, goals):
    return [
        goal for goal in goals
        if resolve_goal_reference(text, [goal["name"]]).status == "matched"
    ]


def build_goal_adjustment(question, *, user_id, cycle_id, remaining_budget):
    if not is_goal_adjustment(question):
        return None

    def reply(message, actions=None):
        return (
            _local_outcome(CoachExplanation(
                source="local_response",
                headline="Goal contribution proposal",
                explanation=message,
                recommended_action=(
                    "Nothing has been saved. Use the button to confirm a one-time "
                    "contribution; this does not schedule daily savings."
                    if actions else "Tell me the goal name and the amount in EGP."
                ),
            ), reason="goal_contribution_proposal"),
            actions or [],
        )

    goals = get_user_goals(user_id, active_only=True, cycle_id=cycle_id)
    matches = _mentioned_goals(question, goals)
    reference = resolve_goal_reference(question, [goal["name"] for goal in goals])
    if not matches and reference.status == "not_found":
        return reply("I could not match that goal to your active goals. Please specify its name.")
    if not matches:
        # Only the latest exchange in this user's cycle may supply context.
        history = get_ai_chat_history(user_id=user_id, cycle_id=cycle_id, limit=1) or []
        if history and "goals" in history[-1].get("topics", []):
            previous = history[-1]
            matches = _mentioned_goals(previous.get("question", ""), goals)
            if not matches:
                matches = _mentioned_goals(
                    previous.get("explanation", "") + " " + previous.get("recommended_action", ""),
                    goals,
                )
    if len(matches) != 1:
        return reply("Which active goal should this contribution go to? I will not choose one for you.")
    goal = matches[0]

    # Ignore an explicitly contrasted old amount, but never choose between
    # multiple unexplained amounts. Goal names themselves may contain numbers.
    amount_text = re.sub(re.escape(goal["name"]), "", question, flags=re.I)
    amount_text = re.split(r"\b(?:instead of|rather than|as you mentioned)\b", amount_text, flags=re.I)[0]
    numbers = re.findall(r"(?<![\w.])[+-]?\d[\d,]*(?:\.\d+)?(?![\w.])", amount_text)
    if len(numbers) != 1:
        return reply("Please specify one contribution amount in EGP so I do not choose the wrong number.")
    try:
        raw = numbers[0]
        if not re.fullmatch(r"[+\-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?", raw):
            raise InvalidOperation
        amount = Decimal(raw.replace(",", ""))
        remaining = Decimal(str(goal["target_amount"])) - Decimal(str(goal["current_amount"]))
        budget = Decimal(str(remaining_budget))
        if not amount.is_finite() or not budget.is_finite() or not remaining.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return reply("Use a valid EGP amount with at most two decimal places.")
    if re.search(r"\b(usd|eur|gbp|dollars?|euros?|percent)\b|[$\u20ac\u00a3%]", question, re.I):
        return reply("Please give the contribution in EGP; I cannot convert currencies here.")
    if amount <= 0 or amount > remaining or amount > budget:
        return reply("The amount must be positive and fit within both your remaining goal target and cycle budget.")
    action = {
        "action_id": f"goal-contribution:{goal['id']}:{amount:.2f}",
        "type": "goal_contribution",
        "goal_id": goal["id"],
        "goal_name": goal["name"],
        "amount": float(amount),
        "label": f"Add EGP {amount:.2f} to {goal['name']}",
        "calculated_by": "user_requested_backend_validated",
        "requires_user_confirmation": True,
    }
    return reply(
        f"For {goal['name']}, the proposed contribution is EGP {amount:.2f}. "
        "This is the amount you requested, not an automatic daily saving rule.",
        [action],
    )
