# Validation and the report

Static checks do not open a connection. A scanner result on a fixture does not certify scripts that were not in that tree. `certifies_untested_scripts` in the scanner JSON is false.

## Static checks

Run from the project root:

```bash
uv run --project "$SKILL_DIRECTORY" python "$SKILL_DIRECTORY/scripts/scan_snowsql.py" . > snowsql-inventory.json
```

The command is read-only. It writes nothing except the file you redirect. Review `snowsql-inventory.json` before you trust a summary a person typed.

The inventory lists SnowSQL invocations, flags, `-o` options, `SNOWSQL_*` names, client directives, file includes, output contracts, and large-result exports. Secret values are `<redacted>`. If a planted or real secret string appears in the JSON, stop and fix the redaction before showing the file.

Importer gates, still with no connection:

```bash
snow --version | uv run --project "$SKILL_DIRECTORY" python "$SKILL_DIRECTORY/scripts/scan_snowsql.py" --check-cli-version
snow helpers import-snowsql-connections --help | uv run --project "$SKILL_DIRECTORY" python "$SKILL_DIRECTORY/scripts/scan_snowsql.py" --check-importer-help
```

Both must exit 0 before an import. `snow helpers check-snowsql-env-vars` must be the read-only check from `references/configuration.md`.

After approved copies exist, run `diff -u` between each original and `snowsql-migrated/` copy. Originals must stay byte-for-byte identical. Files with a blocked finding must not have a translated copy.

## Optional live SQL

Do not run SQL until the user gives a separate confirmation and names a non-production connection. Do not invent credentials. Do not change a network policy. Do not print secret values. Generate any temporary config as mode `0600` and delete it before you finish.

Use synthetic SQL only. Record hashes, row counts, the exact `snow --version` and `snowsql --version`, timings, and redacted diagnostics. A match on one statement does not certify the rest of the project.

| Check | What you are showing |
| --- | --- |
| Stop on error | The CLI stops at the first failing statement. |
| Continue on error | `-o exit_on_error=false` has no CLI equivalent. `--enhanced-exit-codes` still stops. Exit 1 becomes exit 5. |
| CSV edges | Newline, backslash, tab, and CRLF bytes can differ. UTF-8 only. No delimiter or quoting flags. |
| Substitution | A defined `&name` rewrites to `<% name %>`. |
| Undefined variable | The CLI error and exit code are not the SnowSQL undefined-variable exit code. |
| Local `!source` | A local include runs. `http://` does not. |
| Ordered narrow results | Compare counts and hashes for an ordered 10k result and an ordered 1M narrow result when the user approves the cost. |
| Wide CSV | One wide multi-minute CSV is a timing sample. It does not prove truncation is fixed. |

Large file extracts stay `COPY INTO @stage` and `snow stage copy`. A faster TABLE render is not a substitute.

If any of `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_PRIVATE_KEY`, `SNOWFLAKE_ROLE`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, or `SNOWFLAKE_SCHEMA` is missing, skip live SQL and say which names are missing. Do not print values.

## Report

Write `snowsql-migration-report.md` with these sections:

```markdown
# SnowSQL migration report

## Snowflake CLI version

<paste the exact snow --version output>

## Migrated files

<paths under snowsql-migrated/, or none>

## Unresolved blockers

DISPOSITION: blocked
<path, finding name, and the scanner reason. No secret values.>

## Validation evidence

Static scan does not certify untested scripts.
<scanner summary counts, diff paths, and live evidence or "live SQL skipped">

## Rollback

SnowSQL remains installed and its config was not edited.
Restore the CLI config backup from <path>.
Remove the snowsql shell alias if one was added.
```

Include `STATUS: COPIES_WRITTEN` only after copies were written. Include `STATUS: STOPPED_BEFORE_MUTATION` in `migration-plan.md` when you are still waiting for approval.

Blocked items stay in "Unresolved blockers" even if the user accepts every compatible copy.
