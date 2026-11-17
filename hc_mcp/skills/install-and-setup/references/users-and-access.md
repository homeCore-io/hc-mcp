# People, roles and API keys

Everyone signs in with a username and password. What they can do comes from their role. Scripts and services use API keys. Wall tablets use display keys.

Public docs: https://homecore.io/docs/administration/users-auth

If you are the in-app Assistant: adding people, changing roles, resetting passwords and making keys for someone else are admin tasks. Explain the screen below and say an admin needs to do it. Never ask for or repeat a password or key in the chat.

## Roles

Roles are fixed; you cannot define new ones. The app shows them by these names (the API uses the snake_case id). **Settings › People & access** has a "What each role allows" table read from the running server.

| In the app | API id | For |
|---|---|---|
| Admin | `admin` | Everything, including plugins, people and keys. Keep this to one or two people. |
| User | `user` | Trusted to change how the house works: rules, scenes, rooms, shared pages. No plugins or people. |
| Household member | `household_member` | Family. Uses every device and scene, sees alerts, sets up their own Home. Changes nothing shared. |
| Read only | `read_only` | Sees the house, presses nothing. A guest screen. |
| Device operator | `device_operator` | Uses, renames and moves devices; sees plugins and the audit. Writes no rules. |
| Rule editor | `rule_editor` | Writes rules, scenes and rooms; sees plugins and the audit. Cannot command devices. |
| Service operator | `service_operator` | For a program: what a User can do, plus reading the audit. |
| Observer | `observer` | Watches: sees the house, its plugins and the audit; changes nothing. |

A `403 Forbidden` from the API, or a section missing from Settings, means the role lacks the permission. The app hides what the API would refuse.

## The first admin

The first start creates `admin` with a random password in `INITIAL_ADMIN_PASSWORD` (and the log). Sign in, change it on **Me › Password**, and delete the file. homeCore always keeps at least one admin: the only admin cannot be demoted or deleted. Make a second admin account for a trusted person so a forgotten password is never a lockout.

## Add a person

Admin only.

1. **Settings › People & access › + Add a person**.
2. **What should they be able to do?** Pick a role. Household member is marked "suggested for family". **More roles** shows the rest.
3. **Name they sign in with** and **First password** (at least 8 characters).
4. Optionally a **PIN for displays**; people can set their own on **Me**.
5. Press **Add as <role>**.

**Check it works:** they appear in the list with that role and can sign in at `http://<homecore-host>:3001`.

## Change someone's role or password

Open the person from **Settings › People & access**.

- **Role**: choose and **Save**. Their sessions end and they sign in again with the new role. Their API keys are narrowed to what the new role allows.
- **Password**: **Set a new password…**, then **Set**. There is no email reset; an admin resetting it is the way back in.
- **PIN for displays**: **Remove PIN**.
- **Delete…**: removes the account and revokes their API keys. You cannot delete yourself or the only admin.

People change their own password on **Me › Password**. A password change signs that person out everywhere else.

## Sessions

**Me › Signed in** lists where you are signed in and can end any of those sessions. Sign-in is rate-limited: five tries a minute per address, then a short wait.

## API keys

For scripts, dashboards, hc-mcp and other programs. A key carries a subset of its owner's permissions, can expire, can be limited to source addresses, and can be revoked alone. Prefer one over storing a password in a script.

1. **Settings › People & access › API keys**, or **Me › API keys** for your own.
2. **What it's for**: a label.
3. **Whose key** (admins only): yours or someone else's.
4. **What it may do**: **See the house** (reading only), **Use the house** (also commands devices and runs scenes), **Everything you can do**, or **Choose exactly…** to tick individual permissions.
5. **Stops working**: an expiry. **Only from (optional)**: limit to addresses.
6. Press **Make the key**. It is shown only once; **Copy** it into the program, then **Done**.

Manage keys in the **In use** list: **Change**, **New secret** (rotates the secret, keeps the settings) and **Revoke**.

Use a key exactly like a sign-in token:

```sh
curl -s http://<homecore-host>:8080/api/v1/devices -H "Authorization: Bearer hc_sk_<key>"
```

Backups over the API need an admin's key. hc-mcp's `setup` command can make its own key; see https://homecore.io/docs/tools/hc-mcp.

## Wall tablets (displays)

A display is a screen that belongs to the house, with no person signed in.

1. **Settings › Displays**, enter a name, **Make a display**.
2. **Copy the key** (shown only now).
3. On the tablet, open `http://<homecore-host>:3001/display` and enter the key.
4. Back in **Settings › Displays**, choose its pages and kiosk options (**Keep the screen on**, **Dark while Night Mode is on**, **Reload every day at**).

A person can unlock the full app on a display for five minutes with their PIN. Display keys are not touched when people change or leave.

## Things to avoid

- `[auth].whitelist` in `homecore.toml` grants admin with no sign-in to listed addresses. It is deprecated. Use an API key.
- Sharing the admin account. Give each person their own account and role.
- Exposing port 8080 or 3001 to the internet without a reverse proxy and TLS in front.

## Audit

**Settings › Audit** shows who changed what and when: sign-ins, failed sign-ins, account and key changes, settings, rules, devices and plugins. Docs: https://homecore.io/docs/administration/audit-log
