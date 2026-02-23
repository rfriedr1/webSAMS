"""Database repository classes for SAMS."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy import and_, case, func, select, text, tuple_
from sqlalchemy.orm import Session, selectinload

from sams_web.models import (
    Method,
    Preparation,
    Project,
    Sample,
    SampleType,
    Target,
    User,
)


@dataclass
class SearchContext:
    table: str
    fields: tuple[str, ...]


SEARCH_CONTEXTS: dict[str, SearchContext] = {
    "users": SearchContext(
        table="user_t",
        fields=(
            "user_nr",
            "last_name",
            "first_name",
            "organisation",
            "address_1",
            "address_2",
            "town",
            "country",
            "institute",
            "postcode",
            "phone_1",
            "phone_2",
            "email",
            "account",
            "user_comment",
        ),
    ),
    "projects": SearchContext(
        table="project_t",
        fields=(
            "project_nr",
            "project",
            "user_nr",
            "in_date",
            "out_date",
            "invoice",
            "AuftragsNr",
            "order_nr",
            "invoice_nr",
            "letter",
            "project_comment",
            "report",
            "sample_storage_loc",
        ),
    ),
    "samples": SearchContext(
        table="sample_t",
        fields=(
            "sample_nr",
            "project_nr",
            "type",
            "material",
            "fraction",
            "weight",
            "sampling_date",
            "user_label",
            "user_label_nr",
            "user_desc1",
            "user_desc2",
            "MA_nr",
            "lab_comment",
            "user_comment",
            "prep_storage_loc",
            "storage",
        ),
    ),
    "preparations": SearchContext(
        table="preparation_t",
        fields=(
            "sample_nr",
            "prep_nr",
            "batch",
            "cn_ratio",
            "c_percent",
            "n_percent",
            "prep_end",
            "prep_start",
            "prep_comment",
        ),
    ),
    "targets": SearchContext(
        table="target_t",
        fields=(
            "sample_nr",
            "target_nr",
            "prep_nr",
            "magazine",
            "position",
            "target_comment",
            "meas_comment",
            "graph_batch",
            "weight",
            "conc_c",
            "target_id",
        ),
    ),
}


class SamsRepository:
    """DB repository mirroring core `_dm.pas` data functions."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def list_users(self, query: str | None = None, limit: int | None = None) -> list[User]:
        stmt = select(User).order_by(
            case((User.last_name.is_(None), 1), else_=0).asc(),
            User.last_name.asc(),
            case((User.first_name.is_(None), 1), else_=0).asc(),
            User.first_name.asc(),
        )
        if query:
            like = f"%{query}%"
            stmt = stmt.where(
                User.last_name.like(like)
                | User.first_name.like(like)
                | User.organisation.like(like)
                | User.institute.like(like)
            )
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

    def get_user(self, user_nr: int) -> User | None:
        return self.session.get(User, user_nr)

    def get_adjacent_user_nrs(self, user_nr: int) -> tuple[int | None, int | None]:
        previous = self.session.scalar(
            select(func.max(User.user_nr)).where(User.user_nr < user_nr)
        )
        following = self.session.scalar(
            select(func.min(User.user_nr)).where(User.user_nr > user_nr)
        )
        return (
            int(previous) if previous is not None else None,
            int(following) if following is not None else None,
        )

    def get_user_stats(self) -> tuple[int, int]:
        total_count, max_user_nr = self.session.execute(
            select(
                func.count(User.user_nr),
                func.max(User.user_nr),
            )
        ).one()
        return int(total_count or 0), int(max_user_nr or 0)

    def create_user(self, payload: dict[str, Any]) -> User:
        user = User(**payload)
        self.session.add(user)
        self.session.flush()
        return user

    def list_projects_by_user(self, user_nr: int) -> list[Project]:
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

    def list_projects(self, limit: int | None = None) -> list[Project]:
        stmt = select(Project).options(selectinload(Project.user)).order_by(
            case((Project.in_date.is_(None), 1), else_=0).asc(),
            Project.in_date.desc(),
            Project.project_nr.desc(),
        )
        if limit is not None and limit > 0:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt))

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
        prep = Preparation(sample_nr=sample_nr, prep_nr=prep_nr)
        self.session.add(prep)
        self.session.flush()
        return prep

    def create_blank_target(self, sample_nr: int, prep_nr: int = 1, target_nr: int = 1) -> Target:
        target = Target(sample_nr=sample_nr, prep_nr=prep_nr, target_nr=target_nr)
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

    def list_planned_queue_rows(self, show_on_hold: bool = False) -> list[dict[str, Any]]:
        return self._fetch_rows(self._sql_planned(show_on_hold=show_on_hold))

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
                Project.project_nr.label("project_nr"),
                Project.project.label("project"),
                User.user_nr.label("user_nr"),
                User.last_name.label("user_last_name"),
            )
            .select_from(Target)
            .join(Sample, Sample.sample_nr == Target.sample_nr, isouter=True)
            .join(Project, Project.project_nr == Sample.project_nr, isouter=True)
            .join(User, User.user_nr == Project.user_nr, isouter=True)
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

    def global_search(self, context: str, phrase: str, limit: int = 200) -> list[dict[str, Any]]:
        ctx = SEARCH_CONTEXTS.get(context)
        if ctx is None:
            raise ValueError(f"Unsupported search context: {context}")

        concat_fields = ",".join(ctx.fields)
        stmt = text(
            f"""
            SELECT *
            FROM {ctx.table}
            WHERE CONCAT_WS(';',{concat_fields}) LIKE :phrase
            LIMIT :limit
            """
        )
        rows = self.session.execute(stmt, {"phrase": f"%{phrase}%", "limit": limit}).mappings().all()
        return [dict(row) for row in rows]

    def get_dashboard_counts(self, show_on_hold: bool = False) -> dict[str, int]:
        return {
            "planned": self._count_rows(self._sql_planned(show_on_hold=show_on_hold)),
            "in_prep": self._count_rows(self._sql_in_prep()),
            "waiting_for_graph": self._count_rows(self._sql_waiting_for_graph()),
            "waiting_for_meas": self._count_rows(self._sql_waiting_for_meas()),
            "waiting_express": self._count_rows(self._sql_waiting_express()),
        }

    def get_dashboard_tables(self, show_on_hold: bool = False) -> dict[str, list[dict[str, Any]]]:
        return {
            "planned": self._fetch_rows(self._sql_planned(show_on_hold=show_on_hold)),
            "in_prep": self._fetch_rows(self._sql_in_prep()),
            "waiting_for_graph": self._fetch_rows(self._sql_waiting_for_graph_table()),
            "waiting_for_meas": self._fetch_rows(self._sql_waiting_for_meas()),
            "waiting_express": self._fetch_rows(self._sql_waiting_express()),
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

    def get_materials(self) -> list[str]:
        stmt = text("SELECT material FROM material_t ORDER BY indexnr")
        return [row[0] for row in self.session.execute(stmt).all()]

    def get_fractions(self) -> list[str]:
        stmt = text("SELECT fraction FROM fraction_t ORDER BY indexnr")
        return [row[0] for row in self.session.execute(stmt).all()]

    def get_methods(self) -> list[str]:
        stmt = select(Method.method).order_by(
            case((Method.indexnr.is_(None), 1), else_=0).asc(),
            Method.indexnr.asc(),
            Method.method.asc(),
        )
        return [row[0] for row in self.session.execute(stmt).all()]

    def get_sample_types(self) -> list[str]:
        stmt = select(SampleType.type).order_by(
            case((SampleType.indexnr.is_(None), 1), else_=0).asc(),
            SampleType.indexnr.asc(),
            SampleType.type.asc(),
        )
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
        """Close projects where all non-discarded samples have ages."""
        closed = 0
        open_projects = self._fetch_rows(
            "SELECT project_nr FROM project_t WHERE status <> 'closed'"
        )
        for row in open_projects:
            project_nr = row["project_nr"]
            pending = self.session.scalar(
                text(
                    """
                    SELECT COUNT(1)
                    FROM sample_t
                    INNER JOIN preparation_t ON preparation_t.sample_nr = sample_t.sample_nr
                    INNER JOIN target_t ON target_t.sample_nr = sample_t.sample_nr
                    WHERE sample_t.project_nr = :project_nr
                      AND preparation_t.stop = 0
                      AND target_t.stop = 0
                      AND sample_t.c14_age IS NULL
                    """
                ),
                {"project_nr": project_nr},
            )
            if int(pending or 0) == 0:
                self.session.execute(
                    text("UPDATE project_t SET status='closed' WHERE project_nr=:project_nr"),
                    {"project_nr": project_nr},
                )
                closed += 1
        self.session.flush()
        return closed

    def _count_rows(self, sql: str) -> int:
        rows = self._fetch_rows(sql)
        return len(rows)

    def _count_scalar(self, sql: str, params: dict[str, Any] | None = None) -> int:
        value = self.session.scalar(text(sql), params or {})
        return int(value or 0)

    def _fetch_rows(self, sql: str) -> list[dict[str, Any]]:
        result = self.session.execute(text(sql)).mappings().all()
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
    def _sql_planned(show_on_hold: bool = False, material: str = "none") -> str:
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
        if material != "none":
            sql += f" AND sample_t.material = '{material}'"
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
