"""course 上下文 HTTP 路由（薄壳，零业务分支与兜底 try/except）。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.contexts.course.application.commands import (
    CreateCourseCommand,
    EnrollCourseCommand,
)
from app.contexts.course.application.queries import (
    ListCoursesQuery,
    ListCourseStudentsQuery,
)
from app.contexts.course.domain.course import Course
from app.contexts.course.domain.enrollment import Enrollment
from app.contexts.course.interfaces.api.deps import (
    CourseCreatorUser,
    CourseRepo,
    CourseStaffUser,
    EnrollmentRepo,
    StudentUser,
    UserSummaryReaderDep,
    build_create_course_use_case,
    build_enroll_course_use_case,
    build_list_course_students_use_case,
    build_list_courses_use_case,
)
from app.contexts.course.interfaces.api.schemas import (
    CourseListResponse,
    CourseResponse,
    CourseStudentItem,
    CourseStudentListResponse,
    CreateCourseRequest,
    EnrollmentResponse,
)
from app.contexts.identity.application.ports import pick_summary_display_name

router = APIRouter(prefix="/api/v1/courses", tags=["courses"])


def _course_response(course: Course, *, teacher_name: str) -> CourseResponse:
    return CourseResponse(
        id=course.id,
        code=course.code.value,
        name=course.name.value,
        semester=course.semester.value,
        teacher_id=course.teacher_id,
        teacher_name=teacher_name,
        created_at=course.created_at,
    )


def _enrollment_response(
    enrollment: Enrollment, *, student_name: str
) -> EnrollmentResponse:
    return EnrollmentResponse(
        id=enrollment.id,
        course_id=enrollment.course_id,
        student_id=enrollment.student_id,
        student_name=student_name,
        enrolled_at=enrollment.enrolled_at,
    )


@router.get(
    "",
    response_model=CourseListResponse,
    summary="分页查询课程列表（公开，支持按学期筛选）",
)
async def list_courses(
    courses: CourseRepo,
    summary_reader: UserSummaryReaderDep,
    page: Annotated[int, Query(ge=1, description="页码，从 1 起")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数，上限 100")] = 20,
    semester: Annotated[str | None, Query(max_length=32, description="按学期筛选")] = None,
) -> CourseListResponse:
    result = await build_list_courses_use_case(courses).execute(
        ListCoursesQuery(page=page, page_size=page_size, semester=semester)
    )
    summaries = await summary_reader.get_summaries(
        course.teacher_id for course in result.items
    )
    return CourseListResponse(
        items=[
            _course_response(
                course,
                teacher_name=pick_summary_display_name(summaries, course.teacher_id),
            )
            for course in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.post(
    "",
    response_model=CourseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建课程（仅教师/管理员；重复课程编号 409）",
)
async def create_course(
    payload: CreateCourseRequest,
    user: CourseCreatorUser,
    courses: CourseRepo,
) -> CourseResponse:
    course = await build_create_course_use_case(courses).execute(
        CreateCourseCommand(
            actor_id=user.id,
            code=payload.code,
            name=payload.name,
            semester=payload.semester,
        )
    )
    return _course_response(course, teacher_name=user.display_name)


@router.post(
    "/{course_id}/enroll",
    response_model=EnrollmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="学生自助选课（仅学生；重复选课 409，课程不存在 404）",
)
async def enroll_course(
    course_id: UUID,
    user: StudentUser,
    courses: CourseRepo,
    enrollments: EnrollmentRepo,
) -> EnrollmentResponse:
    enrollment = await build_enroll_course_use_case(courses, enrollments).execute(
        EnrollCourseCommand(course_id=course_id, student_id=user.id)
    )
    return _enrollment_response(enrollment, student_name=user.display_name)


@router.get(
    "/{course_id}/students",
    response_model=CourseStudentListResponse,
    summary="分页查询课程选课学生（仅教师/助教/管理员；课程不存在 404）",
)
async def list_course_students(
    course_id: UUID,
    _staff: CourseStaffUser,
    courses: CourseRepo,
    enrollments: EnrollmentRepo,
    summary_reader: UserSummaryReaderDep,
    page: Annotated[int, Query(ge=1, description="页码，从 1 起")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数，上限 100")] = 20,
) -> CourseStudentListResponse:
    result = await build_list_course_students_use_case(courses, enrollments).execute(
        ListCourseStudentsQuery(course_id=course_id, page=page, page_size=page_size)
    )
    summaries = await summary_reader.get_summaries(
        item.student_id for item in result.items
    )
    return CourseStudentListResponse(
        items=[
            CourseStudentItem(
                student_id=item.student_id,
                student_name=pick_summary_display_name(summaries, item.student_id),
                enrolled_at=item.enrolled_at,
            )
            for item in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )
