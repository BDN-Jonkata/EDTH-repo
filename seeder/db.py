"""PostgreSQL helpers: connect, create schema, load the catalog, save simulations."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

SEEDER_DIR = Path(__file__).parent
SCHEMA = SEEDER_DIR / "db" / "schema.sql"


def _load_dotenv():
    """Read .env files (KEY=VALUE lines) into os.environ without overriding real env vars.
    Looks in the repo root first, then in seeder/."""
    for path in (SEEDER_DIR.parent / ".env", SEEDER_DIR / ".env"):
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def connect():
    _load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env (repo root) and fill it in.")
    return psycopg.connect(url)


def apply_schema(conn):
    conn.execute(SCHEMA.read_text(encoding="utf-8"))


def upsert_catalog(conn, catalog):
    for m in catalog["modules"]:
        conn.execute(
            """INSERT INTO sensor_modules (id, kind, name, spec, sim, outputs, native, weather_effects, verified, source)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET kind = EXCLUDED.kind, name = EXCLUDED.name, spec = EXCLUDED.spec,
                 sim = EXCLUDED.sim, outputs = EXCLUDED.outputs, native = EXCLUDED.native,
                 weather_effects = EXCLUDED.weather_effects, verified = EXCLUDED.verified, source = EXCLUDED.source""",
            (m["id"], m["kind"], m["name"], Jsonb(m["spec"]), Jsonb(m["sim"]), Jsonb(m["outputs"]),
             Jsonb(m.get("native", {})), Jsonb(m["weather_effects"]), m["verified"], m["source"]),
        )
    for p in catalog["platforms"]:
        conn.execute(
            """INSERT INTO platform_models (id, name, platform, cost_tier, spec, verified, source)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, platform = EXCLUDED.platform,
                 cost_tier = EXCLUDED.cost_tier, spec = EXCLUDED.spec, verified = EXCLUDED.verified, source = EXCLUDED.source""",
            (p["id"], p["name"], p["platform"], p["cost_tier"], Jsonb(p["spec"]), p["verified"], p["source"]),
        )
        # the catalog file is the source of truth for a platform's loadout
        conn.execute("DELETE FROM platform_model_modules WHERE platform_id = %s", (p["id"],))
        for link in p["modules"]:
            conn.execute(
                "INSERT INTO platform_model_modules (platform_id, module_id, mount, count) VALUES (%s, %s, %s, %s)",
                (p["id"], link["module_id"], link["mount"], link["count"]),
            )


def save_simulation(conn, name, seed, params, scenario, result):
    """Store one run as plain JSON. Returns the new row id."""
    row = conn.execute(
        "INSERT INTO simulations (name, seed, params, scenario, result) VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (name, seed, Jsonb(params), Jsonb(scenario), Jsonb(result)),
    ).fetchone()
    return row[0]


def save_scenario(conn, scenario, truth):
    """Store a generated scenario (replacing one with the same id). Returns the row id."""
    row = conn.execute(
        """INSERT INTO scenarios (scenario_id, name, preset, seed, config, scenario, truth)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (scenario_id) DO UPDATE SET name = EXCLUDED.name, preset = EXCLUDED.preset, seed = EXCLUDED.seed,
             config = EXCLUDED.config, scenario = EXCLUDED.scenario, truth = EXCLUDED.truth, created_at = now()
           RETURNING id""",
        (scenario["id"], scenario["name"], scenario["preset"], scenario["seed"], Jsonb(scenario["config"]), Jsonb(scenario), Jsonb(truth)),
    ).fetchone()
    return row[0]
