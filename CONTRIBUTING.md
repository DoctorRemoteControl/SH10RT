# Public code, private installation data

This repository contains reusable SH10RT command-line software, general documentation and synthetic tests. Device integrations or general household-monitoring platforms outside that scope belong in separate projects. It must not contain installation-specific reports, even when names or addresses have been anonymized.

## Keep private

Store real configurations, credentials, device identities, network inventories, screenshots, consumption databases, telemetry captures, commissioning notes and repair histories under `private/` or outside this checkout. `private/`, local configuration suffixes, runtime databases and their SQLite sidecar files are ignored by Git.

The public `evidence/` path is also ignored to prevent installation captures from being reintroduced. Put genuinely synthetic protocol fixtures in `tests/`, with comments explaining what they exercise. Keep hardware repair accounts in private service records.

## Share general improvements

Use illustrative addresses such as `192.168.1.100` and explicit placeholders such as `YOUR_SERIAL`. Explain behavior, prerequisites, limitations and source documents without describing a particular owner's system. Keep all public documentation and terminal output in English.

Before a commit, inspect both tracked changes and untracked files:

```sh
git status --short
git diff
git diff --cached
```

Ignored paths are not a substitute for reviewing the content of public files. Do not force-add private data. Never include credentials in examples or tests.

## Existing history

Removing a file from the working tree or adding an ignore rule does not remove copies already committed or published. Historical removal is a separate repository-maintenance operation; do not rewrite or force-push shared history as part of ordinary documentation cleanup.

## Project structure

| Path | Responsibility |
| --- | --- |
| `scripts/sh10rt_lan.py` | CLI, device identity checks, native Modbus, authenticated WiNet and the guarded Start path |
| `scripts/launch_sh10rt.py` | CLI launcher menu and optional dependency setup |
| `reference/` | General Modbus register/flag JSON and CSVs, with reviewed source metadata |
| `tests/` | Offline unit tests and local protocol simulators |

## Development checks

```sh
python3 -m unittest discover -s tests -v
python3 scripts/sh10rt_lan.py --help
git diff --check
```

The optional WiNet simulator test requires `websocket-client` from `scripts/requirements.txt`; otherwise it is skipped. Use an isolated virtual environment to install it, as described in the [CLI requirements](NETWORK-SCRIPTS.md#requirements). Native Modbus needs no third-party Python packages.

Changes to device control need simulator coverage of identity mismatch, alarms, preview behavior and uncertain acknowledgments. Preserve the single-write rule and the input-only boundary of `values`. Live writes are not required to run this test suite.

When changing configuration, CLI options or response fields, update the matching guide and examples. Use synthetic identities and measurements in tests; never substitute actual installation data into a public fixture.

Keep the register guide and CSV exports in agreement with the decoder. Include both register space and address, preserve model/firmware qualifications and update source metadata when reviewing another document version. Source PDFs and actual device captures stay outside Git.

The reference CSVs are canonical. Run `python3 scripts/export_modbus_json.py` after editing them and `python3 scripts/export_modbus_json.py --check` before committing; the generated JSON must stay in sync.
