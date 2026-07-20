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

## Routing Quality Gate

Local model routing output is fail-closed. Even when a future runtime is
explicitly enabled, the model cannot route or execute a task directly. It may
only produce a non-authoritative observation after passing the deterministic
quality gate.

Accepted output format:

```json
{"route":"PHONE","confidence":0.91}
```

Rules:

- The runtime policy must be explicitly enabled; the default policy returns
  `Disabled`.
- Output must be non-empty, at most 256 characters, and contain no control or
  Unicode format characters.
- Output must be exact JSON with only `route` and `confidence`.
- `route` must be exactly `PHONE`, `MAC`, or `CLOUD`.
- `confidence` must be at least `0.70` by default.
- Verbose text, markdown, extra fields, plain labels, chain-of-thought markers
  such as `<think>`, and low-confidence outputs are rejected.
- A passing output creates only `LocalModelIntentObservation.Candidate`; it
  does not create a `GoffyExecutionPlan` and cannot approve any action.

## Runtime Adapter Boundary

The disabled runtime adapter boundary is implemented as a bridge from generated
text into the deterministic quality gate:

- `GatedLocalModelRuntimeAdapter` owns the fail-closed policy, model-file
  validation, prompt generation, and handoff into
  `evaluateLocalModelRoutingOutput`.
- The adapter returns `Disabled` unless `LocalModelRuntimePolicy.enabled` is
  explicitly true.
- Model files must be existing `.litertlm` files under the approved app-owned
  model directory and must stay within the 512 MB GOFFY LITE budget.
- The adapter builds a short strict-JSON routing prompt, rejects candidate
  commands over 160 characters before model execution, and rejects generated
  prompts outside the 512-character prompt budget.
- Runtime failures become `Rejected` observations; caller cancellation is not
  swallowed.
- `LocalModelRuntimeGate` is wired into `GoffyIntentRouter` from the ViewModel as
  an observe-only fallback boundary. The default GOFFY LITE gate is disabled,
  exposes `OFF` in the status rail, and does not load a model.
- The gate re-checks model-file availability and approved-root constraints each
  time an unsupported command reaches the fallback boundary. The status rail is
  refreshed at command boundaries instead of using continuous background polling.
- A future LiteRT-LM production provider may delegate through this gate only when
  user enablement, policy enablement, runtime availability, approved app-owned
  model-file validation, and size bounds all pass.

The concrete LiteRT-LM Android runtime dependency remains benchmark/test-only
until production-gated activation, startup/install-size evidence, idle-unload
behavior, and UI-responsiveness evidence are complete. No model binary is
packaged in the APK or committed to the repository.

Standard GOFFY LITE packaging evidence checked on 2026-07-20 after keeping
LiteRT-LM out of the main runtime classpath:

- Debug APK: about 44 MB
- Unsigned release APK: about 23 MB
- Release APK inspection found no `liblitertlm_jni.so`
- Release APK inspection found no `.litertlm` model asset

## Declared Runtime Policy

GOFFY LITE remains the default on the Moto G target. The current code enforces
disabled-by-default observation behavior plus bounded prompt, model output, and
candidate text. The app now also exposes a fail-closed runtime activation gate
that rechecks model-file constraints at use time plus a status rail refreshed at
command boundaries. The remaining values must still be satisfied by a future
LiteRT-LM production provider before a model binary is shipped. Initial budgets
are:

- Disabled by default
- Maximum model file size: 512 MB
- Maximum prompt size: 512 characters
- Maximum accepted model output size: 256 characters
- Minimum routing confidence: 0.70
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
- litert-community/granite-4.0-350m-litert-lm: Apache-2.0 LiteRT-LM artifact
  evaluated on the physical Moto G. It initialized without OOM but returned no
  output chunks, so it is rejected for GOFFY routing.
- litert-community/Qwen3-0.6B `qwen3_0_6b_mixed_int4.litertlm`: Apache-2.0
  LiteRT-LM artifact evaluated on the physical Moto G. It produced output on
  CPU and remains a benchmark-only candidate until quality, latency, unload, and
  UI-responsiveness gates pass.

Sources:

- https://developers.google.com/edge/litert-lm/overview
- https://developers.google.com/edge/mediapipe/solutions/genai/llm_inference/android
- https://github.com/google-ai-edge/LiteRT-LM
- https://github.com/ggml-org/llama.cpp
- https://huggingface.co/HuggingFaceTB/SmolLM2-360M-Instruct
- https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct
- https://huggingface.co/litert-community/granite-4.0-350m-litert-lm
- https://huggingface.co/litert-community/Qwen3-0.6B

## Next Benchmark Gate

Before adding a runtime dependency or model asset, run the dependency
compatibility probe:

```bash
.venv/bin/python scripts/verify_litertlm_android_dependency.py --version 0.14.0 --mode resolve
```

For a stronger gate before app integration, run:

```bash
.venv/bin/python scripts/verify_litertlm_android_dependency.py --version 0.14.0 --mode build
```

The probe checks Google Maven metadata, rejects dynamic Gradle versions such as
`latest.release`, uses an isolated Android project, and reports blocked or
failing toolchain states without changing the GOFFY app.

Latest compatibility evidence, checked on 2026-07-20:

- `com.google.ai.edge.litertlm:litertlm-android:0.14.0`
- JDK `17.0.19`
- Gradle `9.4.1`
- `--mode resolve`: passed
- `--mode build`: passed in an isolated Android debug APK probe

This proves dependency/toolchain compatibility only. It does not prove model
latency, memory pressure, battery impact, or UI responsiveness on the Moto G.

After dependency compatibility is proven:

1. Run the benchmark-only Android instrumentation harness:

   ```bash
   .venv/bin/python scripts/run_moto_g_litertlm_benchmark.py \
     --execute \
     --confirm-device-mutation \
     --model /path/to/tiny-model.litertlm
   ```

   To use a model that is already on the phone, pass an app-owned path such as:

   ```bash
   .venv/bin/python scripts/run_moto_g_litertlm_benchmark.py \
     --execute \
     --confirm-device-mutation \
     --device-model-path /sdcard/Android/data/dev.goffy.os/files/models/tiny-model.litertlm
   ```

2. Run one text-only candidate at a time.
3. Record device model, Android version, battery state, thermal state, model
   file size, backend, peak memory, first-token latency, decode tokens per
   second, and UI responsiveness.
4. Reject any candidate that causes visible command input lag, process death,
   thermal throttling, or sustained battery drain.
5. Only then wire a candidate behind `LocalModelIntentFallback`, still returning
   observations rather than executable plans.

The current harness is intentionally `androidTest`-only. It installs a debug test
APK, requires explicit `--confirm-device-mutation`, accepts only `.litertlm`
files under GOFFY app-owned model directories, uses the CPU backend first, and
stores benchmark JSON under `.goffy-validation/litertlm-benchmark/`.
The JSON records initialization latency, first-chunk latency, total generation
time, output chunk count, character-rate, battery and thermal snapshots, and
managed/native memory snapshots. True token-per-second reporting, peak memory,
UI responsiveness scoring, battery-drain acceptance, reusable idle-unload
behavior, and the production LiteRT-LM provider still belong to future runtime
integration work. Label-quality checks are implemented in the deterministic
routing quality gate above; live app routing calls the fail-closed activation
gate, but the default gate is disabled and no production LiteRT-LM provider is
packaged.

## Physical Moto G LiteRT-LM Evidence

Checked on 2026-07-20 with USB-connected `moto g - 2025`, Android SDK 36,
charging at 100 percent. Model files were downloaded into ignored
`.goffy-validation/models/`, hash-verified against Hugging Face LFS metadata,
then pushed to app-owned external storage for benchmarking. No model binary is
committed.

Granite 350M result:

- Artifact:
  `.goffy-validation/litertlm-benchmark/20260720T180113Z/litertlm-benchmark.json`
- Model:
  `granite-4.0-350m_q8_ekv1280.litertlm`
- Size: 468,209,584 bytes
- SHA-256:
  `c8e9a29493f62b7c44461fb36980987c4c1454c75e95f57ba0539a8edc9dce76`
- CPU init: 3,426 ms
- Generation window: 7,001 ms
- Output chunks: 0
- Result: rejected with `NoModelOutput`

Qwen3 0.6B mixed INT4 result:

- Artifact:
  `.goffy-validation/litertlm-benchmark/20260720T174956Z/litertlm-benchmark.json`
- Model:
  `qwen3_0_6b_mixed_int4.litertlm`
- Size: 497,664,000 bytes
- SHA-256:
  `b1baab462f6be49d70eada79d715c2c52cd9ece0cad00bddf6a2c097d23498e9`
- CPU init: 3,679 ms
- First chunk: 5,188 ms
- Generation window: 27,020 ms
- Output chunks: 267
- Output rate: 44.34 chars/s
- Memory snapshot after benchmark: about 1.16 GB available of 3.82 GB total
- Result: runtime viable, not routing-approved

A stricter label-only prompt against the same Qwen3 model also produced verbose
reasoning text in the output preview. Do not wire this model into executable
routing until GOFFY has production-gated activation, short response stopping
criteria, idle unload behavior, and UI responsiveness evidence. The
deterministic output-quality gate is now in place and the disabled
generated-text adapter calls it, so the observed verbose Qwen3 output would be
rejected rather than treated as a route.

Qwen3 generated-text adapter smoke result:

- Artifact:
  `.goffy-validation/litertlm-benchmark/20260720T190929Z/litertlm-adapter-smoke.json`
- Command:
  `show my battery status`
- Model:
  `qwen3_0_6b_mixed_int4.litertlm`
- Size: 497,664,000 bytes
- CPU init: 1,715 ms
- First chunk: 5,040 ms
- Generation window: 8,613 ms
- Output chunks: 62
- Output characters before bounded stop: 257
- Observation: `Rejected`
- Reason: `Model output exceeded the local routing output budget.`
- Result: adapter smoke passed because real model output reached the deterministic
  quality gate and was rejected as non-authoritative instead of becoming an
  executable route. The smoke stops collecting generated text after the
  256-character routing budget is exceeded.

This physical smoke also found Android regex portability bugs in the first
quality-gate pattern. The pattern now avoids JVM-only anchors and escapes both
literal braces; `matchEntire` continues to enforce whole-string matching.
