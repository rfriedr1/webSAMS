"""Pydantic schemas for API contracts."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    first_name: str | None = None
    last_name: str = Field(min_length=1, max_length=60)
    organisation: str | None = None
    institute: str | None = None
    email: str | None = None


class ProjectCreate(BaseModel):
    user_nr: int
    project: str = Field(min_length=1, max_length=255)
    desired_date: date | None = None
    in_date: date | None = None
    status: str = "planned"


class SampleCreate(BaseModel):
    project_nr: int
    user_label: str = Field(min_length=1, max_length=255)
    user_label_nr: str | None = None
    user_desc1: str | None = None
    user_desc2: str | None = None
    type: str | None = None
    material: str | None = None
    fraction: str | None = None
    weight: float | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_nr: int
    first_name: str | None = None
    last_name: str | None = None
    organisation: str | None = None
    institute: str | None = None
    email: str | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_nr: int
    project: str | None = None
    user_nr: int | None = None
    status: str | None = None
    in_date: date | None = None
    desired_date: date | None = None


class SampleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sample_nr: int
    project_nr: int | None = None
    user_label: str | None = None
    user_label_nr: str | None = None
    material: str | None = None
    type: str | None = None
    c14_age: float | None = None
    c14_age_sig: float | None = None


class DashboardCounts(BaseModel):
    planned: int
    in_prep: int
    waiting_for_graph: int
    waiting_for_meas: int
    waiting_express: int
