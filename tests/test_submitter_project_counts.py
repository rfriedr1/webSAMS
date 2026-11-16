"""Samples and measured targets per project, on the submitter's project table."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from sams_web.models import Base, Project, Sample, Target
from sams_web.repositories import SamsRepository


def test_project_sample_target_counts():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, class_=Session)()
    for nr in (10, 11, 12):
        session.add(Project(project_nr=nr, user_nr=1, project=f"P{nr}"))
    for sample_nr, project_nr in ((100, 10), (101, 10), (102, 10), (110, 11)):
        session.add(Sample(sample_nr=sample_nr, project_nr=project_nr))
    session.add_all([
        Target(sample_nr=100, prep_nr=1, target_nr=1, c14_age=5000, fm=0.5),
        Target(sample_nr=100, prep_nr=1, target_nr=2, fm=0.6),          # FM only: measured
        Target(sample_nr=101, prep_nr=1, target_nr=1),                  # not measured
        Target(sample_nr=110, prep_nr=1, target_nr=1, c14_age=1200),    # C14 only: measured
    ])
    session.commit()

    counts = SamsRepository(session).project_sample_target_counts([10, 11, 12])
    assert counts == {
        10: {"sample_count": 3, "measured_targets": 2},
        11: {"sample_count": 1, "measured_targets": 1},
        12: {"sample_count": 0, "measured_targets": 0},
    }
    assert SamsRepository(session).project_sample_target_counts([]) == {}
