"""Parse one Markdown file into the canonical content request or publish-ready draft."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

from markdown_it import MarkdownIt
from pydantic import Field, model_validator

from .ai.models import (
    ContentMode,
    ContentRequest,
    ContentTask,
    DraftPost,
    GenerationMetadata,
    StrictModel,
    TokenUsage,
)
from .critics import RuleCritic
from .platform import EventState, RunStep, SQLiteRunStore
from .policy import AccountPolicy, load_policy
from .workflow import DraftOrigin, WorkflowState

MAX_MARKDOWN_BYTES = 100_000
ALLOWED_SUFFIXES = {".md", ".markdown"}
ALLOWED_FRONT_MATTER = {"mode", "task", "pipeline"}
SECRET_FRONT_MATTER = {
    "access_token",
    "api_key",
    "app_secret",
    "cookie",
    "password",
    "refresh_token",
    "token",
}

GENERATE_TEMPLATE = """---
mode: generate
task: create
pipeline: full
---

# Topic

Ba cách học Python hiệu quả cho người mới

# Instructions

Viết thành checklist ba bước, giọng thân thiện, có ví dụ thực tế và kết thúc
bằng một câu hỏi.

# Source

Phần này không bắt buộc với `task: create`. Với `repurpose`, `rewrite` hoặc
`summarize`, hãy đặt toàn bộ tài liệu nguồn tại đây.
"""

PUBLISH_TEMPLATE = """---
mode: publish
task: create
pipeline: full
---

# Topic

Học Python cho người mới

# Content

Bạn không cần học mọi thứ cùng lúc.

1. Chọn một bài toán nhỏ.
2. Viết phiên bản đầu tiên.
3. Sửa dựa trên lỗi thật.

> Tiến bộ đến từ vòng lặp thực hành, không phải từ việc đọc thật nhiều.

Bạn đang muốn tự động hóa bài toán nào đầu tiên?

