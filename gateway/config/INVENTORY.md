# Gateway configuration inventory

Every gateway scoped item the Roastery app depends on, where it is
defined in this repository, and how it reaches a running gateway in
each deployment mode. Project files and tags are listed at the end
because they travel with the gateway even though they are not
gateway configuration resources.

## Configuration resources (defined in `resources/`)

| Item | Type | Defined in | Local (Docker) | Prod (Kubernetes) | Notes |
| --- | --- | --- | --- | --- | --- |
| CoreHistorian | `com.inductiveautomation.historian/historian-provider` | `resources/core/com.inductiveautomation.historian/historian-provider/CoreHistorian/` | Mounted with the core resources | Synced or applied through the gateway API (see `../prod/README.md`) | The historian the app uses today. Every history enabled tag in the setup scripts points at provider name `CoreHistorian`. Exported verbatim from the lab Maker gateway; `exports/historian-provider-CoreHistorian.json` is the same config as an API response. |
| db | `ignition/database-connection` | `resources/core/ignition/database-connection/db/` | Mounted with the core resources | Same | Postgres backend connection. JDBC URL is `jdbc:postgresql://db:5432/db`; the host name `db` resolves to the Compose service in local mode and to the in-cluster Service in prod, so one definition serves both modes. Password is a referenced secret (`internal-secret-provider`, name `roastery-db-password`), never a literal. Modeled on the `db` connection in etknorr/project-template; that file references a secret named `mysql-db-password`, which looks like a leftover from another project, so the name was changed here and the change flagged. |
| db | `com.inductiveautomation.historian/historian-provider` (SqlHistorian) | `resources/core/com.inductiveautomation.historian/historian-provider/db/` | Mounted with the core resources | Same | The Postgres backed historian, in the exact shape project-template uses (connection `db`, monthly partitions, pruning off). Defined and ready, but the app's tags still record to `CoreHistorian`. Switching history to Postgres is a deliberate step: repoint the `historyProvider` in `roastery/scripts/setup_roastery_artisan_tags.py` and `setup_maker_stack.py` from `CoreHistorian` to `db`, then re-run them. Left as an open decision in the draft report. |
| RoasterSim | `com.inductiveautomation.opcua/device` (ProgrammableSimulatorDevice) plus `instructions.csv` datafile | `resources/core/com.inductiveautomation.opcua/device/RoasterSim/` | Mounted with the core resources | Lab only, do not deploy | Stands in for the SR800 bean temperature feed in the lab. In production the Pico W monitor in this repo feeds bean temperature over WebSocket and no simulator device is wanted. Exported verbatim from the lab Maker gateway. |
| NorthPlantSim | `com.inductiveautomation.opcua/device` (ProgrammableSimulatorDevice) plus `instructions.csv` datafile | `resources/core/com.inductiveautomation.opcua/device/NorthPlantSim/` | Mounted with the core resources | Lab only, do not deploy | Only serves the ChartLab demo project in the lab. Not a Roastery dependency; included so the repo carries the full lab stack the setup scripts create. |

Resource files copied from the lab gateway carry that gateway's
UUIDs and modification signatures in their `resource.json`. A
gateway refreshes those when it loads and saves the resources;
strip the `attributes` block if a clean import is ever preferred.

## Built in items (nothing to define)

| Item | Why it matters |
| --- | --- |
| Tag provider `default` | The Roastery tags and the `RoastBatch` UDT live here. Ships with every gateway. |
| OPC UA server `Ignition OPC UA Server` | The UDT's OPC members (BeanTempF) address the simulator devices through the built in server. Ships with every gateway. |
| PostgreSQL JDBC driver and POSTGRES translator | The `db` connection references them by name. Both ship with Ignition; the lab gateway's resource tree confirms they are present in 2027. |

## Deliberately not in the repo (human steps)

| Item | Where it comes from |
| --- | --- |
| Gateway admin user | Commissioned on first boot from environment: `.env` values in local mode, the `roastery-admin` Secret (External Secrets from OpenBao) in prod. Never committed. |
| API token `claude-lab` | Created through the Gateway webpage (Platform, Security, API Keys). Hand built token files do not authenticate on these gateways; this is a standing lab finding. The setup scripts expect the resulting token file locally and it is never committed. |
| Maker license key | Free from an Inductive Automation account, applied in the gateway web UI. Activation state lives on the gateway data volume, not in git. |
| Postgres password | `.env` in local mode; OpenBao (`secret/homelab/roastery-db`) via the prod ExternalSecret. Inside the gateway, the `db` connection references it as a gateway secret named `roastery-db-password`, which a human creates in the gateway secret provider on first setup. |
| Gateway network UUID | Local mode: the bootstrap script derives it deterministically from `GATEWAY_NAME`, the project-template pattern. Prod: lives on the PVC with the rest of the gateway state. |

## Project and tags (travel with the gateway, defined elsewhere in this repo)

| Item | Defined in | How it is applied |
| --- | --- | --- |
| Perspective project `Roastery` | `roastery/project/Roastery/` | Local: bind mounted into the gateway. Prod: synced from git by stoker-operator, the homelab pattern. |
| `RoastBatch` UDT, `Roastery/CurrentBatch` instance, Roastery folder tags | `roastery/scripts/setup_roastery_artisan_tags.py` | Run against the gateway REST API once the gateway is up, in both modes. Creates the RoasterSim device first if it is missing. |
| NorthPlant tags (ChartLab only) | `roastery/scripts/setup_maker_stack.py` | Same API route. Not needed for the Roastery app alone. |
