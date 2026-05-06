# Codex Cloud Runbook

## Repository Profile

- Language/runtime: Python 3.10 or newer. Local development currently uses Python 3.13.
- Package manager: `pip` with `requirements.txt` and editable package metadata in `pyproject.toml`.
- Primary package: `plaid-notion-connector`.
- Primary CLI: `plaid-notion-sync`, defined by `pyproject.toml`.
- Build/install command: `python -m pip install -r requirements.txt` then `python -m pip install -e .`.
- Test command: no committed test suite is present. Use `CODEX_RUN_VERIFY=1 scripts/codex-cloud-setup.sh` for `compileall`; if tests are added later, the script will run `pytest` when installed, otherwise `unittest discover`.
- Frontend: none detected. No Node/package-manager install or dev server is required.
- Backend dev server: none detected. This is a command-line sync/export tool.

## Recommended Codex Cloud Settings

- Setup script: enabled.
- Agent internet access: on for setup, because dependencies are installed from PyPI.
- Working directory: repository root.
- Python version: Python 3.10 or newer. Python 3.12 or 3.13 is a good default.
- Run verification by default: optional. Leave `CODEX_RUN_VERIFY` unset for faster setup; set it to `1` when you want compile/test verification during environment setup.

## Setup Script Text

Paste this in the Codex Cloud environment setup command:

```bash
bash scripts/codex-cloud-setup.sh
```

For setup-time verification, use:

```bash
CODEX_RUN_VERIFY=1 bash scripts/codex-cloud-setup.sh
```

## Environment Variables

Use sandbox/test resources in Codex Cloud. Do not point mobile-agent sessions at production Plaid, Supabase, or Notion credentials.

Required for commands that load application settings:

```bash
PLAID_CLIENT_ID=your_sandbox_plaid_client_id
PLAID_SECRET=your_sandbox_plaid_secret
PLAID_ENV=sandbox
SUPABASE_URL=https://your-sandbox-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_sandbox_service_role_key
```

Optional:

```bash
NOTION_API_KEY=secret_for_test_or_sandbox_workspace
NOTION_DATABASE_ID=test_or_sandbox_database_id
STATE_FILE=.connector_state.json
CODEX_RUN_VERIFY=1
```

The setup script itself does not require these application credentials because it only installs dependencies and verifies the CLI help path.

## Secrets Guidance

- Store Plaid, Supabase, and Notion values as Codex Cloud secrets/environment variables, not in files committed to the repo.
- Prefer Plaid `sandbox` and a disposable Supabase project for agent work.
- Do not enter production Plaid secrets, production Supabase service role keys, or personal Notion workspace tokens unless the task explicitly requires live integration work and you are comfortable with that access.
- Keep `.env` and `.connector_state.json` local-only.

## Smoke-Test Prompt For ChatGPT Mobile

```text
In this repo, run bash scripts/codex-cloud-setup.sh, then inspect pyproject.toml and src/plaid_notion_connector/cli.py. Confirm the plaid-notion-sync CLI installs and show me the available subcommands without using any Plaid, Supabase, or Notion secrets.
```
