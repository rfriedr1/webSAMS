"""SQLAlchemy models for the SAMS domain."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, foreign, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base class."""


class User(Base):
    __tablename__ = "user_t"

    user_nr: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    first_name: Mapped[str | None] = mapped_column(String(40))
    last_name: Mapped[str | None] = mapped_column(String(60), index=True)
    organisation: Mapped[str | None] = mapped_column(String(99))
    institute: Mapped[str | None] = mapped_column(String(99))
    address_1: Mapped[str | None] = mapped_column(String(40))
    address_2: Mapped[str | None] = mapped_column(String(40))
    town: Mapped[str | None] = mapped_column(String(30))
    postcode: Mapped[str | None] = mapped_column(String(10))
    country: Mapped[str | None] = mapped_column(String(30))
    phone_1: Mapped[str | None] = mapped_column(String(30))
    phone_2: Mapped[str | None] = mapped_column(String(30))
    fax: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(80))
    www: Mapped[str | None] = mapped_column(String(60))
    account: Mapped[str | None] = mapped_column(String(40))
    invoice: Mapped[int | None] = mapped_column(Integer)
    correspondance: Mapped[int | None] = mapped_column(Integer)
    user_comment: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(40))
    language: Mapped[str | None] = mapped_column(String(2))
    salutation: Mapped[str | None] = mapped_column(String(40))

    projects: Mapped[list["Project"]] = relationship(back_populates="user")


class Project(Base):
    __tablename__ = "project_t"

    project_nr: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project: Mapped[str | None] = mapped_column(String(255), index=True)
    user_nr: Mapped[int | None] = mapped_column(ForeignKey("user_t.user_nr"), index=True)
    invoice_nr: Mapped[int | None] = mapped_column(Integer)
    in_date: Mapped[date | None] = mapped_column(Date)
    out_date: Mapped[date | None] = mapped_column(Date)
    desired_date: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[int | None] = mapped_column(Integer)
    report_type: Mapped[str | None] = mapped_column(String(60))
    letter: Mapped[str | None] = mapped_column(String(255))
    project_comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(40), index=True)
    price: Mapped[str | None] = mapped_column(String(40))
    project_type: Mapped[str | None] = mapped_column(String(60))
    research: Mapped[str | None] = mapped_column(String(60))
    report: Mapped[str | None] = mapped_column(String(255))
    invoice: Mapped[int | None] = mapped_column(Integer)
    auftrags_nr: Mapped[int | None] = mapped_column("AuftragsNr", Integer)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    advisor: Mapped[str | None] = mapped_column(String(60))
    sample_storage_loc: Mapped[str | None] = mapped_column(String(60))
    free_of_charge: Mapped[int | None] = mapped_column("FreeOfCharge", Integer)
    order_nr: Mapped[str | None] = mapped_column(String(60))
    supervisor: Mapped[str | None] = mapped_column(String(120))
    return_to_sender: Mapped[int | None] = mapped_column(Integer)
    returned_to_sender: Mapped[int | None] = mapped_column(Integer)
    prep_return_to_sender: Mapped[int | None] = mapped_column(Integer)
    prep_returned_to_sender: Mapped[int | None] = mapped_column(Integer)

    user: Mapped[User | None] = relationship(back_populates="projects")
    samples: Mapped[list["Sample"]] = relationship(back_populates="project")


