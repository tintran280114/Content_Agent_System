"""Callable Research and Copywriter interfaces for Tín's orchestrator."""

from __future__ import annotations

from typing import Any

from .base import StructuredProvider
from .models import (
    CriticPayload,
    CriticResult,
    Decision,
    DraftPayload,
    DraftPost,
    PolicyContext,
    ResearchBrief,
    ResearchCopywriterResult,
    ResearchPayload,
)
from .prompts import (
    COPYWRITER_PROMPT_VERSION,
    CRITIC_PROMPT_VERSION,
    RESEARCH_PROMPT_VERSION,
    REWRITE_PROMPT_VERSION,
    build_critic_messages,
    build_copywriter_messages,
    build_research_messages,
    build_rewrite_messages,
)

from ..critics import RuleCriticResult


class ResearchAgent:
    def __init__(self, provider: StructuredProvider) -> None:
        self.provider = provider

    def run(self, *, topic: str, policy: Any) -> ResearchBrief:
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("topic must not be empty")
        policy_context = PolicyContext.from_policy(policy)
        response = self.provider.generate(
            messages=build_research_messages(normalized_topic, policy_context),
            response_model=ResearchPayload,
            role="research",
            prompt_version=RESEARCH_PROMPT_VERSION,
        )
        return ResearchBrief(
            **response.output.model_dump(),
            topic=normalized_topic,
            account_id=policy_context.account_id,
            metadata=response.metadata,
        )


class CopywriterAgent:
    def __init__(self, provider: StructuredProvider) -> None:
        self.provider = provider

    def run(self, *, research: ResearchBrief, policy: Any) -> DraftPost:
        policy_context = PolicyContext.from_policy(policy)
        if policy_context.account_id != research.account_id:
            raise ValueError("policy account_id must match research account_id")
        response = self.provider.generate(
            messages=build_copywriter_messages(research, policy_context),
            response_model=DraftPayload,
            role="copywriter",
            prompt_version=COPYWRITER_PROMPT_VERSION,
        )
        return DraftPost(
            **response.output.model_dump(),
            brief_id=research.brief_id,
            topic=research.topic,
            account_id=policy_context.account_id,
            platform=policy_context.platform,
            metadata=response.metadata,
        )


class CriticAgent:
    def __init__(self, provider: StructuredProvider) -> None:
        self.provider = provider

    def run(
        self,
        *,
        draft: DraftPost,
        policy: Any,
        rule_result: RuleCriticResult,
    ) -> CriticResult:
        policy_context = PolicyContext.from_policy(policy)
        if policy_context.account_id != draft.account_id:
            raise ValueError("policy account_id must match draft account_id")
        if rule_result.draft_id != str(draft.draft_id):
            raise ValueError("rule result draft_id must match draft draft_id")
        response = self.provider.generate(
            messages=build_critic_messages(draft, policy_context, rule_result),
            response_model=CriticPayload,
            role="critic",
            prompt_version=CRITIC_PROMPT_VERSION,
        )
        payload = response.output
        violations = list(dict.fromkeys([*rule_result.messages(), *payload.violations]))
        passed = (
            rule_result.passed
            and payload.score >= policy_context.threshold
            and payload.decision == Decision.PASS
        )
        return CriticResult(
            draft_id=draft.draft_id,
            account_id=draft.account_id,
            rule_passed=rule_result.passed,
            score=payload.score,
            violations=violations,
            suggestions=payload.suggestions,
            decision=Decision.PASS if passed else Decision.REWRITE,
            metadata=response.metadata,
        )


class RewriteAgent:
    def __init__(self, provider: StructuredProvider) -> None:
        self.provider = provider

    def run(
        self,
        *,
        research: ResearchBrief,
        draft: DraftPost,
        critic: CriticResult,
        policy: Any,
        rewrite_number: int,
    ) -> DraftPost:
        if rewrite_number not in {1, 2}:
            raise ValueError("rewrite_number must be 1 or 2")
        policy_context = PolicyContext.from_policy(policy)
        if not (policy_context.account_id == research.account_id == draft.account_id):
            raise ValueError("policy, research, and draft account_id values must match")
        if critic.draft_id != draft.draft_id:
            raise ValueError("critic draft_id must match the draft being rewritten")
        response = self.provider.generate(
            messages=build_rewrite_messages(
                brief=research,
                draft=draft,
                critic=critic,
                policy=policy_context,
                rewrite_number=rewrite_number,
            ),
            response_model=DraftPayload,
            role="copywriter",
            prompt_version=REWRITE_PROMPT_VERSION,
        )
        return DraftPost(
            **response.output.model_dump(),
            brief_id=research.brief_id,
            topic=research.topic,
            account_id=policy_context.account_id,
            platform=policy_context.platform,
            metadata=response.metadata,
        )


def run_research_copywriter(
    *,
    topic: str,
    policy: Any,
    research_provider: StructuredProvider,
    copywriter_provider: StructuredProvider,
) -> ResearchCopywriterResult:
    """One-call vertical-slice interface for the shared orchestrator."""

    research = ResearchAgent(research_provider).run(topic=topic, policy=policy)
    draft = CopywriterAgent(copywriter_provider).run(research=research, policy=policy)
    return ResearchCopywriterResult(research=research, draft=draft)
