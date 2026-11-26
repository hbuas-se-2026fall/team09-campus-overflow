import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class QuestionModel(Base):
    """questions 表：Question 聚合根的持久化（迭代 1：标题 + 正文 + 作者引用）。"""

    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # PG 不自动给外键建索引：CASCADE 删用户需按 author_id 找子行，故显式索引
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # 2.5 列表按发布时间新→旧排序，索引提前就位
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    # 采纳引用（US-V03 双写的本侧）：FK→answers SET NULL——采纳答案被删则引用自动清空；
    # 与 answers.question_id 构成环形引用，PG 允许（两列均可空/后写），插入序无约束冲突
    accepted_answer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("answers.id", ondelete="SET NULL"),
        nullable=True,
    )
    # 关闭态（US-Q08，迭代 5）：open/closed；server_default 让存量行随迁移自动归 open
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    # 软删除时间戳（F13）：NULL 表示活跃，非 NULL 表示已软删除（不级联写子表）
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 课程关联（F17）：可空 UUID（零跨上下文外键，存量问题 NULL）
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )

    __table_args__ = (
        # F09：F02 的 ILIKE '%q%' 标题/正文模糊搜索走 pg_trgm GIN；模型同步声明防
        # 后续 alembic --autogenerate 误判为漂移（迁移内显式 CREATE EXTENSION pg_trgm）
        Index(
            "ix_questions_title_trgm",
            "title",
            postgresql_using="gin",
            postgresql_ops={"title": "gin_trgm_ops"},
        ),
        Index(
            "ix_questions_body_trgm",
            "body",
            postgresql_using="gin",
            postgresql_ops={"body": "gin_trgm_ops"},
        ),
    )


class AnswerModel(Base):
    """answers 表：Answer 聚合根的持久化（迭代 2）。

    is_accepted 本迭代恒 False，列先行落库，采纳行为随分支 2 的 accept() 使用。
    """

    __tablename__ = "answers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # CASCADE：删问题连删其回答；显式索引供 list_by_question 与 CASCADE 反查
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_accepted: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 软删除时间戳（F13）：NULL 表示活跃，非 NULL 表示已软删除
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 教师/助教/管理员认证回答状态（F15 D2/D3）
    is_teacher_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", name="fk_answers_verified_by", ondelete="SET NULL"),
        nullable=True,
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # 一题一采纳的库级兜底（AC-12 暴力测试发现应用层检查存在并发竞态）：
        # 部分唯一索引——同一 question_id 下 is_accepted=true 至多一行
        Index(
            "uq_answers_one_accepted_per_question",
            "question_id",
            unique=True,
            postgresql_where=text("is_accepted"),
        ),
    )


class VoteModel(Base):
    """votes 表：Vote 值对象的持久化（迭代 2，多态目标 question/answer）。

    一人一票 = 复合唯一索引 (user_id, target_type, target_id) 不分方向（v3 裁定 #5）；
    target_id 为多态引用（question 或 answer），不做库级外键，存在性由用例检查。
    """

    __tablename__ = "votes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_type: Mapped[str] = mapped_column(String(10), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    direction: Mapped[str] = mapped_column(String(4), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # 事前检查（find_by_user_target）与并发兜底同用此索引
        Index("uq_votes_user_target", "user_id", "target_type", "target_id", unique=True),
        # 目标净票数聚合（answers 排序 / 列表 votes 排序）按 target 反查
        Index("ix_votes_target", "target_type", "target_id"),
    )


class CommentModel(Base):
    """comments 表：Comment 实体持久化（迭代 3，US-C01 / F14 二级回复）。

    多态 target（题评挂 question / 答评挂 answer），与 votes 同模式不做库级外键，
    存在性由用例检查；F14 新增可空自引用 parent_id（RESTRICT 防误删父评论，
    CHECK 禁止自引用，二级上限由领域层校验）。
    """

    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(String(10), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("comments.id", name="fk_comments_parent_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # 评论列表按 (target, created_at 正序) 读取（1.3 功能域 9）
        Index("ix_comments_target_created", "target_type", "target_id", "created_at"),
        # F14：父评论反查索引与禁止自引用库级兜底
        Index("ix_comments_parent_id", "parent_id"),
        CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="ck_comments_no_self_parent",
        ),
    )


class TagModel(Base):
    """tags 表：TagCatalog 目录行（迭代 4，US-T01/T02）。

    name 存建目时规范名（显示名）；key 存归并键（domain Tag.key，应用计算）。
    同名唯一 = key 列唯一索引——键由应用单侧计算并落列，**不用 PG lower(name) 表达式索引**：
    Python str.lower 对个别码位（如 İ U+0130）做全映射（→i̇ 两码位），PG lower 做简单
    映射（→i 一码位），两侧不一致会让"查不到→插入撞索引→重查仍查不到"成死路
    （第九路 X-06 实证 400）。key 单源后应用与库判定恒等。
    """

    __tablename__ = "tags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # 归并键：value.lower() 可能全映射膨胀（≤2 倍），上限取 100
    key: Mapped[str] = mapped_column(String(100), nullable=False)

    __table_args__ = (Index("uq_tags_key", "key", unique=True),)


class QuestionTagModel(Base):
    """question_tags 关联表：问题↔标签多对多（迭代 4，Q03）。

    复合主键天然防同一 (question, tag) 重复挂接；两侧 FK CASCADE——
    删问题或删标签都自动清理关联行（目录孤儿标签保留，v6 定稿：随用随建不回收）。
    """

    __tablename__ = "question_tags"

    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tags.id", ondelete="CASCADE"),
        primary_key=True,
    )

    __table_args__ = (
        # 按标签反查问题（未来发现域）与列表批量装配 tags 的访问路径
        Index("ix_question_tags_tag", "tag_id"),
    )


class PointsAccountModel(Base):
    """可消费积分账户（F07/D12）：与声誉账本分离。"""

    __tablename__ = "points_accounts"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (
        # 库层兜底：应用层条件扣减之外，任何路径都不得把余额写成负数
        CheckConstraint(
            "balance >= 0", name="ck_points_accounts_balance_non_negative"
        ),
    )


class PointLedgerModel(Base):
    """积分流水（只追加）：(source, event_id) 唯一保证同一事件恰记一次。"""

    __tablename__ = "point_ledgers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        Index("uq_point_ledgers_source_event", "source", "event_id", unique=True),
    )


class QuestionBountyModel(Base):
    """教师悬赏（F07/D13）：同题仅一个 open 悬赏（部分唯一索引）。"""

    __tablename__ = "question_bounties"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    teacher_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    settled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_question_bounties_open",
            "question_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
    )


class ReportModel(Base):
    """内容举报表（F18）：多态 target_type 仅限 question/answer，零跨上下文外键。"""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    resolution_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_reports_pending_reporter_target",
            "reporter_id",
            "target_type",
            "target_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_reports_status_created", "status", "created_at"),
        Index("ix_reports_target", "target_type", "target_id"),
        CheckConstraint(
            "target_type IN ('question', 'answer')",
            name="ck_reports_target_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'resolved', 'dismissed')",
            name="ck_reports_status",
        ),
    )