class Sample(Base):
    __tablename__ = "sample_t"

    sample_nr: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_nr: Mapped[int | None] = mapped_column(ForeignKey("project_t.project_nr"), index=True)
    photo: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str | None] = mapped_column(String(60), index=True)
    material: Mapped[str | None] = mapped_column(String(60), index=True)
    fraction: Mapped[str | None] = mapped_column(String(60))
    pre_sub_treat: Mapped[str | None] = mapped_column(String(255))
    weight: Mapped[float | None] = mapped_column(Float)
    preparation: Mapped[str | None] = mapped_column(String(255))
    sampling_date: Mapped[date | None] = mapped_column(Date)
    editable: Mapped[int | None] = mapped_column(Integer)
    not_tobedated: Mapped[int | None] = mapped_column(Integer, index=True)
    user_label: Mapped[str | None] = mapped_column(String(255), index=True)
    user_label_nr: Mapped[str | None] = mapped_column(String(255))
    user_desc1: Mapped[str | None] = mapped_column(String(255))
    user_desc2: Mapped[str | None] = mapped_column(String(255))
    residue: Mapped[str | None] = mapped_column(String(255))
    c14_age: Mapped[float | None] = mapped_column(Float)
    c14_age_sig: Mapped[float | None] = mapped_column(Float)
    av_fm: Mapped[float | None] = mapped_column(Float)
    av_fm_sig: Mapped[float | None] = mapped_column(Float)
    av_dc13: Mapped[float | None] = mapped_column(Float)
    av_dc13_sig: Mapped[float | None] = mapped_column(Float)
    cal1s_min: Mapped[float | None] = mapped_column("cal1sMin", Float)
    cal1s_max: Mapped[float | None] = mapped_column("cal1sMax", Float)
    cal2s_min: Mapped[float | None] = mapped_column("cal2sMin", Float)
    cal2s_max: Mapped[float | None] = mapped_column("cal2sMax", Float)
    delta_r: Mapped[float | None] = mapped_column("delta_R", Float)
    calib: Mapped[str | None] = mapped_column(String(255))
    user_comment: Mapped[str | None] = mapped_column(Text)
    old_info: Mapped[str | None] = mapped_column(Text)
    ma_nr: Mapped[int | None] = mapped_column("MA_nr", Integer)
    s_no_leftover: Mapped[int | None] = mapped_column(Integer)
    s_storage_loc: Mapped[str | None] = mapped_column(String(60))
    prep_storage_loc: Mapped[str | None] = mapped_column(String(60))
    lab_comment: Mapped[str | None] = mapped_column(Text)
    left_over: Mapped[str | None] = mapped_column(String(255))
    storage: Mapped[str | None] = mapped_column(String(60))
    c_n_isotop_a: Mapped[int | None] = mapped_column("CNIsotopA", Integer)
    c_n_isotop_a_moved: Mapped[int | None] = mapped_column("CNIsotopAMoved", Integer)

    project: Mapped[Project | None] = relationship(back_populates="samples")
    preparations: Mapped[list["Preparation"]] = relationship(back_populates="sample")
    targets: Mapped[list["Target"]] = relationship(
        back_populates="sample",
        primaryjoin="Sample.sample_nr == foreign(Target.sample_nr)",
        viewonly=True,
    )


