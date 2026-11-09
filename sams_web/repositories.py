"""Database repository classes for SAMS."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import String, and_, case, cast, exists, false, func, select, text, tuple_
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, selectinload

from sams_web.models import (
    EaCheck,
    QcSignoff,
    QcSignoffItem,
    Method,
    Preparation,
    Project,
    Sample,
    SampleType,
    Target,
    Submitter,
)


# Narrowed *To prep* queues: dashboard / table key -> `sample_t.material`
# (exact value from `material_t`; "cremated bone" is a material of its own
# and is not in *To prep bone*). Shown under *To prep all* (`planned`).
TO_PREP_MATERIAL_QUEUES: dict[str, str] = {
    "to_prep_bone": "bone",
    "to_prep_tooth": "tooth",
}


class SamsRepository:
    """DB repository mirroring core `_dm.pas` data functions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_submitters(self, query: str | None = None, limit: int | None = None) -> list[Submitter]:
        stmt = select(Submitter).order_by(
            case((Submitter.last_name.is_(None), 1), else_=0).asc(),
            Submitter.last_name.asc(),
            case((Submitter.first_name.is_(None), 1), else_=0).asc(),
            Submitter.first_name.asc(),
        )
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                Submitter.last_name.like(like)
                | Submitter.first_name.like(like)
                | Submitter.organisation.like(like)
                | Submitter.institute.like(like)
            )
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get_submitter(self, user_nr: int) -> Submitter | None:
        return self.session.get(Submitter, user_nr)

    # `user_t.last_name` is latin1_swedish_ci, where `ä` sorts as its own
    # letter, so `hack` would not find `Häck`. Converting to a Unicode
    # collation folds case and accents (ä = a, é = e, ß = ss). The cast
    # rules out the index, which does not matter on ~3 000 rows.
    _FOLDED_LAST_NAME = "CONVERT(TRIM(user_t.last_name) USING utf8mb4) COLLATE utf8mb4_unicode_ci"
    _FOLDED_PARAM = "CONVERT(:{name} USING utf8mb4) COLLATE utf8mb4_unicode_ci"

    def find_submitter_nrs_by_last_name(self, name: str) -> list[int]:
        """Submitter numbers for a Magic Nav last-name lookup (`sub:meier`).

        Exact last-name matches win; only when there are none does a
        substring match apply. So `roth` opens the one *Roth* even though
        several *Rothe* records exist, while `häc` still finds *Häck*.
        Case and accents are ignored on MySQL; other dialects (the SQLite
        test database) fold case only.
        """
        needle = " ".join(name.split())
        if not needle:
            return []
        escaped = needle.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        pattern = f"%{escaped}%"
        if self.session.get_bind().dialect.name == "mysql":
            exact_clause = text(
                f"{self._FOLDED_LAST_NAME} = {self._FOLDED_PARAM.format(name='needle')}"
            ).bindparams(needle=needle)
            like_clause = text(
                f"{self._FOLDED_LAST_NAME} LIKE {self._FOLDED_PARAM.format(name='pattern')} ESCAPE '!'"
            ).bindparams(pattern=pattern)
        else:
            folded = func.lower(func.trim(Submitter.last_name))
            exact_clause = folded == needle.lower()
            like_clause = folded.like(pattern.lower(), escape="!")
        for clause in (exact_clause, like_clause):
            nrs = list(
                self.session.scalars(
                    select(Submitter.user_nr).where(clause).order_by(Submitter.user_nr)
                )
            )
            if nrs:
                return nrs
        return []

    def get_adjacent_submitter_nrs(self, user_nr: int) -> tuple[int | None, int | None]:
        previous = self.session.scalar(
            select(func.max(Submitter.user_nr)).where(Submitter.user_nr < user_nr)
        )
        following = self.session.scalar(
            select(func.min(Submitter.user_nr)).where(Submitter.user_nr > user_nr)
        )
        return (
            int(previous) if previous is not None else None,
            int(following) if following is not None else None,
        )

    def get_submitter_stats(self) -> tuple[int, int]:
        total_count, max_user_nr = self.session.execute(
            select(
                func.count(Submitter.user_nr),
                func.max(Submitter.user_nr),
            )
        ).one()
        return int(total_count or 0), int(max_user_nr or 0)

    def create_submitter(self, payload: dict[str, Any]) -> Submitter:
        user = Submitter(**payload)
        self.session.add(user)
        self.session.flush()
        return user

    def list_projects_by_submitter(self, user_nr: int) -> list[Project]:
        stmt = (
            select(Project)
            .where(Project.user_nr == user_nr)
            .order_by(
                case((Project.in_date.is_(None), 1), else_=0).asc(),
                Project.in_date.desc(),
                Project.project_nr.desc(),
            )
        )
        return list(self.session.scalars(stmt))

    def list_projects(
        self, query: str | None = None, limit: int | None = None
    ) -> list[Project]:
        stmt = select(Project).options(selectinload(Project.submitter)).order_by(
            case((Project.in_date.is_(None), 1), else_=0).asc(),
            Project.in_date.desc(),
            Project.project_nr.desc(),
        )
        if query:
            like = f"%{query}%"
            # Submitter columns need an explicit join — `selectinload` above
            # is a loader strategy, not a joined FROM clause.
            stmt = stmt.outerjoin(Project.submitter).where(
                Project.project.like(like)
                | Project.status.like(like)
                | Submitter.last_name.like(like)
                | Submitter.first_name.like(like)
                | Submitter.organisation.like(like)
                # A bare number is almost always a project number.
                | (
                    Project.project_nr == int(query.strip())
                    if query.strip().isdigit()
                    else false()
                )
            )
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def count_projects(self, query: str | None = None) -> int:
        stmt = select(func.count()).select_from(Project)
        if query:
            like = f"%{query}%"
            stmt = stmt.outerjoin(Project.submitter).where(
                Project.project.like(like)
                | Project.status.like(like)
                | Submitter.last_name.like(like)
                | Submitter.first_name.like(like)
                | Submitter.organisation.like(like)
                | (
                    Project.project_nr == int(query.strip())
                    if query.strip().isdigit()
                    else false()
                )
            )
        return int(self.session.scalar(stmt) or 0)

    def count_submitters(self, query: str | None = None) -> int:
        stmt = select(func.count()).select_from(Submitter)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                Submitter.last_name.like(like)
                | Submitter.first_name.like(like)
                | Submitter.organisation.like(like)
                | Submitter.institute.like(like)
            )
        return int(self.session.scalar(stmt) or 0)

    def get_project(self, project_nr: int) -> Project | None:
        return self.session.get(Project, project_nr)

    def get_adjacent_project_nrs(self, project_nr: int) -> tuple[int | None, int | None]:
        previous = self.session.scalar(
            select(func.max(Project.project_nr)).where(Project.project_nr < project_nr)
        )
        following = self.session.scalar(
            select(func.min(Project.project_nr)).where(Project.project_nr > project_nr)
        )
        return (
            int(previous) if previous is not None else None,
            int(following) if following is not None else None,
        )

    def get_project_stats(self) -> tuple[int, int]:
        total_count, max_project_nr = self.session.execute(
            select(
                func.count(Project.project_nr),
                func.max(Project.project_nr),
            )
        ).one()
        return int(total_count or 0), int(max_project_nr or 0)

    def create_project(self, payload: dict[str, Any]) -> Project:
        project = Project(**payload)
        self.session.add(project)
        self.session.flush()
        return project

    def list_samples_by_project(self, project_nr: int) -> list[Sample]:
        stmt = (
            select(Sample)
            .where(Sample.project_nr == project_nr)
            .order_by(Sample.sample_nr.asc())
        )
        return list(self.session.scalars(stmt))

    def get_sample(self, sample_nr: int) -> Sample | None:
        return self.session.get(Sample, sample_nr)

    def get_adjacent_sample_nrs(self, sample_nr: int) -> tuple[int | None, int | None]:
        previous = self.session.scalar(
            select(func.max(Sample.sample_nr)).where(Sample.sample_nr < sample_nr)
        )
        following = self.session.scalar(
            select(func.min(Sample.sample_nr)).where(Sample.sample_nr > sample_nr)
        )
        return (
            int(previous) if previous is not None else None,
            int(following) if following is not None else None,
        )

    def get_sample_stats(self) -> tuple[int, int]:
        total_count, max_sample_nr = self.session.execute(
            select(
                func.count(Sample.sample_nr),
                func.max(Sample.sample_nr),
            )
        ).one()
        return int(total_count or 0), int(max_sample_nr or 0)

    def create_sample(self, payload: dict[str, Any]) -> Sample:
        sample = Sample(**payload)
        self.session.add(sample)
        self.session.flush()
        return sample

    def create_blank_prep(self, sample_nr: int, prep_nr: int = 1) -> Preparation:
        # Legacy flags: write 0 explicitly. An unset mapped column is INSERTed
        # as NULL, and the lab queues filter on `stop = 0`, so a NULL Discarded
        # flag would drop the new preparation out of every queue.
        prep = Preparation(sample_nr=sample_nr, prep_nr=prep_nr, stop=0, p_no_leftover=0)
        self.session.add(prep)
        self.session.flush()
        return prep

    def create_blank_target(self, sample_nr: int, prep_nr: int = 1, target_nr: int = 1) -> Target:
        # `stop` (Discarded) written as 0, not NULL: see `create_blank_prep`.
        target = Target(sample_nr=sample_nr, prep_nr=prep_nr, target_nr=target_nr, stop=0)
        self.session.add(target)
        self.session.flush()
        return target

    def get_sample_details(self, sample_nr: int) -> dict[str, Any] | None:
        sample = self.get_sample(sample_nr)
        if sample is None:
            return None

        project = self.get_project(sample.project_nr) if sample.project_nr else None
        user = self.get_user(project.user_nr) if project and project.user_nr else None

        prep_stmt = (
            select(Preparation)
            .where(Preparation.sample_nr == sample_nr)
            .order_by(Preparation.prep_nr.asc())
        )
        target_stmt = (
            select(Target)
            .where(Target.sample_nr == sample_nr)
            .order_by(Target.prep_nr.asc(), Target.target_nr.asc())
        )
        preparations = list(self.session.scalars(prep_stmt))
        targets = list(self.session.scalars(target_stmt))

        return {
            "sample": sample,
            "project": project,
            "user": user,
            "preparations": preparations,
            "targets": targets,
        }

    def list_preparations_by_sample(self, sample_nr: int) -> list[Preparation]:
        stmt = (
            select(Preparation)
            .where(Preparation.sample_nr == sample_nr)
            .order_by(Preparation.prep_nr.desc())
        )
        return list(self.session.scalars(stmt))

    def list_preparations_by_samples(self, sample_nrs: list[int]) -> list[Preparation]:
        """Preparations of several samples in one query, in sample then
        prep order."""
        if not sample_nrs:
            return []
        stmt = (
            select(Preparation)
            .where(Preparation.sample_nr.in_(sample_nrs))
            .order_by(Preparation.sample_nr.asc(), Preparation.prep_nr.asc())
        )
        return list(self.session.scalars(stmt))

    def list_planned_queue_rows(self, show_on_hold: bool = False) -> list[dict[str, Any]]:
        return self._fetch_rows(self._sql_planned(show_on_hold=show_on_hold))

    def list_to_prep_queues(self, show_on_hold: bool = False) -> dict[str, list[dict[str, Any]]]:
        """The *To prep* queues: all unprepared samples (`planned`) and,
        under it, the same query narrowed to one material per
        `TO_PREP_MATERIAL_QUEUES` entry. Held samples follow the same
        switch in all of them."""
        queues = {"planned": self.list_planned_queue_rows(show_on_hold=show_on_hold)}
        for key, material in TO_PREP_MATERIAL_QUEUES.items():
            queues[key] = self._fetch_rows(
                self._sql_planned(show_on_hold=show_on_hold, by_material=True),
                {"material": material},
            )
        return queues

    def list_waiting_for_graph_queue_rows(self) -> list[dict[str, Any]]:
        return self._fetch_rows(self._sql_waiting_for_graph_table())

    def get_preparation(self, sample_nr: int, prep_nr: int) -> Preparation | None:
        stmt = select(Preparation).where(
            Preparation.sample_nr == sample_nr,
            Preparation.prep_nr == prep_nr,
        )
        return self.session.scalar(stmt)

    def get_adjacent_prep_nrs(self, sample_nr: int, prep_nr: int) -> tuple[int | None, int | None]:
        previous = self.session.scalar(
            select(func.max(Preparation.prep_nr)).where(
                Preparation.sample_nr == sample_nr,
                Preparation.prep_nr < prep_nr,
            )
        )
        following = self.session.scalar(
            select(func.min(Preparation.prep_nr)).where(
                Preparation.sample_nr == sample_nr,
                Preparation.prep_nr > prep_nr,
            )
        )
        return (
            int(previous) if previous is not None else None,
            int(following) if following is not None else None,
        )

    def get_preparation_stats(self, sample_nr: int) -> tuple[int, int]:
        total_count, max_prep_nr = self.session.execute(
            select(
                func.count(Preparation.prep_nr),
                func.max(Preparation.prep_nr),
            ).where(Preparation.sample_nr == sample_nr)
        ).one()
        return int(total_count or 0), int(max_prep_nr or 0)

    def count_targets_by_sample(self, sample_nr: int, prep_nr: int | None = None) -> int:
        stmt = select(func.count()).select_from(Target).where(Target.sample_nr == sample_nr)
        if prep_nr is not None:
            stmt = stmt.where(Target.prep_nr == prep_nr)
        return int(self.session.scalar(stmt) or 0)

    def list_targets_by_sample(
        self,
        sample_nr: int,
        prep_nr: int | None = None,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Target]:
        stmt = select(Target).where(Target.sample_nr == sample_nr)
        if prep_nr is not None:
            stmt = stmt.where(Target.prep_nr == prep_nr).order_by(Target.target_nr.asc())
        else:
            stmt = stmt.order_by(Target.prep_nr.asc(), Target.target_nr.asc())
        if offset > 0:
            stmt = stmt.offset(offset)
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get_target(self, sample_nr: int, prep_nr: int, target_nr: int) -> Target | None:
        stmt = select(Target).where(
            Target.sample_nr == sample_nr,
            Target.prep_nr == prep_nr,
            Target.target_nr == target_nr,
        )
        return self.session.scalar(stmt)

    def get_targets_for_batch_assignment(
        self,
        target_keys: Iterable[tuple[int, int, int]],
    ) -> list[Target]:
        keys = list(target_keys)
        if not keys:
            return []
        stmt = select(Target).where(
            tuple_(Target.sample_nr, Target.prep_nr, Target.target_nr).in_(keys)
        )
        return list(self.session.scalars(stmt))

    def get_adjacent_target_nrs(self, sample_nr: int, prep_nr: int, target_nr: int) -> tuple[int | None, int | None]:
        previous = self.session.scalar(
            select(func.max(Target.target_nr)).where(
                Target.sample_nr == sample_nr,
                Target.prep_nr == prep_nr,
                Target.target_nr < target_nr,
            )
        )
        following = self.session.scalar(
            select(func.min(Target.target_nr)).where(
                Target.sample_nr == sample_nr,
                Target.prep_nr == prep_nr,
                Target.target_nr > target_nr,
            )
        )
        return (
            int(previous) if previous is not None else None,
            int(following) if following is not None else None,
        )

    def get_target_stats(self, sample_nr: int, prep_nr: int) -> tuple[int, int]:
        total_count, max_target_nr = self.session.execute(
            select(
                func.count(Target.target_nr),
                func.max(Target.target_nr),
            ).where(
                Target.sample_nr == sample_nr,
                Target.prep_nr == prep_nr,
            )
        ).one()
        return int(total_count or 0), int(max_target_nr or 0)

    def list_targets_by_magazine(self, magazine_query: str) -> list[dict[str, Any]]:
        query = magazine_query.strip()
        if not query:
            return []

        stmt = (
            select(
                Target.position.label("position"),
                Target.sample_nr.label("sample_nr"),
                Target.prep_nr.label("prep_nr"),
                Target.target_nr.label("target_nr"),
                Sample.user_label.label("user_label"),
                Target.c14_age.label("c14_age"),
                Target.c14_age_sig.label("c14_age_sig"),
                Project.project_nr.label("project_nr"),
                Project.project.label("project"),
                Submitter.user_nr.label("user_nr"),
                Submitter.last_name.label("user_last_name"),
            )
            .select_from(Target)
            .join(Sample, Sample.sample_nr == Target.sample_nr, isouter=True)
            .join(Project, Project.project_nr == Sample.project_nr, isouter=True)
            .join(Submitter, Submitter.user_nr == Project.user_nr, isouter=True)
            .where(Target.magazine.is_not(None), func.lower(func.trim(Target.magazine)) == query.lower())
            .order_by(Target.position.asc(), Target.sample_nr.asc(), Target.prep_nr.asc(), Target.target_nr.asc())
        )
        rows = self.session.execute(stmt).mappings().all()
        return [dict(row) for row in rows]

    def list_magazines(self) -> list[str]:
        stmt = (
            select(Target.magazine)
            .where(Target.magazine.is_not(None), func.trim(Target.magazine) != "")
            .distinct()
            .order_by(Target.magazine.asc())
        )
        return [value for value in self.session.scalars(stmt) if value is not None]

    def resolve_existing_magazine(self, magazine_query: str) -> str | None:
        query = magazine_query.strip()
        if not query:
            return None
        stmt = (
            select(Target.magazine)
            .where(Target.magazine.is_not(None), func.lower(func.trim(Target.magazine)) == query.lower())
            .order_by(Target.magazine.asc())
            .limit(1)
        )
        value = self.session.scalar(stmt)
        return str(value).strip() if value is not None else None

    def count_targets_by_prep(self, sample_nr: int) -> dict[int, int]:
        stmt = (
            select(Target.prep_nr, func.count(Target.target_nr))
            .where(Target.sample_nr == sample_nr)
            .group_by(Target.prep_nr)
        )
        return {int(prep_nr): int(count) for prep_nr, count in self.session.execute(stmt).all()}

    def get_dashboard_counts(self, show_on_hold: bool = False) -> dict[str, int]:
        to_prep = self.list_to_prep_queues(show_on_hold=show_on_hold)
        return {
            **{key: len(rows) for key, rows in to_prep.items()},
            "in_prep": self._count_rows(self._sql_in_prep()),
            "waiting_for_graph": self._count_rows(self._sql_waiting_for_graph()),
            "waiting_for_meas": self._count_rows(self._sql_waiting_for_meas()),
            "waiting_express": self._count_rows(self._sql_waiting_express()),
        }

    def get_dashboard_tables(self, show_on_hold: bool = False) -> dict[str, list[dict[str, Any]]]:
        # Order is the dashboard's display order (Queue Tables pills and
        # panels): express first, because those samples jump the queue.
        return {
            "waiting_express": self._fetch_rows(self._sql_waiting_express()),
            **self.list_to_prep_queues(show_on_hold=show_on_hold),
            "in_prep": self._fetch_rows(self._sql_in_prep()),
            "waiting_for_graph": self._fetch_rows(self._sql_waiting_for_graph_table()),
            "waiting_for_meas": self._fetch_rows(self._sql_waiting_for_meas()),
        }

    def get_standard_counts(self) -> dict[str, int]:
        return {
            "oxas": self._count_scalar(
                """
                SELECT COUNT(*)
                FROM target_t
                INNER JOIN sample_t ON sample_t.sample_nr = target_t.sample_nr
                INNER JOIN project_t ON sample_t.project_nr = project_t.project_nr
                INNER JOIN user_t ON project_t.user_nr = user_t.user_nr
                WHERE target_t.magazine IS NULL
                  AND target_t.graphitized IS NOT NULL
                  AND target_t.stop = 0
                  AND sample_t.type LIKE :sample_type
                  AND sample_t.user_label LIKE :user_label
                  AND user_t.user_nr = 129
                """,
                {"sample_type": "oxa%", "user_label": "oxa%"},
            ),
            "blanks": self._count_scalar(
                """
                SELECT COUNT(*)
                FROM target_t
                INNER JOIN sample_t ON sample_t.sample_nr = target_t.sample_nr
                INNER JOIN project_t ON sample_t.project_nr = project_t.project_nr
                INNER JOIN user_t ON project_t.user_nr = user_t.user_nr
                WHERE target_t.magazine IS NULL
                  AND target_t.graphitized IS NOT NULL
                  AND target_t.stop = 0
                  AND sample_t.type LIKE :sample_type
                  AND sample_t.user_label LIKE :user_label
                  AND user_t.user_nr = 129
                """,
                {"sample_type": "blank%", "user_label": "Phthalic%"},
            ),
            "pferde": self._count_scalar(
                """
                SELECT COUNT(*)
                FROM target_t
                INNER JOIN sample_t ON sample_t.sample_nr = target_t.sample_nr
                INNER JOIN project_t ON sample_t.project_nr = project_t.project_nr
                INNER JOIN user_t ON project_t.user_nr = user_t.user_nr
                WHERE target_t.magazine IS NULL
                  AND target_t.graphitized IS NOT NULL
                  AND target_t.stop = 0
                  AND project_t.project_nr = 748
                """
            ),
            "iaea_c6": self._count_scalar(
                """
                SELECT COUNT(*)
                FROM target_t
                INNER JOIN sample_t ON sample_t.sample_nr = target_t.sample_nr
                INNER JOIN project_t ON sample_t.project_nr = project_t.project_nr
                INNER JOIN user_t ON project_t.user_nr = user_t.user_nr
                WHERE target_t.magazine IS NULL
                  AND target_t.graphitized IS NOT NULL
                  AND target_t.stop = 0
                  AND sample_t.type LIKE :sample_type
                """,
                {"sample_type": "C6"},
            ),
            "iaea_c7": self._count_scalar(
                """
                SELECT COUNT(*)
                FROM target_t
                INNER JOIN sample_t ON sample_t.sample_nr = target_t.sample_nr
                INNER JOIN project_t ON sample_t.project_nr = project_t.project_nr
                INNER JOIN user_t ON project_t.user_nr = user_t.user_nr
                WHERE target_t.magazine IS NULL
                  AND target_t.graphitized IS NOT NULL
                  AND target_t.stop = 0
                  AND sample_t.type LIKE :sample_type
                """,
                {"sample_type": "C7"},
            ),
            "iaea_c8": self._count_scalar(
                """
                SELECT COUNT(*)
                FROM target_t
                INNER JOIN sample_t ON sample_t.sample_nr = target_t.sample_nr
                INNER JOIN project_t ON sample_t.project_nr = project_t.project_nr
                INNER JOIN user_t ON project_t.user_nr = user_t.user_nr
                WHERE target_t.magazine IS NULL
                  AND target_t.graphitized IS NOT NULL
                  AND target_t.stop = 0
                  AND sample_t.type LIKE :sample_type
                """,
                {"sample_type": "C8"},
            ),
        }

    # Material / fraction / type lists are alphabetical everywhere: the
    # legacy `indexnr` is insertion order and means nothing to an operator.
    def get_materials(self) -> list[str]:
        stmt = text("SELECT material FROM material_t ORDER BY material")
        return [row[0] for row in self.session.execute(stmt).all()]

    def get_fractions(self) -> list[str]:
        stmt = text("SELECT fraction FROM fraction_t ORDER BY fraction")
        return [row[0] for row in self.session.execute(stmt).all()]

    def get_methods(self) -> list[str]:
        stmt = select(Method.method).order_by(
            case((Method.indexnr.is_(None), 1), else_=0).asc(),
            Method.indexnr.asc(),
            Method.method.asc(),
        )
        return [row[0] for row in self.session.execute(stmt).all()]

    def get_sample_types(self) -> list[str]:
        stmt = select(SampleType.type).order_by(SampleType.type.asc())
        return [row[0] for row in self.session.execute(stmt).all()]

    def get_project_statuses(self) -> list[str]:
        stmt = text(
            """
            SELECT status
            FROM projectstatus_t
            ORDER BY
              CASE WHEN indexnr IS NULL THEN 1 ELSE 0 END ASC,
              indexnr ASC,
              status ASC
            """
        )
        return [row[0] for row in self.session.execute(stmt).all() if row[0] is not None]

    def get_project_types(self) -> list[str]:
        stmt = text(
            """
            SELECT type
            FROM projecttype_t
            ORDER BY
              CASE WHEN indexnr IS NULL THEN 1 ELSE 0 END ASC,
              indexnr ASC,
              type ASC
            """
        )
        return [row[0] for row in self.session.execute(stmt).all() if row[0] is not None]

    def search_table(
        self, table: str, fields: tuple[str, ...], phrase: str, limit: int
    ) -> list[dict[str, Any]]:
        """Rows of `table` whose `fields`, joined, contain `phrase`.

        `table` and `fields` come only from the static `SEARCH_CONTEXTS`
        registry in search.py, never from the request, so interpolating
        them is safe; the user's phrase is always a bound parameter.
        """
        stmt = text(
            f"""
            SELECT *
            FROM {table}
            WHERE CONCAT_WS(';',{",".join(fields)}) LIKE :phrase
            LIMIT :limit
            """
        )
        rows = self.session.execute(stmt, {"phrase": f"%{phrase}%", "limit": limit}).mappings().all()
        return [dict(row) for row in rows]

    def get_research_values(self) -> list[str]:
        stmt = text(
            """
            SELECT research
            FROM research_t
            ORDER BY
              CASE WHEN indexnr IS NULL THEN 1 ELSE 0 END ASC,
              indexnr ASC,
              research ASC
            """
        )
        return [row[0] for row in self.session.execute(stmt).all() if row[0] is not None]

    def get_report_types(self) -> list[str]:
        stmt = text(
            """
            SELECT type
            FROM reporttype_t
            ORDER BY
              CASE WHEN indexnr IS NULL THEN 1 ELSE 0 END ASC,
              indexnr ASC,
              type ASC
            """
        )
        return [row[0] for row in self.session.execute(stmt).all() if row[0] is not None]

    def get_advisors(self) -> list[str]:
        """Supervisors/advisors from `advisor_t`, used for `project_t.supervisor`."""
        stmt = text(
            """
            SELECT advisor
            FROM advisor_t
            ORDER BY
              CASE WHEN indexnr IS NULL THEN 1 ELSE 0 END ASC,
              indexnr ASC,
              advisor ASC
            """
        )
        return [row[0] for row in self.session.execute(stmt).all() if row[0] is not None]

    def find_projects_for_submitter(self, user_nr: int, limit: int = 60) -> list[Project]:
        """Projects already owned by a submitter, newest first.

        Feeds the import wizard's duplicate-project check: an operator
        importing a second batch for the same customer should be able to
        append to the running project instead of creating a near-duplicate.
        """
        stmt = (
            select(Project)
            .where(Project.user_nr == user_nr)
            .order_by(
                case((Project.in_date.is_(None), 1), else_=0).asc(),
                Project.in_date.desc(),
                Project.project_nr.desc(),
            )
            .limit(limit)
        )
        return list(self.session.scalars(stmt))

    def get_projects_in_progress(
        self,
        *,
        days_window: int = 300,
        include_internal: bool = False,
    ) -> list[dict[str, Any]]:
        safe_days_window = max(days_window, 1)
        cutoff_date = date.today() - timedelta(days=safe_days_window)
        stmt = text(
            """
            SELECT
              p.project,
              u.last_name,
              u.first_name,
              p.in_date,
              p.desired_date,
              p.project_nr,
              u.user_nr,
              COALESCE(sc.samples, 0) AS samples,
              COALESCE(pc.discPrep, 0) AS discPrep,
              COALESCE(pc.prepDone, 0) AS prepDone,
              COALESCE(tc.discTarget, 0) AS discTarget,
              COALESCE(tc.graphDone, 0) AS graphDone,
              COALESCE(tc.inMagazine, 0) AS inMagazine,
              COALESCE(sc.measured, 0) AS measured
            FROM project_t p
            INNER JOIN user_t u ON p.user_nr = u.user_nr
            LEFT JOIN (
              SELECT
                project_nr,
                SUM(CASE WHEN c14_age IS NOT NULL THEN 1 ELSE 0 END) AS measured,
                SUM(CASE WHEN not_tobedated = 0 THEN 1 ELSE 0 END) AS samples
              FROM sample_t
              GROUP BY project_nr
            ) sc ON p.project_nr = sc.project_nr
            LEFT JOIN (
              SELECT
                s.project_nr,
                SUM(CASE WHEN prep.stop = 1 THEN 1 ELSE 0 END) AS discPrep,
                SUM(CASE WHEN prep.prep_end IS NOT NULL THEN 1 ELSE 0 END) AS prepDone
              FROM preparation_t prep
              INNER JOIN sample_t s ON prep.sample_nr = s.sample_nr
              GROUP BY s.project_nr
            ) pc ON p.project_nr = pc.project_nr
            LEFT JOIN (
              SELECT
                s.project_nr,
                SUM(CASE WHEN tgt.stop = 1 THEN 1 ELSE 0 END) AS discTarget,
                SUM(CASE WHEN tgt.graphitized IS NOT NULL THEN 1 ELSE 0 END) AS graphDone,
                SUM(CASE WHEN tgt.magazine IS NOT NULL THEN 1 ELSE 0 END) AS inMagazine
              FROM target_t tgt
              INNER JOIN sample_t s ON tgt.sample_nr = s.sample_nr
              GROUP BY s.project_nr
            ) tc ON p.project_nr = tc.project_nr
            WHERE p.in_date > :cutoff_date
              AND (p.out_date IS NULL OR p.out_date < :legacy_open_cutoff)
              AND (:include_internal = 1 OR NOT (u.last_name = 'intern' AND u.first_name = 'intern'))
            ORDER BY p.desired_date, p.project_nr
            """
        )
        rows = self.session.execute(
            stmt,
            {
                "cutoff_date": cutoff_date,
                "legacy_open_cutoff": date(2010, 1, 1),
                "include_internal": 1 if include_internal else 0,
            },
        ).mappings().all()
        return [dict(row) for row in rows]

    def set_project_running_by_sample(self, sample_nr: int) -> bool:
        project_nr = self.session.scalar(select(Sample.project_nr).where(Sample.sample_nr == sample_nr))
        if project_nr is None:
            return False
        project = self.get_project(project_nr)
        if project is None:
            return False
        project.status = "running"
        self.session.flush()
        return True

    def transfer_age_from_target(self, sample_nr: int, prep_nr: int = 1, target_nr: int = 1) -> bool:
        target = self.session.scalar(
            select(Target).where(
                Target.sample_nr == sample_nr,
                Target.prep_nr == prep_nr,
                Target.target_nr == target_nr,
            )
        )
        sample = self.get_sample(sample_nr)
        if target is None or sample is None:
            return False

        sample.c14_age = target.c14_age
        sample.c14_age_sig = target.c14_age_sig
        sample.av_fm = target.fm
        sample.av_fm_sig = target.fm_sig
        sample.av_dc13 = target.dc13
        sample.cal1s_min = target.cal1s_min
        sample.cal1s_max = target.cal1s_max
        sample.cal2s_min = target.cal2s_min
        sample.cal2s_max = target.cal2s_max
        self.session.flush()
        return True

    def check_project_status(self) -> int:
        """Close projects whose `out_date` is set but status is not yet `closed`.

        Per ADR-0004, delivery (`out_date`) is the trigger for closure;
        `prepaid` projects are skipped because that value is a billing
        flag, not a workflow state.
        """
        result = self.session.execute(
            text(
                """
                UPDATE project_t
                SET status = 'closed'
                WHERE out_date IS NOT NULL
                  AND (status IS NULL OR LOWER(status) <> 'closed')
                  AND (status IS NULL OR LOWER(status) <> 'prepaid')
                """
            )
        )
        self.session.flush()
        return int(result.rowcount or 0)

    def _count_rows(self, sql: str) -> int:
        rows = self._fetch_rows(sql)
        return len(rows)

    def _count_scalar(self, sql: str, params: dict[str, Any] | None = None) -> int:
        value = self.session.scalar(text(sql), params or {})
        return int(value or 0)

    def _fetch_rows(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = self.session.execute(text(sql), params or {}).mappings().all()
        return [dict(row) for row in result]

    @staticmethod
    def _sql_in_prep() -> str:
        return """
        SELECT sample_t.sample_nr, preparation_t.prep_nr, user_label, project_t.project, sample_t.material, user_t.last_name,
               project_t.desired_date, project_t.project_nr, user_t.user_nr,
               DATEDIFF(CURDATE(), preparation_t.prep_start) AS days_in_prep,
               NOT ISNULL(weight_medium) AS in_freeze
        FROM sample_t
        INNER JOIN project_t ON project_t.project_nr = sample_t.project_nr
        INNER JOIN user_t ON user_t.user_nr = project_t.user_nr
        INNER JOIN preparation_t ON preparation_t.sample_nr = sample_t.sample_nr
        WHERE preparation_t.prep_start IS NOT NULL
          AND preparation_t.prep_end IS NULL
          AND preparation_t.stop = 0
        ORDER BY sample_t.sample_nr
        """

    @staticmethod
    def _sql_planned(show_on_hold: bool = False, by_material: bool = False) -> str:
        """Unprepared samples (*To prep all*). With `by_material` the query
        also filters on the bound `:material` parameter (*To prep bone*, …)."""
        sql = """
        SELECT sample_t.sample_nr, preparation_t.prep_nr, user_label, project_t.project, sample_t.material, user_t.last_name,
               project_t.desired_date, project_t.project_nr, user_t.user_nr
        FROM sample_t
        INNER JOIN project_t ON project_t.project_nr = sample_t.project_nr
        INNER JOIN user_t ON user_t.user_nr = project_t.user_nr
        INNER JOIN preparation_t ON preparation_t.sample_nr = sample_t.sample_nr
        WHERE sample_t.sample_nr > 9999
          AND preparation_t.step1_start IS NULL
          AND preparation_t.prep_end IS NULL
          AND sample_t.c14_age IS NULL
          AND sample_t.material <> 'graphite'
          AND preparation_t.stop = 0
          AND preparation_t.prep_start IS NULL
        """
        sql += " AND sample_t.not_tobedated = 1" if show_on_hold else " AND sample_t.not_tobedated = 0"
        if by_material:
            sql += " AND sample_t.material = :material"
        sql += " ORDER BY sample_t.sample_nr, preparation_t.prep_nr"
        return sql

    @staticmethod
    def _sql_waiting_for_graph() -> str:
        return """
        SELECT DISTINCT sample_t.sample_nr, user_label, project_t.project, sample_t.material,
               user_t.last_name, user_t.first_name, project_t.desired_date
        FROM sample_t
        INNER JOIN project_t ON project_t.project_nr = sample_t.project_nr
        INNER JOIN user_t ON user_t.user_nr = project_t.user_nr
        INNER JOIN preparation_t ON preparation_t.sample_nr = sample_t.sample_nr
        INNER JOIN target_t ON target_t.sample_nr = sample_t.sample_nr
        WHERE preparation_t.prep_end IS NOT NULL
          AND target_t.graphitized IS NULL
          AND target_t.target_pressed IS NULL
          AND target_t.calcset IS NULL
          AND sample_t.not_tobedated = 0
          AND preparation_t.stop = 0
          AND target_t.stop = 0
          AND project_t.out_date IS NULL
          AND sample_t.type NOT LIKE 'oxa%'
          AND NOT (user_t.last_name = 'intern' AND user_t.first_name = 'intern')
        ORDER BY sample_t.sample_nr
        """

    @staticmethod
    def _sql_waiting_for_graph_table() -> str:
        return """
        SELECT sample_t.sample_nr, target_t.prep_nr, target_t.target_nr, user_label,
               project_t.project, sample_t.material,
               user_t.last_name, user_t.first_name, project_t.desired_date,
               project_t.project_nr, user_t.user_nr
        FROM sample_t
        INNER JOIN project_t ON project_t.project_nr = sample_t.project_nr
        INNER JOIN user_t ON user_t.user_nr = project_t.user_nr
        INNER JOIN target_t ON target_t.sample_nr = sample_t.sample_nr
        INNER JOIN preparation_t ON preparation_t.sample_nr = target_t.sample_nr
                                 AND preparation_t.prep_nr = target_t.prep_nr
        WHERE preparation_t.prep_end IS NOT NULL
          AND target_t.graphitized IS NULL
          AND target_t.target_pressed IS NULL
          AND target_t.calcset IS NULL
          AND sample_t.not_tobedated = 0
          AND preparation_t.stop = 0
          AND target_t.stop = 0
          AND project_t.out_date IS NULL
          AND sample_t.type NOT LIKE 'oxa%'
          AND NOT (user_t.last_name = 'intern' AND user_t.first_name = 'intern')
        ORDER BY sample_t.sample_nr, target_t.prep_nr, target_t.target_nr
        """

    @staticmethod
    def _sql_waiting_for_meas() -> str:
        return """
        SELECT target_id, type, user_label, user_label_nr, last_name, target_comment,
               co2_final, target_p.desired_date,
               DATEDIFF(target_p.desired_date, CURDATE()) AS days_to_deadline,
               target_p.sample_nr, target_p.prep_nr, target_p.target_nr,
               target_p.project_nr, project_t.user_nr
        FROM target_p
        LEFT JOIN project_t ON project_t.project_nr = target_p.project_nr
        WHERE target_p.sample_nr >= 10000
          AND target_p.graphitized IS NOT NULL
          AND target_p.magazine IS NULL
          AND target_p.target_stop = 0
          AND target_p.not_tobedated = 0
          AND target_p.project_nr NOT IN ('798', '129', '767', '795', '1032', '1083', '1174', '1658', '1759', '2295')
          AND target_p.type NOT IN ('oxa2', 'blank', 'C1', 'C2', 'C3', 'C6', 'C7', 'C8')
        ORDER BY target_id
        """

    @staticmethod
    def _sql_waiting_express() -> str:
        return """
        SELECT DISTINCT sample_t.sample_nr, user_t.last_name, user_label, target_t.graphitized,
               project_t.desired_date, target_t.magazine, project_t.project_nr, user_t.user_nr
        FROM sample_t
        INNER JOIN project_t ON project_t.project_nr = sample_t.project_nr
        INNER JOIN user_t ON user_t.user_nr = project_t.user_nr
        INNER JOIN preparation_t ON preparation_t.sample_nr = sample_t.sample_nr
        INNER JOIN target_t ON target_t.sample_nr = sample_t.sample_nr
        WHERE sample_t.user_label LIKE '%eil%'
          AND target_t.calcset IS NULL
          AND sample_t.not_tobedated = 0
          AND preparation_t.stop = 0
          AND target_t.stop = 0
          AND (project_t.out_date < '1900-01-01' OR project_t.out_date IS NULL)
        ORDER BY sample_t.sample_nr
        """

    # ---- Quality control: EA checks + generic QC sign-off --------------------
    # Tables created by hand on the server (ADR-0005). `qc_tables_available`
    # lets pages degrade to a "not set up yet" notice instead of a 500 while
    # they do not exist.

    QC_TABLES = ("ea_check_t", "qc_signoff_t", "qc_signoff_item_t")
    # Columns that a table created from an earlier version of the DDL may
    # lack (weight_mg came after the first test install). A missing one is
    # reported as "table.column" instead of failing in the ORM.
    QC_LATER_COLUMNS = {"ea_check_t": ("weight_mg",)}

    def missing_qc_tables(self) -> list[str]:
        missing: list[str] = []
        for table in self.QC_TABLES:
            if not self._qc_probe(f"SELECT 1 FROM {table} WHERE 1 = 0"):
                missing.append(table)
                continue
            for column in self.QC_LATER_COLUMNS.get(table, ()):
                if not self._qc_probe(f"SELECT {column} FROM {table} WHERE 1 = 0"):
                    missing.append(f"{table}.{column}")
        return missing

    def _qc_probe(self, sql: str) -> bool:
        try:
            self.session.execute(text(sql))
        except DBAPIError:
            self.session.rollback()
            return False
        return True

    def add_ea_check(self, payload: dict[str, Any]) -> EaCheck:
        check = EaCheck(**payload)
        self.session.add(check)
        self.session.flush()
        return check

    def get_ea_check(self, check_id: int) -> EaCheck | None:
        return self.session.get(EaCheck, check_id)

    def list_ea_checks(
        self,
        *,
        ea: str | None = None,
        standard: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        include_voided: bool = True,
    ) -> list[EaCheck]:
        stmt = select(EaCheck)
        if ea:
            stmt = stmt.where(EaCheck.ea == ea)
        if standard:
            stmt = stmt.where(EaCheck.standard == standard)
        if since is not None:
            stmt = stmt.where(EaCheck.checked_at >= since)
        if until is not None:
            stmt = stmt.where(EaCheck.checked_at <= until)
        if not include_voided:
            stmt = stmt.where(EaCheck.voided == 0)
        stmt = stmt.order_by(EaCheck.checked_at.asc(), EaCheck.id.asc())
        return list(self.session.scalars(stmt))

    def latest_ea_checks(self, *, ea: str, standard: str, limit: int) -> list[EaCheck]:
        """The most recent non-voided checks, oldest first."""
        stmt = (
            select(EaCheck)
            .where(EaCheck.ea == ea, EaCheck.standard == standard, EaCheck.voided == 0)
            .order_by(EaCheck.checked_at.desc(), EaCheck.id.desc())
            .limit(limit)
        )
        return list(reversed(list(self.session.scalars(stmt))))

    def ea_standards_in_use(self) -> set[str]:
        return {str(v) for v in self.session.scalars(select(EaCheck.standard).distinct())}

    def void_ea_check(self, check: EaCheck, *, reason: str, by: str, at: datetime) -> None:
        check.voided = 1
        check.void_reason = reason
        check.voided_by = by
        check.voided_at = at
        self.session.flush()

    def oldest_unsigned_ea_check_at(self, item_type: str) -> dict[str, datetime]:
        """Per EA: when the oldest non-voided, not-yet-signed check was made."""
        signed = exists().where(
            QcSignoffItem.item_type == item_type,
            QcSignoffItem.item_ref == cast(EaCheck.id, String),
        )
        stmt = (
            select(EaCheck.ea, func.min(EaCheck.checked_at))
            .where(EaCheck.voided == 0, ~signed)
            .group_by(EaCheck.ea)
        )
        return {str(ea): at for ea, at in self.session.execute(stmt) if at is not None}

    def signed_item_refs(self, item_type: str, refs: Iterable[str] | None = None) -> dict[str, int]:
        """`item_ref -> signoff_id` for the signed items of a type
        (restricted to `refs` when given)."""
        stmt = select(QcSignoffItem.item_ref, QcSignoffItem.signoff_id).where(
            QcSignoffItem.item_type == item_type
        )
        if refs is not None:
            ref_list = list(refs)
            if not ref_list:
                return {}
            stmt = stmt.where(QcSignoffItem.item_ref.in_(ref_list))
        return {str(ref): int(sid) for ref, sid in self.session.execute(stmt)}

    def create_qc_signoff(
        self,
        payload: dict[str, Any],
        *,
        item_type: str,
        item_refs: list[str],
    ) -> QcSignoff:
        signoff = QcSignoff(**payload)
        self.session.add(signoff)
        self.session.flush()
        for ref in item_refs:
            self.session.add(QcSignoffItem(signoff_id=signoff.id, item_type=item_type, item_ref=ref))
        self.session.flush()
        return signoff

    def list_qc_signoffs(
        self,
        *,
        subject_type: str | None = None,
        subject_key: str | None = None,
    ) -> list[QcSignoff]:
        stmt = select(QcSignoff)
        if subject_type:
            stmt = stmt.where(QcSignoff.subject_type == subject_type)
        if subject_key:
            stmt = stmt.where(QcSignoff.subject_key == subject_key)
        stmt = stmt.order_by(QcSignoff.signed_at.desc(), QcSignoff.id.desc())
        return list(self.session.scalars(stmt))

    def get_qc_signoff(self, signoff_id: int) -> QcSignoff | None:
        return self.session.get(QcSignoff, signoff_id)

    def list_qc_signoff_item_refs(self, signoff_id: int) -> list[str]:
        stmt = select(QcSignoffItem.item_ref).where(QcSignoffItem.signoff_id == signoff_id)
        return [str(ref) for ref in self.session.scalars(stmt)]

