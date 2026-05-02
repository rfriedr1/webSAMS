"""Compatibility exports for split detail-section modules."""

from __future__ import annotations

from sams_web.viewmodels.detail_sections_common import (
    Row,
    SectionSpec,
    format_c14_integer,
    format_cn_ratio,
    format_cn_ratio_from_conc,
    format_d13c,
    format_one_decimal,
    format_total_c_ug,
    is_empty_display_value,
    is_sentinel_date,
)
from sams_web.viewmodels.detail_sections_sample_lab import (
    build_preparation_sections,
    build_sample_sections,
    build_target_sections,
    calculate_preparation_yield,
    format_sample_value,
    format_target_indicator,
    format_target_value,
    format_preparation_value,
)
from sams_web.viewmodels.detail_sections_user_project import (
    build_project_sections,
    build_user_sections,
    format_project_value,
)

__all__ = [
    "Row",
    "SectionSpec",
    "build_preparation_sections",
    "build_project_sections",
    "build_sample_sections",
    "build_target_sections",
    "build_user_sections",
    "calculate_preparation_yield",
    "format_c14_integer",
    "format_cn_ratio",
    "format_cn_ratio_from_conc",
    "format_d13c",
    "format_one_decimal",
    "format_preparation_value",
    "format_project_value",
    "format_sample_value",
    "format_target_indicator",
    "format_target_value",
    "format_total_c_ug",
    "is_empty_display_value",
    "is_sentinel_date",
]