class Preparation(Base):
    __tablename__ = "preparation_t"

    sample_nr: Mapped[int] = mapped_column(ForeignKey("sample_t.sample_nr"), primary_key=True)
    prep_nr: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch: Mapped[str | None] = mapped_column(String(120), index=True)
    prep_comment: Mapped[str | None] = mapped_column(Text)
    weight_start: Mapped[float | None] = mapped_column(Float)
    weight_medium: Mapped[float | None] = mapped_column(Float)
    weight_end: Mapped[float | None] = mapped_column(Float)
    step1_method: Mapped[str | None] = mapped_column(String(60))
    step1_start: Mapped[datetime | None] = mapped_column(DateTime)
    step1_end: Mapped[datetime | None] = mapped_column(DateTime)
    step2_method: Mapped[str | None] = mapped_column(String(60))
    step2_start: Mapped[datetime | None] = mapped_column(DateTime)
    step2_end: Mapped[datetime | None] = mapped_column(DateTime)
    step3_method: Mapped[str | None] = mapped_column(String(60))
    step3_start: Mapped[datetime | None] = mapped_column(DateTime)
    step3_end: Mapped[datetime | None] = mapped_column(DateTime)
    step4_method: Mapped[str | None] = mapped_column(String(60))
    step4_start: Mapped[datetime | None] = mapped_column(DateTime)
    step4_end: Mapped[datetime | None] = mapped_column(DateTime)
    step5_method: Mapped[str | None] = mapped_column(String(60))
    step5_start: Mapped[datetime | None] = mapped_column(DateTime)
    step5_end: Mapped[datetime | None] = mapped_column(DateTime)
    cn_ratio: Mapped[float | None] = mapped_column(Float)
    c_percent: Mapped[float | None] = mapped_column(Float)
    n_percent: Mapped[float | None] = mapped_column(Float)
    prep_end: Mapped[datetime | None] = mapped_column(DateTime)
    prep_start: Mapped[datetime | None] = mapped_column(DateTime)
    stop: Mapped[int | None] = mapped_column(Integer, index=True)
    old_info: Mapped[str | None] = mapped_column(Text)
    p_no_leftover: Mapped[int | None] = mapped_column(Integer)
    left_over: Mapped[str | None] = mapped_column(String(255))
    weight_medium_2: Mapped[float | None] = mapped_column(Float)

    sample: Mapped[Sample] = relationship(back_populates="preparations")
    targets: Mapped[list["Target"]] = relationship(back_populates="preparation")


class Target(Base):
    __tablename__ = "target_t"
    __table_args__ = (
        ForeignKeyConstraint(
            ["sample_nr", "prep_nr"],
            ["preparation_t.sample_nr", "preparation_t.prep_nr"],
        ),
    )

    sample_nr: Mapped[int] = mapped_column(Integer, primary_key=True)
    prep_nr: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_nr: Mapped[int] = mapped_column(Integer, primary_key=True)
    magazine: Mapped[str | None] = mapped_column(String(60), index=True)
    position: Mapped[str | None] = mapped_column(String(20))
    precis: Mapped[str | None] = mapped_column(String(20))
    cycle_min: Mapped[int | None] = mapped_column(Integer)
    cycle_max: Mapped[int | None] = mapped_column(Integer)
    combustion: Mapped[str | None] = mapped_column(String(60))
    catalyst: Mapped[str | None] = mapped_column(String(60))
    cathode_nr: Mapped[str | None] = mapped_column(String(60))
    reactor_nr: Mapped[str | None] = mapped_column(String(60))
    co2_init: Mapped[float | None] = mapped_column(Float)
    co2_final: Mapped[float | None] = mapped_column(Float)
    hydro_init: Mapped[float | None] = mapped_column(Float)
    hydro_final: Mapped[float | None] = mapped_column(Float)
    react_time: Mapped[float | None] = mapped_column(Float)
    target_comment: Mapped[str | None] = mapped_column(Text)
    target_pressed: Mapped[datetime | None] = mapped_column(DateTime)
    stop: Mapped[int | None] = mapped_column(Integer, index=True)
    old_info: Mapped[str | None] = mapped_column(Text)
    meas_comment: Mapped[str | None] = mapped_column(Text)
    fm: Mapped[float | None] = mapped_column(Float)
    fm_sig: Mapped[float | None] = mapped_column(Float)
    dc13: Mapped[float | None] = mapped_column(Float)
    dc13_sig: Mapped[float | None] = mapped_column(Float)
    calcset: Mapped[str | None] = mapped_column(String(120))
    editallowed: Mapped[int | None] = mapped_column(Integer)
    c14_age: Mapped[float | None] = mapped_column(Float)
    c14_age_sig: Mapped[float | None] = mapped_column(Float)
    cal1s_min: Mapped[float | None] = mapped_column("cal1sMin", Float)
    cal1s_max: Mapped[float | None] = mapped_column("cal1sMax", Float)
    cal2s_min: Mapped[float | None] = mapped_column("cal2sMin", Float)
    cal2s_max: Mapped[float | None] = mapped_column("cal2sMax", Float)
    graph_batch: Mapped[str | None] = mapped_column(String(120), index=True)
    graph_date: Mapped[datetime | None] = mapped_column(DateTime)
    weight_combustion: Mapped[float | None] = mapped_column(Float)
    weight: Mapped[float | None] = mapped_column(Float)
    temp: Mapped[float | None] = mapped_column(Float)
    graphitized: Mapped[datetime | None] = mapped_column(DateTime)
    conc_c: Mapped[float | None] = mapped_column(Float)
    conc_n: Mapped[float | None] = mapped_column(Float)
    target_id: Mapped[str | None] = mapped_column(String(120), index=True)
    le_curr: Mapped[float | None] = mapped_column(Float)
    he_curr: Mapped[float | None] = mapped_column(Float)

    sample: Mapped[Sample | None] = relationship(
        back_populates="targets",
        primaryjoin="foreign(Target.sample_nr) == Sample.sample_nr",
        viewonly=True,
    )
    preparation: Mapped[Preparation] = relationship(back_populates="targets")


