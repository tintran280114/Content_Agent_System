"""Callable Research and Copywriter interfaces for Tín's orchestrator."""

from __future__ import annotations

from typing import Any

from ..critics import RuleCriticResult
from .base import StructuredProvider
from .models import (
    ContentRequest,
    ContentTask,
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
    build_copywriter_messages,
    build_critic_messages,
    build_research_messages,
    build_rewrite_messages,
)


class ResearchAgent:
    def __init__(self, provider: StructuredProvider) -> None:
        self.provider = provider

    def run(
        self,
        *,
        policy: Any,
        request: ContentRequest | None = None,
        topic: str | None = None,
        instructions: str = "",
        source_content: str = "",
        source_name: str | None = None,
        task: ContentTask | str = ContentTask.CREATE,
    ) -> ResearchBrief:
        content_request = request or ContentRequest.from_inputs(
            topic=topic or "",
            instructions=instructions,
            source_content=source_content,
            source_name=source_name,
            task=task,
        )
        policy_context = PolicyContext.from_policy(policy)
        response = self.provider.generate(
            messages=build_research_messages(content_request, policy_context),
            response_model=ResearchPayload,
            role="research",
            prompt_version=RESEARCH_PROMPT_VERSION,
        )
        return ResearchBrief(
            **response.output.model_dump(),
            request_id=content_request.request_id,
            topic=content_request.topic,
            account_id=policy_context.account_id,
            metadata=response.metadata,
        )


class CopywriterAgent:
    def __init__(self, provider: StructuredProvider) -> None:
        self.provider = provider

    def run(
        self,
        *,
        research: ResearchBrief,
        policy: Any,
        request: ContentRequest | None = None,
    ) -> DraftPost:
        policy_context = PolicyContext.from_policy(policy)
        if policy_context.account_id != research.account_id:
            raise ValueError("policy account_id must match research account_id")
        content_request = request or ContentRequest(
            request_id=research.request_id or research.brief_id,
            topic=research.topic,
        )
        if research.request_id and content_request.request_id != research.request_id:
            raise ValueError("content request_id must match research request_id")
        response = self.provider.generate(
            messages=build_copywriter_messages(research, policy_context, content_request),
            response_model=DraftPayload,
            role="copywriter",
            prompt_version=COPYWRITER_PROMPT_VERSION,
        )
        return DraftPost(
            **response.output.model_dump(),
            brief_id=research.brief_id,
            request_id=content_request.request_id,
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
        request: ContentRequest | None = None,
        research: ResearchBrief | None = None,
    ) -> CriticResult:
        policy_context = PolicyContext.from_policy(policy)
        if policy_context.account_id != draft.account_id:
            raise ValueError("policy account_id must match draft account_id")
        if rule_result.draft_id != str(draft.draft_id):
            raise ValueError("rule result draft_id must match draft draft_id")
        if request and draft.request_id and request.request_id != draft.request_id:
            raise ValueError("content request_id must match draft request_id")
        if research and research.brief_id != draft.brief_id:
            raise ValueError("research brief_id must match draft brief_id")
        response = self.provider.generate(
            messages=build_critic_messages(
                draft,
                policy_context,
                rule_result,
                request=request,
                research=research,
            ),
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
        request: ContentRequest | None = None,
    ) -> DraftPost:
        if rewrite_number not in {1, 2}:
            raise ValueError("rewrite_number must be 1 or 2")
        policy_context = PolicyContext.from_policy(policy)
        if not (policy_context.account_id == research.account_id == draft.account_id):
            raise ValueError("policy, research, and draft account_id values must match")
        if critic.draft_id != draft.draft_id:
            raise ValueError("critic draft_id must match the draft being rewritten")
        if request and draft.request_id and request.request_id != draft.request_id:
            raise ValueError("content request_id must match draft request_id")
        response = self.provider.generate(
            messages=build_rewrite_messages(
                brief=research,
                draft=draft,
                critic=critic,
                policy=policy_context,
                rewrite_number=rewrite_number,
                request=request,
            ),
            response_model=DraftPayload,
            role="copywriter",
            prompt_version=REWRITE_PROMPT_VERSION,
        )
        return DraftPost(
            **response.output.model_dump(),
            brief_id=research.brief_id,
            request_id=request.request_id if request else draft.request_id,
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
    instructions: str = "",
    source_content: str = "",
    source_name: str | None = None,
    task: ContentTask | str = ContentTask.CREATE,
) -> ResearchCopywriterResult:
    """One-call vertical-slice interface for the shared orchestrator."""

    request = ContentRequest.from_inputs(
        topic=topic,
        instructions=instructions,
        source_content=source_content,
        source_name=source_name,
        task=task,
    )
    research = ResearchAgent(research_provider).run(request=request, policy=policy)
    draft = CopywriterAgent(copywriter_provider).run(
        research=research,
        policy=policy,
        request=request,
    )
    return ResearchCopywriterResult(research=research, draft=draft)
