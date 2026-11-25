"""course 领域层单元测试：值对象归一化/边界校验与聚合创建。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.contexts.course.domain.course import Course
from app.contexts.course.domain.enrollment import Enrollment
from app.contexts.course.domain.value_objects import CourseCode, CourseName, Semester
from app.shared.errors import DomainValidationError


class TestCourseCode:
    def test_normalizes_whitespace_and_uppercase(self) -> None:
        code = CourseCode("  cs-se-301  ")
        assert code.value == "CS-SE-301"
        assert code == CourseCode("CS-SE-301")

    def test_accepts_min_and_max_length(self) -> None:
        assert CourseCode("a1").value == "A1"
        assert CourseCode("C" + "A" * 31).value == "C" + "A" * 31

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "A",
            "A" * 33,
            "-CS101",
            "_CS101",
            "CS 301",
            "CS/301",
            "软件工程",
            "CS-SE-301\n",
            "CS\t301",
            "CS\x00301",
            "CS\ud800301",
        ],
    )
    def test_rejects_invalid_course_code(self, raw: str) -> None:
        with pytest.raises(DomainValidationError):
            CourseCode(raw)


class TestCourseName:
    def test_strips_outer_whitespace(self) -> None:
        name = CourseName("  软件工程  ")
        assert name.value == "软件工程"

    def test_accepts_boundary_lengths(self) -> None:
        assert CourseName("编译").value == "编译"
        assert CourseName("算" * 100).value == "算" * 100

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "  ",
            "算",
            "算" * 101,
            "软件\n工程",
            "软件\r工程",
            "软件\t工程",
            "软件工程\n",
            "软件\x00工程",
            "软件\ud800工程",
        ],
    )
    def test_rejects_invalid_course_name(self, raw: str) -> None:
        with pytest.raises(DomainValidationError):
            CourseName(raw)


class TestSemester:
    def test_accepts_common_semester_formats(self) -> None:
        assert Semester(" 2026-Fall ").value == "2026-Fall"
        assert Semester("2026秋").value == "2026秋"
        assert Semester("2026-2027-1").value == "2026-2027-1"
        assert Semester("S" * 32).value == "S" * 32

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "   ",
            "秋",
            "S" * 33,
            "2026\nFall",
            "2026\rFall",
            "2026\tFall",
            "2026-Fall\n",
            "2026\x00Fall",
            "2026\ud800Fall",
        ],
    )
    def test_rejects_invalid_semester(self, raw: str) -> None:
        with pytest.raises(DomainValidationError):
            Semester(raw)


class TestAggregates:
    def test_course_create_builds_value_objects_and_timestamps(self) -> None:
        teacher_id = uuid4()
        course = Course.create(
            code=" cs-se-301 ",
            name=" 软件工程 ",
            semester=" 2026-Fall ",
            teacher_id=teacher_id,
        )
        assert course.code.value == "CS-SE-301"
        assert course.name.value == "软件工程"
        assert course.semester.value == "2026-Fall"
        assert course.teacher_id == teacher_id
        assert course.created_at.tzinfo is not None

    def test_enrollment_enroll_sets_ids_and_timestamp(self) -> None:
        course_id = uuid4()
        student_id = uuid4()
        enrollment = Enrollment.enroll(course_id=course_id, student_id=student_id)
        assert enrollment.course_id == course_id
        assert enrollment.student_id == student_id
        assert enrollment.enrolled_at.tzinfo is not None
