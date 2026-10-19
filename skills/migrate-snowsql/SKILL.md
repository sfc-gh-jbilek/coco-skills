---
name: migrate-snowsql
title: Migrate SnowSQL
summary: Guided SnowSQL to Snowflake CLI migration with an inventory, one-time import, and approved script copies.
description: "Use when migrating SnowSQL scripts, connection files, or SNOWSQL_* variables to Snowflake CLI. Triggers: migrate SnowSQL, SnowSQL to Snowflake CLI, snow helpers import-snowsql-connections, check-snowsql-env-vars, convert snowsql scripts, $migrate-snowsql. Do not use for warehouse cost, billing, general SQL, or config-v2 connection management. Snowflake CLI is a separate client. Do not describe it as a drop-in replacement, and do not run this workflow unattended."
tools:
  - Bash
  - Read
  - Write
  - Edit
  - Grep
  - Glob
prompt: Migrate my SnowSQL scripts and connections to Snowflake CLI.
language: en
status: Hidden
author: Jan Bilek
type: snowflake
---

# Migrate SnowSQL

## Overview

Guided move from SnowSQL to Snowflake CLI. Two tracks: configuration, then scripts. You inventory and explain first. You change files only after a separate yes for that change.

Load `references/configuration.md`, `references/compatibility.md`, and `references/validation.md` before you classify or edit. Four dispositions only: `compatible`, `rewrite required`, `manual review`, `blocked`.

Out of scope: continuous SnowSQL sync, runtime SnowSQL compatibility, config-v2, and unattended migration.

## Work repo

The inventory, the plan, the script copies, and the report live in the work repo. Do not write them into the SnowSQL project.

The work repo is `$PRODUCT_WORK_ROOT` when that variable is a directory. Otherwise the current git repository is the work repo.

The migration directory inside the work repo:

- `$PRODUCT_WORK_ROOT` is set: `work/snowcli/migrate-snowsql/runs/<slug>/`
- otherwise: `snowsql-migration/` at the work repo root

`<slug>` is the SnowSQL project's directory name. Create that directory before writing. Call it `$MIGRATION_DIR` below. Scan the SnowSQL project by path. Redirect scanner stdout into `$MIGRATION_DIR`.

## Workflow

### 1. Preflight

Record OS, `snowsql --version`, and `snow --version`. Confirm `snow` is Snowflake CLI. Find project files and config locations with `snow --info` (`default_config_file_path`). Do not print secret values. Leave SnowSQL installed and do not edit its config.

Refuse `snow helpers import-snowsql-connections` unless both checks pass. Run them with `uv run --project "$SKILL_DIRECTORY" python "$SKILL_DIRECTORY/scripts/scan_snowsql.py"`:

- `--check-cli-version` reads `snow --version` and must print `newer-than-3.29.0`. Public releases through v3.29.0 (2026-10-07) do not contain the corrected importer. No newer public release is encoded here. A `3.30.0.dev0` build can pass this half only.
- `--check-importer-help` reads `snow helpers import-snowsql-connections --help` and must print `corrected`.

If either check fails, say the corrected importer is not in this install and stop the import. Do not invent a release number.

### 2. Inventory

Run `snow helpers check-snowsql-env-vars` first. It is read-only. Then run the scanner on the SnowSQL project and save stdout as `$MIGRATION_DIR/snowsql-inventory.json`:

```bash
uv run --project "$SKILL_DIRECTORY" python "$SKILL_DIRECTORY/scripts/scan_snowsql.py" "$SNOWSQL_PROJECT" > "$MIGRATION_DIR/snowsql-inventory.json"
```

Write `$MIGRATION_DIR/migration-plan.md` with the line `STATUS: STOPPED_BEFORE_MUTATION`, the four disposition counts, and the blocked reasons from the JSON. Redact secrets. Names and `<redacted>` only.

⚠️ STOP. Do not import, edit, or run SQL until the user approves the plan.

### 3. Connection import

Only after a separate yes, and only if step 1 passed. Back up the Snowflake CLI config file. Run `snow helpers import-snowsql-connections` once. It is not a sync. Show a redacted before/after of connection names and key names. Details: `references/configuration.md`.

⚠️ STOP. Import does not approve script edits or SQL.

### 4. Script copies

Only after a separate yes. Write copies under `$MIGRATION_DIR/snowsql-migrated/`, preserving relative paths. Never edit the original. Skip any file that has a `blocked` finding. Translate only documented equivalents from `references/compatibility.md`. Rewrite a defined `&name` to `<% name %>`. Change `snowsql` to `snow sql`. Show `diff -u` before treating a copy as accepted. If the user rejects a copy, delete it.

Large extracts stay `COPY INTO @stage` followed by `snow stage copy`. A faster TABLE render does not fix CSV truncation.

### 5. Validate and report

Static checks need no connection. A passing fixture does not certify untested scripts. Live SQL needs another yes and a named non-production connection. Follow `references/validation.md`.

Write `$MIGRATION_DIR/snowsql-migration-report.md` with: migrated files, unresolved blockers (`DISPOSITION: blocked`), validation evidence, rollback, and the exact `snow --version` text. After copies exist, include `STATUS: COPIES_WRITTEN`.

## Stopping points

- After the plan, before import, edits, or SQL.
- After import, before script copies or SQL.
- Before each live SQL session, with a named non-production connection.

## Common mistakes

- Treating Snowflake CLI as a drop-in replacement.
- Importing on v3.29.0 or any help text that still says custom config files are used instead of the default list.
- Using `--enhanced-exit-codes` to continue after a SQL error. It changes exit 1 to exit 5 and still stops.
- Rewriting a CSV extract to `snow sql --format CSV` and calling the bytes equivalent.
- Printing passwords, keys, tokens, or connection values.
- Editing the original script or the SnowSQL config.
- Writing the inventory, plan, copies, or report into the SnowSQL project.
