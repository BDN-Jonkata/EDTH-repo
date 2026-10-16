# EDTH project instructions

Distributed multi-sensor fusion into a Common Operational Picture under electronic warfare: 5 friendly drones and 2 ground sensors over about 1 km², 2 hostile drones crossing at close range. Keep the hostile count correct, IDs stable, flag no friendlies, and degrade gracefully when messages are lost.

Read before working:
- [README.md](../README.md) for the plan and module map.
- [docs/data-formats.md](../docs/data-formats.md) for the JSON every module reads and writes. Do not invent other formats; extend that file when a format changes.
- Each module has its own `<module>.md` describing its job.

## Code readability

1. **A function fits on one screen.** Aim for at most 40 lines, never more than 50. If a function grows past that, split it into named steps, each doing one thing. A reader should see the whole function without scrolling.
2. **One place for anything used twice.** When the same logic, constant, formula or data shape appears in two places, move it to one function or module and import it. Check `common/` and the existing module first. Do not copy a helper from another file.
3. Name things by what they mean (`close_crossing`, not `tmp2`). A comment explains why, not what.
4. Keep files focused. If a file mixes unrelated jobs, split it.
5. When you change a function that is already too long, split it as part of the change. Do not leave it longer than you found it. Do not refactor unrelated code.

The simulation in `ui/viewer/sim.js` follows this: a run is a context object passed through one small function per stage (sense, send, deliver, track, lifecycle, prune, snapshot, score, crossing). Add new behaviour as another small stage function, not inside an existing one.

## Data and safety rules

- Only the scoring module reads `truth.json`. Every other module works from `scenario.json` and the sensor messages.
- Sensor modules report their native fields (a camera gives bearing and elevation, never range). Do not use ground-truth positions in the tracker.
- Do not hardcode secrets. `DATABASE_URL` comes from the git-ignored `.env`.
- Sensor numbers in the catalog are assumptions unless `verified` is true. Say so when you rely on them.

## Working in this repo

- Read the existing code and follow its patterns before adding anything.
- Run the relevant tests before reporting done: `python -m unittest discover -s seeder/tests`; `python seeder/seed_catalog.py --check`; `node --check` on changed JS files; `node ui/viewer/test-commands.js` for the mock simulation's commanded motion.
- Generated files (`ui/viewer/catalog.js`, `ui/viewer/scenarios.js`, `seeder/data/db-dump.json.gz`) are made by scripts in `seeder/`. Re-run the script, do not edit by hand.
- Do not commit or push unless asked.
