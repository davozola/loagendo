"""Bounded, auditable local scheduler for Brollant ingestion jobs.

It deliberately has no daemon or web endpoint: launchd (or another local
scheduler) invokes ``run.py --run-jobs``.  Each job writes its own audit row,
so a crash, a source error, or a disabled connector never hides the state of
the rest of the engine.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

from src.sync import GUIABCN_ENDPOINT, IncrementalSync, now_utc

STALE_LOCK_MINUTES = 120
VALID_KINDS = {"api", "web", "opendata", "venues", "enrich", "media", "media_maintenance", "publish", "dedupe", "places", "eventbrite", "ticketmaster", "xceed", "dice", "ai", "ai_agenda", "organizer_text", "official_dates"}
# A completed run that returns far fewer rows than the source usually gives is
# a parser or site regression, not success (CCCB once returned 4 rows after 122).
LOW_VOLUME_RATIO = 0.3


def initialize(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS automation_runs (
      id INTEGER PRIMARY KEY AUTOINCREMENT, job_name TEXT NOT NULL, source TEXT NOT NULL DEFAULT '',
      kind TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
      result_json TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS automation_runs_job_finished ON automation_runs(job_name, finished_at DESC);
    CREATE TABLE IF NOT EXISTS source_health (
      source TEXT PRIMARY KEY, last_success_at TEXT, last_failure_at TEXT,
      last_status TEXT NOT NULL DEFAULT 'never_run', consecutive_failures INTEGER NOT NULL DEFAULT 0,
      last_error TEXT NOT NULL DEFAULT ''
    );
    CREATE TABLE IF NOT EXISTS automation_locks (
      name TEXT PRIMARY KEY, held_at TEXT NOT NULL
    );
    """)