class Material(Base):
    __tablename__ = "material_t"

    material: Mapped[str] = mapped_column(String(60), primary_key=True)
    indexnr: Mapped[int | None] = mapped_column(Integer)


class Fraction(Base):
    __tablename__ = "fraction_t"

    fraction: Mapped[str] = mapped_column(String(60), primary_key=True)
    indexnr: Mapped[int | None] = mapped_column(Integer)


class Method(Base):
    __tablename__ = "method_t"

    method: Mapped[str] = mapped_column(String(60), primary_key=True)
    descr: Mapped[str | None] = mapped_column(Text)
    indexnr: Mapped[int | None] = mapped_column(Integer)


class SampleType(Base):
    __tablename__ = "sampletype_t"

    type: Mapped[str] = mapped_column(String(60), primary_key=True)
    indexnr: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[int | None] = mapped_column(Integer)


class ProjectType(Base):
    __tablename__ = "projecttype_t"

    type: Mapped[str] = mapped_column(String(60), primary_key=True)
    indexnr: Mapped[int | None] = mapped_column(Integer)


class ProjectStatus(Base):
    __tablename__ = "projectstatus_t"

    status: Mapped[str] = mapped_column(String(60), primary_key=True)
    indexnr: Mapped[int | None] = mapped_column(Integer)


class ResearchType(Base):
    __tablename__ = "research_t"

    research: Mapped[str] = mapped_column(String(60), primary_key=True)
    indexnr: Mapped[int | None] = mapped_column(Integer)


class ReportType(Base):
    __tablename__ = "reporttype_t"

    type: Mapped[str] = mapped_column(String(60), primary_key=True)
    indexnr: Mapped[int | None] = mapped_column(Integer)


class TargetP(Base):
    """Mapped DB view used by legacy waiting-for-measurement queries."""

    __tablename__ = "target_p"

    sample_nr: Mapped[int] = mapped_column(Integer, primary_key=True)
    prep_nr: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_nr: Mapped[int] = mapped_column(Integer, primary_key=True)
    target_id: Mapped[str | None] = mapped_column(String(120))
    type: Mapped[str | None] = mapped_column(String(60))
    user_label: Mapped[str | None] = mapped_column(String(255))
    user_label_nr: Mapped[str | None] = mapped_column(String(255))
    last_name: Mapped[str | None] = mapped_column(String(60))
    target_comment: Mapped[str | None] = mapped_column(Text)
    co2_final: Mapped[float | None] = mapped_column(Float)
    desired_date: Mapped[date | None] = mapped_column(Date)
    graphitized: Mapped[datetime | None] = mapped_column(DateTime)
    magazine: Mapped[str | None] = mapped_column(String(60))
    target_stop: Mapped[int | None] = mapped_column(Integer)
    not_tobedated: Mapped[int | None] = mapped_column(Integer)
    project_nr: Mapped[int | None] = mapped_column(Integer)
