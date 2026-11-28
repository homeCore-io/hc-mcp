# .NET plugins

Read this when the plugin is in C#. The SDK is the project `HomeCoreSdk.csproj`,
namespace `HomeCore.PluginSdk` (0.4.6 at the time of writing), targeting
`net8.0`, built on MQTTnet 4. Source:
[hc-plugin-sdk-dotnet](https://github.com/homeCore-io/hc-plugin-sdk-dotnet).

**Releasing:** there is no release workflow, artifact format or runtime for
.NET plugins yet, so a .NET plugin cannot be published to the Catalog today.
You can write and run one against a homeCore you control. If you need the
Catalog, write the plugin in Rust or Python.

## Install

Nothing is on NuGet, and NuGet has no git install, so clone the SDK at a tag
and reference the project. Check the SDK's README for the current method
first:

```bash
git clone --branch v0.4.6 https://github.com/homeCore-io/hc-plugin-sdk-dotnet
dotnet new console -o hc-demo-dotnet        # outside the SDK folder
cd hc-demo-dotnet
dotnet add reference ../hc-plugin-sdk-dotnet/HomeCoreSdk.csproj
dotnet add package Tomlyn                    # the SDK has no TOML parser
```

Create the plugin project outside the SDK's folder: the SDK's project
compiles every `.cs` file under it except `tests/` and `examples/`.
`OnActionWithCaller`, `RequiresRole.SignedIn`, `ApiScopes` and `ApiAccess`
need 0.4.5 or newer.

`hc-demo-dotnet.csproj`:

```xml
<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Exe</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <Nullable>enable</Nullable>
    <ImplicitUsings>enable</ImplicitUsings>
  </PropertyGroup>
  <ItemGroup>
    <ProjectReference Include="../hc-plugin-sdk-dotnet/HomeCoreSdk.csproj" />
    <PackageReference Include="Tomlyn" Version="0.19.0" />
  </ItemGroup>
</Project>
```

## A minimal plugin

One lamp: an immediate `signed_in` action that reads `caller`, an admin
streaming action, REST access, an alert kind, a stop handler and its own
screens. It builds against SDK 0.4.5 on .NET 8, and exits 1 with a message
when the config is missing or the broker can't be reached.

homeCore passes only the config file's path (`args[0]`). Read the broker
settings from its `[homecore]` table:

```toml
[homecore]
broker_host = "127.0.0.1"
broker_port = 1883
plugin_id   = "plugin.demo_lamp"
password    = ""
```

`Program.cs`:

```csharp
// plugin.demo_lamp: one dimmable lamp. Run: hc-demo-dotnet <config.toml>
using System.Text.Json;
using System.Text.Json.Nodes;
using HomeCore.PluginSdk;
using Tomlyn;
using Tomlyn.Model;

const string Version = "0.1.0";
const string Lamp = "demo_lamp";

// homeCore passes the config path as the only argument. Read [homecore] from it.
var configPath = args.Length > 0 ? args[0] : "config/config.toml";
TomlTable hc;
try
{
    hc = (TomlTable)Toml.ToModel(File.ReadAllText(configPath))["homecore"];
}
catch (Exception ex)
{
    Console.Error.WriteLine($"cannot read config {configPath}: {ex.Message}");
    return 1; // never die quietly
}

var client = new PluginClient(new PluginOptions
{
    PluginId = (string)hc["plugin_id"],
    BrokerHost = hc.TryGetValue("broker_host", out var h) ? (string)h : "127.0.0.1",
    BrokerPort = hc.TryGetValue("broker_port", out var p) ? (int)(long)p : 1883,
    Password = hc.TryGetValue("password", out var pw) ? (string)pw : "",
});

var on = false;
var pct = 100.0;
JsonObject State() => new() { ["on"] = on, ["brightness_pct"] = on ? pct : 0 };

if (Ui.FindDir() is { } uiDir) client.WithUiDir(uiDir, Version); // before management

var managed = false;
client.OnConnected += async () =>
{
    if (!managed) // starts a heartbeat per call: once
    {
        managed = true;
        await client.EnableManagementAsync(new ManagementOptions
        {
            Version = Version,
            ConfigPath = configPath,
            Capabilities = new Capabilities
            {
                Actions = new[]
                {
                    new PluginAction { Id = "whoami", Label = "Who am I", Description = "Who is asking.",
                                       RequiresRole = RequiresRole.SignedIn, TimeoutMs = 5_000 },
                    new PluginAction { Id = "scan", Label = "Scan for lamps", Description = "Look for lamps.",
                                       Stream = true, Cancelable = true, ItemKey = "id",
                                       RequiresRole = RequiresRole.Admin, TimeoutMs = 60_000 },
                },
                AlertKinds = new[]
                {
                    new PluginAlertKind { Topic = "lamp_hot", Label = "Lamp running hot",
                                          Severity = AlertSeverity.Warning },
                },
                ApiScopes = new[] { "devices:read" },
            },
        });
    }
    await client.RegisterDeviceFullAsync(Lamp, "Demo Lamp", deviceType: "light"); // subscribes to cmd too
    await client.RegisterDeviceSchemaAsync(Lamp, JsonNode.Parse("""
        {"attributes": {
           "on": {"kind": "bool", "writable": true, "display_name": "Power",
                  "states": {"when_true": {"label": "on", "verb": "turns on"},
                             "when_false": {"label": "off", "verb": "turns off"}}},
           "brightness_pct": {"kind": "float", "writable": true, "display_name": "Brightness",
                              "unit": "%", "min": 0, "max": 100, "step": 1}},
         "actions": [{"id": "toggle", "label": "Toggle", "sentence": "toggle {device}"}]}
        """)!);
    await client.PublishStateAsync(Lamp, State()); // whole state, retained
    await client.PublishAvailabilityAsync(Lamp, true);
    client.Notices.Clear("lamp_unreachable");
};

client.OnCommand += async (deviceId, cmd) =>
{
    if (cmd.TryGetProperty("action", out var a))
    {
        if (a.GetString() != "toggle") return;
        on = !on;
    }
    if (cmd.TryGetProperty("on", out var o)) on = o.GetBoolean(); // keeps the last level
    if (cmd.TryGetProperty("brightness_pct", out var b))
    {
        var v = Math.Clamp(b.GetDouble(), 0, 100);
        on = v > 0;
        if (v > 0) pct = v;
    }
    await client.PublishStatePartialForCommandAsync(deviceId, State(), cmd, "demo");
    // The whole list each time; an empty one clears.
    await client.SetAlertsAsync(deviceId, on && pct >= 100
        ? new[] { new PluginAlert { Topic = "lamp_hot", Reason = "At full power" } }
        : Array.Empty<PluginAlert>());
};

client.OnActionWithCaller = async (action, prms, ctx, caller) =>
{
    if (ctx is not null) // streaming
    {
        for (var i = 0; i < 3; i++)
        {
            if (ctx.IsCanceled()) { await ctx.CanceledAsync(); return null; }
            await ctx.ProgressAsync(percent: i * 33, label: "scanning");
            await ctx.ItemAddAsync(new JsonObject { ["id"] = $"lamp-{i}" });
            await Task.Delay(200);
        }
        await ctx.CompleteAsync(new JsonObject { ["found"] = 3 });
        return null;
    }
    return action switch
    {
        "whoami" => new JsonObject
        {
            ["username"] = caller?.Username,
            ["can_command"] = caller?.Scopes.Contains("devices:command") ?? false,
        },
        _ => null, // the SDK answers "unknown action"
    };
};

// client.ApiAccess holds Url (ends in /api/v1), Key and Scopes once it arrives.
client.OnApiAccess = (url, key, scopes) => Task.CompletedTask;
client.OnStop = () => Task.CompletedTask; // leave the device safe; about 1 second

try
{
    await client.ConnectAsync();
}
catch (Exception ex)
{
    Console.Error.WriteLine($"cannot reach the broker: {ex.Message}");
    return 1;
}
await client.RunAsync();
return 0;
```

Things the SDK leaves to you:

- **No automatic reconnect.** `ConnectAsync` runs once; `OnConnected` fires
  again only if you call `ConnectAsync` again (which re-subscribes devices and
  republishes alerts and the manifest). Watch for a dropped connection and
  either reconnect or exit non-zero so the supervisor restarts the plugin.
- `EnableManagementAsync` starts a heartbeat per call. Call it once.
- `OnConnected` and `OnCommand` are events (`+=`); `OnAction`,
  `OnActionWithCaller`, `OnSetConfig`, `OnApiAccess`, `OnState` and `OnStop`
  are properties (`=`). `OnActionWithCaller` wins over `OnAction` when both
  are set.
- An exception in `OnCommand` is logged and swallowed; one in an action
  becomes `{"status": "error"}`.
- SIGTERM and SIGINT run `StopAsync` (your `OnStop`, then every device
  offline, the plugin offline) and exit 0. Don't add your own handler.
- The schema JSON is passed through as you write it. Use core's
  `DeviceSchema` (`attributes` with `kind`, `writable`, `unit`, `min`, `max`,
  `states`; `actions` with `sentence`).

## The SDK's names

| Concept | .NET SDK |
|---|---|
| Construct | `new PluginClient(new PluginOptions { PluginId, BrokerHost, BrokerPort, Password })` |
| Connect | `await client.ConnectAsync()`; throws on failure |
| Run loop | `await client.RunAsync()`, until stopped |
| Connected hook | `client.OnConnected += async () => { ... }` |
| Register | `RegisterDeviceFullAsync(id, name, deviceType:, area:)`; also subscribes to its commands |
| Schema | `RegisterDeviceSchemaAsync(id, schema)` |
| State | `PublishStateAsync(id, state)` (whole, retained), `PublishStatePartialAsync(id, patch)`, `PublishStateForCommandAsync` and `PublishStatePartialForCommandAsync(id, state, cmd, fallbackSource)` |
| Availability | `PublishAvailabilityAsync(id, online)`; plugin status `PublishPluginStatusAsync("active")` |
| Commands | `client.OnCommand += async (deviceId, JsonElement cmd) => { ... }` |
| Management | `EnableManagementAsync(new ManagementOptions { Version, ConfigPath, HeartbeatIntervalSecs, Capabilities })` |
| Manifest | `new Capabilities { Actions, ConfigSchema, ConfigDescriptor, AlertKinds, ApiScopes }` |
| Action | `new PluginAction { Id, Label, Description, Params, Result, Stream, Cancelable, Concurrency, ItemKey, ItemOperations, RequiresRole, TimeoutMs }` |
| Action handler | `client.OnActionWithCaller = async (action, prms, ctx, caller) => JsonObject?`; `null` means unknown, or a finished stream |
| Stages | `ctx.ProgressAsync(percent:, label:, message:, data:)`, `ItemAddAsync` / `ItemUpdateAsync` / `ItemRemoveAsync`, `WarningAsync`, `AwaitingUserAsync(prompt, responseSchema)` then `AwaitRespondAsync()`, `CompleteAsync`, `ErrorAsync`, `CanceledAsync`, `IsCanceled()` |
| Roles | `RequiresRole.Admin`, `User` (default), `ReadOnly`, `SignedIn` |
| Caller | `Caller` record (`Uid`, `Username`, `Role`, `Scopes`, `Kind`): fourth argument, and `ctx.Caller`; never in `prms` |
| REST access | automatic: `client.ApiAccess` (`Url` ends in `/api/v1`, `Key`, `Scopes`), `await client.WaitForApiAccessAsync(timeout)`, `client.OnApiAccess = (url, key, scopes) => Task` |
| Settings | `ConfigSchema` and `ConfigDescriptor` on `Capabilities`; `client.OnSetConfig = async cfg => bool` writes a form's changes |
| Notices | `client.Notices.Raise(PluginNotice.Warning(code, msg, remedy))`, `.Clear(code)`, `.Set(...)` |
| Alerts | `new PluginAlertKind { Topic, Label, Severity, DefaultOn }`; `SetAlertsAsync(id, new[] { new PluginAlert { Topic, Reason, Key, Action } })`; `SetPluginAlertsAsync` |
| Own screens | `Ui.FindDir()` then `client.WithUiDir(dir, version)`, before `EnableManagementAsync` |
| Stop | `client.OnStop = () => Task` |
| Logs | `client.EnableLogForwarding(LogLevel.Information)` with `loggingBuilder.AddHomeCore(client, level)`, or `ForwardLogAsync` |
| Other devices | `SubscribeStateAsync(id)` with `OnState` |

Files sent to actions, pictures the plugin keeps and async action handlers
are Rust only.

`Ui.FindDir` looks at `HC_PLUGIN_UI_DIR`, then `ui/` beside the program, then
`ui/dist` beside the nearest `.csproj`. To ship screens beside the program,
copy them into the output:

```xml
<ItemGroup>
  <None Include="ui/dist/**" Link="ui/%(RecursiveDir)%(Filename)%(Extension)"
        CopyToOutputDirectory="PreserveNewest" />
</ItemGroup>
```

## Run and test

```bash
dotnet build -c Release
dotnet run -- config/config.toml          # against a sandbox broker
```

homeCore runs `<binary> <config path>`, so a sandbox `[[plugins]]` entry's
`binary` must be the built program itself (`bin/Release/net8.0/hc-demo-dotnet`,
or the output of `dotnet publish`), never `dotnet`. The SDK's own tests use
xunit (`dotnet test`).
