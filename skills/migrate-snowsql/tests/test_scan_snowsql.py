import json
import subprocess
import sys
from pathlib import Path

import scan_snowsql

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SCRIPT = Path(scan_snowsql.__file__)
DISPOSITIONS = (
    "compatible",
    "rewrite required",
    "manual review",
    "blocked",
)
PLANTED = (
    "SuperSecretPlantedValue123",
    "AnotherPlantedTokenValue456",
)


def _scan(name: str) -> dict:
    return scan_snowsql.scan(FIXTURES / name)


def _matching(payload: dict, **filters: str) -> list[dict]:
    return [
        finding
        for finding in payload["findings"]
        if all(finding[key] == value for key, value in filters.items())
    ]


def test_safe_mappings_stay_compatible():
    payload = _scan("safe_mappings")
    assert payload["summary"]["blocked"] == 0
    assert payload["summary"]["manual review"] == 0
    assert _matching(payload, kind="flag", name="query", disposition="compatible")
    assert _matching(payload, kind="flag", name="connection", disposition="compatible")
    assert _matching(payload, kind="flag", name="filename", disposition="compatible")
    assert _matching(payload, kind="flag", name="variable", disposition="compatible")
    assert _matching(payload, kind="flag", name="username", disposition="compatible")
    assert _matching(payload, kind="flag", name="accountname", disposition="compatible")
    assert _matching(payload, kind="flag", name="warehouse", disposition="compatible")
    assert set(payload["summary"]) == set(DISPOSITIONS)


def test_unsupported_o_options_are_blocked():
    payload = _scan("unsupported_options")
    for name in ("timing", "friendly"):
        findings = _matching(payload, kind="option", name=name)
        assert findings
        assert findings[0]["disposition"] == "blocked"
        assert "Unsupported -o setting" in findings[0]["reason"]


def test_continue_on_error_and_mid_script_set_are_blocked():
    payload = _scan("continue_on_error")
    exit_on_error = _matching(payload, kind="option", name="exit_on_error")
    assert exit_on_error
    assert exit_on_error[0]["disposition"] == "blocked"
    reason = exit_on_error[0]["reason"]
    assert "exit 1" in reason
    assert "exit 5" in reason
    assert "does not continue" in reason
    directive = _matching(payload, kind="directive", name="!set")
    assert directive
    assert directive[0]["disposition"] == "blocked"
    assert "Mid-script !set" in directive[0]["reason"]


def test_output_contracts_block_csv_and_rewrite_json():
    payload = _scan("output_contracts")
    csv_findings = _matching(payload, kind="option", name="output_format", path="run.sh")
    csv = next(item for item in csv_findings if item["line"] == 1)
    json_finding = next(item for item in csv_findings if item["line"] == 2)
    assert csv["disposition"] == "blocked"
    for word in ("newline", "backslash", "tab", "CRLF", "delimiter", "quoting", "UTF-8"):
        assert word in csv["reason"]
    assert json_finding["disposition"] == "rewrite required"
    assert "--format JSON" in json_finding["reason"]
    assert _matching(payload, kind="output_contract", name="output_file")


def test_large_export_stays_copy_into_and_stage_copy():
    payload = _scan("large_exports")
    exports = _matching(payload, kind="export", name="large-result")
    assert exports
    assert exports[0]["disposition"] == "blocked"
    text = exports[0]["recommendation"]
    assert "COPY INTO @stage" in text
    assert "snow stage copy" in text
    assert "table-streaming" in text
    assert "retry result chunks" in text
    assert "silent CSV truncation" in text
    csv = _matching(payload, kind="option", name="output_format")
    assert csv[0]["disposition"] == "blocked"


def test_undefined_variable_exit_code_is_blocked_when_unbound():
    payload = _scan("undefined_variable")
    missing = _matching(payload, kind="variable", name="missing_name")
    bound = _matching(payload, kind="variable", name="day")
    assert missing and missing[0]["disposition"] == "blocked"
    assert "undefined-variable" in missing[0]["reason"]
    assert bound and bound[0]["disposition"] == "rewrite required"


