# Roastery: Artisan Style Roast Console for Ignition 2027 Maker

A Perspective roast console for a FreshRoast SR800, modeled on Artisan
(the open source roasting software) and rebuilt with Ignition 2027
Maker Edition and the new canvas chart components. It is the Ignition
side of the Ignition Coffee Lab: the SR800 temperature feed arrives
over WebSocket (in the real setup, from the Pico W monitor in this
same repository), and this console is where the roast is run, logged,
and reviewed.

![Roastery console, desktop](docs/shots/roastery-artisan-desktop.png)

## What it does

- Live roast curve (canvas line chart) with bean temperature history,
  a derived rate of rise series, a dashed target profile generated
  from four editable target points, and an optional background roast
  drawn behind the live curve.
- The full Artisan event set, Charge, Dry End, First Crack Start and
  End, Second Crack Start and End, and Drop, each stamping elapsed
  time and bean temperature, plus four custom event buttons whose
  names and kinds are set in the config popup.
- Phases bar with drying, Maillard, and development segments that
  fill in as events land, and the development time ratio (DTR)
  computed at Drop.
- Fan and Heat as SR800 style level steppers (1 to 9). Every change
  is logged with elapsed time and temperature and drawn as a step
  trace strip under the main curve, the way Artisan annotates control
  moves.
- A Roast Setup config popup: roaster connection settings, the full
  batch metadata form, the target designer points, alarm thresholds,
  and a results section for weight out after Drop.
- A roast log page with saved batches (metadata, phase times, DTR,
  weight loss, roast degree, and the saved curve), where any past
  roast can be selected as the background profile.
- A deviation tile showing live bean temperature minus the target
  curve temperature at the current elapsed time.
- Lite alarms surfaced as a banner on the main view.
- Mobile responsive layout that stacks cleanly at phone width.

![Roastery console, mobile](docs/shots/roastery-artisan-mobile.png)
![Roast Setup config popup](docs/shots/roastery-artisan-config.png)
![Roast summary after a test roast](docs/shots/roastery-artisan-summary.png)
![Roast log](docs/shots/roastery-artisan-log.png)

## Design: one probe, derived rate of rise

The SR800 setup has a single bean temperature probe. There is no drum
or environmental probe, and the UDT models exactly that: one
BeanTempF member fed by the probe. Rate of rise is not a probe. It is
derived on the gateway by a tag value changed event script on
BeanTempF that keeps a rolling window and writes an exponentially
smoothed delta per minute to RateOfRiseF, with the smoothing time
constant set by the RoRSmoothingSec member. In the lab the derivation
was verified against a simulator ramping at exactly 25 F per minute:
the derived value converged on the true slope.

There is deliberately no PID anywhere in this design. The SR800 is
run on manual Fan and Heat levels, so the console exposes those
levels and nothing else.

## Repository layout

- `project/Roastery/`: the Perspective project exactly as it runs on
  the Maker gateway (project.json, page config, and the ten views:
  Main, Config, Log, Tile, EventCell, EventsStrip, PhasesBar,
  Controls, MetaCard, Summary).
- `scripts/`: the Python that builds and reproduces the environment.
  - `api27m.py`: small helper for the gateway REST API. It reads the
    API token from a local `apitoken-2027-maker.txt` file (never
    committed; see below) and is imported by the other scripts.
  - `setup_maker_stack.py`: creates the shared stack the app depends
    on: the CoreHistorian provider and the Programmable Device
    Simulator devices with their programs.
  - `setup_roastery_artisan_tags.py`: creates the RoastBatch UDT
    (81 members) and the `Roastery/CurrentBatch` instance, including
    history on the probe tags and the RoR derivation event script.
  - `build_roastery_artisan.py`: writes the project view files. It
    was written against a lab checkout layout (it writes into a
    `gateway-2027-maker` folder next to the script); on a fresh
    gateway you can equally copy `project/Roastery` into the
    gateway and scan it, see below.
  - `validate_roastery_artisan.py`: checks that the served views
    match the authored files, starts every view in a live session,
    and scans the gateway log for project warnings.
  - `screenshot_roastery_artisan.py`, `screenshot_roastery_artisan_verify.py`,
    `screenshot_roastery_artisan_verify2.py`: Playwright click tests
    and screenshot capture used to prove the interactions.
- `docs/coffee-roaster-app.md`: the full build note, including the
  Artisan feature mapping (implemented, adapted, and excluded, with
  reasons) grounded in the Artisan 5.0.0 source, the popup and
  navigation action shapes proven on 2027, and the beta quirks found.
- `docs/shots/`: screenshots from the verified build.

## Standing it up

1. Install Ignition 2027 (this build used 2027.2.0-beta1) and
   commission it as Maker Edition, or point the scripts at an
   existing 2027 gateway. In the lab the Maker gateway was a direct
   install commissioned on first boot with `IGNITION_EDITION=maker`.
2. Create an API key through the gateway webpage: Platform,
   Security, API Keys, add a Basic Token named `claude-lab`. Two
   gotchas from the lab notes: a new key defaults to requiring a
   secure channel (it returns 401 over plain HTTP until that is
   unchecked), and the key level gets 403 until it is granted under
   Security, General Settings, Roles and Permissions.
3. Save the token in the three line labeled format the helper
   expects, as `apitoken-2027-maker.txt` next to the scripts (or set
   the `APITOKEN_FILE` environment variable). The file is gitignored
   and must never be committed. Format:

   ```
   key name: claude-lab
   token: <the secret from the gateway>
   header: X-Ignition-API-Token: claude-lab:<the secret>
   ```

4. Create the data stack, from `scripts/`:
   `python3 setup_maker_stack.py`, then
   `python3 setup_roastery_artisan_tags.py`.
5. Install the project: copy `project/Roastery` into the gateway at
   `data/projects/Roastery`, then ask the gateway to scan for it
   (POST `/data/api/v1/scan/projects` with the API token), or run
   `build_roastery_artisan.py` in a lab layout checkout.
6. Open the Perspective client for the Roastery project. Note that
   Maker Edition opens every session behind a Personal Use Only
   agreement modal; click AGREE & CLOSE to reach the console.
7. Optionally run `validate_roastery_artisan.py` and the screenshot
   verify scripts to reproduce the lab proof.

## Honest lab notes

- In the lab there is no physical SR800 attached. A Programmable
  Device Simulator device (RoasterSim) stands in for the WebSocket
  probe feed, and the SR800 CONNECTED pill on the console reads the
  probe tag quality. The app treats the feed exactly as it will
  treat the real WebSocket feed.
- The gateway runs in trial mode until a free Maker license key from
  an Inductive Automation account is applied. Everything above works
  in trial.
- Test roasts in the log from the lab verification were short
  click-through roasts (about 18 seconds) used to prove the event,
  phase, save, and background flows; their computed statistics are
  not meaningful roast data.
