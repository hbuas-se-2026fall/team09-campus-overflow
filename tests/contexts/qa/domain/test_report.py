"""举报领域值对象、枚举与聚合单元测试（F18）。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.contexts.qa.domain.report import (
    Report,
    ReportAction,
    ReportReason,
    ReportStatus,
    ReportTargetType,
    ResolutionNote,
    normalize_resolution_note,
)
from app.shared.errors import DomainValidationError


class TestReportEnumsAndValueObjects:
    def test_target_types_exclude_comment(self) -> None:
        assert [t.value for t in ReportTargetType] == ["question", "answer"]
        assert [s.value for s in ReportStatus] == ["pending", "resolved", "dismissed"]
        assert [a.value for a in ReportAction] == [
            "dismiss",
            "close_question",
            "soft_delete",
        ]

    def test_report_reason_strips_and_validates_bounds(self) -> None:
        assert ReportReason("  疑似广告引流内容  ").value == "疑似广告引流内容"
        assert ReportReason("12345").value == "12345"
        assert ReportReason("字" * 500).value == "字" * 500

        for bad in ("", "    ", "1234", "字" * 501, "违规内容\x00测试", "违规内容\ud800测试"):
            with pytest.raises(DomainValidationError):
                ReportReason(bad)

    def test_resolution_note_and_normalizer(self) -> None:
        assert normalize_resolution_note(None) is None
        assert normalize_resolution_note("   ") is None
        note = normalize_resolution_note("  已核实并处理  ")
        assert note == ResolutionNote("已核实并处理")
        assert ResolutionNote("好").value == "好"
        assert ResolutionNote("备" * 500).value == "备" * 500

        for bad in ("", "   ", "备" * 501, "备注\x00", "备注\ud800"):
            with pytest.raises(DomainValidationError):
                ResolutionNote(bad)

        with pytest.raises(DomainValidationError):
            normalize_resolution_note("bad\x00note")


class TestReportAggregate:
    def test_file_initializes_pending_report(self) -> None:
        rid, tid = uuid4(), uuid4()
        report = Report.file(
            reporter_id=rid,
            target_type=ReportTargetType.QUESTION,
            target_id=tid,
            reason="  包含无关广告外链，影响课程讨论秩序  ",
        )
        assert report.reporter_id == rid
        assert report.target_type is ReportTargetType.QUESTION
        assert report.target_id == tid
        assert report.reason.value == "包含无关广告外链，影响课程讨论秩序"
        assert report.status is ReportStatus.PENDING
        assert report.resolution_action is None
        assert report.resolution_note is None
        assert report.resolved_by is None
        assert report.resolved_at is None
        assert report.created_at.tzinfo is not None
