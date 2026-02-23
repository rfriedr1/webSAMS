from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from sams_web.models import Base, Preparation, Target
from sams_web.setup_store import SetupStore
from sams_web.services import SamsService, TextSanitizer
from sams_web.thresholds import ThresholdStore


def _make_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    return SessionLocal()


def _make_service(session: Session, tmp_dir: str) -> SamsService:
    setup_store = SetupStore(Path(tmp_dir) / "setup.json")
    threshold_store = ThresholdStore(setup_store)
    return SamsService(
        session,
        threshold_store=threshold_store,
        setup_store=setup_store,
    )


def test_create_sample_creates_blank_prep_and_target():
    with TemporaryDirectory() as tmp_dir:
        session = _make_session()
        service = _make_service(session, tmp_dir)

        user = service.create_user({"last_name": "Miller", "first_name": "Anne"})
        project = service.add_new_project_by_user_nr(user_nr=user.user_nr, project_name="Project A")
        sample = service.add_new_sample_by_project_nr(project_nr=project.project_nr, sample_name="S-001")

        prep = session.scalar(
            select(Preparation).where(Preparation.sample_nr == sample.sample_nr, Preparation.prep_nr == 1)
        )
        target = session.scalar(
            select(Target).where(
                Target.sample_nr == sample.sample_nr,
                Target.prep_nr == 1,
                Target.target_nr == 1,
            )
        )

        assert prep is not None
        assert target is not None


def test_text_sanitizer():
    value = 'A&B;C$"?D%'
    assert TextSanitizer.replace_bad_characters(value) == "A_B,C_D_"
    assert TextSanitizer.replace_umlaute("äöüß") == "aeoeuess"
