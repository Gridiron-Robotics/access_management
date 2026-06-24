# Cerbos Hub — the web UI for managing the rules

You picked **Cerbos Hub** as the place admins author and manage the *rules*
(what each role can do). This is the optional control-plane on top of the
policies in this repo. Assignments (who has which role) still come from the HRMS
page — see [`integration/README.md`](README.md). Two things, two homes.

## What Hub gives you

- A **web console + playground** to write, edit, and test policies, with instant
  feedback — no YAML-by-hand required for whoever manages the rules.
- **CI/CD for policies**: on every change Hub compiles + runs the tests, builds a
  signed **bundle**, and distributes it to your self-hosted PDP fleet.
- **Decision logs** and audit of who changed which rule.

## The model (important): the repo stays the source of truth

```
   policies/ in THIS repo  ──watched by──►  Cerbos Hub  ──builds & tests──►  bundle
                                               │  (web UI / playground)         │
   you (PR) ──────────────────────────────────┘                                ▼
                                                        self-hosted Cerbos PDP pulls it
```

Hub **connects to this Git repository** as its policy source. So you keep
git-ops and the `harden/` gate *and* get the GUI — they're not a trade-off. The
only deploy change is: the PDP fetches a bundle from Hub instead of reading
baked-in disk files.

## Disk mode vs Hub mode — pick deliberately

| | Disk mode (default, `conf.yaml`) | Hub mode (`conf.hub.yaml`) |
|---|---|---|
| Policies reach PDP via | baked into the image | pulled bundle from Hub |
| Rule-authoring UI | none (edit YAML + PR) | **Hub web console + playground** |
| Runtime dependency | none (fully self-contained) | Hub SaaS (PDP caches; survives brief outages) |
| Best when | air-gapped / max self-containment | you want a GUI + central distribution |

You can **start on disk and switch to Hub later** with zero policy changes.

## Enable Hub mode (one-time)

1. Create a free account at <https://hub.cerbos.cloud> and a **workspace**.
2. **Connect this repo** (`Gridiron-Robotics/access_management`) as the policy
   source; set the policy directory to `policies/`. Hub now builds a bundle on
   every push; the `latest` label tracks your default branch.
3. In Hub, create **PDP / client credentials**. You'll get:
   `CERBOS_HUB_CLIENT_ID`, `CERBOS_HUB_CLIENT_SECRET`, `CERBOS_HUB_WORKSPACE_SECRET`.
4. Put those values in your deploy environment (placeholders are in
   `.kamal/secrets`; never commit the real values).
5. Export the three secrets in your deploy environment (they're listed in
   `.kamal/secrets`, empty until you set them).
6. Deploy Hub mode with the ready-made destination overlay:
   `bundle exec kamal deploy -d hub` (uses `config/deploy.hub.yml`, which sets
   `CERBOS_CONFIG=/conf.hub.yaml` + the Hub secrets). Plain `kamal deploy` stays
   on disk mode. The PDP starts and pulls the bundle from Hub.

> The Dockerfile already bakes in **both** `conf.yaml` and `conf.hub.yaml`, so
> switching modes is just the `CERBOS_CONFIG` env var — no image rebuild logic.

## This doesn't replace the gate

`harden/verify.sh` (and the CI gatekeeper) still compile and test `policies/`
**before** anything merges — your first line of defense. Hub then re-tests and
builds the bundle. For production, **pin `bundleLabel`** to a named release
rather than `latest`, exactly like the pinned image tag and Kamal version.
