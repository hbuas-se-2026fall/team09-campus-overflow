"""编辑问题用例：提问者编辑自己的问题（US-Q08；裁定 D6 仅标题+正文）。"""

from __future__ import annotations

from app.contexts.qa.application.commands import EditQuestionCommand
from app.contexts.qa.application.course_access_policy import (
    ensure_course_question_access,
)
from app.contexts.qa.application.ports import CourseAccessReader
from app.contexts.qa.domain.errors import NotQuestionAuthorError, QuestionNotFoundError
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import QuestionRepository
from app.shared.sentinel import UnsetType


class EditQuestionUseCase:
    """编辑用例：问题不存在→404；非提问者→403；已关闭→409（全冻结裁定）；
    标题/正文校验失败→422（ValueError，由路由映射）；F17 支持变更/解绑课程关联。

    PATCH 部分更新：命令缺省侧沿用既有值合并后再入域方法（标签不可编辑，D6）。
    """

    def __init__(
        self,
        question_repository: QuestionRepository,
        course_reader: CourseAccessReader | None = None,
    ) -> None:
        self._question_repository = question_repository
        self._course_reader = course_reader

    async def execute(self, command: EditQuestionCommand) -> Question:
        # 统一“先锁 Question”单根锁序（F13 D7），闭环编辑与关闭/软删除并发窗口
        question = await self._question_repository.get_by_id(
            command.question_id, for_update=True
        )
        if question is None:
            raise QuestionNotFoundError("问题不存在")
        if question.author_id != command.actor_id:
            raise NotQuestionAuthorError("仅提问者可编辑问题")
        question.ensure_open("编辑")
        if not isinstance(command.course_id, UnsetType) and command.course_id is not None:
            await ensure_course_question_access(
                course_id=command.course_id,
                actor_id=command.actor_id,
                actor_role=command.actor_role,
                course_reader=self._course_reader,
            )
        title_value = command.title if command.title is not None else question.title.value
        body_value = command.body if command.body is not None else question.body.value
        question.edit_title_body(
            title_value=title_value,
            body_value=body_value,
            course_id=command.course_id,
        )
        await self._question_repository.update(question)
        return question