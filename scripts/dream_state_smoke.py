"""Read and exercise dream state through MCP on a disposable native-game run.

--start-new-run embarks from the main menu. Otherwise start at its first map.
Spends switch/entry costs, advances a turn if needed, and leaves the dream.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run(args):
    report = {"status": "running", "checks": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    errlog = args.output.with_suffix(".stderr.log").open("w", encoding="utf-8")

    def check(name, **details):
        report["checks"].append({"name": name, **details})
        print(name, json.dumps(details, ensure_ascii=False), flush=True)

    def mod(s):
        return s["player"]["mod_state"]["WitnessWeaver"]

    def dream(s):
        return mod(s)["dream_realm"]

    def validate(s):
        d = dream(s)
        for pile in ("hand", "bank"):
            assert len(d[pile]) == d[pile + "_count"]
            for index, card in enumerate(d[pile]):
                assert card["index"] == index and card["index_scope"] == "dream_realm." + pile
                assert {"id", "name", "cost", "description", "target_type", "keywords",
                        "unplayable_reason", "is_phantom", "exhausts_on_play"} <= card.keys()
                assert card["name"] and card["description"], card
                assert not card["automatic_play_supported"]
        assert d["total_cards_count"] == d["hand_count"] + d["bank_count"]
        assert len(d["pending_returns"]) == d["pending_count"]
        if mod(s)["in_combat"]:
            assert d["energy"] == s["player"]["energy"]
            assert d["energy_source_form"] == mod(s)["active_form"]
        return d

    params = StdioServerParameters(command=sys.executable, args=[
        str(Path(__file__).resolve().parents[1] / "mcp/server.py"), "--host", "127.0.0.1",
        "--port", str(args.port), "--no-trust-env"])
    try:
        async with stdio_client(params, errlog=errlog) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()

                async def call(name, arguments, raw=False):
                    result = await session.call_tool(name, arguments)
                    assert not result.isError, result
                    value = "".join(b.text for b in result.content if b.type == "text")
                    return value if raw else json.loads(value)

                async def state():
                    return await call("get_game_state", {"format": "json"})

                async def wait(predicate):
                    deadline = asyncio.get_running_loop().time() + 40
                    while asyncio.get_running_loop().time() < deadline:
                        s = await state()
                        if predicate(s):
                            return s
                        await asyncio.sleep(0.2)
                    raise TimeoutError("Dream state did not reach expected postcondition")

                async def action(name):
                    result = await call("mod_action", {"mod_id": "WitnessWeaver", "mod_action": name})
                    assert result["status"] == "ok", result

                async def switch():
                    s = await state()
                    before = mod(s)["active_form"]
                    await action("switch_form")
                    return await wait(lambda s: mod(s)["active_form"] != before and
                                      not mod(s)["is_swapping"] and not mod(s)["action_pending"])

                s = await state()
                if args.start_new_run:
                    assert s.get("menu_screen") == "main"
                    for option in ("singleplayer", "WITNESSWEAVER-WITNESS_WEAVER"):
                        assert (await call("menu_select", {"option": option}))["status"] == "ok"
                    assert (await call("menu_select", {"option": "confirm", "seed": "WWMCPSTATE111"}))["status"] == "ok"
                    s = await wait(lambda s: s.get("state_type") == "map")
                assert s.get("state_type") == "map", "Use a disposable first-floor map"
                d = validate(s)
                assert d["energy"] is None and d["total_cards_count"] == 0
                check("noncombat_dream_is_empty_with_null_energy")
                assert (await call("map_choose_node", {"node_index": s["map"]["next_options"][0]["index"]}))["status"] == "ok"
                s = await wait(lambda s: s.get("battle", {}).get("is_play_phase") and mod(s)["actions"]["switch_form"]["available"])
                d = validate(s)
                assert d["bank_count"] == 4 and d["hand_count"] == 0 and not d["is_open"]
                assert all(not c["can_play"] for c in d["bank"])
                assert {c["id"] for c in d["bank"]} == {"WITNESSWEAVER-DREAM_" + suffix for suffix in ("BREATH", "INSIGHT", "BLADE", "SHELTER")}
                report["folded_snapshot"] = s
                check("four_folded_tokens_with_complete_native_card_info")
                s = await switch()
                entry = next((c for c in s["player"]["hand"] if c["id"] == "WITNESSWEAVER-WEAVE_SHELTER"), None)
                if entry is None:
                    s = await switch()  # End on Witness to avoid Weaver's interactive survey.
                    old_round = s["battle"]["round"]
                    assert (await call("combat_end_turn", {}))["status"] == "ok"
                    await wait(lambda s: s.get("battle", {}).get("round", 0) > old_round and mod(s)["actions"]["switch_form"]["available"])
                    s = await switch()
                    entry = next(c for c in s["player"]["hand"] if c["id"] == "WITNESSWEAVER-WEAVE_SHELTER")
                d = validate(s)
                assert d["can_enter"] and entry["index"] in d["entry_card_indices"]
                check("entry_eligibility_and_native_hand_index")
                assert (await call("combat_play_card", {"card_index": entry["index"]}))["status"] == "ok"
                s = await wait(lambda s: dream(s)["is_open"] and not dream(s)["is_transitioning"] and dream(s)["can_leave"])
                d = validate(s)
                assert d["hand_count"] == 4 and d["bank_count"] == 0
                assert all(c["can_play"] and c["unplayable_reason"] is None for c in d["hand"])
                assert d["entry_limit_reached"] and d["last_entry_turn"] == d["current_turn"]
                assert d["exits_after_manual_card_play"] and not d["ends_turn_on_exit"]
                assert not any(c["can_play"] for c in s["player"]["hand"])
                report["open_snapshot"] = s
                check("opened_dream_exposes_real_playability_and_exit_rules", energy=d["energy"], turn=d["current_turn"])
                assert dream(await state()) == d
                assert dream(await state()) == d
                check("repeated_reads_do_not_advance_dream_state")
                result = await call("combat_play_card", {"card_index": 0})
                assert result["status"] == "error", result
                assert dream(await state()) == d
                check("hidden_native_hand_play_rejected_without_dream_mutation")
                markdown = await call("get_game_state", {"format": "markdown"}, raw=True)
                assert all('"' + field + '"' in markdown for field in ("pending_returns", "entry_limit_reached", "energy_source_form", "dream_growth"))
                check("markdown_contains_complete_dream_state")
                await action("leave_dream")
                s = await wait(lambda s: not dream(s)["is_open"] and not dream(s)["is_transitioning"] and not mod(s)["action_pending"])
                after = validate(s)
                assert after["hand_count"] == 0 and after["bank_count"] == 4
                assert after["energy"] == d["energy"] and after["last_exit_turn"] == d["current_turn"]
                assert not after["can_enter"] and after["entry_limit_reached"]
                report["closed_snapshot"] = s
                check("native_leave_updates_piles_and_same_turn_entry_limit")
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
    parser.add_argument("--start-new-run", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("out/runtime-dream-state-native/dream-state-smoke.json"))
    asyncio.run(run(parser.parse_args()))
