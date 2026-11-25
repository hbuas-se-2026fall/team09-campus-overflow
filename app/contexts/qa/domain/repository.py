from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.bounty import Bounty, PointsEntry
from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.question import Question, QuestionStatus
from app.contexts.qa.domain.tag import _MAX_TAGS_PER_QUESTION, Tag
from app.contexts.qa.domain.vote import Vote, VoteTarget
from app.shared.errors import DomainValidationError
from app.shared.text_validation import reject_unsafe_text

# F02/D5：检索词长度上限。独立常量，不复用 _TITLE_MAX_LENGTH——两者当前同为 100
# 是巧合，标题上限将来调整时搜索口径不应跟着变。
_MAX_QUERY_LENGTH = 100


class QuestionSort(StrEnum):
    """列表排序口径（US-Q02 + 1.3 L161-164，v3 裁定 #4：迭代 2 实现）。"""

    LATEST = "latest"  # 发布时间新→旧（默认）
    VOTES = "votes"  # 净票数高→低（v3 裁定 #1：up − down）


@dataclass(frozen=True, slots=True)
class QuestionFilter:
    """列表筛选条件（F01/US-Q07）；空条件等价于不筛选（向后兼容，D1 裁定）。

    - tags：原始显示名，构造时经 Tag 校验并归并为 key（大小写不敏感，与
      tags.key 列同源，D4 裁定）；同名 key 去重，重复传参不报错也不重复计数；
      去重后数量复用每题标签上限（评审加固：AND 语义下超限必然空结果，
      直接 422 拒绝，防超长 EXISTS 链）；
    - 时间闭区间 [created_from, created_to]，必须带时区（D2 裁定，naive → 422）；
    - status=None 表示全部（D1）；
    - q：标题 + 正文的模糊检索词（F02）；strip 后空串归一为 None（等价于不传），
      非空时至多 100 字（D5，超限 422），不允许制表符/换行（D7 裁定），
      大小写不敏感由 SQL ILIKE 保证。
    """

    tags: tuple[str, ...] = ()
    status: QuestionStatus | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    q: str | None = None
    course_id: UUID | None = None
    tag_keys: tuple[str, ...] = field(init=False, default=())

    def __post_init__(self) -> None:
        if self.q is not None:
            normalized_q = self.q.strip()
            if not normalized_q:
                # 纯空白等价于不传（F02：空 q 不进入 SQL 条件）
                object.__setattr__(self, "q", None)
            else:
                # D7：shared 的 reject_unsafe_text 有意放行 \t\n\r（正文需要），
                # 检索词单独收紧，不改 shared 签名
                if any(ch in normalized_q for ch in "\t\n\r"):
                    raise DomainValidationError("搜索关键词不能包含制表符或换行符")
                reject_unsafe_text(normalized_q, field_name="搜索关键词")
                if len(normalized_q) > _MAX_QUERY_LENGTH:
                    raise DomainValidationError(
                        f"搜索关键词至多 {_MAX_QUERY_LENGTH} 字，"
                        f"实际 {len(normalized_q)} 字"
                    )
                # 回写规范化值，避免 infra 拿到带首尾空白的 q 去拼 LIKE
                object.__setattr__(self, "q", normalized_q)

        for name, value in (
            ("created_from", self.created_from),
            ("created_to", self.created_to),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise DomainValidationError(f"{name} 必须包含时区信息")
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from > self.created_to
        ):
            raise DomainValidationError("created_from 不能晚于 created_to")

        keys: list[str] = []
        seen: set[str] = set()
        for raw in self.tags:
            # 空串/非法字符由 Tag 抛 DomainValidationError，经全局映射落 422（C2）
            key = Tag(raw).key
            if key not in seen:
                seen.add(key)
                keys.append(key)
        if len(keys) > _MAX_TAGS_PER_QUESTION:
            # AND 语义：每题标签 ≤5，超限必然空结果——域内直接拒绝，不进 SQL
            raise DomainValidationError(
                f"标签筛选至多 {_MAX_TAGS_PER_QUESTION} 个，实际 {len(keys)} 个"
            )
        object.__setattr__(self, "tag_keys", tuple(keys))


