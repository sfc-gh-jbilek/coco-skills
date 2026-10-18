# Script compatibility

Translate only equivalents documented in [Migrating from SnowSQL to Snowflake CLI](https://docs.snowflake.com/en/user-guide/snowsql-migrate). Four dispositions only. Snowflake CLI is a separate client. Do not describe it as a drop-in replacement.

## Commands

| SnowSQL | Snowflake CLI | Disposition |
| --- | --- | --- |
| `snowsql -q "select 1"` | `snow sql -q "select 1"` | compatible |
| `snowsql -f file.sql` | `snow sql -f file.sql` (`-f` is repeatable) | compatible |
| `snowsql -c dev` | `snow sql -c dev` | compatible |
| `snowsql -D name=value` | `snow sql -D name=value` | compatible |
| `cat file.sql \| snowsql` | `cat file.sql \| snow sql --stdin` | rewrite required |
| `snowsql` with account flags and no saved connection | `snow sql --temporary-connection` (`-x`) plus the same flags | rewrite required |
| `snowsql --probe-connection` | `snow connection test`. `--enable-diag` writes a report. This is not a TLS chain dump. | manual review |
| JWT from user, account, and private key | `snow connection generate-jwt` | manual review |
| PUT and GET | Run the SQL with `snow sql` | compatible |

Without `-q`, `-f`, or `--stdin`, `snow sql` reads stdin and then still enters the REPL. The piped SQL is discarded. The alias `snowsql='snow sql'` does not fix that.

Interactive SQL is `snow sql` with no `-q` or `-f`. `;>` schedules a statement and prints a query id in the REPL and in noninteractive input. `!queries`, `!result`, and `!abort` work in both. `!edit` fails outside the REPL.

## Connection flags

These forms are accepted on `snow sql`: `--account` or `--accountname`, `--user` or `--username`, `--database` or `--dbname`, `--schema` or `--schemaname`, `--role` or `--rolename`, `--warehouse`, `--host`, `--port`, `--protocol`, and `--private-key-file` or `--private-key-path`.

| Flag | Disposition |
| --- | --- |
| `--warehousename` | rewrite required. Use `--warehouse`. |
| `--config` | manual review. The CLI flag is `--config-file`. A SnowSQL config may also hold `[variables]`, which are not connection keys. |
| `--password`, `--passphrase`, tokens | manual review. Redact the value. |

Runtime connection flags override the connection for that command. They do not save a connection. `snow connection add` saves one.

## Variables

SnowSQL `&name` and `&{name}` remain accepted and are deprecated. Prefer `<% name %>`. Substitution is on by default. There is no `-o variable_substitution`.

| Source | Snowflake CLI | Disposition |
| --- | --- | --- |
| `-D name=value` with `&name` | `-D name=value` and `<% name %>` | rewrite required |
| `[variables]` in a SnowSQL config | `-D` or a `snowflake.yml` `env` value referenced as `<% ctx.env.name %>` | manual review |
| `&{ctx.env.name}` | `<% ctx.env.name %>` | rewrite required |
| SnowSQL built-in variables | none | blocked |
| `&name` with no definition in the project | SQL file execution errors | blocked |

Undefined-variable exit codes differ. Do not treat a SnowSQL exit code for an unset `&name` as the CLI exit code. The CLI errors when a SQL file references an unknown variable.

`ctx.env` applies only to project definition `env` values, not to `-D` variables.

## Client directives

| Directive | Disposition |
| --- | --- |
| Local `!source` / `!load` | compatible |
| `https://` `!source` / `!load` | manual review. Rejected when `--local-only`, `SNOWFLAKE_CLI_SQL_LOCAL_ONLY`, or `cli.sql_local_only` is set. A redirect from `https://` to `http://` is rejected. |
| `http://` `!source` / `!load` | blocked. Plaintext `http://` sources are not allowed. |
| `!define` | rewrite required. Use `-D`. Redact secret values. |
| `!exit`, `!quit`, `!queries`, `!result`, `!abort` | compatible |
| `!edit` | blocked outside the REPL |
| `!set` | blocked |
| Any other `!` directive | manual review |

## Output

Supported `--format` values are `TABLE`, `JSON`, `JSON_EXT`, and `CSV`. There is no `-o output_file`. Use shell redirection.

| SnowSQL | Disposition |
| --- | --- |
| `-o output_format=json` and `-o output_file=out.json` | rewrite required: `snow sql --format JSON > out.json` |
| `-o output_format=csv` or `tsv`, including a small file | blocked |
| `-o output_file` for a large extract | blocked. Keep `COPY INTO @stage` followed by `snow stage copy`. |
| Any other `-o` setting (`timing`, `friendly`, `quiet`, `log_level`, `header`, `rowset_size`, and the rest) | blocked |

CSV, newline, backslash, tab, and CRLF differences are blocked. Snowflake CLI CSV is UTF-8 only, uses a newline of `\n`, and has no delimiter or quoting flags. A clean Linux run is not evidence that truncation is fixed.

A merged table-streaming change improves large TABLE rendering speed and memory only. It does not retry result chunks, validate row counts, or fix silent CSV truncation. Do not cite a faster TABLE render as proof that a CSV extract is safe.

## Stop on error

Noninteractive `snow sql` stops at the first failing SQL statement and returns a nonzero exit code. There is no continue-on-error switch.

| Form | Disposition |
| --- | --- |
| `-o exit_on_error=true` | compatible. Drop the flag. The CLI already stops. |
| `-o exit_on_error=false` | blocked |
| Mid-script `!set exit_on_error=...` | blocked |
| `--enhanced-exit-codes` or `SNOWFLAKE_ENHANCED_EXIT_CODES=1` | manual review |

`--enhanced-exit-codes` changes a SQL failure from exit 1 to exit 5 and still stops at the first failing statement. It does not continue.

## Large extracts

Do not stream a large result through `snow sql` CSV or TABLE output and call it an export. Keep:

```sql
COPY INTO @my_stage/extract/
FROM (select ... )
FILE_FORMAT = (TYPE = CSV)
HEADER = TRUE;
```

```bash
snow stage copy @my_stage/extract/ ./extract/ --recursive
```

Use a stage and a file format the user already has, or ask before creating them. Do not run the `COPY INTO` until the user confirms a named non-production connection.
