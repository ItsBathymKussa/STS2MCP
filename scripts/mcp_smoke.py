"""Probe a running game through the actual MCP stdio server.

Read-only by default. --exercise-combat spends cards and ends one turn in
the current singleplayer combat; use only a disposable test save.
"""

import argparse
import asyncio
import json
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logging.getLogger("httpx").setLevel(logging.WARNING)


async def run(args):
    report = {"started_at": datetime.now(timezone.utc).isoformat(), "checks": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def check(name, **details):
        report["checks"].append({"name": name, **details})
        save()
        print(name, json.dumps(details, ensure_ascii=False), flush=True)

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).resolve().parents[1] / "mcp" / "server.py"),
              "--host", "127.0.0.1", "--port", str(args.port), "--no-trust-env"],
    )
    async with stdio_client(params) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            init = await session.initialize()
            tool_names = {tool.name for tool in (await session.list_tools()).tools}
            assert {"get_game_state", "combat_play_card", "combat_end_turn"} <= tool_names
            check("mcp_initialize_and_tools", server=init.serverInfo.name, tools=len(tool_names))

            async def call(name, arguments):
                result = await session.call_tool(name, arguments)
                assert not result.isError, result
                return json.loads("".join(block.text for block in result.content if block.type == "text"))

            async def state():
                return await call("get_game_state", {"format": "json"})

            async def wait_state(predicate):
                deadline = asyncio.get_running_loop().time() + 25
                while asyncio.get_running_loop().time() < deadline:
                    current = await state()
                    if predicate(current):
                        return current
                    await asyncio.sleep(0.25)
                raise TimeoutError("Game state did not reach the expected postcondition")

            current = await state()
            report["initial_state"] = current
            check("mcp_get_game_state", state_type=current["state_type"],
                  character=current.get("player", {}).get("character"))
            if not args.exercise_combat:
                report["status"] = "passed"
                save()
                return

            assert current.get("battle", {}).get("is_play_phase"), "Start in a playable combat"
            player = current["player"]
            invalid = await call("combat_play_card", {"card_index": 9999})
            assert invalid["status"] == "error", invalid
            after_invalid = await state()
            assert after_invalid["player"]["energy"] == player["energy"]
            assert after_invalid["player"]["hand"] == player["hand"]
            check("reject_invalid_card_without_mutation", response=invalid)

            for card_type in ("Skill", "Attack"):
                current = await state()
                player = current["player"]
                card = next(c for c in player["hand"]
                            if c["type"] == card_type and c["rarity"] == "Basic"
                            and (card_type != "Skill" or "DEFEND" in c["id"])
                            and c["can_play"] and c["target_type"] in ("Self", "AnyEnemy"))
                arguments = {"card_index": card["index"]}
                target = None
                if card["target_type"] == "AnyEnemy":
                    target = next(e for e in current["battle"]["enemies"] if e["hp"] > 0)
                    arguments["target"] = target["entity_id"]
                result = await call("combat_play_card", arguments)
                assert result["status"] == "ok", result
                after = await wait_state(lambda s: len(s.get("player", {}).get("hand", []))
                                         < len(player["hand"]))
                assert after["player"]["energy"] < player["energy"], after
                if card_type == "Skill":
                    assert after["player"]["block"] > player["block"], after
                else:
                    after = await wait_state(lambda s: any(e["entity_id"] == target["entity_id"]
                                             and e["hp"] < target["hp"]
                                             for e in s.get("battle", {}).get("enemies", [])))
                check("mcp_play_" + card_type.lower(), card_id=card["id"],
                      energy_before=player["energy"], energy_after=after["player"]["energy"])

            current = await state()
            round_before = current["battle"]["round"]
            result = await call("combat_end_turn", {})
            assert result["status"] == "ok", result
            after = await wait_state(lambda s: s.get("battle", {}).get("round", 0) > round_before
                                     and s["battle"]["is_play_phase"])
            check("mcp_end_turn_and_enemy_resolution", round_before=round_before,
                  round_after=after["battle"]["round"], hp_after=after["player"]["hp"],
                  energy_after=after["player"]["energy"])
            report["final_state"] = after
            if args.finish_combat:
                for _ in range(80):
                    current = await state()
                    if "battle" not in current:
                        # Combat teardown and the reward overlay span multiple frames.
                        current = await wait_state(lambda s: "rewards" in s or s.get("state_type") == "game_over")
                        assert "rewards" in current, current
                        check("combat_completed_and_rewards_visible", state_type=current["state_type"],
                              hp=current["player"]["hp"], rewards=current["rewards"])
                        report["final_state"] = current
                        break
                    assert current["battle"]["round"] < 15, "Combat exceeded smoke-test turn budget"
                    if not current["battle"]["is_play_phase"]:
                        await asyncio.sleep(0.25)
                        continue
                    assert not current.get("card_select") and not current.get("hand_select"), \
                        "Selection requires manual policy; this smoke test only exercises basic cards"
                    playable = [c for c in current["player"]["hand"]
                                if c["can_play"] and c["rarity"] == "Basic"
                                and c["target_type"] in ("Self", "AnyEnemy")]
                    playable.sort(key=lambda c: (c["type"] != "Attack", -c["index"]))
                    if playable:
                        card = playable[0]
                        arguments = {"card_index": card["index"]}
                        if card["target_type"] == "AnyEnemy":
                            arguments["target"] = next(e["entity_id"] for e in current["battle"]["enemies"]
                                                       if e["hp"] > 0)
                        result = await call("combat_play_card", arguments)
                        assert result["status"] == "ok", result
                        before_signature = (current["player"]["energy"],
                                            [c["id"] for c in current["player"]["hand"]])
                        await wait_state(lambda s: "battle" not in s
                                         or (s["player"]["energy"], [c["id"] for c in s["player"]["hand"]])
                                         != before_signature)
                    else:
                        result = await call("combat_end_turn", {})
                        assert result["status"] == "ok", result
                        round_before = current["battle"]["round"]
                        await wait_state(lambda s: "battle" not in s
                                         or (s["battle"]["round"] > round_before and s["battle"]["is_play_phase"]))
                else:
                    raise TimeoutError("Combat exceeded smoke-test action budget")
            report["status"] = "passed"
            save()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=15526)
    parser.add_argument("--exercise-combat", action="store_true")
    parser.add_argument("--finish-combat", action="store_true", help="Also finish the current basic-card combat")
    parser.add_argument("--output", type=Path, default=Path("out/runtime/mcp-smoke.json"))
    args = parser.parse_args()
    if args.finish_combat:
        args.exercise_combat = True
    asyncio.run(run(args))
