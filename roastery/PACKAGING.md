# Gateway packaging for the Roastery

The Roastery app in `project/` is only half the system: it also
needs a gateway configured to serve it. This folder carries that
gateway setup with it, structured after etknorr/project-template.
Until 2026-11-14 the same material lived in a `gateway/` folder
at the root of this repository; it moved inside `roastery/` so
the app and its gateway setup travel together, in the template's
shape.

Two deployment modes:

- **Local**: Docker Compose, for spinning the whole thing up on
  a workstation (`docker-compose.yml` here).
- **Prod**: Kubernetes manifests for the k3s homelab (`prod/`),
  drafted here and destined for the homelab repo.

The gateway configuration itself lives in
`services/ignition/config/` and is shared by both modes: the
historians, the database connection, and the simulator devices,
in the on-disk resource format the template uses.
`services/ignition/config/INVENTORY.md` lists every gateway
scoped item the app needs and where it is defined.

## Layout

```text
roastery/
  docker-compose.yml   local stack: gateway + Postgres + MQTT
  .env.example         every secret is a placeholder here
  scripts/
    docker-bootstrap.sh  volume bootstrap (project-template pattern)
  services/
    ignition/
      config/
        INVENTORY.md   every gateway scoped item, and where it lives
        exports/       the same config as gateway API responses
        resources/     gateway config resources, on-disk format
          core/        shared by all modes
          local/       local mode overrides (inherits core)
          prod/        prod mode overrides (inherits core)
    db/
      init/            Postgres first start SQL (database, then
                       the batches, batch_series and batch_events
                       tables, mirroring scripts/setup_roastery_db.py)
    mqtt/              Mosquitto broker for the MQTT source slot
  prod/
    README.md          how this maps into the homelab repo
    *.yaml             Kustomize set modeled on homelab k8s/ignition
    argocd-application.yaml  stub for the move into homelab k8s/apps
  project/             the Perspective project (mounted by compose)
```

One deviation from the template, flagged deliberately: the
template mounts `./services/ignition/projects` as the gateway's
projects directory; here compose mounts `./project` instead,
because `project/` is the single authored source of the project
(the lab builders and validators work against it in place) and a
second copy under `services/` would fork it. The config
resources do live under `services/ignition/config/`, as in the
template.

## How config flows, per mode

**Local (Docker).** Compose bind mounts this folder into the
gateway: `project/` becomes the gateway's projects directory,
and `services/ignition/config/resources/core` plus
`.../local` become its config resource collections, with the
gateway started in config mode `local` (which inherits `core`).
The historians, the database connection, and the simulator
devices therefore exist at first boot as files, no API calls
needed. Tags and the `RoastBatch` UDT are the exception: run the
app setup scripts against the gateway API once it is up
(`scripts/setup_roastery_v4_tags.py`), the same scripts the lab
used. Postgres runs beside the gateway as the `db` service and
creates the application tables from `services/db/init/` on
first start. The `mqtt` service is the broker for the app's
MQTT source slot (see `services/mqtt/README.md`).

**Prod (Kubernetes).** Nothing is bind mounted. The gateway
keeps its state on a Longhorn PVC, is commissioned from
environment and OpenBao backed Secrets on first boot, and
receives its project and gateway configuration from git through
stoker-operator, the homelab pattern, with the setup scripts as
the by hand fallback. Postgres runs in the namespace as a
StatefulSet, also named `db`, so the one database connection
definition in `services/ignition/config/` resolves identically
in both modes. Details and the deliberate differences from the
homelab platform gateway are in `prod/README.md`.

## The historian decision, stated plainly

The app today records history to the **SQL historian** on the
Postgres `db` connection (the v3 pass repointed the probe tags
to it). Both providers are declared in
`services/ignition/config/resources/core/`: CoreHistorian stays
defined but unused, and `db` records. Which one records is a tag
setting (`historyProvider` in the setup scripts), not a gateway
rebuild.

## What a human still has to do

No file in this folder can do these, by design or by platform:

1. **Create the API key** through the gateway web page
   (Platform, Security, API Keys) before running the setup
   scripts. Hand built token files do not authenticate on these
   gateways.
2. **Apply the Maker license key** (free, from an Inductive
   Automation account) in the gateway web UI. Until then the
   gateway runs in trial mode with periodic resets; activation
   state lives on the data volume, not in git.
3. **Set real secrets where the placeholders are**: `.env` from
   `.env.example` locally; OpenBao entries
   `secret/homelab/roastery-admin` and
   `secret/homelab/roastery-db` in prod; and the gateway secret
   `roastery-db-password` inside the gateway's secret provider,
   which the `db` connection references.
4. **Local only**: have Traefik and its external `proxy`
   network running first (the ignition-guides setup the
   template assumes), or uncomment the direct port in the
   compose file.
5. **First roast data**: in production the SR800 feed comes from
   the Pico W monitor over WebSocket. The simulator devices in
   `services/ignition/config/` are lab stand-ins and should not
   be deployed to prod; nothing in the gateway config dials the
   real roaster yet, because that connection lives on the Pico
   and app side.

## Security posture

This folder contains no secrets: passwords and tokens appear
only as environment variable references, Kubernetes Secret
references, and placeholders. The local mode follows the
template's local development convenience posture once
commissioned (an admin set by `.env`); lock the gateway down
before exposing either mode beyond a trusted network, the same
warning project-template carries about its own defaults.
