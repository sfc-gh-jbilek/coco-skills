"""Read-only inventory of SnowSQL scripts and configuration.

The scanner prints redacted JSON on stdout. It does not write files, import
connections, or open a Snowflake session. A passing scan does not certify
scripts that were not in the tree.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCANNER = "migrate-snowsql"
SCHEMA_VERSION = 1

# Public snowflakedb/snowflake-cli v3.29.0 (2026-10-07) ships an older importer.
# No later public release was published when this gate was written.
PUBLIC_RELEASE_WITHOUT_CORRECTION = (3, 29, 0)

DISPOSITIONS = (
    "compatible",
    "rewrite required",
    "manual review",
    "blocked",
)
_RANK = {name: index for index, name in enumerate(DISPOSITIONS)}

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    "snowsql-migrated",
    ".snowflake",
}
SKIP_FILES = {
    "snowsql-inventory.json",
    "snowsql-migration-report.md",
    "migration-plan.md",
}
TEXT_SUFFIXES = {
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".bat",
    ".cmd",
    ".cnf",
    ".ini",
    ".py",
}
MAX_BYTES = 1_000_000

_HELP_MARKERS = (
    "does not replace the default file list",
    "not copied onto it",
)

_SECRET_KEY = (
    r"(?:--)?(?:password|passwd|pwd|passphrase|secret|token|"
    r"private[-_]key[-_]file[-_]pwd|api[-_]key|access[-_]key|secret[-_]key|"
    r"SNOWSQL_PWD|SNOWSQL_PASSWORD|SNOWSQL_PRIVATE_KEY_PASSPHRASE|SNOWSQL_PROXY_PWD)"
)
_SECRET_RE = re.compile(
    rf"(?i)({_SECRET_KEY})(\s*=\s*|\s+)([\"']?)([^\s\"';&|]+)"
)
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:\.dev(\d+))?")
_OPTION_RE = re.compile(
    r"(?i)(?:^|\s)-o\s*([A-Za-z0-9_]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|(\S+))"
)
_LONG_FLAG = re.compile(r"(?i)--([A-Za-z0-9-]+)(?:=|\s+|$)(\"[^\"]*\"|'[^']*'|\S+)?")
_SHORT_WITH_VALUE = re.compile(
    r"(?i)(?:^|\s)-([qfcD])(?:\s+|=)(\"[^\"]*\"|'[^']*'|\S+)"
)
_DIRECTIVE = re.compile(r"(?im)^[ \t]*(![A-Za-z]+)[ \t]*(.*)$")
_VAR = re.compile(r"&\{([A-Za-z_][A-Za-z0-9_.]*)\}|(?<![&])&([A-Za-z_][A-Za-z0-9_]*)")
_ENV_NAME = re.compile(r"\b(SNOWSQL_[A-Z0-9_]+)\b")
_DEFINE = re.compile(r"(?im)^[ \t]*!define[ \t]+([A-Za-z_][A-Za-z0-9_]*)")
_D_FLAG = re.compile(r"(?i)(?:^|\s)(?:-D|--variable)(?:\s+|=)(\"[^\"]*\"|'[^']*'|\S+)")
_FILENAME = re.compile(
    r"(?i)(?:^|\s)(?:-f|--filename)(?:\s+|=)(\"[^\"]*\"|'[^']*'|\S+)"
)
_QUERY = re.compile(r"(?i)(?:^|\s)(?:-q|--query)(?:\s+|=)(\"[^\"]*\"|'[^']*'|\S+)")
_LARGE = re.compile(r"(?i)large[-_ ]?result|large[-_ ]?export|large_export|\bunload\b")

COMPATIBLE_LONG = {
    "account",
    "accountname",
    "user",
    "username",
    "database",
    "dbname",
    "schema",
    "schemaname",
    "role",
    "rolename",
    "warehouse",
    "host",
    "port",
    "protocol",
    "private-key-file",
    "private-key-path",
    "authenticator",
    "query",
    "filename",
    "connection",
    "variable",
    "stdin",
    "format",
    "temporary-connection",
}

ENV_MAP = {
    "SNOWSQL_ACCOUNT": ("rewrite required", "SNOWFLAKE_ACCOUNT"),
    "SNOWSQL_USER": ("rewrite required", "SNOWFLAKE_USER"),
    "SNOWSQL_PWD": ("rewrite required", "SNOWFLAKE_PASSWORD"),
    "SNOWSQL_PASSWORD": ("rewrite required", "SNOWFLAKE_PASSWORD"),
    "SNOWSQL_DATABASE": ("rewrite required", "SNOWFLAKE_DATABASE"),
    "SNOWSQL_SCHEMA": ("rewrite required", "SNOWFLAKE_SCHEMA"),
    "SNOWSQL_WAREHOUSE": ("rewrite required", "SNOWFLAKE_WAREHOUSE"),
    "SNOWSQL_ROLE": ("rewrite required", "SNOWFLAKE_ROLE"),
    "SNOWSQL_HOST": ("rewrite required", "SNOWFLAKE_HOST"),
    "SNOWSQL_PORT": ("rewrite required", "SNOWFLAKE_PORT"),
    "SNOWSQL_PROTOCOL": ("rewrite required", "SNOWFLAKE_PROTOCOL"),
    "SNOWSQL_REGION": (
        "manual review",
        "Put the account identifier in SNOWFLAKE_ACCOUNT. Do not copy the region name.",
    ),
    "SNOWSQL_PROXY_HOST": ("manual review", "HTTPS_PROXY or HTTP_PROXY host"),
    "SNOWSQL_PROXY_PORT": ("manual review", "HTTPS_PROXY or HTTP_PROXY port"),
    "SNOWSQL_PROXY_USER": ("manual review", "HTTPS_PROXY or HTTP_PROXY username"),
    "SNOWSQL_PROXY_PWD": ("manual review", "HTTPS_PROXY or HTTP_PROXY password"),
    "SNOWSQL_PRIVATE_KEY_PASSPHRASE": ("rewrite required", "PRIVATE_KEY_PASSPHRASE"),
}

ALIAS_KEYS = {
    "accountname": "account",
    "username": "user",
    "dbname": "database",
    "databasename": "database",
    "schemaname": "schema",
    "warehousename": "warehouse",
    "rolename": "role",
    "pwd": "password",
    "private_key_path": "private_key_file",
    "private_key_file_pwd": "private_key_passphrase",
    "proxy_pwd": "proxy_password",
}

OPTION_KEYS_COPIED = {
    "login_timeout",
    "client_session_keep_alive",
    "ocsp_fail_open",
    "insecure_mode",
    "client_store_temporary_credential",
}

SECRET_CONFIG_KEYS = {
    "password",
    "pwd",
    "passphrase",
    "token",
    "secret",
    "private_key_file_pwd",
    "private_key_passphrase",
    "proxy_password",
    "proxy_pwd",
}

CSV_REASON = (
    "Snowflake CLI CSV is not a SnowSQL output contract. Export is UTF-8 only. "
    "The writer uses a newline of \\n, and there are no CSV delimiter or quoting flags. "
    "Newline, backslash, tab, and CRLF bytes can differ. "
    "A clean Linux run is not evidence that truncation is fixed."
)

LARGE_RECOMMENDATION = (
    "Keep the extract as COPY INTO @stage followed by snow stage copy. "
    "A merged table-streaming change improves large TABLE rendering speed and memory only. "
    "It does not retry result chunks, validate row counts, or fix silent CSV truncation."
)

CONTINUE_REASON = (
    "There is no continue-after-error switch. A failed SQL statement stops the command. "
    "--enhanced-exit-codes changes a SQL failure from exit 1 to exit 5 and still stops "
    "at the first failing statement. It does not continue."
)

SET_REASON = (
    "Mid-script !set is not a Snowflake CLI directive. "
    "Session options cannot be changed mid-script."
)

UNDEFINED_REASON = (
    "Undefined SnowSQL variable. In a SQL file, Snowflake CLI errors on an unknown "
    "variable. That exit code is not the SnowSQL undefined-variable exit code."
)

ENV_RUNTIME_REASON = (
    "SNOWSQL_* variables are not normal Snowflake CLI runtime variables. "
    "snow helpers check-snowsql-env-vars only prints suggestions."
)


def redact(text: str) -> str:
    """Replace secret assignments with a placeholder. Names stay."""

    def _replace(match: re.Match[str]) -> str:
        return f"{match.group(1)}{match.group(2)}{match.group(3)}<redacted>"

    return _SECRET_RE.sub(_replace, text)


def collect_secret_values(text: str) -> set[str]:
    values: set[str] = set()
    for match in _SECRET_RE.finditer(text):
        value = match.group(4)
        if len(value) >= 8:
            values.add(value)
    return values


def normalize_help(text: str) -> str:
    cleaned = re.sub(r"[│╭╮╰╯─]", " ", text)
    return re.sub(r"\s+", " ", cleaned).lower()


def importer_help_is_corrected(text: str) -> bool:
    """True when help text describes the corrected one-time importer.

    Public v3.29.0 tells the user that ``--snowsql-config-file`` imports
    *instead* of the default locations, and it does not say that unnamed
    connection keys are not copied onto named connections.
    """

    folded = normalize_help(text)
    return all(marker in folded for marker in _HELP_MARKERS)


def cli_version_key(text: str) -> tuple[int, int, int, int, int] | None:
    """Return a sort key, or None when no X.Y.Z version is present.

    A final release sorts after its ``.devN`` prerelease:
    ``3.30.0.dev0`` is newer than ``3.29.0`` and older than ``3.30.0``.
    """

    match = _VERSION_RE.search(text)
    if match is None:
        return None
    major, minor, patch = (int(match.group(index)) for index in (1, 2, 3))
    dev = match.group(4)
    if dev is None:
        return (major, minor, patch, 1, 0)
    return (major, minor, patch, 0, int(dev))


def cli_version_is_newer_than_public(text: str) -> bool:
    key = cli_version_key(text)
    if key is None:
        return False
    major, minor, patch = PUBLIC_RELEASE_WITHOUT_CORRECTION
    threshold = (major, minor, patch, 1, 0)
    return key > threshold


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _finding(
    *,
    path: str,
    line: int,
    kind: str,
    name: str,
    disposition: str,
    reason: str,
    recommendation: str = "",
    evidence: str = "",
) -> dict[str, object]:
    if disposition not in _RANK:
        raise ValueError(f"unknown disposition: {disposition}")
    return {
        "path": path,
        "line": line,
        "kind": kind,
        "name": name,
        "disposition": disposition,
        "reason": reason,
        "recommendation": recommendation,
        "evidence": redact(evidence)[:500],
    }


def _worst(findings: list[dict[str, object]]) -> str:
    if not findings:
        return "compatible"
    return max((str(item["disposition"]) for item in findings), key=_RANK.__getitem__)


def logical_lines(text: str) -> list[tuple[int, str]]:
    grouped: list[tuple[int, str]] = []
    buffer: list[str] = []
    start = 1
    for index, line in enumerate(text.splitlines(), 1):
        if not buffer:
            start = index
        if line.endswith("\\") and not line.endswith("\\\\"):
            buffer.append(line[:-1])
            continue
        buffer.append(line)
        grouped.append((start, " ".join(part.strip() for part in buffer)))
        buffer = []
    if buffer:
        grouped.append((start, " ".join(part.strip() for part in buffer)))
    return grouped


def split_shell(line: str) -> list[str]:
    parts: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(line):
        character = line[index]
        if quote:
            buffer.append(character)
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
            buffer.append(character)
            index += 1
            continue
        if line.startswith("&&", index) or character == ";":
            parts.append("".join(buffer))
            buffer = []
            index += 2 if line.startswith("&&", index) else 1
            continue
        buffer.append(character)
        index += 1
    parts.append("".join(buffer))
    return [part.strip() for part in parts if part.strip()]


def _parse_options(command: str) -> list[tuple[str, str]]:
    options: list[tuple[str, str]] = []
    for match in _OPTION_RE.finditer(command):
        value = match.group(2)
        if value is None:
            value = match.group(3)
        if value is None:
            value = match.group(4) or ""
        options.append((match.group(1).lower(), value))
    return options


def _is_large(*chunks: str) -> bool:
    return _LARGE.search("\n".join(chunks)) is not None


def _classify_option(key: str, value: str, large: bool) -> tuple[str, str, str]:
    lowered = value.strip().lower()
    if key == "exit_on_error":
        if lowered == "false":
            return "blocked", CONTINUE_REASON, ""
        if lowered == "true":
            return (
                "compatible",
                "exit_on_error=true already matches noninteractive snow sql, "
                "which stops on the first SQL error. Drop the -o flag.",
                "",
            )
        return "blocked", CONTINUE_REASON, ""
    if key == "variable_substitution":
        if lowered == "true":
            return (
                "rewrite required",
                "Drop -o variable_substitution. Snowflake CLI substitutes by default. "
                "Prefer <% name %> over &name.",
                "",
            )
        return (
            "blocked",
            "Snowflake CLI cannot turn variable substitution off.",
            "",
        )
    if key == "output_format":
        if lowered in {"csv", "tsv"}:
            return "blocked", CSV_REASON, LARGE_RECOMMENDATION if large else ""
        if lowered == "json":
            if large:
                return "blocked", CSV_REASON, LARGE_RECOMMENDATION
            return (
                "rewrite required",
                "Use snow sql --format JSON and shell redirection. There is no -o output_format.",
                "",
            )
        return (
            "blocked",
            "Unsupported -o output_format. snow sql --format accepts TABLE, JSON, "
            "JSON_EXT, and CSV. " + CSV_REASON,
            "",
        )
    if key == "output_file":
        if large:
            return "blocked", LARGE_RECOMMENDATION, LARGE_RECOMMENDATION
        return (
            "rewrite required",
            "There is no -o output_file. Redirect snow sql stdout in the shell.",
            "",
        )
    return (
        "blocked",
        f"Unsupported -o setting {key}. Snowflake CLI does not accept -o options.",
        "",
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        if size > MAX_BYTES:
            continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name == "config":
            files.append(path)
    return files


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _bound_names(files: list[tuple[str, str]]) -> set[str]:
    names: set[str] = set()
    for _path, text in files:
        for match in _DEFINE.finditer(text):
            names.add(match.group(1))
        for match in _D_FLAG.finditer(text):
            token = _unquote(match.group(1))
            name = token.split("=", 1)[0].strip()
            if name:
                names.add(name)
        section = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[") and stripped.endswith("]"):
                section = stripped[1:-1].strip().lower()
                continue
            if section == "variables" and "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key:
                    names.add(key)
    return names


def _variable_findings(
    *,
    path: str,
    line: int,
    text: str,
    bound: set[str],
    evidence: str,
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    seen: set[str] = set()
    for match in _VAR.finditer(text):
        name = match.group(1) or match.group(2)
        if name in seen:
            continue
        seen.add(name)
        if name.startswith("ctx.env.") or name.startswith("_"):
            findings.append(
                _finding(
                    path=path,
                    line=line,
                    kind="variable",
                    name=name,
                    disposition="blocked" if name.startswith("_") else "rewrite required",
                    reason=(
                        "SnowSQL built-in variables are not supported."
                        if name.startswith("_")
                        else "Project env values use <% ctx.env.name %>, not &{ctx.env.name}."
                    ),
                    evidence=evidence,
                )
            )
            continue
        if name in bound:
            findings.append(
                _finding(
                    path=path,
                    line=line,
                    kind="variable",
                    name=name,
                    disposition="rewrite required",
                    reason="Rewrite &name to <% name %>. -D still passes the value.",
                    evidence=evidence,
                )
            )
        else:
            findings.append(
                _finding(
                    path=path,
                    line=line,
                    kind="variable",
                    name=name,
                    disposition="blocked",
                    reason=UNDEFINED_REASON,
                    evidence=evidence,
                )
            )
    return findings


def _referenced_sql(root: Path, script: Path, command: str) -> str:
    chunks: list[str] = []
    for match in _FILENAME.finditer(command):
        name = _unquote(match.group(1))
        for candidate in (script.parent / name, root / name):
            if candidate.is_file():
                chunks.append(_read_text(candidate))
                break
    return "\n".join(chunks)


def _scan_command(
    *,
    root: Path,
    script: Path,
    line_no: int,
    command: str,
    bound: set[str],
) -> list[dict[str, object]]:
    if re.search(r"(?<![\w./-])snowsql(?![\w-])", command) is None:
        return []
    relative = _rel(root, script)
    evidence = command.strip()
    children: list[dict[str, object]] = []
    options = _parse_options(command)
    query = ""
    query_match = _QUERY.search(command)
    if query_match:
        query = _unquote(query_match.group(1))
    referenced = _referenced_sql(root, script, command)
    large = _is_large(
        " ".join(value for _key, value in options),
        query,
        referenced,
        command,
    )
    for key, value in options:
        disposition, reason, recommendation = _classify_option(key, value, large)
        children.append(
            _finding(
                path=relative,
                line=line_no,
                kind="option",
                name=key,
                disposition=disposition,
                reason=reason,
                recommendation=recommendation,
                evidence=evidence,
            )
        )
        if key in {"output_format", "output_file"}:
            children.append(
                _finding(
                    path=relative,
                    line=line_no,
                    kind="output_contract",
                    name=key,
                    disposition=disposition,
                    reason=reason,
                    recommendation=recommendation,
                    evidence=evidence,
                )
            )
    if large:
        children.append(
            _finding(
                path=relative,
                line=line_no,
                kind="export",
                name="large-result",
                disposition="blocked",
                reason=LARGE_RECOMMENDATION,
                recommendation=LARGE_RECOMMENDATION,
                evidence=evidence,
            )
        )
    for match in _LONG_FLAG.finditer(command):
        flag = match.group(1).lower()
        if flag in {"option"}:
            continue
        if flag == "warehousename":
            children.append(
                _finding(
                    path=relative,
                    line=line_no,
                    kind="flag",
                    name=flag,
                    disposition="rewrite required",
                    reason="Use --warehouse. Snowflake CLI does not accept --warehousename.",
                    evidence=evidence,
                )
            )
        elif flag == "config":
            children.append(
                _finding(
                    path=relative,
                    line=line_no,
                    kind="flag",
                    name=flag,
                    disposition="manual review",
                    reason=(
                        "The Snowflake CLI flag is --config-file. A SnowSQL --config file "
                        "may also hold [variables], which are not imported."
                    ),
                    evidence=evidence,
                )
            )
        elif flag == "enhanced-exit-codes":
            children.append(
                _finding(
                    path=relative,
                    line=line_no,
                    kind="flag",
                    name=flag,
                    disposition="manual review",
                    reason=CONTINUE_REASON,
                    evidence=evidence,
                )
            )
        elif flag in {"password", "passphrase", "token", "secret"}:
            children.append(
                _finding(
                    path=relative,
                    line=line_no,
                    kind="flag",
                    name=flag,
                    disposition="manual review",
                    reason="Connection secret redacted. Do not print the value.",
                    evidence=evidence,
                )
            )
        elif flag in COMPATIBLE_LONG or flag in {"query", "filename", "connection", "variable"}:
            children.append(
                _finding(
                    path=relative,
                    line=line_no,
                    kind="flag",
                    name=flag,
                    disposition="compatible",
                    reason="Documented snow sql flag.",
                    evidence=evidence,
                )
            )
        else:
            children.append(
                _finding(
                    path=relative,
                    line=line_no,
                    kind="flag",
                    name=flag,
                    disposition="manual review",
                    reason=f"No documented snow sql equivalent for --{flag}.",
                    evidence=evidence,
                )
            )
    for match in _SHORT_WITH_VALUE.finditer(command):
        flag = match.group(1)
        name = {"q": "query", "f": "filename", "c": "connection", "D": "variable"}[flag]
        children.append(
            _finding(
                path=relative,
                line=line_no,
                kind="flag",
                name=name,
                disposition="compatible",
                reason="Documented snow sql flag.",
                evidence=evidence,
            )
        )
        if flag == "f":
            children.append(
                _finding(
                    path=relative,
                    line=line_no,
                    kind="include",
                    name=_unquote(match.group(2)),
                    disposition="compatible",
                    reason="snow sql -f is repeatable and runs the file.",
                    evidence=evidence,
                )
            )
    for match in _FILENAME.finditer(command):
        if not match.group(0).lstrip().lower().startswith("--filename"):
            continue
        children.append(
            _finding(
                path=relative,
                line=line_no,
                kind="include",
                name=_unquote(match.group(1)),
                disposition="compatible",
                reason="snow sql --filename is repeatable and runs the file.",
                evidence=evidence,
            )
        )
    if re.search(r"\|\s*snowsql\b", command) and "--stdin" not in command.lower():
        children.append(
            _finding(
                path=relative,
                line=line_no,
                kind="flag",
                name="stdin",
                disposition="rewrite required",
                reason=(
                    "cat file | snowsql does not run the file. "
                    "Use snow sql --stdin. Without --stdin the SQL is discarded."
                ),
                evidence=evidence,
            )
        )
    if query:
        children.extend(
            _variable_findings(
                path=relative,
                line=line_no,
                text=query,
                bound=bound,
                evidence=evidence,
            )
        )
    for name in sorted(set(_ENV_NAME.findall(command))):
        disposition, suggestion = ENV_MAP.get(
            name, ("manual review", "No documented replacement.")
        )
        children.append(
            _finding(
                path=relative,
                line=line_no,
                kind="env_var",
                name=name,
                disposition=disposition,
                reason=f"{ENV_RUNTIME_REASON} Suggested name: {suggestion}.",
                evidence=name,
            )
        )
    invocation = _finding(
        path=relative,
        line=line_no,
        kind="invocation",
        name="snowsql",
        disposition=_worst(children),
        reason="Snowflake CLI command is snow sql. Review each flag before reusing the script.",
        evidence=evidence,
    )
    return [invocation, *children]


def _scan_directives(
    *,
    path: str,
    text: str,
    bound: set[str],
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        match = _DIRECTIVE.match(line)
        if match is None:
            findings.extend(
                _variable_findings(
                    path=path,
                    line=line_no,
                    text=line,
                    bound=bound,
                    evidence=line,
                )
            )
            continue
        name = match.group(1).lower()
        argument = match.group(2).strip()
        if name == "!set":
            findings.append(
                _finding(
                    path=path,
                    line=line_no,
                    kind="directive",
                    name=name,
                    disposition="blocked",
                    reason=SET_REASON,
                    evidence=line,
                )
            )
        elif name in {"!source", "!load"}:
            target = argument.split()[0] if argument else ""
            if target.lower().startswith("http://"):
                disposition = "blocked"
                reason = "Plaintext http:// sources are not allowed."
            elif target.lower().startswith("https://"):
                disposition = "manual review"
                reason = (
                    "https:// !source is fetched unless --local-only, "
                    "SNOWFLAKE_CLI_SQL_LOCAL_ONLY, or cli.sql_local_only is set."
                )
            else:
                disposition = "compatible"
                reason = "Local !source and !load are supported."
            findings.append(
                _finding(
                    path=path,
                    line=line_no,
                    kind="include",
                    name=target or name,
                    disposition=disposition,
                    reason=reason,
                    evidence=line,
                )
            )
        elif name == "!define":
            findings.append(
                _finding(
                    path=path,
                    line=line_no,
                    kind="directive",
                    name=name,
                    disposition="rewrite required",
                    reason="Pass the variable with snow sql -D. Do not print secret values.",
                    evidence=redact(line),
                )
            )
        elif name in {"!exit", "!quit", "!queries", "!result", "!abort"}:
            findings.append(
                _finding(
                    path=path,
                    line=line_no,
                    kind="directive",
                    name=name,
                    disposition="compatible",
                    reason="Supported in the REPL and in noninteractive snow sql input.",
                    evidence=line,
                )
            )
        elif name == "!edit":
            findings.append(
                _finding(
                    path=path,
                    line=line_no,
                    kind="directive",
                    name=name,
                    disposition="blocked",
                    reason="!edit fails outside the REPL.",
                    evidence=line,
                )
            )
        else:
            findings.append(
                _finding(
                    path=path,
                    line=line_no,
                    kind="directive",
                    name=name,
                    disposition="manual review",
                    reason="No documented snow sql equivalent for this client directive.",
                    evidence=line,
                )
            )
    return findings


def _scan_config(path: str, text: str) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    section: str | None = None
    for line_no, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        if section is None or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip().lower()
        if not key:
            continue
        evidence = f"{key}=<redacted>"
        if section == "variables":
            disposition = "manual review"
            reason = "[variables] is not imported. Use snow sql -D or a snowflake.yml env section."
        elif section == "connection_options":
            disposition = "blocked"
            reason = "[connection_options] is not imported."
        elif section == "options" and key in OPTION_KEYS_COPIED:
            disposition = "compatible"
            reason = (
                "Copied from [options] only when a connection omits this key. "
                "A later blank does not keep the value."
            )
        elif section == "options":
            disposition = "blocked"
            reason = "This [options] setting is not copied by the importer."
        elif key in ALIAS_KEYS:
            disposition = "rewrite required"
            reason = (
                f"Rename {key} to {ALIAS_KEYS[key]} after the raw merge. "
                "A blank value is skipped so the next alias is used."
            )
        elif key in SECRET_CONFIG_KEYS:
            disposition = "manual review"
            reason = "Secret value redacted. Passwords stay strings."
        elif section == "connections" or section.startswith("connections."):
            disposition = "manual review"
            reason = (
                "Named connections do not receive keys from the unnamed [connections] section. "
                "Confirm this key on the connection that should own it."
            )
        else:
            disposition = "manual review"
            reason = "Confirm whether this SnowSQL setting has a Snowflake CLI equivalent."
        findings.append(
            _finding(
                path=path,
                line=line_no,
                kind="config_key",
                name=f"{section}.{key}",
                disposition=disposition,
                reason=reason,
                evidence=evidence,
            )
        )
    return findings


def _looks_like_config(path: Path, text: str) -> bool:
    if path.suffix.lower() in {".cnf", ".ini"} or path.name == "config":
        return "[" in text
    return "[connections]" in text or "[variables]" in text or "[options]" in text


def scan(root: Path) -> dict[str, object]:
    root = root.resolve()
    files = _iter_files(root)
    loaded = [( _rel(root, path), _read_text(path)) for path in files]
    bound = _bound_names(loaded)
    secrets: set[str] = set()
    findings: list[dict[str, object]] = []
    scanned: list[str] = []
    for path, (relative, text) in zip(files, loaded, strict=True):
        scanned.append(relative)
        secrets.update(collect_secret_values(text))
        if path.suffix.lower() == ".sql" or "!source" in text.lower() or "!set" in text.lower():
            findings.extend(_scan_directives(path=relative, text=text, bound=bound))
        for line_no, logical in logical_lines(text):
            for command in split_shell(logical):
                findings.extend(
                    _scan_command(
                        root=root,
                        script=path,
                        line_no=line_no,
                        command=command,
                        bound=bound,
                    )
                )
        if _looks_like_config(path, text):
            findings.extend(_scan_config(relative, text))
    findings.sort(
        key=lambda item: (
            str(item["path"]),
            int(item["line"]),
            str(item["kind"]),
            str(item["name"]),
            str(item["disposition"]),
        )
    )
    summary = {name: 0 for name in DISPOSITIONS}
    for item in findings:
        summary[str(item["disposition"])] += 1
    payload: dict[str, object] = {
        "scanner": SCANNER,
        "schema_version": SCHEMA_VERSION,
        "read_only": True,
        "certifies_untested_scripts": False,
        "public_importer_release": None,
        "public_release_without_corrected_importer": "3.29.0",
        "files_scanned": scanned,
        "findings": findings,
        "summary": summary,
    }
    encoded = json.dumps(payload, indent=2, sort_keys=True)
    for secret in sorted(secrets, key=len, reverse=True):
        encoded = encoded.replace(secret, "<redacted>")
    return json.loads(encoded)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only SnowSQL migration inventory.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument(
        "--check-importer-help",
        action="store_true",
        help="Read snow helpers import-snowsql-connections --help on stdin.",
    )
    parser.add_argument(
        "--check-cli-version",
        action="store_true",
        help="Read snow --version text on stdin.",
    )
    args = parser.parse_args(argv)
    if args.check_importer_help and args.check_cli_version:
        print("Pass only one check flag.", file=sys.stderr)
        return 2
    if args.check_importer_help:
        corrected = importer_help_is_corrected(sys.stdin.read())
        print("corrected" if corrected else "rejected")
        return 0 if corrected else 2
    if args.check_cli_version:
        newer = cli_version_is_newer_than_public(sys.stdin.read())
        print("newer-than-3.29.0" if newer else "not-newer-than-3.29.0")
        return 0 if newer else 2
    root = Path(args.root)
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2
    payload = scan(root)
    sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
