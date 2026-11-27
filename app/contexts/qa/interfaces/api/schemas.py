from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contexts.qa.domain.question import QuestionStatus
from app.contexts.qa.domain.report import (
    ReportAction,
    ReportStatus,
    ReportTargetType,
)
from app.shared.errors import DomainValidationError
from app.shared.text_validation import reject_unsafe_text


class AskQuestionRequest(BaseModel):
    """POST /api/v1/questions 请求体。

    str_strip_whitespace 在长度约束之前生效：纯空白标题/正文 strip 后为空 → 422。
    tags 可选（迭代 4，Q03）：schema 只拦原始数量滥用（≤20 松上限）与类型/结构错误
    （数组形 422）；去重后 ≤5、白名单字符等语义校验在领域层（字符串形 422），
    两种 422 形态见 api-contract-notes。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    course_id: UUID | None = None


class PostAnswerRequest(BaseModel):
    """POST /api/v1/questions/{qid}/answers 请求体（US-A01）。

    正文与问题共用 1~5000 字约束；作者只取令牌，绝不取自请求体。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    body: str = Field(min_length=1, max_length=5000)


class EditAnswerRequest(BaseModel):
    """PATCH /api/v1/answers/{id} 请求体（US-A02 / F12）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    body: str = Field(min_length=1, max_length=5000)

    @field_validator("body")
    @classmethod
    def _reject_unsafe_chars(cls, value: str) -> str:
        reject_unsafe_text(value, field_name="回答正文")
        return value


class VoteRequest(BaseModel):
    """投票请求体（US-V01）：direction 枚举即校验，非法值 422。"""

    model_config = ConfigDict(extra="forbid")

    direction: Literal["up", "down"]


class CommentRequest(BaseModel):
    """评论请求体（US-C01 / F14）：正文复用 Body 约束（1~5000 字），
    可选 parent_id 指向一级父评论。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    body: str = Field(min_length=1, max_length=5000)
    parent_id: UUID | None = None


class CommentResponse(BaseModel):
    """评论白名单（平铺按时间正序返回，1.3 功能域 9 / F14 D1）。"""

    id: UUID
    body: str
    author_id: UUID
    author_name: str
    parent_id: UUID | None = None
    created_at: datetime


class QuestionResponse(BaseModel):
    """问题响应白名单：不含任何内部字段。tags/status/course_* 为公开字段。"""

    id: UUID
    title: str
    body: str
    author_id: UUID
    author_name: str
    created_at: datetime
    tags: list[str] = Field(default_factory=list)
    status: QuestionStatus
    course_id: UUID | None = None
    course_name: str | None = None


class QuestionListItem(BaseModel):
    """列表条目白名单：不含正文（正文最长 5000 字，列表页不需要）与任何内部字段（S-12）。

    tags 为迭代 4 新增字段（增量、向后兼容）；course_* 为 F17 新增字段。
    """

    id: UUID
    title: str
    author_id: UUID
    author_name: str
    created_at: datetime
    tags: list[str] = Field(default_factory=list)
    status: QuestionStatus
    course_id: UUID | None = None
    course_name: str | None = None


class TagListResponse(BaseModel):
    """标签目录响应（US-T01，访客可用）：码点序、同名唯一（T02）。"""

    tags: list[str]


class QuestionListResponse(BaseModel):
    """分页契约：total_pages = ceil(total/page_size)，空库为 0。"""

    items: list[QuestionListItem]
    total: int
    page: int
    page_size: int
    total_pages: int


class AnswerResponse(BaseModel):
    """回答白名单（US-A01/A05 / F15）：votes 为净票数（v3 裁定 #1，可为负）。"""

    id: UUID
    body: str
    author_id: UUID
    author_name: str
    created_at: datetime
    votes: int
    is_accepted: bool
    is_teacher_verified: bool = False
    verified_by_name: str | None = None
    verified_at: datetime | None = None
    comments: list[CommentResponse] = Field(default_factory=list)


