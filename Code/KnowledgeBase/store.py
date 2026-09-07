"""真实故事、Function 演化、Pattern 与大纲的统一 SQLite 知识库。"""

import hashlib
import json
import sqlite3
from pathlib import Path

from Contracts.snapshot import (
    load_function_contracts,
    load_occurrences,
    load_snapshot,
    load_story_profiles as load_snapshot_story_profiles,
)
from Contracts.run_result import failed_run_result
from Contracts.story_profile import StoryProfile
from Contracts.versioning import observation_version_id, story_version_id


DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "knowledge" / "story_knowledge.db"

_PATTERN_USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pattern_usage (
    usage_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_id  TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    claimed_at  TEXT NOT NULL,
    outline_id  TEXT,
    FOREIGN KEY (snapshot_id, pattern_id) REFERENCES patterns(snapshot_id, pattern_id),
    FOREIGN KEY (outline_id) REFERENCES outlines(outline_id)
);
"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id        TEXT PRIMARY KEY,
    parent_snapshot_id TEXT REFERENCES snapshots(snapshot_id),
    schema_version     INTEGER NOT NULL,
    source_workflow    TEXT NOT NULL,
    namespace          TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    payload_json       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS serving_snapshots (
    pointer_id  INTEGER PRIMARY KEY CHECK (pointer_id = 1),
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    promoted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id             TEXT PRIMARY KEY,
    workflow           TEXT NOT NULL CHECK (workflow IN ('bootstrap', 'evolve')),
    namespace          TEXT NOT NULL,
    parent_snapshot_id TEXT REFERENCES snapshots(snapshot_id),
    snapshot_id        TEXT UNIQUE REFERENCES snapshots(snapshot_id),
    status             TEXT NOT NULL CHECK (status IN ('RUNNING', 'PASS', 'FAIL')),
    corpus_dir         TEXT,
    created_at         TEXT NOT NULL,
    completed_at       TEXT,
    payload_json       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stories (
    story_id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS story_versions (
    story_version_id TEXT PRIMARY KEY,
    story_id         TEXT NOT NULL REFERENCES stories(story_id),
    content_sha256   TEXT NOT NULL,
    title            TEXT,
    category         TEXT,
    source_file      TEXT,
    text_content     TEXT NOT NULL,
    created_by_run_id TEXT NOT NULL REFERENCES pipeline_runs(run_id),
    payload_json     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_stories (
    run_id           TEXT NOT NULL REFERENCES pipeline_runs(run_id),
    story_id         TEXT NOT NULL REFERENCES stories(story_id),
    story_version_id TEXT NOT NULL REFERENCES story_versions(story_version_id),
    position         INTEGER NOT NULL,
    PRIMARY KEY (run_id, story_id)
);

CREATE TABLE IF NOT EXISTS observations (
    obs_id   TEXT PRIMARY KEY,
    story_id TEXT NOT NULL REFERENCES stories(story_id)
);

CREATE TABLE IF NOT EXISTS observation_versions (
    observation_version_id TEXT PRIMARY KEY,
    obs_id                 TEXT NOT NULL REFERENCES observations(obs_id),
    story_version_id       TEXT NOT NULL REFERENCES story_versions(story_version_id),
    created_by_run_id      TEXT NOT NULL REFERENCES pipeline_runs(run_id),
    observation_order      INTEGER NOT NULL,
    payload_json           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_observations (
    run_id                 TEXT NOT NULL REFERENCES pipeline_runs(run_id),
    obs_id                 TEXT NOT NULL REFERENCES observations(obs_id),
    observation_version_id TEXT NOT NULL REFERENCES observation_versions(observation_version_id),
    PRIMARY KEY (run_id, obs_id)
);

CREATE TABLE IF NOT EXISTS snapshot_story_versions (
    snapshot_id      TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    story_id         TEXT NOT NULL REFERENCES stories(story_id),
    story_version_id TEXT NOT NULL REFERENCES story_versions(story_version_id),
    position         INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, story_id)
);

CREATE TABLE IF NOT EXISTS snapshot_observation_versions (
    snapshot_id            TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    obs_id                 TEXT NOT NULL REFERENCES observations(obs_id),
    observation_version_id TEXT NOT NULL REFERENCES observation_versions(observation_version_id),
    PRIMARY KEY (snapshot_id, obs_id)
);

CREATE TABLE IF NOT EXISTS functions (
    function_id        TEXT PRIMARY KEY,
    function_name      TEXT NOT NULL,
    definition         TEXT NOT NULL,
    status             TEXT NOT NULL,
    latest_snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    payload_json       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS function_versions (
    snapshot_id  TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    function_id  TEXT NOT NULL REFERENCES functions(function_id),
    version      INTEGER,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, function_id)
);

CREATE TABLE IF NOT EXISTS function_evolution_events (
    event_id     TEXT PRIMARY KEY,
    function_id  TEXT NOT NULL REFERENCES functions(function_id),
    snapshot_id  TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    version      INTEGER,
    action       TEXT NOT NULL,
    created_at   TEXT,
    payload_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshot_functions (
    snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    function_id TEXT NOT NULL REFERENCES functions(function_id),
    position    INTEGER NOT NULL,
    PRIMARY KEY (snapshot_id, function_id)
);

CREATE TABLE IF NOT EXISTS function_contracts (
    snapshot_id  TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    function_id  TEXT NOT NULL REFERENCES functions(function_id),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, function_id)
);

CREATE TABLE IF NOT EXISTS function_occurrences (
    snapshot_id            TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    occurrence_id          TEXT NOT NULL,
    obs_id                 TEXT NOT NULL REFERENCES observations(obs_id),
    observation_version_id TEXT NOT NULL REFERENCES observation_versions(observation_version_id),
    story_id                TEXT NOT NULL REFERENCES stories(story_id),
    function_id             TEXT REFERENCES functions(function_id),
    status                  TEXT NOT NULL,
    payload_json            TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, occurrence_id)
);

CREATE TABLE IF NOT EXISTS patterns (
    snapshot_id       TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    pattern_id        TEXT NOT NULL,
    pattern_name      TEXT,
    status            TEXT NOT NULL CHECK (status IN ('published', 'blocked', 'retired', 'merged', 'rejected', 'manual_review')),
    latest_version_id TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, pattern_id)
);

CREATE TABLE IF NOT EXISTS pattern_versions (
    pattern_version_id TEXT PRIMARY KEY,
    snapshot_id  TEXT NOT NULL,
    pattern_id   TEXT NOT NULL,
    status       TEXT NOT NULL,
    parent_version_id TEXT REFERENCES pattern_versions(pattern_version_id),
    action       TEXT,
    structure_signature TEXT,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (snapshot_id, pattern_id) REFERENCES patterns(snapshot_id, pattern_id)
);

CREATE TABLE IF NOT EXISTS pattern_evidence (
    pattern_version_id TEXT NOT NULL REFERENCES pattern_versions(pattern_version_id),
    story_id           TEXT NOT NULL REFERENCES stories(story_id),
    PRIMARY KEY (pattern_version_id, story_id)
);

CREATE TABLE IF NOT EXISTS pattern_runs (
    run_id             TEXT PRIMARY KEY,
    snapshot_id        TEXT NOT NULL UNIQUE REFERENCES snapshots(snapshot_id),
    parent_snapshot_id TEXT REFERENCES snapshots(snapshot_id),
    namespace          TEXT NOT NULL,
    workflow           TEXT NOT NULL CHECK (workflow IN ('bootstrap', 'evolve')),
    status             TEXT NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),
    input_signature    TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    completed_at       TEXT,
    payload_json       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pattern_story_sequences (
    snapshot_id               TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    story_id                  TEXT NOT NULL REFERENCES stories(story_id),
    occurrence_signature      TEXT NOT NULL,
    inherited_from_snapshot_id TEXT REFERENCES snapshots(snapshot_id),
    payload_json              TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, story_id)
);

