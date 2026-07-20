# Local Phone Model

Status: feasibility and safety boundary only.

GOFFY can use a small on-phone model later, but the model must not become the
authority that executes tools. The current implementation keeps deterministic
routing as the only executable route and adds a disabled local-model observation
boundary for unsupported commands.

## Role

The phone model is allowed to help with:

- Intent hints for unsupported natural-language phrasing
- Slot extraction proposals for already allowlisted tools
- Short offline explanations when no tool execution is required
- Confidence and ambiguity signals

The phone model is not allowed to:

- Invoke a tool
- Select a permission level
- Approve a CONFIRM or SENSITIVE action
- Expand a deterministic tool schema
- Read camera, microphone, files, clipboard, or notifications by itself
- Run in the background without visible user action

## Declared Runtime Policy

GOFFY LITE remains the default on the Moto G target. The current code enforces
disabled-by-default observation behavior plus bounded prompt and candidate text.
The remaining values are declared gates for the future runtime integration and
must be wired before a model binary is shipped. Initial budgets are:

- Disabled by default
- Maximum model file size: 512 MB
- Maximum prompt size: 512 characters
- Idle unload window: 60 seconds by default, bounded to 5 minutes
- No model load during cold start
- No model load for deterministic commands
- No background model loop

The first model integration must collect real Moto measurements for startup
impact, peak memory, time to first token, decode speed, battery impact, and UI
responsiveness before the model is enabled in any default mode.

## Reuse-First Scan

Checked on 2026-07-20:

- LiteRT-LM: Apache-2.0, current Google AI Edge path for Android/Kotlin local
  LLMs. Preferred runtime candidate after benchmarking because it is the current
  maintained Google path and has Android/Kotlin API coverage.
- MediaPipe LLM Inference API: not selected for new work because Google marks it
  maintenance-only and recommends LiteRT-LM for Android/Kotlin projects.
- llama.cpp: MIT, mature and efficient across platforms. Keep as fallback for
  Mac Hub experiments, Termux experiments, or native-runtime comparison, but do
  not add its native build surface to the Android app before LiteRT-LM is
  evaluated.
- SmolLM2-360M-Instruct: Apache-2.0, small enough to be a first text-only
  benchmark candidate. Its own model card warns outputs may be inaccurate, so it
  must remain assistive and verified.
- Qwen2.5-0.5B-Instruct: Apache-2.0, second text-only benchmark candidate. Its
  long-context capability is not a reason to use long prompts on the Moto.

Sources:

- https://developers.google.com/edge/litert-lm/overview
- https://developers.google.com/edge/mediapipe/solutions/genai/llm_inference/android
- https://github.com/google-ai-edge/LiteRT-LM
- https://github.com/ggml-org/llama.cpp
- https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct
- https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct

## Next Benchmark Gate

Before adding a runtime dependency or model asset:

1. Create a standalone benchmark build variant or isolated sample path.
2. Run one text-only candidate at a time.
3. Record device model, Android version, battery state, thermal state, model
   file size, backend, peak memory, first-token latency, decode tokens per
   second, and UI responsiveness.
4. Reject any candidate that causes visible command input lag, process death,
   thermal throttling, or sustained battery drain.
5. Only then wire a candidate behind `LocalModelIntentFallback`, still returning
   observations rather than executable plans.
