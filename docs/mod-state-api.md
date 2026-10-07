# Optional mod state and action API (v1)

Mods can explicitly register JSON state and actions without taking a binary
dependency on STS2_MCP. Copy `sdk/ModStateApi.cs` into your mod source, compile
it normally, and register from your existing mod initializer. The same source
SDK is compiled into the bridge; a process-wide, versioned AppDomain registry
stores delegates using only framework and public game types. This works in
either mod initialization order and requires no reflection or private fields.
Without STS2_MCP installed, registration is inert and the mod still loads.

```csharp
using STS2MCP.ModApi;

ModStateApi.Register("MyMod", (player, describeCard) =>
{
    // Return null when this provider does not apply to the given player.
    if (player.GetRelic<MyRelic>() is not { } relic) return null;
    return new Dictionary<string, object?>
    {
        ["schema_version"] = 1,
        ["charges"] = relic.Charges,
        ["extra_hand"] = relic.ExtraHand.Cards.Select(card =>
            describeCard(card, PileType.Hand)).ToList()
    };
});
```

`Register` optionally accepts a third callback:
`Func<Player, string, Dictionary<string, JsonElement>, Dictionary<string, object?>>`.
The string is the mod action ID, and the dictionary contains action parameters.
Return an object such as `{status: "ok", queued: true}` or
`{status: "error", error: "reason"}`. `Unregister(modId)` removes the provider;
registering the same ID replaces it. IDs are case-sensitive. Keep the v1 SDK
signatures unchanged when vendoring it.

Both callbacks run on the Godot main thread for the **local player**. Read
callbacks must not spend energy, draw, shuffle, swap, or otherwise advance
gameplay. Only return JSON-compatible dictionaries, arrays, strings, numbers,
booleans and nulls; never return game model objects or delegates. The bridge
materializes each returned state as JSON. Provider exceptions or invalid state
serialization appear under that mod's `status: "error"` entry while native
state remains available. A null state omits the mod and rejects its actions for
that player. Never infer an inactive card's playability from active-form hooks.

Action callbacks must validate phase, selections, costs, life state and
availability, reject unknown actions/parameters, and enqueue the mod's native
`GameAction` through `RunManager.Instance.ActionQueueSynchronizer.RequestEnqueue`.
They must retain native animations, hooks, RNG and multiplayer synchronization.
The bridge does not supply arbitrary methods, scripts or private-field access.
Queued actions complete asynchronously; re-read state after animations finish.

## Client access

`get_game_state(format="json")` and `mp_get_game_state(format="json")` expose
`player.mod_state[modId]`. Markdown output includes the same extension data.

MCP:

```json
{"mod_id":"WitnessWeaver","mod_action":"switch_form"}
```

Pass this to the new `mod_action` tool. Optional `parameters` defaults to `{}`;
set `multiplayer: true` for a co-op run. REST clients post to the normal SP/MP
endpoint:

```json
{"action":"mod_action","mod_id":"WitnessWeaver","mod_action":"switch_form","parameters":{}}
```

## WitnessWeaver integration

The character's `McpStateIntegration.Register()` publishes:

| Field | Meaning |
| --- | --- |
| `active_form` | `Witness` or `Weaver` |
| `is_swapping`, `action_pending` | Transition/action in progress |
| `switches_this_turn`, `switch_cost` | Actual switch counter and current energy/Blank Space cost |
| `actions` | `switch_form`, `rearrange_form`, `leave_dream`, each with current availability |
| `forms.Witness`, `forms.Weaver` | Form identity, active flag, HP, maximum HP, block and current energy |
| Per-form `deck`, `hand`, `draw_pile`, `discard_pile`, `exhaust_pile`, `play_pile` | Independent arrays with corresponding `_count` fields |
| Card fields | ID, name, description, cost, target, upgrade, keywords, pile-local index and playability |
| `dream_realm` | Independent dream cards, hand/bank, transition and exit behavior |

Current energy is exact for **both** forms during combat. Outside combat,
energy/maximum energy are null and combat piles are empty. Maximum energy is
provided only for the active form because inactive local powers can modify
the hook result. Inactive costs/descriptions are previews evaluated in the
current active context (`cost_context: current_active_form_preview`); read
again after switching for authoritative costs and playability. Inactive hand
cards have `requires_switch: true` and `can_play: false`.

Native `combat_play_card` indices refer only to the current native hand.
Dream indices belong to a separate hand and are not supported by that action.
Dream cards are exposed as state with `standard_hand_action_supported: false`;
`leave_dream` uses the existing animated, synchronized native action.

Draw piles expose membership sorted by rarity and ID, with
`draw_order_known: false`. They do not leak the next shuffled draw. All reads
use real cards without exchanging the forms or invoking gameplay commands.

## Verification on STS2 v0.111.0

Both projects compile with zero warnings/errors against BaseLib 3.4.7.
`scripts/mod_state_smoke.py` uses the real MCP stdio session and a disposable
WitnessWeaver run starting on its first map. It verifies both decks, free
rearrangement, both starting hands/energies, active-only discard changes,
four animated switches with per-form pile preservation and source energy
consumption, rejection at zero energy without mutation, next-turn resets,
Markdown output and invalid provider/action/phase/parameter rejection.

```powershell
./mcp/.venv/Scripts/python.exe scripts/mod_state_smoke.py
```

Local evidence is ignored under `out/runtime-mod-state-delivery/`. The native
headless run checks gameplay and action completion; it does not establish
visible animation quality, two-client co-op behavior, non-empty exhaust-pile
movement, death handoff, or complete dream-card automation. The previous
native combat smoke remains available for ordinary bridge regression tests.
