"""Extra-analysis flags read as Yes / No in tables."""

from sams_web.routers.pages_shared import format_table_cell_value
from sams_web.viewmodels.detail_sections_user_project import PROJECT_SAMPLE_COLUMNS


def test_analysis_flags_render_yes_no():
    assert format_table_cell_value("c_n_isotop_a", 1) == "Yes"
    assert format_table_cell_value("c_n_isotop_a", 0) == "No"
    assert format_table_cell_value("dendro_a", 0) == "No"
    assert format_table_cell_value("c_n_isotop_a", None) == ""
    # Other integer columns are untouched.
    assert format_table_cell_value("sample_nr", 1) == 1


def test_project_sample_table_shows_cn_isotope_analysis():
    assert "c_n_isotop_a" in PROJECT_SAMPLE_COLUMNS