def test_stdin_pipe_is_rewrite_required():
    payload = _scan("stdin_pipe")
    stdin = _matching(payload, kind="flag", name="stdin")
    assert stdin and stdin[0]["disposition"] == "rewrite required"
    assert "--stdin" in stdin[0]["reason"]


def test_planted_credential_is_absent_from_scanner_output():
    payload = _scan("planted_credential")
    encoded = json.dumps(payload)
    for secret in PLANTED:
        assert secret not in encoded
    assert "<redacted>" in encoded
    assert _matching(payload, kind="env_var", name="SNOWSQL_PWD")
    password = _matching(payload, kind="config_key", name="connections.password")
    assert password
    assert password[0]["evidence"] == "password=<redacted>"
    assert "example-account" not in encoded


def test_scanner_does_not_certify_untested_scripts():
    payload = _scan("safe_mappings")
    assert payload["certifies_untested_scripts"] is False
    assert payload["read_only"] is True
    assert payload["public_importer_release"] is None
    assert payload["public_release_without_corrected_importer"] == "3.29.0"
    assert payload["scanner"] == "migrate-snowsql"


def test_scan_is_deterministic_and_read_only(tmp_path: Path):
    source = FIXTURES / "planted_credential"
    target = tmp_path / "project"
    target.mkdir()
    for path in source.iterdir():
        (target / path.name).write_bytes(path.read_bytes())
    before = {path.name: path.read_bytes() for path in target.iterdir()}
    first = subprocess.run(
        [sys.executable, str(SCRIPT), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    second = subprocess.run(
        [sys.executable, str(SCRIPT), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout == second.stdout
    assert first.stderr == ""
    after = {path.name: path.read_bytes() for path in target.iterdir()}
    assert after == before
    for secret in PLANTED:
        assert secret not in first.stdout


def test_importer_help_gate_rejects_v3_29_and_accepts_corrected_wording():
    corrected = (FIXTURES / "importer_help" / "corrected.txt").read_text()
    old = (FIXTURES / "importer_help" / "v3.29.0.txt").read_text()
    assert scan_snowsql.importer_help_is_corrected(corrected)
    assert not scan_snowsql.importer_help_is_corrected(old)


def test_cli_version_gate_requires_newer_than_public_v3_29():
    assert not scan_snowsql.cli_version_is_newer_than_public("Snowflake CLI version: 3.29.0")
    assert not scan_snowsql.cli_version_is_newer_than_public("3.29.0.dev0")
    assert scan_snowsql.cli_version_is_newer_than_public("Snowflake CLI version: 3.30.0.dev0")
    assert scan_snowsql.cli_version_is_newer_than_public("3.30.0")
    assert not scan_snowsql.cli_version_is_newer_than_public("snowsql version 1.5.2")


def test_check_flags_use_exit_codes():
    corrected = (FIXTURES / "importer_help" / "corrected.txt").read_text()
    old = (FIXTURES / "importer_help" / "v3.29.0.txt").read_text()
    accepted = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-importer-help"],
        check=False,
        capture_output=True,
        text=True,
        input=corrected,
    )
    rejected = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-importer-help"],
        check=False,
        capture_output=True,
        text=True,
        input=old,
    )
    newer = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-cli-version"],
        check=False,
        capture_output=True,
        text=True,
        input="Snowflake CLI version: 3.30.0.dev0\n",
    )
    older = subprocess.run(
        [sys.executable, str(SCRIPT), "--check-cli-version"],
        check=False,
        capture_output=True,
        text=True,
        input="Snowflake CLI version: 3.29.0\n",
    )
    assert accepted.returncode == 0 and accepted.stdout.strip() == "corrected"
    assert rejected.returncode == 2 and rejected.stdout.strip() == "rejected"
    assert newer.returncode == 0 and newer.stdout.strip() == "newer-than-3.29.0"
    assert older.returncode == 2 and older.stdout.strip() == "not-newer-than-3.29.0"