CREATE TABLE IF NOT EXISTS motif_evidence (
    snapshot_id  TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    motif_id     TEXT NOT NULL,
    evidence_id  TEXT NOT NULL,
    story_id     TEXT NOT NULL REFERENCES stories(story_id),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, motif_id, evidence_id)
);

CREATE TABLE IF NOT EXISTS motif_pair_reviews (
    variant_pair_id TEXT NOT NULL,
    input_signature TEXT NOT NULL,
    verdict         TEXT NOT NULL CHECK (verdict IN ('SAME_PATTERN', 'RELATED', 'DIFFERENT')),
    similarity      REAL NOT NULL,
    recall_tier     TEXT NOT NULL CHECK (recall_tier IN ('HIGH', 'EXPANDED')),
    payload_json    TEXT NOT NULL,
    PRIMARY KEY (variant_pair_id, input_signature)
);

CREATE TABLE IF NOT EXISTS motif_clusters (
    snapshot_id        TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    cluster_id         TEXT NOT NULL,
    pattern_id         TEXT,
    status             TEXT NOT NULL CHECK (status IN ('candidate', 'published', 'blocked')),
    structure_signature TEXT NOT NULL,
    payload_json       TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, cluster_id)
);

CREATE TABLE IF NOT EXISTS snapshot_patterns (
    snapshot_id        TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    pattern_id         TEXT NOT NULL,
    pattern_version_id TEXT NOT NULL REFERENCES pattern_versions(pattern_version_id),
    status             TEXT NOT NULL CHECK (status IN ('published', 'blocked')),
    is_new             INTEGER NOT NULL CHECK (is_new IN (0, 1)),
    PRIMARY KEY (snapshot_id, pattern_id),
    FOREIGN KEY (snapshot_id, pattern_id) REFERENCES patterns(snapshot_id, pattern_id)
);

CREATE TABLE IF NOT EXISTS outlines (
    outline_id       TEXT PRIMARY KEY,
    snapshot_id      TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    pattern_id       TEXT,
    pattern_name     TEXT NOT NULL,
    genre            TEXT NOT NULL,
    user_request     TEXT,
    schema_version   INTEGER NOT NULL,
    validation_ok    INTEGER NOT NULL CHECK (validation_ok IN (0, 1)),
    created_at       TEXT NOT NULL,
    outline_json     TEXT NOT NULL,
    outline_markdown TEXT NOT NULL,
    FOREIGN KEY (snapshot_id, pattern_id) REFERENCES patterns(snapshot_id, pattern_id)
);

{_PATTERN_USAGE_SCHEMA}

CREATE TABLE IF NOT EXISTS generation_outcomes (
    outcome_id       TEXT PRIMARY KEY,
    snapshot_id      TEXT NOT NULL REFERENCES snapshots(snapshot_id),
    pattern_id       TEXT,
    outline_id       TEXT REFERENCES outlines(outline_id),
    planner_mode     TEXT NOT NULL CHECK (planner_mode IN ('published', 'dynamic')),
    validation_ok    INTEGER NOT NULL CHECK (validation_ok IN (0, 1)),
    retry_occurred   INTEGER NOT NULL CHECK (retry_occurred IN (0, 1)),
    failure_type     TEXT,
    follow_up_action TEXT NOT NULL CHECK (follow_up_action IN ('accepted', 'rejected', 'rewritten')),
    created_at       TEXT NOT NULL,
    payload_json     TEXT NOT NULL,
    FOREIGN KEY (snapshot_id, pattern_id) REFERENCES patterns(snapshot_id, pattern_id)
);

CREATE INDEX IF NOT EXISTS idx_generation_outcomes_pattern
    ON generation_outcomes (snapshot_id, pattern_id);
