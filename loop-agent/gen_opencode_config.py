#!/usr/bin/env python3
"""Emit the final opencode.json for one run: the committed guardrails
(loop-agent/opencode.json) MERGED with the provider/model/key injected by the
worker as env (§10.1). Prints the merged JSON to stdout; the entrypoint redirects
it to /work/opencode.json (the repo root, where OpenCode looks).

Env the worker injects:
  LOOP_LLM_BASE_URL   e.g. https://openrouter.ai/api/v1
  LOOP_LLM_API_KEY    the OpenRouter key
  LOOP_LLM_MODEL      the model slug (e.g. z-ai/glm-5.3-flash)
  LOOP_LLM_REASONING  optional reasoning effort
  LOOP_LLM_ROUTE_ORDER optional OpenRouter provider-order lock (e.g. "z-ai") so the
                       upstream is pinned to z.ai — the exact slug is confirmed at
                       build when the key is added and Test-connection is run (§10).
"""
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    base = json.loads((HERE / "opencode.json").read_text())

    model = os.environ.get("LOOP_LLM_MODEL", "").strip()
    base_url = os.environ.get("LOOP_LLM_BASE_URL", "").strip()
    reasoning = os.environ.get("LOOP_LLM_REASONING", "").strip()
    route_order = os.environ.get("LOOP_LLM_ROUTE_ORDER", "").strip()

    model_cfg: dict = {"name": model}
    # Declare capabilities explicitly: OpenCode strips image attachments from
    # models it doesn't know, and a custom provider model defaults to no
    # attachment support — the agent then believes it "has no image input".
    # GLM-5.3-Flash is natively multimodal (Z.ai docs), so declare it.
    model_cfg["attachment"] = True
    model_cfg["tool_call"] = True
    model_cfg["modalities"] = {"input": ["text", "image"], "output": ["text"]}
    model_options: dict = {}
    if reasoning:
        # AI-SDK passes reasoningEffort through to the provider; OpenRouter maps it.
        model_options["reasoningEffort"] = reasoning
    if route_order:
        # OpenRouter provider routing lock — pin the upstream (z.ai) and forbid
        # fallbacks so the same provider always serves the model.
        model_options["provider"] = {"order": [route_order], "allow_fallbacks": False}
    if model_options:
        model_cfg["options"] = model_options

    base["provider"] = {
        "loop": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "CKG loop agent",
            "options": {
                "baseURL": base_url,
                # Env reference — OpenCode resolves {env:...} at runtime and sends
                # it as `Authorization: Bearer <key>` (verified in-container against a
                # header-capturing probe). Keeps the key off disk vs a literal.
                "apiKey": "{env:LOOP_LLM_API_KEY}",
            },
            "models": {model: model_cfg},
        }
    }
    base["model"] = f"loop/{model}"

    print(json.dumps(base, indent=2))


if __name__ == "__main__":
    main()