class QuestionDetailResponse(BaseModel):
    """详情白名单。

    answers 按 D2 定稿排序（已采纳恒最前 > 净票数降序 > 时间正序）；
    accepted_answer_id 顶层返回便于前端直接定位（v3 裁定 #3）；
    comments 为题评（US-C01，按时间正序）；tags 迭代 1 恒为空列表（分支 3 就位）。
    """

    id: UUID
    title: str
    body: str
    author_id: UUID
    author_name: str
    created_at: datetime
    accepted_answer_id: UUID | None
    tags: list[str] = Field(default_factory=list)
    status: QuestionStatus
    course_id: UUID | None = None
    course_name: str | None = None
    answers: list[AnswerResponse] = Field(default_factory=list)
    comments: list[CommentResponse] = Field(default_factory=list)


class EditQuestionRequest(BaseModel):
    """PATCH /api/v1/questions/{id} 请求体（US-Q08；D6 仅标题+正文；F17 可选 course_id）。

    PATCH 部分更新：title/body/course_id 均可选、至少给一个（模型级校验，缺失即 422 数组形）；
    显式传 course_id: null 可解绑课程。
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=100)
    body: str | None = Field(default=None, min_length=1, max_length=5000)
    course_id: UUID | None = None

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> EditQuestionRequest:
        if (
            self.title is None
            and self.body is None
            and "course_id" not in self.model_fields_set
        ):
            raise DomainValidationError("至少提供 title、body 或 course_id 之一")
        return self


class BadgeResponse(BaseModel):
    """单枚徽章（F06）：稳定 code + 类别/等级/阈值。"""

    model_config = ConfigDict(extra="forbid")

    code: str
    kind: str
    tier: str
    threshold: float


class UserBadgesResponse(BaseModel):
    """GET /api/v1/users/{id}/badges 响应（公开；实时计算）。"""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    answer_count: int
    accepted_count: int
    acceptance_rate: float
    longest_streak_days: int
    badges: list[BadgeResponse]


class BountyCreateRequest(BaseModel):
    """发起悬赏请求体（F07）：金额 1~1,000,000。"""

    model_config = ConfigDict(extra="forbid")

    amount: int = Field(gt=0, le=1_000_000)


class BountyResponse(BaseModel):
    """悬赏白名单响应（F07）。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    question_id: UUID
    teacher_id: UUID
    amount: int
    status: str
    created_at: datetime
    settled_at: datetime | None


class PointEntryResponse(BaseModel):
    """积分流水行（F07 闭环；与 ReputationEntryResponse 字段口吻对齐）。"""

    model_config = ConfigDict(extra="forbid")

    source: str
    event_id: UUID
    delta: int
    reason: str
    occurred_at: datetime


class MyPointsResponse(BaseModel):
    """GET /api/v1/users/me/points 响应。"""

    model_config = ConfigDict(extra="forbid")

    balance: int
    entries: list[PointEntryResponse]


class CourseLeaderboardEntryResponse(BaseModel):
    """课程贡献排行榜条目（F17）。"""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    display_name: str
    accepted_count: int
    net_votes: int
    answer_count: int
    rank: int


class CourseLeaderboardResponse(BaseModel):
    """GET /api/v1/courses/{course_id}/leaderboard 响应（F17）。"""

    model_config = ConfigDict(extra="forbid")

    course_id: UUID
    course_code: str
    course_name: str
    entries: list[CourseLeaderboardEntryResponse]


class CreateReportRequest(BaseModel):
    """POST /api/v1/reports 请求体（F18）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    target_type: ReportTargetType
    target_id: UUID
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def _reject_unsafe_reason(cls, value: str) -> str:
        reject_unsafe_text(value, field_name="举报理由")
        return value


class ResolveReportRequest(BaseModel):
    """POST /api/v1/admin/reports/{report_id}/resolve 请求体（F18）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action: ReportAction
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _reject_unsafe_note(cls, value: str | None) -> str | None:
        if value is not None:
            reject_unsafe_text(value, field_name="处理备注")
        return value


class ReportResponse(BaseModel):
    """举报工单响应白名单（F18）。"""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    reporter_id: UUID
    reporter_name: str
    target_type: ReportTargetType
    target_id: UUID
    target_question_id: UUID | None = None
    target_title: str | None = None
    target_body: str | None = None
    target_is_deleted: bool | None = None
    reason: str
    status: ReportStatus
    resolution_action: ReportAction | None = None
    resolution_note: str | None = None
    resolved_by: UUID | None = None
    resolved_by_name: str | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class ReportListResponse(BaseModel):
    """GET /api/v1/admin/reports 分页响应（F18）。"""

    model_config = ConfigDict(extra="forbid")

    items: list[ReportResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
