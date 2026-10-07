// SPDX-License-Identifier: MIT
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Models;

namespace STS2MCP.ModApi;

/// <summary>Source SDK: compile this file into a mod, without referencing STS2_MCP.dll.</summary>
public static class ModStateApi
{
    // Only framework/game types cross the assembly boundary. Each compiled copy
    // uses the same process registry, irrespective of mod initialization order.
    private const string RegistryKey = "STS2MCP.ModStateApi.v1";

    public static void Register(string modId,
        Func<Player, Func<CardModel, PileType, Dictionary<string, object?>>, Dictionary<string, object?>?> readState,
        Func<Player, string, Dictionary<string, JsonElement>, Dictionary<string, object?>>? executeAction = null)
    {
        if (string.IsNullOrWhiteSpace(modId)) throw new ArgumentException("A mod ID is required.", nameof(modId));
        ArgumentNullException.ThrowIfNull(readState);
        lock (AppDomain.CurrentDomain)
        {
            var entry = new Dictionary<string, Delegate> { ["read"] = readState };
            if (executeAction != null) entry["action"] = executeAction;
            Registry[modId] = entry;
        }
    }

    public static void Unregister(string modId)
    {
        lock (AppDomain.CurrentDomain) Registry.Remove(modId);
    }

    public static Dictionary<string, Dictionary<string, Delegate>> GetProviders()
    {
        lock (AppDomain.CurrentDomain)
            return Registry.ToDictionary(pair => pair.Key, pair => new Dictionary<string, Delegate>(pair.Value));
    }

    private static Dictionary<string, Dictionary<string, Delegate>> Registry
    {
        get
        {
            if (AppDomain.CurrentDomain.GetData(RegistryKey) is Dictionary<string, Dictionary<string, Delegate>> registry)
                return registry;
            registry = new Dictionary<string, Dictionary<string, Delegate>>(StringComparer.Ordinal);
            AppDomain.CurrentDomain.SetData(RegistryKey, registry);
            return registry;
        }
    }
}
