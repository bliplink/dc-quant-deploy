CREATE TABLE IF NOT EXISTS dc.strategy_live_registry
(
    `id` String,
    `strategy_name` String,
    `strategy_version` String,
    `category` String,
    `scene` String,
    `runtime_type` String,
    `symbol_scope` String,
    `text_scope` String,
    `artifact_uri` String,
    `entry_class` String,
    `parameters_json` String,
    `status` String,
    `effective_time` DateTime,
    `retire_time` Nullable(DateTime),
    `source` String,
    `payload` String,
    `description` String
)
ENGINE = ReplacingMergeTree(effective_time)
ORDER BY (strategy_name, strategy_version, effective_time);

ALTER TABLE dc.strategy_live_registry
    ADD COLUMN IF NOT EXISTS `description` String DEFAULT '' AFTER `payload`;

-- description is a runtime snapshot copied from strategy_candidate.description.
-- Do not backfill runtime description from strategy_scene_meta anymore.

-- Detect invalid ACTIVE rows with blank description.
SELECT
    strategy_name,
    strategy_version,
    scene,
    runtime_type,
    effective_time
FROM dc.strategy_live_registry
WHERE status = 'ACTIVE'
  AND (description = '' OR description IS NULL)
ORDER BY scene, strategy_name, effective_time DESC;

-- Detect duplicate ACTIVE versions for one strategy_name.
SELECT
    strategy_name,
    count() AS active_count,
    groupArray(strategy_version) AS active_versions
FROM dc.strategy_live_registry
WHERE status = 'ACTIVE'
GROUP BY strategy_name
HAVING count() > 1;

-- Detect ACTIVE rows whose description diverges from the candidate source.
SELECT
    r.strategy_name,
    r.strategy_version,
    r.description AS registry_description,
    c.description AS candidate_description
FROM dc.strategy_live_registry r
LEFT JOIN
(
    SELECT
        strategy_name,
        strategy_version,
        argMax(description, create_time) AS description
    FROM dc.strategy_candidate
    GROUP BY strategy_name, strategy_version
) c
ON lower(r.strategy_name) = lower(c.strategy_name)
   AND lower(r.strategy_version) = lower(c.strategy_version)
WHERE r.status = 'ACTIVE'
  AND ifNull(r.description, '') != ifNull(c.description, '');
