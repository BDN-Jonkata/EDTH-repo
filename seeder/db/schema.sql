-- Schema for the sensor/platform catalog and saved simulations.
-- Safe to run repeatedly.

CREATE TABLE IF NOT EXISTS sensor_modules (
    id              text PRIMARY KEY,
    kind            text NOT NULL CHECK (kind IN ('eo_camera', 'thermal_camera', 'microphone', 'rf_receiver', 'radar', 'gnss', 'imu')),
    name            text NOT NULL,
    spec            jsonb NOT NULL DEFAULT '{}',      -- manufacturer facts
    sim             jsonb NOT NULL DEFAULT '{}',      -- numbers the simulation uses
    outputs         jsonb NOT NULL DEFAULT '[]',      -- names of the fields the module produces
    native          jsonb NOT NULL DEFAULT '{}',      -- output type + fields with units
    weather_effects jsonb NOT NULL DEFAULT '{}',      -- fog/rain/wind/night multipliers
    verified        boolean NOT NULL DEFAULT false,   -- spec read from an official datasheet
    source          text
);

-- for databases created before the native column existed
ALTER TABLE sensor_modules ADD COLUMN IF NOT EXISTS native jsonb NOT NULL DEFAULT '{}';

CREATE TABLE IF NOT EXISTS platform_models (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    platform    text NOT NULL CHECK (platform IN ('uas', 'ground')),
    cost_tier   text NOT NULL CHECK (cost_tier IN ('low', 'mid', 'high')),
    spec        jsonb NOT NULL DEFAULT '{}',
    verified    boolean NOT NULL DEFAULT false,
    source      text
);

CREATE TABLE IF NOT EXISTS platform_model_modules (
    platform_id text NOT NULL REFERENCES platform_models (id) ON DELETE CASCADE,
    module_id   text NOT NULL REFERENCES sensor_modules (id),
    mount       text NOT NULL DEFAULT 'body',
    count       integer NOT NULL DEFAULT 1 CHECK (count > 0),
    PRIMARY KEY (platform_id, module_id, mount)
);

-- A saved run: scenario and result are stored as plain JSON.
CREATE TABLE IF NOT EXISTS simulations (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,
    seed        integer NOT NULL,
    params      jsonb NOT NULL DEFAULT '{}',          -- mode, weather, loss, delay, drift
    scenario    jsonb NOT NULL,
    result      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS simulations_created_idx ON simulations (created_at DESC);

-- Which detection modalities each platform carries.
CREATE OR REPLACE VIEW platform_loadouts AS
SELECT p.id, p.name, p.platform,
       array_agg(DISTINCT m.kind ORDER BY m.kind) AS kinds
FROM platform_models p
JOIN platform_model_modules pm ON pm.platform_id = p.id
JOIN sensor_modules m ON m.id = pm.module_id
GROUP BY p.id, p.name, p.platform;
