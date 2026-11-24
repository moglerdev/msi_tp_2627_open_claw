# Hermes deployment notes

The Hermes agent runs on a separate bot server (not the GPU box) as several profiles in
**one multiplexed gateway** (`gateway.multiplex_profiles: true`, one systemd user unit).
Each profile has its own home directory (`.env`, `SOUL.md`, skills, logs). Run one with
`hermes -p <profile> …`.

## Model wiring

- The main model is an external free-tier model; **subagents** (`delegate_task`) and the last
  fallback entry point at the local llama-server provider.
- The local provider is declared in `config.yaml` under `providers:` with
  `api_mode: chat_completions` and any non-empty `api_key` (llama-server doesn't check it).
- llama-server ignores the `model` field and always serves the loaded model, so the name in
  the config is cosmetic. After swapping the served model, update the names anyway so logs
  and `/list` stay honest.
- Chat aliases (`model_aliases:`) switch the model per thread: an ambiguous name such as
  `/model qwen` matches dozens of catalogue entries and does nothing, so define explicit
  aliases.

## Pitfalls we hit

1. **`/model` takes no trailing message.** Anything that isn't a flag becomes part of the
   model name, and names with spaces are rejected ("Model names cannot contain spaces").
   Send two messages: switch, then ask in the same thread. A typo in the alias produces the
   same error and never reaches a proxy.
2. **The delegation pin is global per profile.** `delegate_task` has no per-task model.
   Pinned subagents don't inherit the main fallback chain; give `delegation` its own
   `fallback_providers`.
3. **Single slot.** With `--parallel 1`, subagents queue up and each run evicts the
   prefix cache, so the next main turn pays the cold prefill (~70 s for a 20k-token
   prompt). Keep `delegation.max_concurrent_children` at 2 or lower.
4. **Free-tier catalogues rot silently.** Models disappear (404 "unavailable for free"), and
   the fallback chain hides it. Probe with the same headers Hermes sends
   (`HTTP-Referer` is what the gate checks), otherwise you measure the gate, not the model.
5. **Don't trust a model's statement about itself** (which model a subagent used, whether it
   supports vision). The server log is the proof.
6. **`-z` (oneshot) doesn't load `agent.system_prompt`.** Test gateway-like behaviour with
   `hermes chat -Q -q "…"`.
7. **Instructions inside tool results are not followed** in the gateway; results are wrapped
   as untrusted data. Behaviour rules belong in `agent.system_prompt` or `SOUL.md`.
8. **Don't rewrite config files with a YAML round-trip**; it reindents unrelated lines.
   Append new top-level keys instead and keep a `.bak` per change.
9. Local patches to the vendored checkout (e.g. the Mattermost adapter) don't survive
   `hermes update`. After each update check `git diff --stat` still shows them.

## Mattermost

Sending to a public channel needs no membership; receiving `posted` events does. A bot that
can be @-mentioned but never answers is simply not a channel member.