#HocPython #Python
"""


class ContentMarkdownError(ValueError):
    """A safe, user-actionable Markdown validation error."""


class ContentMarkdownDocument(StrictModel):
    """Parsed, immutable handoff from one uploaded Markdown file."""

    source_name: str = Field(min_length=1, max_length=255)
    mode: ContentMode
    task: ContentTask
    pipeline: Literal["draft", "full"] = "full"
    topic: str = Field(min_length=1, max_length=500)
    instructions: str = Field(default="", max_length=5_000)
    source_content: str = Field(default="", max_length=30_000)
    final_content: str = Field(default="", max_length=30_000)
    sections: dict[str, str] = Field(default_factory=dict)
    block_types: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_mode_contract(self) -> ContentMarkdownDocument:
        if self.mode == ContentMode.PUBLISH and not self.final_content:
            raise ValueError("mode 'publish' requires a '# Content' section")
        if self.mode == ContentMode.GENERATE and self.final_content:
            raise ValueError("mode 'generate' must use '# Source', not '# Content'")
        if self.mode == ContentMode.GENERATE:
            ContentRequest.from_inputs(
                topic=self.topic,
                instructions=self.instructions,
                source_content=self.source_content,
                source_name=self.source_name if self.source_content else None,
                task=self.task,
                mode=self.mode,
            )
        return self

    def to_content_request(self) -> ContentRequest:
        content = self.source_content if self.mode == ContentMode.GENERATE else self.final_content
        return ContentRequest.from_inputs(
            topic=self.topic,
            instructions=self.instructions,
            source_content=content,
            source_name=self.source_name if content else None,
            task=self.task,
            mode=self.mode,
        )


class MarkdownImportResult(StrictModel):
    run_id: UUID
    draft_id: UUID
    workflow_state: WorkflowState
    policy: AccountPolicy
    request: ContentRequest
    hard_rule_passed: bool
    hard_rule_messages: list[str] = Field(default_factory=list)


def _parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ContentMarkdownError(
            "Markdown must start with front matter containing mode, task, and pipeline."
        )
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ContentMarkdownError("Markdown front matter is missing its closing '---'.") from exc

    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing], start=2):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            raise ContentMarkdownError(
                f"Front matter line {line_number} must use 'key: value'."
            )
        raw_key, raw_value = stripped.split(":", 1)
        key = raw_key.strip().casefold().replace("-", "_")
        value = raw_value.strip().strip("\"'")
        if key in SECRET_FRONT_MATTER:
            raise ContentMarkdownError(
                f"Secret field '{raw_key.strip()}' is forbidden in content Markdown."
            )
        if key not in ALLOWED_FRONT_MATTER:
            allowed = ", ".join(sorted(ALLOWED_FRONT_MATTER))
            raise ContentMarkdownError(
                f"Unknown front matter field '{raw_key.strip()}'. Allowed fields: {allowed}."
            )
        if not value:
            raise ContentMarkdownError(f"Front matter field '{raw_key.strip()}' cannot be empty.")
        if key in metadata:
            raise ContentMarkdownError(f"Duplicate front matter field '{raw_key.strip()}'.")
        metadata[key] = value
    body = "\n".join(lines[closing + 1 :]).strip()
    return metadata, body


def _normalized_heading(value: str) -> str | None:
    ascii_heading = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
        if not unicodedata.combining(character)
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", ascii_heading).strip()
    aliases = {
        "topic": "topic",
        "subject": "topic",
        "chu de": "topic",
        "instructions": "instructions",
        "instruction": "instructions",
        "writing brief": "instructions",
        "brief": "instructions",
        "yeu cau": "instructions",
        "source": "source",
        "source content": "source",
        "reference": "source",
        "reference material": "source",
        "noi dung nguon": "source",
        "content": "content",
        "final content": "content",
        "final post": "content",
        "post": "content",
        "bai viet": "content",
    }
    return aliases.get(normalized)


def _parse_sections(body: str) -> tuple[dict[str, str], list[str]]:
    parser = MarkdownIt("commonmark", {"html": False})
    tokens = parser.parse(body)
    body_lines = body.splitlines()
    headings: list[tuple[str, int, int]] = []

    for index, token in enumerate(tokens):
        if token.type != "heading_open" or token.map is None:
            continue
        inline = tokens[index + 1] if index + 1 < len(tokens) else None
        if inline is None or inline.type != "inline":
            continue
        section_name = _normalized_heading(inline.content)
        if section_name:
            headings.append((section_name, int(token.map[0]), int(token.map[1])))

    sections: dict[str, str] = {}
    for index, (name, _, content_start) in enumerate(headings):
        if name in sections:
            raise ContentMarkdownError(f"Markdown contains more than one '{name}' section.")
        content_end = headings[index + 1][1] if index + 1 < len(headings) else len(body_lines)
        sections[name] = "\n".join(body_lines[content_start:content_end]).strip()

    block_types: set[str] = set()
    interesting = {
        "blockquote_open": "quote",
        "bullet_list_open": "bullet_list",
        "fence": "code_block",
        "heading_open": "heading",
        "image": "image",
        "ordered_list_open": "ordered_list",
    }
    for token in tokens:
        if token.type in interesting:
            block_types.add(interesting[token.type])
        for child in token.children or []:
            if child.type in interesting:
                block_types.add(interesting[child.type])
    return sections, sorted(block_types)


def parse_content_markdown(
    content: bytes | str,
    *,
    source_name: str,
) -> ContentMarkdownDocument:
    """Validate and parse one UTF-8 Markdown file without rendering raw HTML."""

    suffix = Path(source_name).suffix.casefold()
    if suffix not in ALLOWED_SUFFIXES:
        raise ContentMarkdownError("Content file must use the .md or .markdown extension.")
    if isinstance(content, bytes):
        if len(content) > MAX_MARKDOWN_BYTES:
            raise ContentMarkdownError("Content Markdown is larger than 100 KB.")
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ContentMarkdownError("Content Markdown must be encoded as UTF-8.") from exc
    else:
        text = content.removeprefix("\ufeff")
        if len(text.encode("utf-8")) > MAX_MARKDOWN_BYTES:
            raise ContentMarkdownError("Content Markdown is larger than 100 KB.")
    metadata, body = _parse_front_matter(text)
    sections, block_types = _parse_sections(body)

    missing = [name for name in ("mode", "task") if name not in metadata]
    if missing:
        raise ContentMarkdownError(
            "Markdown front matter is missing: " + ", ".join(missing) + "."
        )
    try:
        mode = ContentMode(metadata["mode"].casefold())
    except ValueError as exc:
        raise ContentMarkdownError("mode must be 'generate' or 'publish'.") from exc
    try:
        task = ContentTask(metadata["task"].casefold())
    except ValueError as exc:
        choices = ", ".join(task.value for task in ContentTask)
        raise ContentMarkdownError(f"task must be one of: {choices}.") from exc
    pipeline = metadata.get("pipeline", "full").casefold()
    if pipeline not in {"draft", "full"}:
        raise ContentMarkdownError("pipeline must be 'draft' or 'full'.")
    topic = sections.get("topic", "").strip()
    if not topic:
        raise ContentMarkdownError("Markdown requires a non-empty '# Topic' section.")

    try:
        return ContentMarkdownDocument(
            source_name=Path(source_name).name,
            mode=mode,
            task=task,
            pipeline=pipeline,
            topic=topic,
            instructions=sections.get("instructions", ""),
            source_content=sections.get("source", "") if mode == ContentMode.GENERATE else "",
            final_content=sections.get("content", "") if mode == ContentMode.PUBLISH else "",
            sections=sections,
            block_types=block_types,
            metadata=metadata,
        )
    except ValueError as exc:
        raise ContentMarkdownError(str(exc)) from exc


def import_publish_document(
    store: SQLiteRunStore,
    *,
    policy_path: str | Path,
    document: ContentMarkdownDocument,
) -> MarkdownImportResult:
    """Create an auditable manual draft while preserving every publisher guard."""

    if document.mode != ContentMode.PUBLISH:
        raise ContentMarkdownError("Only mode 'publish' can be imported as a final draft.")
    policy = load_policy(policy_path)
    if not policy.active:
        raise ContentMarkdownError(f"Account '{policy.account_id}' is inactive.")
    request = document.to_content_request()
    run_id = uuid4()
    publish_lines = document.final_content.splitlines()
    trailing_hashtags: list[str] = []
    if publish_lines:
        last_nonempty = next(
            (index for index in range(len(publish_lines) - 1, -1, -1) if publish_lines[index].strip()),
            None,
        )
        if last_nonempty is not None:
            candidate = publish_lines[last_nonempty].strip()
            tokens = candidate.split()
            if tokens and all(re.fullmatch(r"#[^\s#]+", token) for token in tokens):
                trailing_hashtags = tokens
                del publish_lines[last_nonempty]
    publish_body = "\n".join(publish_lines).strip()
    draft = DraftPost(
        brief_id=uuid4(),
        request_id=request.request_id,
        topic=request.topic,
        account_id=policy.account_id,
        platform=policy.platform,
        content=publish_body,
        hashtags=trailing_hashtags,
        call_to_action="",
        policy_constraints_applied=list(policy.constraints),
        metadata=GenerationMetadata(
            provider="operator",
            model="markdown-import-v1",
            role="operator",
            prompt_version="content-markdown-v1",
            provider_sdk="local/1",
            latency_ms=0,
            usage=TokenUsage(),
            generated_at=datetime.now(UTC),
        ),
    )
    rule_result = RuleCritic().evaluate(draft=draft, policy=policy)
    needs_review = policy.publishing.approval_required or not rule_result.passed
    workflow_state = WorkflowState.HUMAN_REVIEW if needs_review else WorkflowState.PASSED

    store.start_run(
        run_id=run_id,
        topic=request.topic,
        policy=policy,
        source_path=policy_path,
        request=request,
    )
    store.record_event(run_id=run_id, step=RunStep.RUN, state=EventState.STARTED)
    store.record_event(run_id=run_id, step=RunStep.POLICY, state=EventState.COMPLETED)
    store.save_artifact(
        run_id=run_id,
        kind="draft_post",
        entity_id=draft.draft_id,
        artifact=draft,
    )
    store.save_draft_revision(
        run_id=run_id,
        draft=draft,
        revision=0,
        origin=DraftOrigin.MARKDOWN_IMPORT.value,
    )
    store.record_event(
        run_id=run_id,
        step=RunStep.COPYWRITER,
        state=EventState.COMPLETED,
        provider="operator",
        model="markdown-import-v1",
    )
    store.create_workflow(
        run_id=run_id,
        current_draft_id=draft.draft_id,
        state=workflow_state.value,
    )
    if needs_review:
        store.record_event(
            run_id=run_id,
            step=RunStep.HUMAN_REVIEW,
            state=EventState.COMPLETED,
            error_code=None if rule_result.passed else "hard_policy_review_required",
            error_message=None if rule_result.passed else "; ".join(rule_result.messages()),
        )
    store.complete_run(run_id)
    store.record_event(run_id=run_id, step=RunStep.RUN, state=EventState.COMPLETED)
    return MarkdownImportResult(
        run_id=run_id,
        draft_id=draft.draft_id,
        workflow_state=workflow_state,
        policy=policy,
        request=request,
        hard_rule_passed=rule_result.passed,
        hard_rule_messages=rule_result.messages(),
    )


def metadata_summary(document: ContentMarkdownDocument) -> Mapping[str, str]:
    """Small UI-friendly view that deliberately excludes uploaded body content."""

    return {
        "Mode": document.mode.value,
        "Task": document.task.value,
        "Pipeline": document.pipeline,
        "Topic": document.topic,
        "Blocks": ", ".join(document.block_types) or "paragraph",
    }