class QuestionRepository(Protocol):
    """问题聚合持久化端口：domain 定义接口，infrastructure 实现。

    权衡注记（有意保留宽接口）：本 Protocol 5 个方法，读/写用例各只用其中 1~2 个，
    测试 fake 因此需实现全部方法。课程规模下不拆 ``QuestionReader`` /
    ``QuestionWriter``——拆分只增加类型、装配与 import 成本，收益低于维护成本；
    若后续端口方法继续膨胀（如 F03 相关推荐再叠加数个查询），再按用例收窄。
    """

    async def add(self, question: Question) -> None:
        """新增问题（聚合整体落库）。"""
        ...

    async def update(self, question: Question) -> None:
        """更新既有问题聚合（采纳双写 accepted_answer_id，US-V03 迭代 3）。"""
        ...

    async def get_by_id(
        self,
        question_id: UUID,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Question | None:
        """按问题 ID 查询；for_update=True 时对问题行加写锁（须在事务内持有至提交）。

        默认过滤软删除行；include_deleted=True 仅限删除用例判定作者幂等 204 vs 非作者 404。
        """
        ...

    async def soft_delete(self, question_id: UUID, deleted_at: datetime) -> bool:
        """条件软删除问题（F13）：由未删迁移为已删返回 True；已删返回 False；
        不存在抛 QuestionNotFoundError；已有采纳答案抛 AcceptedAnswerCannotDeleteError。
        """
        ...

    async def list_related(self, question_id: UUID, limit: int) -> list[Question]:
        """列出与指定问题标签共现的相关问题（F03，只读）。

        排序规则：标签重合数降序 → 净票数降序 → created_at 降序 → id 降序；
        排除自身；无标签返回空列表；不过滤关闭态（D3 裁定）。
        """
        ...

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        sort: QuestionSort = QuestionSort.LATEST,
        filters: QuestionFilter | None = None,
    ) -> tuple[list[Question], int]:
        """分页列出问题，返回（当前页聚合列表，总条数）。

        sort=latest：按发布时间新→旧；sort=votes：按净票数高→低（v3 裁定 #4）。
        两种排序均以 id 作确定性 tiebreaker，跨页不重复/不漏项。
        filters 的 COUNT 与当前页必须同口径（F01，避免 total 与结果不自洽）。
        """
        ...


class AnswerRepository(Protocol):
    """回答聚合持久化端口：domain 定义接口，infrastructure 实现（迭代 2）。"""

    async def add(self, answer: Answer) -> None:
        """新增回答（聚合整体落库）。"""
        ...

    async def update(self, answer: Answer) -> None:
        """更新既有回答聚合的采纳态（仅翻转 is_accepted，US-V03 迭代 3）。"""
        ...

    async def update_body(self, answer: Answer) -> None:
        """F12：仅更新回答正文（与采纳条件更新分离，不触碰 is_accepted）。"""
        ...

    async def update_verification(self, answer: Answer) -> None:
        """F15：仅更新回答认证状态（与正文/采纳更新职责隔离，ISP）。"""
        ...

    async def get_by_id(
        self, answer_id: UUID, *, include_deleted: bool = False
    ) -> Answer | None:
        """按回答 ID 查询（投票/采纳/编辑/删除定位回答使用）。

        默认过滤自身已删或所属问题已删的回答；include_deleted=True 仅限删除用例读取。
        """
        ...

    async def soft_delete(self, answer_id: UUID, deleted_at: datetime) -> bool:
        """条件软删除回答（F13）：父问题活跃且未采纳由未删迁移为已删返回 True；
        父问题活跃且已删返回 False；不存在抛 AnswerNotFoundError；
        父问题已删抛 QuestionNotFoundError；已采纳抛 AcceptedAnswerCannotDeleteError。
        """
        ...

    async def list_by_question(self, question_id: UUID) -> list[Answer]:
        """列出问题的全部回答，按 D2 定稿排序：已采纳恒最前，其余按净票数降序。

        净票数为读时聚合（v3 裁定 #1：up − down），重建时填入 Answer.votes_count。
        """
        ...


class VoteRepository(Protocol):
    """投票持久化端口：domain 定义接口，infrastructure 实现（迭代 2）。"""

    async def find_by_user_target(
        self, user_id: UUID, target_type: VoteTarget, target_id: UUID
    ) -> Vote | None:
        """查用户对某目标的既有票（不分方向）：一人一票的事前检查。"""
        ...

    async def add(self, vote: Vote) -> None:
        """落一票。并发重复票由复合唯一索引兜底（IntegrityError → 409）。"""
        ...