def load_config(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ValueError("No existe la configuración de automatización") from error
    except json.JSONDecodeError as error:
        raise ValueError("automation.json no es JSON válido") from error
    if not isinstance(value, dict) or not isinstance(value.get("jobs"), list):
        raise ValueError("automation.json requiere una lista jobs")
    names = set()
    for job in value["jobs"]:
        if not isinstance(job, dict) or not isinstance(job.get("name"), str) or not job["name"]:
            raise ValueError("Cada trabajo requiere name")
        if job["name"] in names: raise ValueError("Los nombres de trabajo deben ser únicos")
        names.add(job["name"])
        if job.get("kind") not in VALID_KINDS: raise ValueError("Tipo de trabajo no permitido: %s" % job.get("kind"))
        if not isinstance(job.get("every_minutes"), int) or not 1 <= job["every_minutes"] <= 10080:
            raise ValueError("every_minutes debe estar entre 1 y 10080")
        if job["kind"] in ("api", "web") and not isinstance(job.get("source"), str):
            raise ValueError("Los trabajos de fuente requieren source")
    return value


def _last_terminal(conn, name):
    row = conn.execute("SELECT finished_at,status FROM automation_runs WHERE job_name=? AND status IN ('completed','failed','interrupted','suspect','partial') ORDER BY id DESC LIMIT 1", (name,)).fetchone()
    if not row or not row[0]: return None
    try: return (dt.datetime.fromisoformat(row[0]),row[1])
    except ValueError: return None


def is_due(conn, job, now):
    last = _last_terminal(conn, job["name"])
    if last is None: return True
    finished,status=last
    # A failed connector should be visible and recover automatically, but it
    # must not hammer a site on every 15-minute scheduler wake-up. A job may
    # opt into a longer explicit retry delay; otherwise its normal cadence is
    # used for every terminal result.
    minutes=job.get('retry_after_minutes',job['every_minutes']) if status!='completed' else job['every_minutes']
    return now-finished >= dt.timedelta(minutes=minutes)


def _maintain_media(conn, media_root):
    """Repair references to missing previews without deleting audit metadata."""
    cleared = 0
    rows = conn.execute("SELECT asset_id,local_path FROM media_assets WHERE local_path IS NOT NULL").fetchall()
    for asset_id, local_path in rows:
        if not Path(local_path).is_file():
            conn.execute("UPDATE media_assets SET local_path=NULL,content_type=NULL WHERE asset_id=?", (asset_id,)); cleared += 1
    duplicate_refs = conn.execute("SELECT COUNT(*) FROM (SELECT sha256 FROM media_assets WHERE sha256<>'' GROUP BY sha256 HAVING COUNT(*)>1)").fetchone()[0]
    conn.commit()
    from src.media import retry_transient_download_failures
    retried = retry_transient_download_failures(conn)
    return {"cleared_missing_paths": cleared, "deduplicated_file_groups": duplicate_refs, "transient_failures_requeued": retried, "media_root": str(media_root)}


def execute(conn, job, media_root):
    kind = job["kind"]
    if kind == "api":
        source = job["source"]
        endpoint = job.get("endpoint") or (GUIABCN_ENDPOINT if source == "guiabcn" else "")
        if not endpoint.startswith("https://"): raise ValueError("Endpoint HTTPS pendiente para %s" % source)
        return IncrementalSync(conn).run(source, endpoint, page_size=job.get("page_size", 250), max_rows=job.get("max_rows", 10000), timeout_seconds=job.get("timeout_seconds", 180),
                                         organizers_endpoint=job.get("organizers_endpoint", ""), since_days=job.get("since_days", 0))
    if kind == "opendata":
        from src.opendata_bcn import sync as sync_opendata
        return sync_opendata(conn, timeout=job.get("timeout_seconds", 900), file=job.get("file") or None)
    if kind == "venues":
        from src.venue_feeds import sync_enabled
        return sync_enabled(conn, timeout=job.get("timeout_seconds", 25))
    if kind == "web":
        from src.web_agendas import sync
        return sync(conn, job["source"], timeout=job.get("timeout_seconds", 30))
    if kind == "enrich":
        from src.guia_detail import enrich_sources
        return enrich_sources(conn, job.get("limit", 100), timeout=job.get("timeout_seconds", 20))
    if kind == "places":
        from src.place_images import fetch_place_images
        return fetch_place_images(conn, media_root, limit=job.get("limit", 60), timeout=job.get("timeout_seconds", 20))
    if kind == "ticketmaster":
        from src.ticketmaster_api import sync as sync_ticketmaster
        return sync_ticketmaster(conn)
    if kind == "xceed":
        from src.xceed_api import sync as sync_xceed
        return sync_xceed(conn)
    if kind == "dice":
        from src.dice_sitemap import sync as sync_dice
        return sync_dice(conn, limit=job.get("limit", 200))
    if kind == "eventbrite":
        from src.eventbrite_api import enrich_eventbrite
        return enrich_eventbrite(conn, job.get("limit", 300), timeout=job.get("timeout_seconds", 20))
    if kind == "ai":
        from src.ai_assist import run as run_ai
        return run_ai(conn, job)
    if kind == "organizer_text":
        from src.organizer_text import run as run_organizer
        return run_organizer(conn, job.get("limit", 150), timeout=job.get("timeout_seconds", 15))
    if kind == "official_dates":
        from src.official_dates import run_all
        return run_all(conn, job)
    if kind == "ai_agenda":
        from src.ai_agenda import run as run_agendas
        return run_agendas(conn, job)
    if kind == "dedupe":
        from src.dedupe import refresh_match_candidates
        result = refresh_match_candidates(conn)
        return {"status": "completed", "pairs": result["pairs"], "records_compared": result["records_compared"], "by_source_pair": result["by_source_pair"]}
    if kind == "publish":
        from src.publish_static import publish
        return publish(conn, job, media_root=media_root)
    if kind == "media":
        from src.media import download_local_previews
        return download_local_previews(conn, media_root, job.get("limit", 100), job.get("source"))
    return _maintain_media(conn, media_root)


def _median_rows(conn, source, exclude_run_id=None):
    rows = [r[0] for r in conn.execute("SELECT rows_received FROM sync_runs WHERE source=? AND status='completed' AND id<>COALESCE(?,-1) ORDER BY id DESC LIMIT 7", (source, exclude_run_id))]
    if not rows: return None
    rows.sort(); return rows[len(rows) // 2]


def volume_check(conn, source, result):
    """Flag a completed run whose row count collapsed against recent history."""
    if not source or result.get("status") != "completed": return None
    received = result.get("rows_received")
    if received is None: return None
    median = _median_rows(conn, source, result.get("id"))
    if median is None or median < 10: return None
    if received < median * LOW_VOLUME_RATIO:
        return "LOW_VOLUME: %s filas frente a una mediana reciente de %s; posible cambio en la fuente o en el parser" % (received, median)
    return None


def _health(conn, source, status, error=""):
    # «skipped»: el trabajo no se ha podido intentar (p. ej. falta la clave de
    # la API); no dice nada de la salud de la fuente.
    if not source or status == "skipped": return
    now = now_utc()
    previous = conn.execute("SELECT consecutive_failures FROM source_health WHERE source=?", (source,)).fetchone()
    failures = 0 if status == "completed" else (previous[0] if previous else 0) + 1
    conn.execute("""INSERT INTO source_health(source,last_success_at,last_failure_at,last_status,consecutive_failures,last_error)
      VALUES(?,?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET last_success_at=excluded.last_success_at,
      last_failure_at=excluded.last_failure_at,last_status=excluded.last_status,
      consecutive_failures=excluded.consecutive_failures,last_error=excluded.last_error""",
      (source, now if status == "completed" else None, now if status != "completed" else None, status, failures, error[:500]))


def run_due(conn, config, media_root, *, force=False, now=None):
    initialize(conn)
    now = now or dt.datetime.now(dt.timezone.utc)
    # Un candado más viejo que esto se da por abandonado. 30 minutos se quedaba
    # corto: una publicación que recalcula todo el catálogo puede pasar de 30
    # minutos y otra pasada la daba por muerta (18-10-2026).
    stale_before = (now - dt.timedelta(minutes=STALE_LOCK_MINUTES)).isoformat(timespec="seconds")
    with conn:
        conn.execute("DELETE FROM automation_locks WHERE name='engine' AND held_at<?", (stale_before,))
        acquired = conn.execute("INSERT OR IGNORE INTO automation_locks(name,held_at) VALUES ('engine',?)", (now_utc(),)).rowcount
    if not acquired:
        return {"ran_at": now.isoformat(timespec="seconds"), "outcomes": [], "status": "engine_busy"}
    # launchd may terminate a process during logout, sleep, or an upgrade.
    # A row left running must never suppress the next safe retry or disguise
    # a stale job as an active sync.
    with conn:
        conn.execute("""UPDATE automation_runs SET status='interrupted',finished_at=?,
          error='Proceso interrumpido antes de finalizar' WHERE status='running'""", (now_utc(),))
    outcomes = []
    try:
        for job in config["jobs"]:
            if not job.get("enabled", True):
                outcomes.append({"name": job["name"], "status": "disabled"}); continue
            if not force and not is_due(conn, job, now):
                outcomes.append({"name": job["name"], "status": "not_due"}); continue
            source = job.get("source", "")
            with conn:
                run_id = conn.execute("INSERT INTO automation_runs(job_name,source,kind,started_at,status) VALUES(?,?,?,?,?)", (job["name"], source, job["kind"], now_utc(), "running")).lastrowid
            try:
                result = execute(conn, job, media_root)
                status = "completed" if result.get("status", "completed") == "completed" else result.get("status", "failed")
                error = "" if status == "completed" else json.dumps(result, ensure_ascii=False)
                anomaly = volume_check(conn, source, result)
                if anomaly:
                    status, error = "suspect", anomaly; result = {**result, "anomaly": anomaly}
            except Exception as exc:
                result, status, error = {}, "failed", str(exc)
            with conn:
                conn.execute("UPDATE automation_runs SET finished_at=?,status=?,result_json=?,error=? WHERE id=?", (now_utc(), status, json.dumps(result, ensure_ascii=False, sort_keys=True), error[:1000], run_id))
                _health(conn, source, status, error)
            outcomes.append({"name": job["name"], "source": source, "status": status, "result": result, "error": error})
        return {"ran_at": now.isoformat(timespec="seconds"), "outcomes": outcomes}
    finally:
        with conn: conn.execute("DELETE FROM automation_locks WHERE name='engine'")


def status(conn):
    initialize(conn)
    return {
        "health": [dict(zip(("source", "last_success_at", "last_failure_at", "last_status", "consecutive_failures", "last_error"), row)) for row in conn.execute("SELECT source,last_success_at,last_failure_at,last_status,consecutive_failures,last_error FROM source_health ORDER BY source")],
        "recent_runs": [dict(zip(("job_name", "source", "kind", "started_at", "finished_at", "status", "error"), row)) for row in conn.execute("SELECT job_name,source,kind,started_at,finished_at,status,error FROM automation_runs ORDER BY id DESC LIMIT 100")],
    }
