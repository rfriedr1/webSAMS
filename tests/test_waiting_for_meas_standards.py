"""Lab → Analysis: *Waiting for measurement* leaves standards out unless
*Include standards* is ticked. No database: the SQL is checked as text and
the service is stubbed for the page."""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from sams_web.dependencies import get_service
from sams_web.main import app
from sams_web.setup_store import SetupStore
from sams_web.repositories import WAITING_FOR_MEAS_STANDARD_TYPES, SamsRepository

STANDARDS_FILTER = "target_p.type NOT IN ('oxa2', 'blank', 'C1', 'C2', 'C3', 'C6', 'C7', 'C8')"


def test_standards_are_left_out_by_default():
    assert STANDARDS_FILTER in SamsRepository._sql_waiting_for_meas()
    assert WAITING_FOR_MEAS_STANDARD_TYPES == ("oxa2", "blank", "C1", "C2", "C3", "C6", "C7", "C8")


def test_include_standards_drops_only_the_type_filter():
    without = SamsRepository._sql_waiting_for_meas()
    with_standards = SamsRepository._sql_waiting_for_meas(include_standards=True)
    assert "target_p.type NOT IN" not in with_standards
    assert without.replace(f" AND {STANDARDS_FILTER}", "") == with_standards
    # The excluded projects (798 CO2 HD has standards of its own) stay out.
    assert "target_p.project_nr NOT IN" in with_standards
    assert with_standards.rstrip().endswith("ORDER BY target_id")


class _Service:
    def __init__(self):
        self.calls: list[bool] = []

    def list_waiting_for_meas(self, include_standards=False):
        self.calls.append(include_standards)
        rows = [{"target_id": "1.1.1", "type": "arch", "sample_nr": 1, "prep_nr": 1, "target_nr": 1}]
        if include_standards:
            rows += [
                {"target_id": "2.1.1", "type": "oxa2", "sample_nr": 2, "prep_nr": 1, "target_nr": 1},
                {"target_id": "3.1.1", "type": "blank", "sample_nr": 3, "prep_nr": 1, "target_nr": 1},
            ]
        return rows

    def list_magazines(self):
        return ["MA261120"]

    def resolve_existing_magazine(self, query):
        return query

    def list_targets_by_magazine(self, magazine):
        return []

    # The magazine list beside it (magazine_list.py).
    setup_store = SetupStore(Path(tempfile.mkdtemp()) / "setup.json")

    def list_recent_magazines(self, limit, find=None):
        return [{"magazine": "MA261120", "last_changed": None, "target_count": 0, "measured_targets": 0}]

    def count_magazines(self, find=None):
        return 1


def _get(url: str) -> tuple[_Service, str]:
    service = _Service()
    app.dependency_overrides[get_service] = lambda: service
    try:
        response = TestClient(app).get(url)
    finally:
        app.dependency_overrides.pop(get_service, None)
    assert response.status_code == 200
    return service, response.text


def test_analysis_page_shows_the_switch_unticked_by_default():
    service, html = _get("/lab/analysis")
    assert service.calls == [False]
    assert "Include standards" in html
    assert 'name="include_standards" value="true" checked' not in html
    assert "1 rows</span>" in html


def test_ticked_switch_lists_and_counts_standards_and_keeps_the_magazine():
    service, html = _get("/lab/analysis?include_standards=true&magazine=MA261120")
    assert service.calls == [True]
    assert 'name="include_standards" value="true" checked' in html
    assert "3 rows · 2 standards" in html
    # The switch keeps the open magazine; the magazine lookup keeps the switch.
    assert '<input type="hidden" name="magazine" value="MA261120" />' in html
    assert '<input type="hidden" name="include_standards" value="true" />' in html
    assert 'href="/lab/analysis?include_standards=true#tbl-magazine-targets" class="magazine-clear"' in html
