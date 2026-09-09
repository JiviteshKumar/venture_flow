"""An analysis must not write to a filename another analysis is using.

`run_due_diligence` used to end with an unconditional

    open("due_diligence_report.json", "w")

with `MAX_CONCURRENT_ANALYSES` set to 3. Three analyses running together
overwrote each other's file, and the last writer won.

That is not a theoretical race. During testing, a report read from that file
after one analysis had actually been written by a different analysis running
alongside it, and the difference between them was whether founder research had
executed -- so the file produced a confident, wrong answer to the exact
question being investigated.

Two further reasons it was wrong on a server: the report is already persisted
to Postgres and returned to the caller, so the file is redundant; and on a
container host the working directory is ephemeral and may be read-only, so an
unconditional write can raise at the very end of a successful four-minute
analysis.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ventureflow_agent  # noqa: E402


class TestNothingIsWrittenByDefault:
    def test_no_file_appears_when_no_directory_is_configured(
        self, monkeypatch, tmp_path
    ):
        """The server case. A deployment that has not asked for local copies
        must not accumulate them."""
        monkeypatch.setattr(ventureflow_agent, "REPORT_DIR", "")
        monkeypatch.chdir(tmp_path)

        ventureflow_agent._write_debug_copy({"final_score": 50}, "Uber")

        assert list(tmp_path.iterdir()) == [], (
            "a file was written without being asked for"
        )

    def test_the_old_fixed_filename_is_gone(self, monkeypatch, tmp_path):
        """Specifically that name, because that is the one three concurrent
        analyses collided on."""
        monkeypatch.setattr(ventureflow_agent, "REPORT_DIR", str(tmp_path))
        ventureflow_agent._write_debug_copy({"final_score": 50}, "Uber")

        assert not (tmp_path / "due_diligence_report.json").exists()


class TestConcurrentRunsDoNotCollide:
    def test_two_reports_for_the_same_company_get_two_files(
        self, monkeypatch, tmp_path
    ):
        """The actual defect: same company, same directory, two runs."""
        monkeypatch.setattr(ventureflow_agent, "REPORT_DIR", str(tmp_path))

        ventureflow_agent._write_debug_copy({"run": "first"}, "Uber")
        ventureflow_agent._write_debug_copy({"run": "second"}, "Uber")

        files = sorted(tmp_path.glob("*.json"))
        assert len(files) == 2, (
            f"two analyses produced {len(files)} file(s); one overwrote the other"
        )
        contents = {json.loads(f.read_text(encoding="utf-8"))["run"] for f in files}
        assert contents == {"first", "second"}

    def test_many_concurrent_writes_all_survive(self, monkeypatch, tmp_path):
        """MAX_CONCURRENT_ANALYSES is 3; this exercises more than that from
        real threads, since the timestamp is what makes the name unique."""
        from concurrent.futures import ThreadPoolExecutor

        monkeypatch.setattr(ventureflow_agent, "REPORT_DIR", str(tmp_path))
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(
                lambda i: ventureflow_agent._write_debug_copy({"run": i}, "Uber"),
                range(8),
            ))

        assert len(list(tmp_path.glob("*.json"))) == 8


class TestItCannotBreakAFinishedAnalysis:
    """The write happens after the analysis has succeeded. Failing there would
    throw away four minutes of completed work over a debugging convenience."""

    def test_an_unwritable_directory_does_not_raise(self, monkeypatch, tmp_path):
        target = tmp_path / "a-file-not-a-directory"
        target.write_text("", encoding="utf-8")
        monkeypatch.setattr(ventureflow_agent, "REPORT_DIR", str(target))

        ventureflow_agent._write_debug_copy({"final_score": 50}, "Uber")

    def test_unserialisable_content_does_not_raise(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ventureflow_agent, "REPORT_DIR", str(tmp_path))
        ventureflow_agent._write_debug_copy({"obj": object()}, "Uber")

    @pytest.mark.parametrize("name", [
        "", "   ", "../../etc/passwd", "C:\\\\Windows\\\\System32", "02 uber/../x",
        "a" * 500, "🙂",
    ])
    def test_a_hostile_company_name_stays_inside_the_directory(
        self, monkeypatch, tmp_path, name
    ):
        """The filename is built from the company name, which comes from an
        uploaded file."""
        monkeypatch.setattr(ventureflow_agent, "REPORT_DIR", str(tmp_path))
        ventureflow_agent._write_debug_copy({"final_score": 50}, name)

        for written in tmp_path.rglob("*.json"):
            assert written.parent == tmp_path, (
                f"{name!r} escaped the configured directory: {written}"
            )


class TestWhenAskedItActuallyWrites:
    def test_the_report_content_round_trips(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ventureflow_agent, "REPORT_DIR", str(tmp_path))
        report = {"final_score": 41.0, "company": "Uber", "sections": {"a": 1}}

        ventureflow_agent._write_debug_copy(report, "Uber")

        written = next(tmp_path.glob("*.json"))
        assert json.loads(written.read_text(encoding="utf-8")) == report
        assert "Uber" in written.name

    def test_a_missing_directory_is_created(self, monkeypatch, tmp_path):
        nested = tmp_path / "reports" / "nested"
        monkeypatch.setattr(ventureflow_agent, "REPORT_DIR", str(nested))

        ventureflow_agent._write_debug_copy({"final_score": 50}, "Uber")

        assert len(list(nested.glob("*.json"))) == 1
