"""Exercise WitnessWeaver state/actions through MCP, using a disposable run.

Start at the first map before combat, or use --start-new-run from the main menu.
This spends cards, swaps forms and ends a
turn. Never point it at a save you want to keep.
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.getLogger("httpx").setLevel(logging.WARNING)
PILES = ("deck", "hand", "draw_pile", "discard_pile", "exhaust_pile", "play_pile")


async def run(args):
    report = {"checks": [], "status": "running"}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def check(name, **details):
        report["checks"].append({"name": name, **details})
        print(name, json.dumps(details, ensure_ascii=False), flush=True)

    def mod(s):
        value = s["player"]["mod_state"]["WitnessWeaver"]
        assert value.get("status") != "error", value
        return value

    def validate(s):
        value = mod(s)
        assert value["schema_version"] == 1
        for name, face in value["forms"].items():
            assert face["is_active"] == (name == value["active_form"])
            for pile in PILES:
                cards = face[pile]
                assert len(cards) == face[pile + "_count"]
                assert [c["index"] for c in cards] == list(range(len(cards)))
                assert all({"id", "name", "cost", "description", "target_type"} <= c.keys() for c in cards)
            assert not face["draw_order_known"]
        active = value["forms"][value["active_form"]]
        if value["in_combat"]:
            assert active["energy"] == s["player"]["energy"]
            assert [c["id"] for c in active["hand"]] == [c["id"] for c in s["player"]["hand"]]
        else:
            assert all(f["energy"] is None and f["hand"] == [] for f in value["forms"].values())
        return value

    def identity(value):
        return {name: {pile: [(c["id"], c["is_upgraded"]) for c in face[pile]] for pile in PILES}
                for name, face in value["forms"].items()}

    params = StdioServerParameters(command=sys.executable, args=[
        str(Path(__file__).resolve().parents[1] / "mcp/server.py"),
        "--host", "127.0.0.1", "--port", str(args.port), "--no-trust-env"])
    errlog = args.output.with_suffix(".stderr.log").open("w", encoding="utf-8")
    try:
        async with stdio_client(params, errlog=errlog) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert "mod_action" in names
                check("mcp_tool_registered", tool_count=len(names))

                async def call(name, arguments, raw=False):
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, result
                    data = "".join(b.text for b in result.content if b.type == "text")
                    return data if raw else json.loads(data)

                async def state():
                    return await call("get_game_state", {"format": "json"})

                async def wait(predicate):
                    deadline = asyncio.get_running_loop().time() + 35
                    while asyncio.get_running_loop().time() < deadline:
                        s = await state()
                        if predicate(s):
                            return s
                        await asyncio.sleep(0.2)
                    raise TimeoutError("State did not reach expected postcondition")

                async def action(name, **extra):
                    return await call("mod_action", {"mod_id": "WitnessWeaver", "mod_action": name, **extra})

                s = await state()
                if args.start_new_run:
                    assert s.get("menu_screen") == "main", "Start on the disposable profile's main menu"
                    assert (await call("menu_select", {"option": "singleplayer"}))["status"] == "ok"
                    assert (await call("menu_select", {"option": "WITNESSWEAVER-WITNESS_WEAVER"}))["status"] == "ok"
                    assert (await call("menu_select", {"option": "confirm", "seed": "WWMCPSTATE111"}))["status"] == "ok"
                    s = await wait(lambda s: s.get("state_type") == "map")
                assert s["state_type"] == "map", "Start on a disposable map before first combat"
                before = validate(s)
                report["map_snapshot"] = s
                check("noncombat_two_decks_and_null_energy", counts={n: f["deck_count"] for n, f in before["forms"].items()})
                for bad_args in ({"mod_id": "MissingMod", "mod_action": "switch_form"},
                                 {"mod_id": "WitnessWeaver", "mod_action": "unknown"},
                                 {"mod_id": "WitnessWeaver", "mod_action": "switch_form"},
                                 {"mod_id": "WitnessWeaver", "mod_action": "rearrange_form", "parameters": {"bad": 1}}):
                    result = await call("mod_action", bad_args)
                    assert result["status"] == "error", result
                assert identity(validate(await state())) == identity(before)
                check("invalid_provider_action_phase_parameters_rejected")
                markdown = await call("get_game_state", {"format": "markdown"}, raw=True)
                assert "## Mod State" in markdown and '"Weaver"' in markdown and '"draw_pile"' in markdown
                check("markdown_includes_mod_state")

                original = before["active_form"]
                for _ in range(2):
                    old = mod(await state())["active_form"]
                    result = await action("rearrange_form")
                    assert result["status"] == "ok", result
                    s = await wait(lambda s: mod(s)["active_form"] != old and mod(s)["actions"]["rearrange_form"]["available"])
                    assert identity(validate(s)) == identity(before)
                assert mod(s)["active_form"] == original
                check("free_rearrange_preserves_each_form_deck")

                node = s["map"]["next_options"][0]
                result = await call("map_choose_node", {"node_index": node["index"]})
                assert result["status"] == "ok", result
                s = await wait(lambda s: s.get("battle", {}).get("is_play_phase") and mod(s)["actions"]["switch_form"]["available"])
                value = validate(s)
                report["combat_before"] = s
                assert all(f["energy"] == 3 and f["hand_count"] == 5 for f in value["forms"].values())
                check("combat_both_hands_and_energy", energy={n: f["energy"] for n, f in value["forms"].items()})
                card = next(c for c in s["player"]["hand"] if c["id"] == "WITNESSWEAVER-WITNESS_DEFEND")
                result = await call("combat_play_card", {"card_index": card["index"]})
                assert result["status"] == "ok", result
                s = await wait(lambda s: mod(s)["forms"]["Witness"]["discard_pile_count"] == 1 and mod(s)["actions"]["switch_form"]["available"])
                value = validate(s)
                check("played_card_moves_only_active_form_pile", witness_energy=value["forms"]["Witness"]["energy"])
                for i in range(4):
                    before = validate(s)
                    old = before["active_form"]
                    other = "Weaver" if old == "Witness" else "Witness"
                    result = await action("switch_form")
                    assert result["status"] == "ok", result
                    s = await wait(lambda s: mod(s)["active_form"] == other and not mod(s)["is_swapping"] and not mod(s)["action_pending"])
                    after = validate(s)
                    assert identity(after) == identity(before), "Switch must preserve per-form pile identities/order"
                    assert after["forms"][old]["energy"] == before["forms"][old]["energy"] - 1
                    assert after["forms"][other]["energy"] == before["forms"][other]["energy"]
                    check("switch_preserves_piles_and_spends_source_energy", switch=i + 1, active=other,
                          energy={n: f["energy"] for n, f in after["forms"].items()})
                before = validate(s)
                assert before["forms"][before["active_form"]]["energy"] == 0
                result = await action("switch_form")
                assert result["status"] == "error", result
                after = validate(await state())
                assert identity(after) == identity(before) and after["active_form"] == before["active_form"]
                assert {n: f["energy"] for n, f in after["forms"].items()} == {n: f["energy"] for n, f in before["forms"].items()}
                check("insufficient_energy_rejected_without_mutation")
                round_before = s["battle"]["round"]
                assert (await call("combat_end_turn", {}))["status"] == "ok"
                s = await wait(lambda s: s.get("battle", {}).get("round", 0) > round_before and mod(s)["actions"]["switch_form"]["available"])
                value = validate(s)
                assert all(f["energy"] == 3 for f in value["forms"].values())
                check("both_forms_reset_energy_next_turn", round=s["battle"]["round"])
                report["combat_after"] = s
                report["status"] = "passed"
    except BaseException as ex:
        report["status"] = "failed"
        report["error"] = repr(ex)
        raise
    finally:
        errlog.close()
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=15526)
    parser.add_argument("--start-new-run", action="store_true", help="Embark a disposable WitnessWeaver run from the main menu")
    parser.add_argument("--output", type=Path, default=Path("out/runtime-mod-state-delivery/mod-state-smoke.json"))
    asyncio.run(run(parser.parse_args()))
