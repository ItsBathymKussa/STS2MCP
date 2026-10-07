using System;
using System.Collections.Generic;
using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;
using STS2MCP.ModApi;

namespace STS2_MCP;

public static partial class McpMod
{
    private static Dictionary<string, object?> BuildModState(Player player)
    {
        var result = new Dictionary<string, object?>();
        foreach (var (id, provider) in ModStateApi.GetProviders())
        {
            try
            {
                var read = (Func<Player, Func<CardModel, PileType, Dictionary<string, object?>>, Dictionary<string, object?>?>)provider["read"];
                var value = read(player, BuildCardInfo);
                if (value != null) result[id] = JsonSerializer.SerializeToElement(value);
            }
            catch (Exception ex)
            {
                // A broken optional provider must not suppress the native snapshot.
                result[id] = new Dictionary<string, object?> { ["status"] = "error", ["error"] = ex.Message };
            }
        }
        return result;
    }

    private static Dictionary<string, object?> ExecuteModAction(Player player, Dictionary<string, JsonElement> data)
    {
        if (!data.TryGetValue("mod_id", out var idElement) || idElement.ValueKind != JsonValueKind.String ||
            !data.TryGetValue("mod_action", out var actionElement) || actionElement.ValueKind != JsonValueKind.String)
            return Error("mod_id and mod_action must be strings");
        var id = idElement.GetString()!;
        if (!ModStateApi.GetProviders().TryGetValue(id, out var provider)) return Error($"Mod provider is not registered: {id}");
        if (!provider.TryGetValue("action", out var handler)) return Error($"Mod provider is read-only: {id}");
        var parameters = new Dictionary<string, JsonElement>();
        if (data.TryGetValue("parameters", out var parameterElement))
        {
            if (parameterElement.ValueKind != JsonValueKind.Object) return Error("parameters must be an object");
            foreach (var property in parameterElement.EnumerateObject()) parameters[property.Name] = property.Value;
        }
        try
        {
            var read = (Func<Player, Func<CardModel, PileType, Dictionary<string, object?>>, Dictionary<string, object?>?>)provider["read"];
            if (read(player, BuildCardInfo) == null) return Error($"Mod provider does not apply to this player: {id}");
            return ((Func<Player, string, Dictionary<string, JsonElement>, Dictionary<string, object?>>)handler)(player, actionElement.GetString()!, parameters);
        }
        catch (Exception ex) { return Error($"Mod action failed ({id}): {ex.Message}"); }
    }
}