class CommentRepository(Protocol):
    """评论持久化端口：domain 定义接口，infrastructure 实现（迭代 3，US-C01 / F14）。"""

    async def add(self, comment: Comment) -> None:
        """新增评论（多态 target：题评挂 Question、答评挂 Answer）。"""
        ...

    async def get_by_id(self, comment_id: UUID) -> Comment | None:
        """按评论 ID 查询（F14 校验二级回复的父评论存在性、归属与层级）。"""
        ...

    async def list_by_target(
        self, target_type: CommentTarget, target_id: UUID
    ) -> list[Comment]:
        """列出某目标的全部评论，按时间正序（1.3 功能域 9：答评按时间正序排列）。"""
        ...


class UserActivityRepository(Protocol):
    """用户活跃统计端口（F06 徽章）：只读聚合，不落表。"""

    async def answer_stats(self, user_id: UUID) -> tuple[int, int]:
        """返回（回答总数，被采纳回答数）。"""
        ...

    async def active_dates(self, user_id: UUID) -> list[date]:
        """返回该用户有内容行为的自然日（Asia/Shanghai，去重升序）。

        活跃 = 发帖/回答/评论/投票（D11），不含登录。
        """
        ...


class PointsRepository(Protocol):
    """可消费积分端口（F07，D12）：教师开户/扣减/入账/流水，均同事务。"""

    async def ensure_teacher_account(self, user_id: UUID) -> int:
        """惰性开户并返回余额；首次开户同事务写入初始授予流水（幂等）。"""
        ...

    async def deduct(self, user_id: UUID, amount: int) -> bool:
        """条件扣减（余额 ≥ amount 才成功）；False 表示余额不足。"""
        ...

    async def credit(self, user_id: UUID, amount: int) -> None:
        """入账（无账户时以 0 余额开户，不发放教师初始额度）。"""
        ...

    async def append(self, user_id: UUID, entry: PointsEntry) -> bool:
        """追加流水；同 (source, event_id) 已存在返回 False（幂等）。"""
        ...

    async def balance(self, user_id: UUID) -> int:
        """当前余额（无账户 0）。"""
        ...

    async def list_entries(self, user_id: UUID) -> list[PointsEntry]:
        """按 occurred_at DESC, id DESC 返回该用户全部积分流水。"""
        ...



class BountyRepository(Protocol):
    """悬赏端口（F07，D13）：同题仅一个 open 悬赏。"""

    async def add(self, bounty: Bounty) -> None:
        """插入悬赏；已有 open 悬赏时抛 BountyAlreadyActiveError。"""
        ...

    async def get_active(self, question_id: UUID) -> Bounty | None:
        """读取该问题进行中的悬赏。"""
        ...

    async def settle(self, question_id: UUID) -> Bounty | None:
        """open→settled 条件更新；返回被结算的悬赏，无 open 返回 None（只成功一次）。"""
        ...

    async def refund(self, question_id: UUID) -> Bounty | None:
        """open→refunded 条件更新；返回被退款的悬赏，无 open 返回 None（只成功一次）。"""
        ...


class TagCatalogRepository(Protocol):
    """TagCatalog 持久化端口（迭代 4，US-T01/T02）：目录 = tags 表全局唯一。

    get-or-create 语义（随用随建，T02）：同名（lower 归一键）命中既有行则复用，
    未命中则插入；并发双插由 lower(name) 唯一索引兜底，实现内 savepoint 重试。
    """

    async def get_or_create(self, tag: Tag) -> Tag:
        """按归并键取目录内标签，不存在则创建（幂等）。"""
        ...

    async def list_all(self) -> list[Tag]:
        """列出目录全部标签（显示名 = 建目时的规范名）。"""
        ...


@dataclass(frozen=True, slots=True)
class CourseLeaderboardEntry:
    """课程贡献排行榜条目（F17：基于课程内活跃问题采纳数与净赞数只读聚合）。"""

    user_id: UUID
    accepted_count: int
    net_votes: int
    answer_count: int
    rank: int


class CourseLeaderboardRepository(Protocol):
    """课程贡献榜单只读查询端口（ISP：独立于 QuestionRepository）。"""

    async def list_top_contributors(
        self, course_id: UUID, *, limit: int
    ) -> list[CourseLeaderboardEntry]:
        """按采纳数降序、净赞数降序聚合课程答主贡献排名。"""
        ...