"""


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(*values: str) -> str:
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()


class StoryKnowledgeStore:
    def __init__(self, db_path=DEFAULT_DB_PATH):
        self.db_path = Path(db_path)

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(pattern_usage)")
            }
            if columns and "usage_id" not in columns:
                conn.execute("ALTER TABLE pattern_usage RENAME TO pattern_usage_legacy")
                conn.executescript(_PATTERN_USAGE_SCHEMA)
                conn.execute(
                    """INSERT INTO pattern_usage
                       (pattern_id, snapshot_id, claimed_at, outline_id)
                       SELECT pattern_id, snapshot_id, claimed_at, outline_id
                       FROM pattern_usage_legacy"""
                )
                conn.execute("DROP TABLE pattern_usage_legacy")

    @staticmethod
    def _story_stub(conn: sqlite3.Connection, story_id: str) -> None:
        conn.execute("INSERT OR IGNORE INTO stories (story_id) VALUES (?)", (story_id,))

    @staticmethod
    def _observation_stub(conn: sqlite3.Connection, obs_id: str, story_id: str) -> None:
        StoryKnowledgeStore._story_stub(conn, story_id)
        conn.execute(
            "INSERT OR IGNORE INTO observations (obs_id, story_id) VALUES (?, ?)",
            (obs_id, story_id),
        )

    def begin_function_run(
        self,
        run_id: str,
        workflow: str,
        namespace: str,
        parent_snapshot_id: str | None,
        corpus_dir: str | None = None,
    ) -> None:
        self.initialize()
        with self.connect() as conn:
            self._recover_interrupted_function_runs(conn)
            conn.execute(
                """INSERT INTO pipeline_runs
                   (run_id, workflow, namespace, parent_snapshot_id, snapshot_id, status,
                    corpus_dir, created_at, completed_at, payload_json)
                   VALUES (?, ?, ?, ?, NULL, 'RUNNING', ?,
                           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NULL, '{}')
                   ON CONFLICT(run_id) DO NOTHING""",
                (run_id, workflow, namespace, parent_snapshot_id, corpus_dir),
            )

    def load_function_run(self, run_id: str) -> dict | None:
        self.initialize()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    @staticmethod
    def _remove_function_run_staging(conn: sqlite3.Connection, run_id: str) -> None:
        conn.execute("DELETE FROM run_observations WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM run_stories WHERE run_id=?", (run_id,))
        conn.execute("DELETE FROM observation_versions WHERE created_by_run_id=?", (run_id,))
        conn.execute(
            """DELETE FROM observations
               WHERE NOT EXISTS (
                   SELECT 1 FROM observation_versions
                   WHERE observation_versions.obs_id=observations.obs_id
               )"""
        )
        conn.execute("DELETE FROM story_versions WHERE created_by_run_id=?", (run_id,))

    def _recover_interrupted_function_runs(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            """SELECT run_id, workflow, namespace, parent_snapshot_id FROM pipeline_runs
               WHERE status='RUNNING' AND snapshot_id IS NULL"""
        ).fetchall()
        for row in rows:
            run_id = row["run_id"]
            self._remove_function_run_staging(conn, run_id)
            failure = failed_run_result(
                stage=row["workflow"], workflow=row["workflow"], run_id=run_id,
                namespace=row["namespace"], snapshot_id=None,
                parent_snapshot_id=row["parent_snapshot_id"],
                error_code="INTERRUPTED_BEFORE_SNAPSHOT",
                error="进程在 Snapshot 发布前中断",
            )
            conn.execute(
                """UPDATE pipeline_runs
                   SET status='FAIL', completed_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                       payload_json=? WHERE run_id=?""",
                (_json(failure), run_id),
            )

    def stage_story_observations(
        self,
        run_id: str,
        normalized_story: dict,
        story_config: dict,
        observations: list[dict],
        position: int,
        story_profile: dict | None = None,
    ) -> list[dict]:
        """写入当前 Run 的不可见版本；返回带版本 ID 的 Observation。"""
        metadata = normalized_story["metadata"]
        text = normalized_story["raw_text"]
        story_id = metadata["story_id"]
        version_id = metadata.get("story_version_id") or story_version_id(story_id, text)
        content_sha = metadata.get("content_sha256") or hashlib.sha256(text.encode("utf-8")).hexdigest()
        normalized_profile = (
            StoryProfile.model_validate(story_profile).model_dump()
            if story_profile is not None else None
        )
        story_payload = {
            **metadata,
            "story_id": story_id,
            "story_version_id": version_id,
            "source_file": story_config.get("source_file"),
            "story_profile": normalized_profile,
        }
        staged = []
        with self.connect() as conn:
            self._story_stub(conn, story_id)
            conn.execute(
                """INSERT OR IGNORE INTO story_versions
                   (story_version_id, story_id, content_sha256, title, category, source_file,
                    text_content, created_by_run_id, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    version_id, story_id, content_sha, metadata.get("title"),
                    metadata.get("story_type"), story_config.get("source_file"), text,
                    run_id, _json(story_payload),
                ),
            )
            stored = conn.execute(
                "SELECT payload_json FROM story_versions WHERE story_version_id=?",
                (version_id,),
            ).fetchone()
            if stored and json.loads(stored["payload_json"]) != story_payload:
                raise ValueError(f"story version 已存在且人物画像不一致: {story_id}")
            conn.execute(
                """INSERT OR REPLACE INTO run_stories
                   (run_id, story_id, story_version_id, position) VALUES (?, ?, ?, ?)""",
                (run_id, story_id, version_id, position),
            )
            conn.execute(
                """DELETE FROM run_observations WHERE run_id=?
                   AND obs_id IN (SELECT obs_id FROM observations WHERE story_id=?)""",
                (run_id, story_id),
            )
            for order, item in enumerate(observations, 1):
                observation = dict(item, story_version_id=version_id, observation_order=order)
                observation["observation_version_id"] = (
                    item.get("observation_version_id")
                    or observation_version_id(version_id, observation)
                )
                obs_id = observation["obs_id"]
                self._observation_stub(conn, obs_id, story_id)
                conn.execute(
                    """INSERT OR IGNORE INTO observation_versions
                       (observation_version_id, obs_id, story_version_id, created_by_run_id,
                        observation_order, payload_json) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        observation["observation_version_id"], obs_id, version_id,
                        run_id, order, _json(observation),
                    ),
                )
                stored_observation = conn.execute(
                    "SELECT payload_json FROM observation_versions WHERE observation_version_id=?",
                    (observation["observation_version_id"],),
                ).fetchone()
                if stored_observation and json.loads(stored_observation["payload_json"]) != observation:
                    raise ValueError(f"observation version 已存在且人物绑定不一致: {obs_id}")
                conn.execute(
                    """INSERT OR REPLACE INTO run_observations
                       (run_id, obs_id, observation_version_id) VALUES (?, ?, ?)""",
                    (run_id, obs_id, observation["observation_version_id"]),
                )
                staged.append(observation)
        return staged

    @staticmethod
    def _profile_record(story_id: str, story_version_id: str, payload: dict) -> dict:
        raw_profile = payload.get("story_profile")
        profile = (
            StoryProfile.model_validate(raw_profile).model_dump()
            if raw_profile is not None else None
        )
        return {
            "story_id": story_id,
            "story_version_id": story_version_id,
            "profile": profile,
        }

    def load_story_profiles(self, snapshot_id: str) -> list[dict]:
        """读取 Snapshot 中每个 story version 的人物画像（缺失也保留记录）。"""
        manifest = self.load_snapshot_manifest(snapshot_id)
        if manifest.get("schema_version") != 5:
            raise ValueError(
                f"Snapshot {snapshot_id} 尚未包含 StoryProfile，请显式重建 schema 5 Snapshot"
            )
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT ssv.story_id, ssv.story_version_id, sv.payload_json
                   FROM snapshot_story_versions ssv
                   JOIN story_versions sv ON sv.story_version_id=ssv.story_version_id
                   WHERE ssv.snapshot_id=? ORDER BY ssv.position, ssv.story_id""",
                (snapshot_id,),
            ).fetchall()
        return [
            self._profile_record(row["story_id"], row["story_version_id"], json.loads(row["payload_json"]))
            for row in rows
        ]

    def load_run_story_profile_view(
        self, parent_snapshot_id: str | None, run_id: str,
    ) -> list[dict]:
        """返回父 Snapshot 被当前 Run 按 story 覆盖后的 Profile 视图。"""
        if parent_snapshot_id:
            manifest = self.load_snapshot_manifest(parent_snapshot_id)
            if manifest.get("schema_version") != 5:
                raise ValueError(
                    f"父 Snapshot {parent_snapshot_id} 尚未包含 StoryProfile，请显式重建 schema 5 Snapshot"
                )
        with self.connect() as conn:
            if parent_snapshot_id:
                rows = conn.execute(
                    """SELECT ssv.story_id, ssv.story_version_id, sv.payload_json
                       FROM snapshot_story_versions ssv
                       JOIN story_versions sv ON sv.story_version_id=ssv.story_version_id
                       WHERE ssv.snapshot_id=?
                         AND ssv.story_id NOT IN (SELECT story_id FROM run_stories WHERE run_id=?)
                       UNION ALL
                       SELECT rs.story_id, rs.story_version_id, sv.payload_json
                       FROM run_stories rs
                       JOIN story_versions sv ON sv.story_version_id=rs.story_version_id
                       WHERE rs.run_id=?
                       ORDER BY 1""",
                    (parent_snapshot_id, run_id, run_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT rs.story_id, rs.story_version_id, sv.payload_json
                       FROM run_stories rs
                       JOIN story_versions sv ON sv.story_version_id=rs.story_version_id
                       WHERE rs.run_id=? ORDER BY rs.position, rs.story_id""",
                    (run_id,),
                ).fetchall()
        return [
            self._profile_record(row["story_id"], row["story_version_id"], json.loads(row["payload_json"]))
            for row in rows
        ]

    def load_run_observation_view(self, parent_snapshot_id: str | None, run_id: str) -> list[dict]:
        """Bank 计算视图：父 Snapshot，按当前 Run 中的 story 覆盖。"""
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT payload_json FROM (
                     SELECT ov.payload_json, ssv.position, ov.observation_order
                     FROM snapshot_observation_versions sov
                     JOIN observation_versions ov
                       ON ov.observation_version_id=sov.observation_version_id
                     JOIN observations o ON o.obs_id=sov.obs_id
                     JOIN snapshot_story_versions ssv
                       ON ssv.snapshot_id=sov.snapshot_id AND ssv.story_id=o.story_id
                     WHERE sov.snapshot_id=?
                       AND o.story_id NOT IN (SELECT story_id FROM run_stories WHERE run_id=?)
                     UNION ALL
                     SELECT ov.payload_json, rs.position, ov.observation_order
                     FROM run_observations ro
                     JOIN observation_versions ov
                       ON ov.observation_version_id=ro.observation_version_id
                     JOIN observations o ON o.obs_id=ro.obs_id
                     JOIN run_stories rs ON rs.run_id=ro.run_id AND rs.story_id=o.story_id
                     WHERE ro.run_id=?
                   ) ORDER BY position, observation_order""",
                (parent_snapshot_id, run_id, run_id),
            ).fetchall() if parent_snapshot_id else conn.execute(
                """SELECT ov.payload_json FROM run_observations ro
                   JOIN observation_versions ov
                     ON ov.observation_version_id=ro.observation_version_id
                   WHERE ro.run_id=? ORDER BY ov.observation_order""",
                (run_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def fail_function_run(self, run_id: str, report: dict) -> None:
        """失败 Run 保留报告，移除其暂存成员。"""
        with self.connect() as conn:
            row = conn.execute("SELECT status FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()
            if not row or row["status"] != "RUNNING":
                return
            self._remove_function_run_staging(conn, run_id)
            conn.execute(
                """UPDATE pipeline_runs SET status='FAIL', completed_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                   payload_json=? WHERE run_id=?""",
                (_json(report), run_id),
            )

    def _commit_snapshot(
        self,
        conn: sqlite3.Connection,
        snapshot_path,
        run_id: str,
    ) -> dict:
        snapshot_path = Path(snapshot_path)
        manifest, functions, _evaluation = load_snapshot(str(snapshot_path))
        snapshot_id = manifest["snapshot_id"]
        parent_snapshot_id = manifest.get("parent_snapshot_id")
        if parent_snapshot_id is None:
            row = conn.execute(
                "SELECT parent_snapshot_id FROM pipeline_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            parent_snapshot_id = row["parent_snapshot_id"] if row else None
        if parent_snapshot_id and not conn.execute(
            "SELECT 1 FROM snapshots WHERE snapshot_id=?", (parent_snapshot_id,)
        ).fetchone():
            raise ValueError(f"父 Snapshot 尚未入库: {parent_snapshot_id}")
        conn.execute(
            """INSERT OR IGNORE INTO snapshots
               (snapshot_id, parent_snapshot_id, schema_version, source_workflow,
                namespace, created_at, payload_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id, parent_snapshot_id, manifest["schema_version"],
                manifest["source_workflow"], manifest["namespace"],
                manifest["created_at"], _json(manifest),
            ),
        )
        if parent_snapshot_id:
            conn.execute(
                """INSERT OR IGNORE INTO snapshot_story_versions
                   SELECT ?, story_id, story_version_id, position
                   FROM snapshot_story_versions WHERE snapshot_id=?
                     AND story_id NOT IN (SELECT story_id FROM run_stories WHERE run_id=?)""",
                (snapshot_id, parent_snapshot_id, run_id),
            )
            conn.execute(
                """INSERT OR IGNORE INTO snapshot_observation_versions
                   SELECT ?, sov.obs_id, sov.observation_version_id
                   FROM snapshot_observation_versions sov
                   JOIN observations o ON o.obs_id=sov.obs_id
                   WHERE sov.snapshot_id=?
                     AND o.story_id NOT IN (SELECT story_id FROM run_stories WHERE run_id=?)""",
                (snapshot_id, parent_snapshot_id, run_id),
            )
            conn.execute(
                """INSERT OR REPLACE INTO snapshot_story_versions
                   SELECT ?, rs.story_id, rs.story_version_id,
                          COALESCE(
                            (SELECT position FROM snapshot_story_versions
                             WHERE snapshot_id=? AND story_id=rs.story_id),
                            (SELECT COALESCE(MAX(position), 0) FROM snapshot_story_versions
                             WHERE snapshot_id=?) + rs.position
                          )
                   FROM run_stories rs WHERE rs.run_id=?""",
                (snapshot_id, parent_snapshot_id, parent_snapshot_id, run_id),
            )
        else:
            conn.execute(
                """INSERT OR REPLACE INTO snapshot_story_versions
                   SELECT ?, story_id, story_version_id, position FROM run_stories WHERE run_id=?""",
                (snapshot_id, run_id),
            )
        conn.execute(
            """INSERT OR REPLACE INTO snapshot_observation_versions
               SELECT ?, obs_id, observation_version_id FROM run_observations WHERE run_id=?""",
            (snapshot_id, run_id),
        )
        snapshot_profiles = load_snapshot_story_profiles(str(snapshot_path))
        snapshot_story_ids = {
            row["story_id"] for row in conn.execute(
                "SELECT story_id FROM snapshot_story_versions WHERE snapshot_id=?",
                (snapshot_id,),
            )
        }
        profile_story_ids = {record["story_id"] for record in snapshot_profiles}
        if snapshot_story_ids != profile_story_ids:
            raise ValueError("Snapshot Profile 必须覆盖 Snapshot 中的全部故事")
        for record in snapshot_profiles:
            row = conn.execute(
                """SELECT sv.story_version_id, sv.payload_json
                   FROM snapshot_story_versions ssv
                   JOIN story_versions sv ON sv.story_version_id=ssv.story_version_id
                   WHERE ssv.snapshot_id=? AND ssv.story_id=?""",
                (snapshot_id, record["story_id"]),
            ).fetchone()
            if not row or row["story_version_id"] != record["story_version_id"]:
                raise ValueError(f"Snapshot Profile 没有对应的 story version: {record['story_id']}")
            payload = json.loads(row["payload_json"])
            try:
                stored_profile = StoryProfile.model_validate(
                    payload.get("story_profile")
                ).model_dump()
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Story version 的 Profile 无效: {record['story_id']}") from exc
            if stored_profile != record.get("profile"):
                raise ValueError(f"Snapshot Profile 与 story version 不一致: {record['story_id']}")
        for position, function in enumerate(functions, 1):
            conn.execute(
                """INSERT INTO functions
                   (function_id, function_name, definition, status, latest_snapshot_id, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(function_id) DO UPDATE SET
                   function_name=excluded.function_name, definition=excluded.definition,
                   status=excluded.status, latest_snapshot_id=excluded.latest_snapshot_id,
                   payload_json=excluded.payload_json
                   WHERE (SELECT created_at FROM snapshots WHERE snapshot_id=excluded.latest_snapshot_id)
                      >= (SELECT created_at FROM snapshots WHERE snapshot_id=functions.latest_snapshot_id)""",
                (
                    function["function_id"], function["function_name"], function["definition"],
                    function.get("status", "provisional"), snapshot_id, _json(function),
                ),
            )
            conn.execute(
                """INSERT OR REPLACE INTO function_versions
                   (snapshot_id, function_id, version, payload_json) VALUES (?, ?, ?, ?)""",
                (
                    snapshot_id,
                    function["function_id"],
                    function.get("version") or max(
                        (item.get("version", 0) for item in function.get("version_history") or []),
                        default=0,
                    ),
                    _json(function),
                ),
            )
            conn.execute(
                """INSERT OR REPLACE INTO snapshot_functions
                   (snapshot_id, function_id, position) VALUES (?, ?, ?)""",
                (snapshot_id, function["function_id"], position),
            )
            for event in function.get("version_history") or []:
                event_json = _json(event)
                conn.execute(
                    """INSERT OR IGNORE INTO function_evolution_events
                       (event_id, function_id, snapshot_id, version, action, created_at, payload_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        _digest(function["function_id"], event_json), function["function_id"],
                        snapshot_id, event.get("version"), event.get("action", "UNKNOWN"),
                        event.get("ts"), event_json,
                    ),
                )
        occurrences = load_occurrences(str(snapshot_path))
        for occurrence in occurrences:
            obs_id, story_id = occurrence["obs_id"], occurrence["story_id"]
            conn.execute(
                """INSERT OR REPLACE INTO function_occurrences
                   (snapshot_id, occurrence_id, obs_id, observation_version_id,
                    story_id, function_id, status, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id, occurrence["occurrence_id"], obs_id,
                    occurrence["observation_version_id"], story_id,
                    occurrence.get("function_id"), occurrence["status"], _json(occurrence),
                ),
            )
        for contract in load_function_contracts(str(snapshot_path)):
            conn.execute(
                """INSERT OR REPLACE INTO function_contracts
                   (snapshot_id, function_id, payload_json) VALUES (?, ?, ?)""",
                (snapshot_id, contract["function_id"], _json(contract)),
            )
        conn.execute(
            """UPDATE pipeline_runs SET snapshot_id=?, status='PASS',
               completed_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), payload_json=?
               WHERE run_id=?""",
            (snapshot_id, _json({"snapshot_path": str(snapshot_path.resolve())}), run_id),
        )
        return manifest

    def commit_function_run(self, snapshot_path, run_id: str) -> dict:
        self.initialize()
        with self.connect() as conn:
            manifest = self._commit_snapshot(conn, snapshot_path, run_id)
            self._check(conn)
        return manifest

    def load_pattern_run(self, snapshot_id: str) -> dict | None:
        self.initialize()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pattern_runs WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def begin_pattern_run(self, snapshot_id: str, input_signature: str) -> dict:
        self.initialize()
        with self.connect() as conn:
            self._recover_interrupted_pattern_runs(conn)
            snapshot = conn.execute(
                "SELECT parent_snapshot_id, namespace, source_workflow FROM snapshots WHERE snapshot_id=?",
                (snapshot_id,),
            ).fetchone()
            if not snapshot:
                raise ValueError(f"知识库中不存在 Snapshot: {snapshot_id}")
            workflow = snapshot["source_workflow"]
            parent_snapshot_id = snapshot["parent_snapshot_id"]
            if workflow == "evolve":
                parent = conn.execute(
                    "SELECT status, namespace FROM pattern_runs WHERE snapshot_id=?",
                    (parent_snapshot_id,),
                ).fetchone()
                if not parent or parent["status"] != "SUCCESS":
                    raise ValueError(f"父 Snapshot 缺少成功的 Pattern 运行: {parent_snapshot_id}")
                if parent["namespace"] != snapshot["namespace"]:
                    raise ValueError(
                        f"父子 Snapshot namespace 不一致: {parent['namespace']} != {snapshot['namespace']}"
                    )
            run_id = "PR_" + _digest(snapshot_id)[:16]
            payload = {
                "run_id": run_id,
                "snapshot_id": snapshot_id,
                "parent_snapshot_id": parent_snapshot_id,
                "namespace": snapshot["namespace"],
                "workflow": workflow,
            }
            conn.execute(
                """INSERT INTO pattern_runs
                   (run_id, snapshot_id, parent_snapshot_id, namespace, workflow, status,
                    input_signature, created_at, completed_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, 'RUNNING', ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NULL, ?)
                   ON CONFLICT(snapshot_id) DO UPDATE SET
                   status='RUNNING', input_signature=excluded.input_signature,
                   completed_at=NULL, payload_json=excluded.payload_json""",
                (
                    run_id, snapshot_id, parent_snapshot_id, snapshot["namespace"],
                    workflow, input_signature, _json(payload),
                ),
            )
        return payload

    @staticmethod
    def _recover_interrupted_pattern_runs(conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT snapshot_id, payload_json FROM pattern_runs WHERE status='RUNNING'"
        ).fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload.update(failed_run_result(
                stage="pattern", workflow=payload.get("workflow"),
                run_id=payload.get("run_id"), namespace=payload.get("namespace"),
                snapshot_id=row["snapshot_id"],
                parent_snapshot_id=payload.get("parent_snapshot_id"),
                error_code="INTERRUPTED_BEFORE_PATTERN_COMMIT",
                error="进程在 Pattern 提交前中断",
            ))
            conn.execute(
                """UPDATE pattern_runs
                   SET status='FAILED', completed_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                       payload_json=? WHERE snapshot_id=?""",
                (_json(payload), row["snapshot_id"]),
            )

    def clear_pattern_snapshot(self, snapshot_id: str) -> None:
        """清除指定 Snapshot 的 Pattern 派生状态，以便显式重建。"""
        self.initialize()
        with self.connect() as conn:
            version_ids = [
                row["pattern_version_id"]
                for row in conn.execute(
                    "SELECT pattern_version_id FROM pattern_versions WHERE snapshot_id=?",
                    (snapshot_id,),
                )
            ]
            if version_ids:
                placeholders = ",".join("?" for _ in version_ids)
                descendant = conn.execute(
                    f"SELECT 1 FROM pattern_versions WHERE parent_version_id IN ({placeholders}) LIMIT 1",
                    version_ids,
                ).fetchone()
                if descendant:
                    raise ValueError(f"Pattern Snapshot 存在后续版本，不能重建: {snapshot_id}")
                used = conn.execute(
                    f"SELECT 1 FROM pattern_usage WHERE snapshot_id=? LIMIT 1",
                    (snapshot_id,),
                ).fetchone()
                if used:
                    raise ValueError(f"Pattern Snapshot 已被使用，不能重建: {snapshot_id}")
                outlines = conn.execute(
                    "SELECT 1 FROM outlines WHERE snapshot_id=? LIMIT 1", (snapshot_id,)
                ).fetchone()
                if outlines:
                    raise ValueError(f"Pattern Snapshot 已生成大纲，不能重建: {snapshot_id}")
                conn.execute(
                    f"DELETE FROM pattern_evidence WHERE pattern_version_id IN ({placeholders})",
                    version_ids,
                )
            conn.execute("DELETE FROM snapshot_patterns WHERE snapshot_id=?", (snapshot_id,))
            conn.execute("DELETE FROM pattern_versions WHERE snapshot_id=?", (snapshot_id,))
            conn.execute("DELETE FROM patterns WHERE snapshot_id=?", (snapshot_id,))
            conn.execute("DELETE FROM motif_clusters WHERE snapshot_id=?", (snapshot_id,))
            conn.execute("DELETE FROM motif_evidence WHERE snapshot_id=?", (snapshot_id,))
            conn.execute("DELETE FROM pattern_story_sequences WHERE snapshot_id=?", (snapshot_id,))
            conn.execute("DELETE FROM pattern_runs WHERE snapshot_id=?", (snapshot_id,))

    def fail_pattern_run(self, snapshot_id: str, error: dict) -> None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM pattern_runs WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
            if not row:
                return
            payload = json.loads(row["payload_json"])
            payload.update(error)
            conn.execute(
                """UPDATE pattern_runs SET status='FAILED', completed_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                   payload_json=? WHERE snapshot_id=?""",
                (_json(payload), snapshot_id),
            )

    def load_pattern_sequences(self, snapshot_id: str | None) -> dict[str, dict]:
        if not snapshot_id:
            return {}
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT story_id, occurrence_signature, inherited_from_snapshot_id, payload_json
                   FROM pattern_story_sequences WHERE snapshot_id=? ORDER BY story_id""",
                (snapshot_id,),
            ).fetchall()
        return {
            row["story_id"]: {
                "occurrence_signature": row["occurrence_signature"],
                "inherited_from_snapshot_id": row["inherited_from_snapshot_id"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        }

    def load_motif_evidence(self, snapshot_id: str | None) -> list[dict]:
        if not snapshot_id:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT payload_json FROM motif_evidence
                   WHERE snapshot_id=? ORDER BY motif_id, evidence_id""",
                (snapshot_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def load_motif_pair_review(self, pair_id: str, input_signature: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                """SELECT payload_json FROM motif_pair_reviews
                   WHERE variant_pair_id=? AND input_signature=?""",
                (pair_id, input_signature),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def load_motif_clusters(self, snapshot_id: str | None) -> list[dict]:
        if not snapshot_id:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM motif_clusters WHERE snapshot_id=? ORDER BY cluster_id",
                (snapshot_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def load_snapshot_pattern_rows(self, snapshot_id: str | None) -> list[dict]:
        if not snapshot_id:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT sp.pattern_id, sp.pattern_version_id, sp.status, sp.is_new,
                          p.pattern_name, p.payload_json, pv.payload_json AS version_json,
                          pv.structure_signature,
                          (SELECT MIN(s.created_at) FROM patterns p2
                           JOIN snapshots s ON s.snapshot_id=p2.snapshot_id
                           WHERE p2.pattern_id=sp.pattern_id) AS born_at
                   FROM snapshot_patterns sp
                   JOIN patterns p ON p.snapshot_id=sp.snapshot_id AND p.pattern_id=sp.pattern_id
                   JOIN pattern_versions pv ON pv.pattern_version_id=sp.pattern_version_id
                   WHERE sp.snapshot_id=? ORDER BY sp.pattern_id""",
                (snapshot_id,),
            ).fetchall()
        return [{
            "pattern_id": row["pattern_id"],
            "pattern_version_id": row["pattern_version_id"],
            "status": row["status"],
            "is_new": bool(row["is_new"]),
            "pattern_name": row["pattern_name"],
            "pattern": json.loads(row["payload_json"]),
            "version": json.loads(row["version_json"]),
            "structure_signature": row["structure_signature"],
            "born_at": row["born_at"],
        } for row in rows]

    def commit_pattern_run(self, snapshot_id: str, data: dict) -> dict:
        """原子发布一个 PatternSet；前置节点不写正式 Pattern 数据。"""
        self.initialize()
        with self.connect() as conn:
            run = conn.execute(
                "SELECT run_id, status FROM pattern_runs WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
            if not run:
                raise ValueError(f"Pattern 运行尚未开始: {snapshot_id}")
            if run["status"] == "SUCCESS":
                return json.loads(conn.execute(
                    "SELECT payload_json FROM pattern_runs WHERE snapshot_id=?", (snapshot_id,)
                ).fetchone()[0])

            for story_id, item in sorted(data["sequences"].items()):
                conn.execute(
                    """INSERT OR REPLACE INTO pattern_story_sequences
                       (snapshot_id, story_id, occurrence_signature, inherited_from_snapshot_id, payload_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        snapshot_id, story_id, item["occurrence_signature"],
                        item.get("inherited_from_snapshot_id"), _json(item["payload"]),
                    ),
                )
            for motif in data["motifs"]:
                for evidence in motif["evidence"]:
                    evidence_id = _digest(
                        motif["motif_id"], evidence["story_id"],
                        _json(evidence.get("structural_orders") or []),
                        _json(evidence.get("occurrence_ids") or []),
                    )
                    payload = {
                        "motif_id": motif["motif_id"],
                        "function_ids": motif["function_ids"],
                        "function_names": motif["function_names"],
                        "length": motif["length"],
                        "evidence": evidence,
                    }
                    conn.execute(
                        """INSERT OR REPLACE INTO motif_evidence
                           (snapshot_id, motif_id, evidence_id, story_id, payload_json)
                           VALUES (?, ?, ?, ?, ?)""",
                        (snapshot_id, motif["motif_id"], evidence_id, evidence["story_id"], _json(payload)),
                    )
            for review in data["reviews"]:
                conn.execute(
                    """INSERT OR IGNORE INTO motif_pair_reviews
                       (variant_pair_id, input_signature, verdict, similarity, recall_tier, payload_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        review["variant_pair_id"], review["input_signature"], review["verdict"],
                        review["embedding_similarity"], review["recall_tier"], _json(review),
                    ),
                )
            for cluster in data["clusters"]:
                conn.execute(
                    """INSERT OR REPLACE INTO motif_clusters
                       (snapshot_id, cluster_id, pattern_id, status, structure_signature, payload_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot_id, cluster["cluster_id"], cluster.get("pattern_id"),
                        cluster["status"], cluster["structure_signature"], _json(cluster),
                    ),
                )
            for item in data["patterns"]:
                pattern = item["pattern"]
                conn.execute(
                    """INSERT OR REPLACE INTO patterns
                       (snapshot_id, pattern_id, pattern_name, status, latest_version_id, payload_json)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot_id, item["pattern_id"], pattern.get("pattern_name"),
                        item["status"], item["pattern_version_id"], _json(pattern),
                    ),
                )
                version = item.get("version")
                if version:
                    conn.execute(
                        """INSERT OR IGNORE INTO pattern_versions
                           (pattern_version_id, snapshot_id, pattern_id, status, parent_version_id,
                            action, structure_signature, payload_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            item["pattern_version_id"], snapshot_id, item["pattern_id"],
                            item["status"], version.get("parent_version_id"), version["action"],
                            item["structure_signature"], _json(version),
                        ),
                    )
                    for story_id in sorted(set(pattern.get("story_ids") or [])):
                        self._story_stub(conn, story_id)
                        conn.execute(
                            """INSERT OR IGNORE INTO pattern_evidence
                               (pattern_version_id, story_id) VALUES (?, ?)""",
                            (item["pattern_version_id"], story_id),
                        )
                if item["status"] in {"published", "blocked"}:
                    conn.execute(
                        """INSERT OR REPLACE INTO snapshot_patterns
                           (snapshot_id, pattern_id, pattern_version_id, status, is_new)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            snapshot_id, item["pattern_id"], item["pattern_version_id"],
                            item["status"], int(item["is_new"]),
                        ),
                    )
            result = dict(data["result"])
            result.update({"run_id": run["run_id"], "snapshot_id": snapshot_id})
            conn.execute(
                """UPDATE pattern_runs SET status='SUCCESS',
                   completed_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), payload_json=?
                   WHERE snapshot_id=?""",
                (_json(result), snapshot_id),
            )
            self._check(conn)
        return result

    def record_outline(self, document: dict, markdown_text: str) -> str:
        body = dict(document)
        body.pop("outline_id", None)
        body.setdefault("schema_version", 1)
        required = ("snapshot_id", "pattern_name", "genre", "generated_at", "validation")
        missing = [key for key in required if not body.get(key)]
        if missing:
            raise ValueError(f"大纲缺少字段: {', '.join(missing)}")
        validation_ok = bool(body["validation"].get("overall_ok"))
        outline_id = "OUT_" + _digest(_json(body))[:16]
        body["outline_id"] = outline_id
        payload = _json(body)

        self.initialize()
        with self.connect() as conn:
            snapshot_id = body["snapshot_id"]
            pattern_id = body.get("pattern_id")
            usage_id = None
            if not conn.execute(
                "SELECT 1 FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone():
                raise ValueError(f"大纲来源 Snapshot 尚未入库: {snapshot_id}")
            if pattern_id and not conn.execute(
                "SELECT 1 FROM patterns WHERE snapshot_id=? AND pattern_id=?",
                (snapshot_id, pattern_id),
            ).fetchone():
                raise ValueError(f"大纲来源 Pattern 尚未入库: {pattern_id}")
            existing = conn.execute(
                "SELECT outline_json, outline_markdown FROM outlines WHERE outline_id=?",
                (outline_id,),
            ).fetchone()
            if existing and (existing["outline_json"] != payload or existing["outline_markdown"] != markdown_text):
                raise ValueError(f"大纲 ID 冲突: {outline_id}")
            if pattern_id and not existing:
                usage = conn.execute(
                    """SELECT usage_id FROM pattern_usage
                       WHERE pattern_id=? AND snapshot_id=? AND outline_id IS NULL
                       ORDER BY claimed_at, usage_id LIMIT 1""",
                    (pattern_id, snapshot_id),
                ).fetchone()
                if usage:
                    usage_id = usage["usage_id"]
                else:
                    conn.execute(
                        """INSERT INTO pattern_usage
                           (pattern_id, snapshot_id, claimed_at, outline_id)
                           VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NULL)""",
                        (pattern_id, snapshot_id),
                    )
                    usage_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                """INSERT OR IGNORE INTO outlines
                   (outline_id, snapshot_id, pattern_id, pattern_name, genre, user_request,
                    schema_version, validation_ok, created_at, outline_json, outline_markdown)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    outline_id, snapshot_id, pattern_id, body["pattern_name"], body["genre"],
                    body.get("user_request"), body["schema_version"], int(validation_ok),
                    body["generated_at"], payload, markdown_text,
                ),
            )
            if usage_id is not None:
                conn.execute(
                    "UPDATE pattern_usage SET outline_id=? WHERE usage_id=?",
                    (outline_id, usage_id),
                )
            self._check(conn)
        return outline_id

    def record_generation_outcome(
        self,
        snapshot_id: str,
        pattern_id: str | None,
        outline_id: str | None,
        planner_mode: str,
        validation_ok: bool,
        retry_occurred: bool,
        failure_type: str | None,
        follow_up_action: str,
        payload: dict | None = None,
    ) -> str:
        """在当前 Snapshot 范围记录一次 Outline 生成反馈。"""
        if planner_mode not in {"published", "dynamic"}:
            raise ValueError(f"未知 Planner 模式: {planner_mode}")
        if follow_up_action not in {"accepted", "rejected", "rewritten"}:
            raise ValueError(f"未知生成后续动作: {follow_up_action}")
        body = dict(payload or {})
        body.update({
            "snapshot_id": snapshot_id,
            "pattern_id": pattern_id,
            "outline_id": outline_id,
            "planner_mode": planner_mode,
            "validation_ok": bool(validation_ok),
            "retry_occurred": bool(retry_occurred),
            "failure_type": failure_type,
            "follow_up_action": follow_up_action,
        })
        outcome_id = "GO_" + _digest(_json(body))[:16]
        self.initialize()
        with self.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO generation_outcomes
                   (outcome_id, snapshot_id, pattern_id, outline_id, planner_mode,
                    validation_ok, retry_occurred, failure_type, follow_up_action,
                    created_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,
                           strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), ?)""",
                (
                    outcome_id, snapshot_id, pattern_id, outline_id, planner_mode,
                    int(validation_ok), int(retry_occurred), failure_type,
                    follow_up_action, _json(body),
                ),
            )
            self._check(conn)
        return outcome_id

    def load_generation_outcomes(self, snapshot_id: str | None = None) -> list[dict]:
        self.initialize()
        with self.connect() as conn:
            if snapshot_id:
                rows = conn.execute(
                    """SELECT * FROM generation_outcomes
                       WHERE snapshot_id=? ORDER BY created_at, outcome_id""",
                    (snapshot_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM generation_outcomes ORDER BY created_at, outcome_id"
                ).fetchall()
        outcomes = []
        for row in rows:
            item = dict(row)
            item["validation_ok"] = bool(item["validation_ok"])
            item["retry_occurred"] = bool(item["retry_occurred"])
            item["payload"] = json.loads(item.pop("payload_json"))
            outcomes.append(item)
        return outcomes

    def load_pattern_feedback(self, snapshot_id: str) -> dict[str, dict]:
        """按 Snapshot 聚合反馈；首次失败不降权，重复失败才产生负分。"""
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT pattern_id,
                          COUNT(*) AS outcome_count,
                          SUM(CASE WHEN validation_ok=1 THEN 1 ELSE 0 END) AS pass_count,
                          SUM(CASE WHEN validation_ok=0 THEN 1 ELSE 0 END) AS failure_count,
                          SUM(CASE WHEN follow_up_action='accepted' THEN 1 ELSE 0 END) AS accepted_count,
                          SUM(CASE WHEN follow_up_action='rewritten' THEN 1 ELSE 0 END) AS rewritten_count,
                          SUM(CASE WHEN follow_up_action='rejected' THEN 1 ELSE 0 END) AS rejected_count
                   FROM generation_outcomes
                   WHERE snapshot_id=? AND pattern_id IS NOT NULL
                   GROUP BY pattern_id""",
                (snapshot_id,),
            ).fetchall()
        feedback = {}
        for row in rows:
            accepted_count = row["accepted_count"] or 0
            rewritten_count = row["rewritten_count"] or 0
            failure_count = row["failure_count"] or 0
            feedback[row["pattern_id"]] = {
                "outcome_count": row["outcome_count"],
                "pass_count": row["pass_count"] or 0,
                "failure_count": failure_count,
                "accepted_count": accepted_count,
                "rewritten_count": rewritten_count,
                "rejected_count": row["rejected_count"] or 0,
                "priority_delta": accepted_count + rewritten_count - max(failure_count - 1, 0),
            }
        return feedback

    def claim_pattern(self, snapshot_id: str, pattern_id: str) -> None:
        """记录 Pattern 领取审计，不阻止跨批次复用。"""
        self.initialize()
        with self.connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM patterns WHERE snapshot_id=? AND pattern_id=?",
                (snapshot_id, pattern_id),
            ).fetchone():
                raise ValueError(f"知识库中不存在 Pattern: {pattern_id}")
            conn.execute(
                """INSERT INTO pattern_usage
                   (pattern_id, snapshot_id, claimed_at, outline_id)
                   VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NULL)""",
                (pattern_id, snapshot_id),
            )

    def used_pattern_ids(self) -> set[str]:
        """返回历史使用审计中的 Pattern ID，不作为候选禁用名单。"""
        self.initialize()
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT pattern_id FROM pattern_usage
                   UNION SELECT pattern_id FROM outlines WHERE pattern_id IS NOT NULL"""
            ).fetchall()
        return {row[0] for row in rows}

    def load_outline(self, outline_id: str) -> dict:
        self.initialize()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT outline_json FROM outlines WHERE outline_id=?", (outline_id,)
            ).fetchone()
        if not row:
            raise ValueError(f"知识库中不存在大纲: {outline_id}")
        return json.loads(row["outline_json"])

    @staticmethod
    def _check(conn: sqlite3.Connection) -> None:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(f"知识库外键检查失败: {len(violations)}")

    def status(self) -> dict:
        if not self.db_path.is_file():
            raise ValueError(f"知识库不存在: {self.db_path}")
        tables = (
            "pipeline_runs", "stories", "story_versions", "run_stories",
            "observations", "observation_versions", "run_observations",
            "snapshot_story_versions", "snapshot_observation_versions",
            "functions", "function_versions", "function_evolution_events", "snapshots",
            "serving_snapshots",
            "function_occurrences", "function_contracts", "patterns", "pattern_versions",
            "pattern_runs", "pattern_story_sequences", "motif_evidence",
            "motif_pair_reviews", "motif_clusters", "snapshot_patterns",
            "outlines", "pattern_usage", "generation_outcomes",
        )
        self.initialize()
        with self.connect() as conn:
            counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
            workflows = {
                row["workflow"]: row["count"]
                for row in conn.execute(
                    "SELECT workflow, COUNT(*) AS count FROM pipeline_runs GROUP BY workflow"
                )
            }
            pattern_status = {
                row["status"]: row["count"]
                for row in conn.execute("SELECT status, COUNT(*) AS count FROM patterns GROUP BY status")
            }
        return {
            "db_path": str(self.db_path.resolve()),
            "counts": counts,
            "workflows": workflows,
            "pattern_status": pattern_status,
        }

    def serving_snapshot(self) -> dict:
        """读取当前 serving Snapshot 及其发布时间信息。"""
        self.initialize()
        with self.connect() as conn:
            row = conn.execute(
                """SELECT ss.snapshot_id, ss.promoted_at,
                          s.created_at AS snapshot_created_at, s.namespace
                   FROM serving_snapshots ss
                   JOIN snapshots s ON s.snapshot_id=ss.snapshot_id
                   WHERE ss.pointer_id=1"""
            ).fetchone()
        if not row:
            raise ValueError("知识库没有 serving Snapshot，请先显式 promote_snapshot")
        return dict(row)

    def serving_snapshot_id(self) -> str:
        return self.serving_snapshot()["snapshot_id"]

    def resolve_snapshot_id(self, snapshot_id: str | None = None) -> str:
        return snapshot_id or self.serving_snapshot_id()

    def promote_snapshot(self, snapshot_id: str) -> dict:
        """显式切换 serving 指针；Snapshot 本身保持不可变。"""
        self.initialize()
        with self.connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone():
                raise ValueError(f"知识库中不存在 Snapshot: {snapshot_id}")
            if not conn.execute(
                """SELECT 1 FROM pattern_runs
                   WHERE snapshot_id=? AND status='SUCCESS'""",
                (snapshot_id,),
            ).fetchone():
                raise ValueError(f"Snapshot 缺少成功的 Pattern 运行: {snapshot_id}")
            if not conn.execute(
                """SELECT 1 FROM snapshot_patterns
                   WHERE snapshot_id=? AND status='published'""",
                (snapshot_id,),
            ).fetchone():
                raise ValueError(f"Snapshot 没有已发布 Pattern: {snapshot_id}")
            conn.execute(
                """INSERT INTO serving_snapshots(pointer_id, snapshot_id, promoted_at)
                   VALUES (1, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                   ON CONFLICT(pointer_id) DO UPDATE SET
                   snapshot_id=excluded.snapshot_id, promoted_at=excluded.promoted_at""",
                (snapshot_id,),
            )
            row = conn.execute(
                """SELECT ss.snapshot_id, ss.promoted_at,
                          s.created_at AS snapshot_created_at, s.namespace
                   FROM serving_snapshots ss
                   JOIN snapshots s ON s.snapshot_id=ss.snapshot_id
                   WHERE ss.pointer_id=1"""
            ).fetchone()
        return dict(row)

    def latest_snapshot_id(self, namespace: str | None = None) -> str:
        with self.connect() as conn:
            if namespace:
                row = conn.execute(
                    """SELECT snapshot_id FROM snapshots WHERE namespace=?
                       ORDER BY created_at DESC LIMIT 1""",
                    (namespace,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT snapshot_id FROM snapshots ORDER BY created_at DESC LIMIT 1"
                ).fetchone()
        if not row:
            raise ValueError("知识库中没有已发布 Snapshot")
        return row["snapshot_id"]

    def load_snapshot_manifest(self, snapshot_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT payload_json FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
            ).fetchone()
        if not row:
            raise ValueError(f"知识库中不存在 Snapshot: {snapshot_id}")
        return json.loads(row["payload_json"])

    def load_functions(self, snapshot_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT fv.payload_json
                   FROM snapshot_functions sf
                   JOIN function_versions fv
                     ON fv.snapshot_id=sf.snapshot_id AND fv.function_id=sf.function_id
                   WHERE sf.snapshot_id=? ORDER BY sf.position""",
                (snapshot_id,),
            ).fetchall()
        if not rows:
            raise ValueError(f"Snapshot 没有 Function: {snapshot_id}")
        return [json.loads(row["payload_json"]) for row in rows]

    def load_contracts(self, snapshot_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM function_contracts WHERE snapshot_id=? ORDER BY function_id",
                (snapshot_id,),
            ).fetchall()
        return [json.loads(row["payload_json"]) for row in rows]

    def load_occurrences(self, snapshot_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT payload_json FROM function_occurrences
                   WHERE snapshot_id=? ORDER BY story_id, occurrence_id""",
                (snapshot_id,),
            ).fetchall()
        if not rows:
            raise ValueError(f"Snapshot 没有 FunctionOccurrence: {snapshot_id}")
        return [json.loads(row["payload_json"]) for row in rows]

    def load_story_pattern_inputs(self, snapshot_id: str) -> dict:
        manifest = self.load_snapshot_manifest(snapshot_id)
        occurrences = self.load_occurrences(snapshot_id)
        with self.connect() as conn:
            observations = [
                json.loads(row["payload_json"])
                for row in conn.execute(
                    """SELECT ov.payload_json
                       FROM snapshot_observation_versions sov
                       JOIN observation_versions ov
                         ON ov.observation_version_id=sov.observation_version_id
                       JOIN observations o ON o.obs_id=sov.obs_id
                       WHERE sov.snapshot_id=? ORDER BY o.story_id, ov.observation_order""",
                    (snapshot_id,),
                )
            ]
            metadata = [
                json.loads(row["payload_json"])
                for row in conn.execute(
                    """SELECT sv.payload_json
                       FROM snapshot_story_versions ssv
                       JOIN story_versions sv ON sv.story_version_id=ssv.story_version_id
                       WHERE ssv.snapshot_id=? ORDER BY ssv.position, ssv.story_id""",
                    (snapshot_id,),
                )
            ]
        return {
            "manifest": manifest,
            "functions": self.load_functions(snapshot_id),
            "contracts": self.load_contracts(snapshot_id),
            "observations": observations,
            "story_metadata": metadata,
            "occurrences": occurrences,
        }

    def load_pattern_catalog(self, snapshot_id: str) -> dict:
        self.initialize()
        groups = {"published": [], "rejected": [], "manual_review": []}
        with self.connect() as conn:
            rows = conn.execute(
                """SELECT sp.status, p.payload_json
                   FROM snapshot_patterns sp
                   JOIN patterns p ON p.snapshot_id=sp.snapshot_id AND p.pattern_id=sp.pattern_id
                   WHERE sp.snapshot_id=? ORDER BY sp.pattern_id""",
                (snapshot_id,),
            ).fetchall()
        for row in rows:
            if row["status"] == "published":
                groups["published"].append(json.loads(row["payload_json"]))
        if not groups["published"]:
            raise ValueError(f"Snapshot 没有已发布 Pattern: {snapshot_id}")
        return {
            "snapshot_id": snapshot_id,
            "published_patterns": groups["published"],
            "rejected_patterns": groups["rejected"],
            "manual_review_patterns": groups["manual_review"],
        }
