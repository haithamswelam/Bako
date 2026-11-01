import re
from dataclasses import dataclass
from typing import Literal


CoachQuestionTopic = Literal[
    "conversation",
    "budget_pace",
    "spending",
    "goals",
    "unsupported",
]


@dataclass(frozen=True)
class CoachQuestionPlan:
    topics: tuple[CoachQuestionTopic, ...]
    supported: bool
    goal_reference_status: Literal[
        "not_applicable", "general", "matched", "not_found"
    ] = "not_applicable"
    requested_goal_name: str | None = None
    matched_goal_name: str | None = None
    available_goal_names: tuple[str, ...] = ()
    conversation_kind: Literal[
        "none", "greeting", "thanks", "help", "acknowledgement"
    ] = "none"
    conversation_language: Literal["en", "ar"] = "en"
    needs_clarification: bool = False


@dataclass(frozen=True)
class GoalReference:
    status: Literal["general", "matched", "not_found"]
    requested_name: str | None
    matched_name: str | None


_TOPIC_PATTERNS: tuple[tuple[CoachQuestionTopic, tuple[str, ...]], ...] = (
    (
        "goals",
        (
            r"\bgoal",
            r"\bcontribution",
            r"\bsaving target",
            r"\bsave for\b",
            r"\btarget date",
            r"\bdeadline\b",
        ),
    ),
    (
        "spending",
        (
            r"\bspend",
            r"\bspent\b",
            r"\bdaily expense",
            r"\bvariable expense",
            r"\bcategory",
            r"\bsubcategory",
            r"\btransaction",
            r"\bgrocer",
            r"\bsupermarket",
            r"\bouting",
            r"\bbills?\b",
            r"\brent\b",
            r"\belectricity\b",
            r"\binternet\b",
            r"\binstallment",
            r"\bloan\b",
            r"\bunpaid\b",
            r"\bcredit card",
            r"\bcard due\b",
            r"\bcard balance\b",
            r"\boutstanding\b",
            r"\bsettled\b",
        ),
    ),
    (
        "budget_pace",
        (
            r"\bbudget",
            r"\bpace\b",
            r"\bdaily allowance",
            r"\bsafe daily",
            r"\bbalance\b",
            r"\bover[ -]?spend",
            r"\bafford\b",
            r"\bon track\b",
            r"\brecommendation",
            r"\badvice\b",
            r"\bcurrent cycle\b",
        ),
    ),
)

_CONVERSATION_PATTERNS: tuple[
    tuple[
        Literal["greeting", "thanks", "help", "acknowledgement"],
        tuple[str, ...],
    ],
    ...,
] = (
    (
        "greeting",
        (
            r"^(?:(?:hi|hello|hey)(?:\s+(?:there|bako))?"
            r"(?:,?\s+how are you)?|good morning|good afternoon|good evening)$",
            r"^(?:مرحبا|مرحباً|أهلا|اهلا|أهلاً|السلام عليكم|صباح الخير|مساء الخير)$",
        ),
    ),
    (
        "thanks",
        (
            r"^(?:thank you|thanks|thank you very much|thanks a lot)"
            r"(?:,?\s+that helped)?$",
            r"^(?:شكرا|شكراً|متشكر|مشكور)$",
        ),
    ),
    (
        "help",
        (
            r"^(?:can you help me|help me|what can you do|how can you help me|"
            r"what else can you help me with|how are you)$",
            r"^(?:هل يمكنك مساعدتي|ممكن تساعدني|كيف يمكنك مساعدتي|ماذا يمكنك أن تفعل|كيف حالك)$",
        ),
    ),
    (
        "acknowledgement",
        (
            r"^(?:ok|okay|great|sounds good|understood|got it)$",
            r"^(?:حسنا|حسناً|تمام|مفهوم|جيد)$",
        ),
    ),
)

_AMBIGUOUS_MONEY_REQUESTS = (
    re.compile(
        r"^(?:can i|could i|i want to|how do i)\s+"
        r"(?:add|put|move)\s+(?:some\s+)?money\??$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:ممكن|هل يمكنني|اريد|أريد)\s+"
        r"(?:اضيف|أضيف|احط|أحط)\s+(?:فلوس|مال)[?؟]?$"
    ),
)

_GOAL_NAME_PATTERNS = (
    re.compile(r"\b(?:my|the)\s+(.+?)\s+goal\b", re.IGNORECASE),
    re.compile(r"\bgoal\s+(?:called|named)\s+(.+?)(?:[?.!,]|$)", re.IGNORECASE),
    re.compile(
        r"\bsave\s+for\s+(?:my\s+|the\s+)?(.+?)(?:\s+goal)?(?:[?.!,]|$)",
        re.IGNORECASE,
    ),
)
_GENERIC_GOAL_REFERENCES = {
    "a goal",
    "goal",
    "goals",
    "my goal",
    "my goals",
    "the goal",
    "the goals",
}


def _normalize_entity_name(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() else " "
        for character in value.casefold()
    )
    return " ".join(normalized.split())


def resolve_goal_reference(
    question: str,
    available_goal_names,
) -> GoalReference:
    """Resolve an explicitly named goal against backend-owned goal names."""

    names = tuple(available_goal_names)
    normalized_question = _normalize_entity_name(question)
    matched_names = [
        name
        for name in names
        if (
            f" {_normalize_entity_name(name)} "
            in f" {normalized_question} "
        )
    ]
    if matched_names:
        matched_name = max(matched_names, key=len)
        return GoalReference(
            status="matched",
            requested_name=matched_name,
            matched_name=matched_name,
        )

    # A pronoun is not a goal name (for example, "the button for my goal").
    if re.search(r"\b(?:my|the|this|that)\s+goal\b(?!\s+(?:called|named)\b)", question, re.I):
        return GoalReference(status="general", requested_name=None, matched_name=None)

    requested_name = None
    for pattern in _GOAL_NAME_PATTERNS:
        match = pattern.search(question)
        if match:
            candidate = " ".join(match.group(1).split()).strip(" '\"")
            if _normalize_entity_name(candidate) not in _GENERIC_GOAL_REFERENCES:
                requested_name = candidate[:100]
                break

    if requested_name:
        return GoalReference(
            status="not_found",
            requested_name=requested_name,
            matched_name=None,
        )
    return GoalReference(
        status="general",
        requested_name=None,
        matched_name=None,
    )


def route_coach_question(question: str) -> CoachQuestionPlan:
    """Select read-only context topics using predictable low-risk rules."""

    normalized = " ".join(question.lower().split())
    if not normalized:
        raise ValueError("question cannot be empty")

    if any(pattern.fullmatch(normalized) for pattern in _AMBIGUOUS_MONEY_REQUESTS):
        return CoachQuestionPlan(
            topics=("goals",),
            supported=True,
            goal_reference_status="general",
            needs_clarification=True,
        )

    topics = tuple(
        topic
        for topic, patterns in _TOPIC_PATTERNS
        if any(re.search(pattern, normalized) for pattern in patterns)
    )
    if not topics:
        conversational_text = normalized.strip(" .,!؟?")
        for kind, patterns in _CONVERSATION_PATTERNS:
            if any(
                re.fullmatch(pattern, conversational_text)
                for pattern in patterns
            ):
                return CoachQuestionPlan(
                    topics=("conversation",),
                    supported=True,
                    conversation_kind=kind,
                    conversation_language=(
                        "ar"
                        if re.search(r"[\u0600-\u06ff]", conversational_text)
                        else "en"
                    ),
                )
        return CoachQuestionPlan(topics=("unsupported",), supported=False)
    return CoachQuestionPlan(topics=topics, supported=True)
