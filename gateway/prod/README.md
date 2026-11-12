# Roastery in Kubernetes (prod mode, draft)

Best effort manifests for running the Roastery gateway in the k3s
homelab. These files were drafted in the ignition-coffee-lab repo so
the app carries its deployment story with it, but prod is ultimately
hosted from the homelab repo: when Eric is ready, this folder moves
to `k8s/roastery/` in etknorr/homelab and `argocd-application.yaml`
goes to `k8s/apps/` there. Until then, nothing here is live.

## How it maps to the homelab platform gateway

Modeled file for file on `k8s/ignition/` in the homelab repo, which
deploys the platform gateway by ArgoCD. Same shape: one Deployment
(Recreate strategy) on a Longhorn PVC, ClusterIP Service, HTTPRoute
on the shared `homelab` Gateway, admin credentials from OpenBao
through External Secrets, and a Kustomization tying it together.
Deliberate differences, each also commented in the manifests:

| Difference | Why |
| --- | --- |
| Image pinned to `inductiveautomation/ignition:2027.2.0-beta1` instead of `latest` | The homelab README itself says to pin to a licensed version; the Roastery targets the 2027 early access build, which is a real Docker Hub tag. |
| `IGNITION_EDITION=maker` | The Roastery is a Maker Edition app, and edition is per gateway. The platform gateway runs its own licensed edition. A Maker gateway is personal use only; that fits a home roastery and would not fit shared infrastructure. |
| Separate namespace `roastery` and hostname `roastery.home.lan` | Keeps the Maker gateway's blast radius (trial resets until activated, personal use terms) away from the platform gateway. |
| Postgres StatefulSet added (`postgres.yaml`) | The platform gateway has no database; the Roastery wants a Postgres backend and SQL historian. The Service is named `db` so the gateway's one database connection definition resolves in both modes. |
| Readiness probe path `/StatusPing` instead of `/main/StatusPing.jsp` | That is the endpoint the 2027 lab gateway answers. |
| Config mode arg `-Dignition.config.mode=prod` | Mirrors the Docker mode's command. The homelab deployment passes only `-n` today, so verify the `--` arg form on first deploy. |

## How configuration reaches the gateway in this mode

There are no bind mounts in Kubernetes. Three channels, matching how
the homelab already works:

1. **Gateway state lives on the PVC.** First boot commissions the
   gateway from the Deployment env (EULA, Maker edition, admin from
   the `roastery-admin` Secret). Maker activation happens once in
   the web UI and persists on the volume, exactly as the homelab
   ignition README describes for its gateway.
2. **Projects and gateway config come from git.** The homelab answer
   is stoker-operator (knorrlabs/stoker-operator), which syncs
   gateway configuration from a Git repository. Point it at this
   repo: `roastery/project/` for the project and
   `gateway/config/resources/` for the configuration resources
   (historian, database connection, devices in the lab). Seeding by
   hand is the fallback: apply `gateway/config/exports/` through
   the gateway REST API, then run the repo's tag setup scripts.
3. **Tags and the UDT come from the setup scripts.**
   `roastery/scripts/setup_roastery_artisan_tags.py` run against
   the gateway API creates the `RoastBatch` UDT and instance,
   exactly as in the lab and in local mode.

## Secrets

No secret values anywhere in these files. Two ExternalSecrets pull
from OpenBao through the existing `openbao` ClusterSecretStore:

- `homelab/roastery-admin` (username, password): gateway admin.
- `homelab/roastery-db` (password): Postgres password.

One wart to know about: the gateway's database connection references
the password as a gateway level secret named `roastery-db-password`
(the Ignition secret provider pattern Eric's template uses). A human
creates that gateway secret with the same value on first setup;
nothing syncs it from OpenBao automatically in this draft.

## Simulator devices stay in the lab

`RoasterSim` exists so the lab has a bean temperature feed. In prod
the SR800 feed arrives from the Pico W monitor over WebSocket, and
the simulator resources should not be synced. `NorthPlantSim` is
ChartLab's lab device and likewise stays behind.

## The alternative worth deciding

This draft gives the Roastery its own gateway because Maker edition
forces the question. The cheaper topology is to skip this folder's
Deployment entirely and put the Roastery project on the existing
homelab gateway (`k8s/ignition/`), delivered by stoker-operator
like everything else there. Trade off: that gateway is not a Maker
gateway, its licensing and uptime serve the whole house, and the
roastery inherits both. The manifests here keep the dedicated
option ready; the decision is Eric's when the folder moves.
