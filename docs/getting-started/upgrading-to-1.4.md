# Upgrading To 1.4

ScholarAIO 1.4 changes the runtime layout. Older runtime roots such as
`data/papers/`, `data/explore/`, `data/proceedings/`, `data/inbox*`, and
`workspace/<name>/papers.json` are migration inputs, not normal runtime inputs.

The migration is explicit by design. ScholarAIO does not move user data during
`git pull`, package installation, import, setup, or normal command startup.

## What Changes

Fresh-layout defaults are:

- papers: `data/libraries/papers/`
- proceedings: `data/libraries/proceedings/`
- exploration libraries: `data/libraries/explore/`
- citation styles: `data/libraries/citation_styles/`
- tool references: `data/libraries/toolref/`
- inboxes and pending queues: `data/spool/`
- rebuildable state and indexes: `data/state/`
- workspace paper refs: `workspace/<name>/refs/papers.json`
- system-owned outputs: `workspace/_system/`

The migration command moves supported old roots into these locations, records a
journal under `.scholaraio-control/migrations/`, verifies the result, and
archives old roots into the journal instead of deleting them directly.

## Recommended Path

Use this path when your existing ScholarAIO folder already contains the old
`data/`, `workspace/`, and `config*.yaml` files.

```bash
# 1. Update the code/package.
git pull
pip install -e ".[full]"

# 2. Inspect the runtime state.
scholaraio migrate status

# 3. Run the one-command offline migration.
scholaraio migrate upgrade --migration-id upgrade-1.4.0 --confirm

# 4. Verify the journal.
scholaraio migrate verify --migration-id upgrade-1.4.0

# 5. Rebuild indexes after data lands in the fresh layout.
scholaraio index --rebuild

# 6. Run the normal setup diagnostic.
scholaraio setup check
```

Use a different `--migration-id` if you prefer a timestamped or machine-specific
name, for example `upgrade-1.4.0-20260426`.

## Lowest-Risk Path

For a release upgrade, the safest operational pattern is:

1. Keep the old folder unchanged until the new folder passes verification.
2. Copy the old runtime files into an upgraded ScholarAIO checkout.
3. Run `migrate upgrade` in that upgraded checkout.

The copied runtime should include:

- `data/`
- `workspace/`
- `config.yaml`
- `config.local.yaml`, if present

After migration, confirm the fresh layout and rebuilt search index with real
commands such as:

```bash
scholaraio search "your topic" --limit 5
scholaraio show "<paper-id>" --layer 2
scholaraio ws list
scholaraio explore list
```

## What To Avoid

- Do not expect `git pull` or `pip install -U scholaraio` to migrate data.
- Do not manually move large runtime directories unless you are following a
  recovery plan.
- Do not delete old roots by hand before `migrate verify` succeeds.
- Do not treat `data/state/` indexes as durable data; rebuild them when in
  doubt.

## If Migration Is Interrupted

Normal commands are intentionally blocked while a migration lock exists. Inspect
the state first:

```bash
scholaraio migrate status
```

If the process died and you have reviewed the journal, clear the lock explicitly:

```bash
scholaraio migrate recover --clear-lock
```

Then rerun `migrate upgrade` with the same `--migration-id` or run targeted
`migrate verify` / `migrate finalize` commands as directed by the journal.
