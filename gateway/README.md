# Gateway configuration for the Roastery

The Roastery app in `../roastery/` is only half the system: it also
needs a gateway configured to serve it. This folder carries that
gateway configuration as text, plus the two deployment modes Eric
asked for:

- **Local**: Docker Compose, for spinning the whole thing up on a
  workstation (`local/`).
- **Prod**: Kubernetes manifests for the k3s homelab (`prod/`),
  drafted here and destined for the homelab repo.

The configuration itself lives in `config/` and is shared by both
modes: the historian, the database connection, and the simulator
devices, in the same on-disk resource format Eric's
project-template repo uses. `config/INVENTORY.md` lists every
gateway scoped item the app needs and where it is defined.

This is not the Docker Compose file at the root of
ignition-coffee-lab: that one belongs to the Pico W roaster
platform. This folder is the Ignition side.

## Layout

```text
gateway/
  README.md            this file
  config/
    INVENTORY.md       every gateway scoped item, and where it lives
    exports/           the same config as gateway API responses
    resources/         gateway config resources, on-disk format
      core/            shared by all modes
      local/           local mode overrides (inherits core)
      prod/            prod mode overrides (inherits core)
  local/
    docker-compose.yml Ignition 2027 Maker + Postgres, Traefik front
    .env.example       every secret is a placeholder here
    scripts/           volume bootstrap (project-template pattern)
    services/db/init/  Postgres first start SQL
  prod/
    README.md          how this maps into the homelab repo
    *.yaml             Kustomize set modeled on homelab k8s/ignition
    argocd-application.yaml  stub for the move into homelab k8s/apps
```

## How config flows, per mode

**Local (Docker).** Compose bind mounts the repo into the gateway:
`roastery/project/` becomes the gateway's projects directory, and
`config/resources/core` plus `config/resources/local` become its
config resource collections, with the gateway started in config
mode `local` (which inherits `core`). The historian, the database
connection, and the simulator devices therefore exist at first boot
as files, no API calls needed. Tags and the `RoastBatch` UDT are
the exception: run the app setup scripts against the gateway API
once it is up (`roastery/scripts/setup_roastery_artisan_tags.py`),
the same scripts the lab used. Postgres runs beside the gateway as
the `db` service.

**Prod (Kubernetes).** Nothing is bind mounted. The gateway keeps
its state on a Longhorn PVC, is commissioned from environment and
OpenBao backed Secrets on first boot, and receives its project and
gateway configuration from git through stoker-operator, the
homelab pattern, with the setup scripts as the by hand fallback.
Postgres runs in the namespace as a StatefulSet, also named `db`,
so the one database connection definition in `config/` resolves
identically in both modes. Details and the deliberate differences
from the homelab platform gateway are in `prod/README.md`.

## The historian decision, stated plainly

The app today records history to **CoreHistorian**, the built in
historian, because that is what the lab gateway runs and what the
setup scripts configure. This folder also defines a Postgres
backed SQL historian (provider `db` on connection `db`) in the
exact shape Eric's project-template uses, ready to become the
historian: repoint `historyProvider` in the two setup scripts
from `CoreHistorian` to `db` and re-run them. Both providers are
declared in `config/resources/core/`; which one records is a tag
setting, not a gateway rebuild. The draft report flags this as an
open decision rather than silently switching the app's history.

## What a human still has to do

No file in this folder can do these, by design or by platform:

1. **Create the API key** through the gateway web page (Platform,
   Security, API Keys) before running the setup scripts. Hand
   built token files do not authenticate on these gateways.
2. **Apply the Maker license key** (free, from an Inductive
   Automation account) in the gateway web UI. Until then the
   gateway runs in trial mode with periodic resets; activation
   state lives on the data volume, not in git.
3. **Set real secrets where the placeholders are**: `.env` from
   `local/.env.example` locally; OpenBao entries
   `secret/homelab/roastery-admin` and `secret/homelab/roastery-db`
   in prod; and the gateway secret `roastery-db-password` inside
   the gateway's secret provider, which the `db` connection
   references.
4. **Local only**: have Traefik and its external `proxy` network
   running first (the ignition-guides setup Eric's template
   assumes), or uncomment the direct port in the compose file.
5. **First roast data**: in production the SR800 feed comes from
   the Pico W monitor over WebSocket. The simulator devices in
   `config/` are lab stand-ins and should not be deployed to
   prod; nothing in the gateway config dials the real roaster
   yet, because that connection lives on the Pico and app side.

## Security posture

This folder contains no secrets: passwords and tokens appear only
as environment variable references, Kubernetes Secret references,
and placeholders. The local mode follows the template's
local development convenience posture once commissioned (an admin
set by `.env`); lock the gateway down before exposing either mode
beyond a trusted network, the same warning project-template
carries about its own defaults.
