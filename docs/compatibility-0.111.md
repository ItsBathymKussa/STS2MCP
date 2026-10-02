# STS2 v0.111.0 compatibility fork

## Scope

This branch of [Gennadiyev/STS2MCP](https://github.com/Gennadiyev/STS2MCP)
targets Slay the Spire 2 **v0.111.0**, game commit **41cef1ea**.
The upstream baseline is `55e064850a68f3b4cde7e5fd525bf9b2dec4e885`.
Compatibility work and native game smoke tests were performed on 2026-10-02.

The tests use the installed **WitnessWeaver 0.3.0** character mod and
**BaseLib 3.4.7**, without changing either mod. They exercise a real game
process with its scene tree, action queue, native RNG, and normal combat timing.
They are **headless** runtime tests; rendered appearance and animation quality
are not verified. No model service or API key is needed for these smoke tests.
The smoke driver is a small fixed policy, not a trained gameplay AI.

## Changes

- `StartRunLobby.MaxPlayers` is no longer public. Singleplayer reports a capacity
  of 1; unknown multiplayer capacity is omitted rather than fabricated.
- `LoadRunLobby.ConnectedPlayerIds` is replaced by the public `PlayerIds` and
  `PlayerCount` APIs. Connected/ready summaries retain all expected save players.
  `is_about_to_begin` uses the public `IsAboutToBeginGame()` check, including
  pending connections and multiplayer minimum-player rules.
- Standard singleplayer now has a lobby, but `SetSeed` rejects standard mode.
  Seeded embark uses the public `NGame.DebugSeedOverride` that the game's own
  AutoSlayer uses. It still clicks the original embark control, keeps standard
  mode, and canonicalizes seeds with the native `SeedHelper`.
- Embark availability is checked before setting a seed.
- The mod manifest declares `min_game_version: 0.111.0`.
- Python dependencies require `mcp>=1.7.1,<2`. A fresh unconstrained install
  previously selected SDK 2.2.0, which removes `mcp.server.fastmcp` and fails
  before the server starts. The lock-file metadata follows the same constraint.
- Added an isolated game launcher and a real MCP stdio smoke driver.

The compatibility changes add no private-member reflection, custom gameplay RNG,
or animation-skipping behavior. Upstream's existing UI reflection remains in
the bridge; this work does not migrate that implementation.

## Verified runtime coverage

| Check | Result |
| --- | --- |
| Release build against v0.111.0 game assemblies | Passed, 0 warnings / 0 errors |
| Mod initialization and localhost HTTP listener | Passed |
| Main menu and custom character enumeration | Passed |
| Select `WITNESSWEAVER-WITNESS_WEAVER` | Passed |
| Seeded standard embark (`wwmcp111test` → `WWMCP111TEST`) | Passed |
| Map selection and playable combat | Passed |
| Actual stdio MCP initialize / list tools | Passed, 64 tools |
| MCP SDK 1.30.0 and locked SDK 1.26.0 | Passed; both can enumerate/read the running game |
| `uv lock --check --offline` / `pip check` | Passed |
| Structured combat state and custom card text | Passed |
| Invalid card index rejection without hand/energy mutation | Passed |
| Play custom defense and targeted attack through MCP | Passed |
| End turn, enemy resolution, draw/energy refresh | Passed |
| First combat completed through MCP | Passed; 12 cards played, HP 18 |
| Four-option custom character card reward | Passed |
| Select `KEEP_DREAM`, claim 8 gold, return to map | Passed; gold 107 |
| Selected Weaver card persisted in `TwinKnot.OtherDeck` | Passed; reserve deck 11 cards |
| Seed/mode persistence on entering floor 2 | Passed; standard mode, exact seed |
| Restart game and continue floor-2 save | Passed; HP 18, gold 107, playable combat |
| Profile / profiles / compendium / wiki HTTP endpoints | Passed |

The HTTP listener could not start inside the execution sandbox (invalid handle).
Launching the same isolated copy outside that sandbox allowed it to start;
no listener implementation or system URL permissions were changed.

The test settings kept `fast_mode: normal`. No AutoSlayer defensive buffs,
stat edits, or Instant Mode were used. All settings, progress, current-run saves,
and logs were written to the test run's separate user-data directory. The
template was the workspace's existing VisualQA profile, not the player's save.

## Reproduce

Use an isolated copy of the game with BaseLib, the character mod, and this
bridge installed. The copy's `override.cfg` must contain:

```ini
[application]
config/use_custom_user_dir=true
config/custom_user_dir_name="WitnessWeaver-VisualQA"
```

Build the bridge (PowerShell, repository root):

```powershell
./build.ps1 -GameDir '<isolated game directory>'
```

Copy `out/STS2_MCP/STS2_MCP.dll` and `mod_manifest.json` into the test game's
`mods/STS2_MCP/` folder, naming the manifest `STS2_MCP.json`.
The optional `STS2_MCP.conf` in that folder may specify `{"port":15526}`.

Create a Python 3.11+ environment in `mcp/.venv` and install the project with
`pip install -e mcp`, or use `uv sync --directory mcp --locked`.

Launch a fresh test profile; the script refuses to overwrite an existing one:

```powershell
./scripts/Start-TestGame.ps1 -GameDir '<isolated game directory>' `
  -RunDirectory 'out/my-compat-test' -Headless
```

An optional `-TemplateUserDataRoot` points to an existing **test** custom user
directory (the folder containing `default/`). Only settings, preferences, and
progress are copied, never `current_run.save` or run history. Without a template,
complete any first-time prompts using the bridge's advertised menu options.

From the main menu, use `menu_select(singleplayer)`, select the custom character
by ID, then `menu_select(confirm, seed="WWMCP111TEST")`. Wait for `state_type=map`
and use `map_choose_node(0)`. Wait for a playable combat before running:

```powershell
./mcp/.venv/Scripts/python.exe ./scripts/mcp_smoke.py --finish-combat `
  --output out/my-compat-test/mcp-smoke.json
```

The driver requires basic defense/attack cards and is intended for a disposable
singleplayer combat. It fails on unsupported selections or exceeded action/turn
budgets. Without `--exercise-combat` / `--finish-combat`, it only lists tools and
reads game state. Rewards and save/load checks above were driven separately
through the bridge and checked against the test save.

Local evidence is stored under `out/runtime-final/`: `game.log`,
`reload-game.log`, `mcp-smoke.json`, `reward-smoke.json`, `save-smoke.json`,
`reload-smoke.json`, and state snapshots. These contain game state and remain
ignored by Git. Game binaries, original game source, and saves are not published.

## Remaining coverage and custom-character integration

This proves the tested singleplayer bridge flow on v0.111.0, not an entire run
or multiplayer compatibility. Lobby changes compile against the public APIs;
two-client co-op and reconnect behavior still need live tests.

The bridge does not yet expose WitnessWeaver's complete reserve state or provide
actions for Switch Form, Rearrange Form, and neutral-card destination buttons.
Selecting a fixed-form Weaver reward was verified through the existing native
reward flow. Full autonomous character testing needs those extra state/actions,
plus targeted death-handoff, dream-realm, and selection tests. Winning this
smoke combat does not establish character balance or full mechanic coverage.
