"""One project's history: its experiments running now, its plans, its past experiments.

Read-only. An experiment runs now while its cell is In use with the same data
filename; every other one is past.
"""

from src.data.db import get_db, DatabaseError, to_text, hours_text
from src.data.projects_manager import ProjectsManager


class ProjectHistory:
    def __init__(self, db=None):
        self._db = db or get_db()
        self.projects = ProjectsManager(self._db)

    def experiments(self, project: str) -> tuple[list, list]:
        """(running, past) experiments of ``project``, newest first."""
        rows = self._db.fetch_all(
            "SELECT h.channel, h.status, h.current_owner, h.start_date, h.end_date,"
            " h.expected_end_date, h.data_filename,"
            " CASE WHEN c.channel IS NULL THEN 0 ELSE 1 END AS running"
            " FROM icm.channel_history h"
            " LEFT JOIN icm.cells c ON c.channel = h.channel"
            "  AND c.data_filename = h.data_filename AND c.status = 'In use'"
            " WHERE h.project_id = ? ORDER BY h.start_date DESC, h.id DESC", (project,))
        running, past = [], []
        for r in rows:
            entry = {k: to_text(v) for k, v in r.items() if k != "running"}
            (running if r.get("running") else past).append(entry)
        return running, past

    def plans(self, project: str) -> list:
        """The project's pending and scheduled plans (schedule order first)."""
        try:
            rows = self._db.fetch_all(
                "SELECT name, status, urgency, test_length_h, channel FROM icm.experiment_plan"
                " WHERE project_id = ? AND status IN ('pending', 'scheduled')"
                " ORDER BY CASE status WHEN 'scheduled' THEN 0 ELSE 1 END, priority, id",
                (project,))
        except DatabaseError:
            return []  # no plans table before migration 023
        return [{**{k: to_text(v) for k, v in r.items()},
                 "test_length_h": hours_text(r.get("test_length_h"))} for r in rows]
