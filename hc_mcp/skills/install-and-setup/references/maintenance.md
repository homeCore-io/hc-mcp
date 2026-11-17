# Backups, upgrades, logs and status

Public docs:
- https://homecore.io/docs/administration/backup-restore
- https://homecore.io/docs/administration/logging
- https://homecore.io/docs/administration/system-status
- https://homecore.io/docs/getting-started/migration

Backups, restores and restarts are admin tasks. If you are the in-app Assistant, point the person to the screen and say an admin does it.

## Back up

A homeCore backup is one zip file holding the house's state (`state.redb`: devices, users, keys, scenes, rooms), history (`history.db`), `homecore.toml`, modes, rules, each plugin's settings and calendars. It leaves out the audit log, the sign-in secret (`data/jwt_secret`; after a restore on a new machine everyone signs in again) and log files.

**From the app:** **Settings › Data & backups**.

- **Back up now** downloads a fresh backup.
- **save them too** saves the app's own data (pages, displays, everyone's Home, pictures). homeCore's backup does not hold it, so save both.
- The card lists the backups homeCore keeps on the house. Click one to download it.

**On a schedule:** homeCore makes one every 24 hours by default and keeps the newest 7 in `backups/` under its home. The card says so; **Change** opens the `[backup]` section of **Settings › Configuration** (`every_hours`, `keep`, `dir`; `every_hours = 0` turns it off).

These sit on the same disk as homeCore. Copy them somewhere else too. A nightly pull from another machine, with an admin's API key:

```sh
curl -s -X POST http://<homecore-host>:8080/api/v1/system/backup \
  -H "Authorization: Bearer $HC_BACKUP_KEY" \
  -o homecore-$(date +%Y%m%d).zip
```

**Docker file-level copy** (includes everything in `homecore-data/`, the audit log and `jwt_secret` too):

```sh
docker compose stop
tar -czf homecore-backup-$(date +%Y%m%d).tar.gz homecore-data
docker compose start
```

**Check it works:** **Settings › Data & backups** shows the time of the last backup, and `unzip -l <file>.zip` lists `state.redb`.

## Restore

A restore replaces devices, rules, settings and accounts with the backup's. Take a fresh backup first.

**From the app:** **Settings › Data & backups › Restore**.

1. **Choose a backup file…**, or **Put back…** next to a kept backup.
2. The page reads the backup and shows what it brings back and when it was made.
3. **Back up now first** if you have not.
4. **Put it back…**, type `restore` to confirm, and choose **Put it back and restart**.

homeCore stages the archive and applies it on the next start, before opening anything, then restarts. Under systemd this needs core v0.1.97 or later, or a manual `sudo systemctl restart homecore`.

**Check it works:** after the restart, sign in with an account from the backup and compare device and rule counts on **Settings**.

Restoring the app's own data is on the same page, from the file saved with **save them too**.

## Upgrade

Read the [release notes](https://homecore.io/docs/release-notes) first. **Settings › System** says when a newer homeCore or app is out, with a "what's new" link. The update itself is done on the machine that runs homeCore; the app cannot do it.

Back up before upgrading.

### Docker

```sh
cd homecore-docker
git pull                      # newer compose files, if any
docker compose pull
docker compose up -d
```

The `homecore-data/` folder and the `app-data` volume carry over. A Python runtime is upgraded the same way on its machine (`docker compose -f compose.runtime-python.yml pull && ... up -d`); its version follows core's, and the Catalog warns when a runtime is older than core expects.

### Binary

1. Download and verify the new `homecore-core-vX.Y.Z-linux-x86_64.tar.gz` (see [binaries-and-service.md](binaries-and-service.md#install-core)).
2. Stop core: `sudo systemctl stop homecore`.
3. Extract it in the parent folder of `homecore/`. It replaces `bin/homecore`, the profiles and templates, and leaves `config/homecore.toml`, `data/`, `rules/` and `plugins/` alone (the archive carries only `homecore.toml.example`).
4. Compare `config/homecore.toml.example` with your file for new sections.
5. Start core: `sudo systemctl start homecore`.

Update the app container separately (`docker pull ghcr.io/homecore-io/hc-web-svelte:latest` and recreate it).

### Plugins

Plugins are not touched by a core upgrade. **Settings › Plugins** shows **Update** per plugin and **Update all (n)**. A plugin version that needs a newer core says so in the Catalog.

**Check it works:** `curl http://<homecore-host>:8080/api/v1/health` reports the new version, and **Settings › System** shows the versions of homeCore and the app.

## Logs

| Where | What |
|---|---|
| **Settings › Logs** | Live log from core and every plugin, filtered by level, with **Pause** and **Resume**. Admin. |
| A plugin's **Log** tab | That plugin's lines only. |
| **Settings › System** › "How much homeCore writes to its log" | **Quiet** (warnings and errors), **Normal** (info), **Detailed** (debug), or **Custom**. **Keep it after a restart** saves it. Turn Detailed back down afterwards. |
| `docker compose logs -f homecore` | Container output (Docker). |
| `journalctl -u homecore -f` | Service output (systemd). |
| `logs/homecore.YYYY-MM-DD` | Rolling JSON log files under homeCore's home; pruned after 5 days by default. |

`RUST_LOG` set in the environment overrides the configured levels. The live log in the app reads an in-memory buffer of the last 500 lines.

## System status

**Settings › System** shows the homeCore and app versions, time zone, uptime, storage, who is connected now, device firmware updates, and **Restart homeCore…**. It links to **Events** and **Audit**.

Over the API:

```sh
curl http://<homecore-host>:8080/api/v1/health                 # no sign-in needed
curl http://<homecore-host>:8080/api/v1/system/versions        # no sign-in needed
curl -H "Authorization: Bearer $TOKEN" http://<homecore-host>:8080/api/v1/system/status
```

`system/status` returns version, uptime, rule, device and active-plugin counts, database sizes, time zone and `last_backup_at`.

## Move to a new machine

1. Back up on the old machine (app or API) and copy the file across.
2. Install homeCore on the new machine and sign in with its new first-admin password.
3. Install the same plugins from the Catalog (before or after the restore; settings come back with the restore on core v0.1.97 and later).
4. Restore the backup and restart. Sign in with the old accounts.
5. Review `homecore.toml` for addresses or paths that belonged to the old machine.
6. Restore the app's data from its own saved file.

Details: https://homecore.io/docs/getting-started/migration
