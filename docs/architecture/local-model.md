# Local Phone Model

Status: feasibility, safety boundary, developer-variant runtime setting control,
bounded observe-only unsupported-command execution, and physical Moto G
modelDebug smoke evidence.

GOFFY can use a small on-phone model later, but the model must not become the
authority that executes tools. The current implementation keeps deterministic
routing as the only executable route, adds a local-model observation boundary for
unsupported commands, and exposes a foreground runtime setting control only in
the runtime-capable `modelDebug` variant.

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

## Micro Intent Fallback

GOFFY LITE now includes a zero-dependency micro intent fallback for unsupported
commands. It is not an LLM, does not load a model file, does not use camera,
microphone, files, clipboard, network, or notifications, and does not execute
tools. It only scores bounded local command text against small PHONE, MAC, and
CLOUD vocabularies, then returns a non-authoritative
`LocalModelIntentObservation.Candidate`.

The micro fallback exists because physical Moto G `modelDebug` evidence showed
LiteRT-LM observation was safe but too slow and memory-heavy for production
default routing hints. The micro fallback keeps GOFFY useful offline while the
heavier runtime remains benchmark-only. Risky unsupported commands such as
delete, wipe, credentials, or install language are rejected instead of converted
into route hints, and ties across targets fail closed as ambiguous.

Deterministic routes remain the only executable authority. A micro fallback
candidate changes only the failed unsupported-command timeline summary, for
example `Local model suggested MAC, but GOFFY needs a deterministic route before
execution`.

## Runtime Adapter Boundary

The disabled runtime adapter boundary is implemented as a bridge from generated
text into the deterministic quality gate:

- `GatedLocalModelRuntimeAdapter` owns the fail-closed policy, model-file
  validation, prompt generation, and handoff into
  `evaluateLocalModelRoutingOutput`.
- The adapter returns `Disabled` unless `LocalModelRuntimePolicy.enabled` is
  explicitly true.
- `GatedLocalModelRuntimeProvider` is a suspend boundary for generated-text
  observations. The synchronous deterministic router remains authoritative and
  does not block the UI thread on model generation.
- Unsupported commands may run the provider only when the foreground status is
  `READY`, the command already passed local prompt safety checks, and the
  developer/runtime-validation build has explicitly wired observation execution.
  The ViewModel records this as a PHONE timeline task with no tool, no
  permission grant, and a terminal failed/cancelled phase.
- `LocalModelRuntimeSettingsStore` persists the user enablement bit in
  app-private preferences and applies it only after a synchronous commit plus
  read-back verification on an IO dispatcher. If storage cannot be read or
  verified, the runtime stays disabled and the UI reports the failure.
- `LocalModelRuntimeProviderLoader` resolves the optional LiteRT-LM provider by
  a fixed local class name. Normal `debug` and `release` builds do not include
  that class or the LiteRT-LM dependency, so the loader returns `null` and the UI
  does not expose runtime controls.
- Model files must be existing `.litertlm` files under the approved app-owned
  model directory and must stay within the 512 MB GOFFY LITE budget.
- The adapter builds a short strict-JSON routing prompt, rejects candidate
  commands over 160 characters before model execution, and rejects generated
  prompts outside the 512-character prompt budget.
- Runtime failures become `Rejected` observations; caller cancellation is not
  swallowed. Generation is bounded by the runtime policy timeout before its
  output enters the deterministic quality gate.
- `LocalModelRuntimeGate` is wired into `GoffyIntentRouter` from the ViewModel as
  an observe-only fallback boundary. The default GOFFY LITE gate is disabled,
  exposes `OFF` in the status rail, and does not load a model.
- The gate re-checks model-file availability and approved-root constraints each
  time an unsupported command reaches the fallback boundary. The status rail is
  refreshed at command boundaries instead of using continuous background polling.
- A future LiteRT-LM production provider may delegate through this gate only when
  user enablement, policy enablement, runtime availability, approved app-owned
  model-file validation, and size bounds all pass.
- `modelDebug` is a developer/runtime-validation build type that compiles the
  real LiteRT-LM Android provider from `android/app/src/modelDebug`. It uses the
  official `Engine` API on `Dispatchers.Default`, CPU backend, app cache
  directory, bounded output collection, and explicit `use`/close blocks. It
  still defaults to disabled user activation, exposes a foreground enable/disable
  setting after verified storage, runs only observe-only unsupported-command
  execution when ready, and is not part of normal `debug` or `release` GOFFY
  LITE packaging.
- `scripts/verify_android_apk_budget.py` is part of `verify_all.py` after the
  release APK build. It blocks the default GOFFY LITE APK when it exceeds 32 MiB
  or packages LiteRT-LM/model APK entries such as `liblitertlm` or `.litertlm`.
  It also rejects LiteRT-LM in the normal `debugRuntimeClasspath` or
  `releaseRuntimeClasspath`, so local-model provider work cannot silently regress
  default Moto builds.

The concrete LiteRT-LM Android runtime dependency remains outside default
GOFFY LITE packaging until production-gated activation, startup/install-size
evidence, idle-unload behavior, and UI-responsiveness evidence are complete. No
model binary is packaged in the APK or committed to the repository.

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
command boundaries. The `modelDebug` runtime setting control stores only the
user enablement bit and can run one bounded observe-only unsupported-command
pass when the provider is ready. It still does not make the model an executable
router. The remaining values must still be satisfied before a model binary is
shipped in any default build. Initial budgets are:

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

The current `modelDebug` smoke proves one foreground unsupported-command pass can
complete on the Moto G, but it is not enough to ship a default runtime. Repeated
run responsiveness, idle-unload acceptance, production prompt stopping, and
operator UX for model install/remove remain open.

Production acceptance now has a read-only evidence verifier:

```bash
.venv/bin/python scripts/collect_modeldebug_idle_cleanup_evidence.py \
  --execute \
  --observation-report .goffy-validation/modeldebug-observation-smoke/run-3/modeldebug-observation-report.json \
  --output .goffy-validation/modeldebug-observation-smoke/idle-cleanup.json

.venv/bin/python scripts/verify_modeldebug_acceptance.py \
  --idle-evidence-json .goffy-validation/modeldebug-observation-smoke/idle-cleanup.json \
  .goffy-validation/modeldebug-observation-smoke/run-1/modeldebug-observation-report.json \
  .goffy-validation/modeldebug-observation-smoke/run-2/modeldebug-observation-report.json \
  .goffy-validation/modeldebug-observation-smoke/run-3/modeldebug-observation-report.json
```

The verifier requires at least three executed `modelDebug` observation reports,
the fixed unsupported command `open settings`, terminal non-executable `FAILED`
timeline evidence, visible proof that local-model observation ran, bounded
memory/logcat artifacts, a consistent model SHA-256, each run at or below 15
seconds by default, bounded logcat evidence containing the fixed observation
engine teardown marker `observation_engine_scope_closed`, and separate
idle-cleanup JSON with `provider_closed_after_idle=true`. The smoke runner
accepts safe model-output rejection reasons such as strict-schema mismatch or
output-budget overflow; it does not require one exact model failure string. The
acceptance JSON separates `accepted_runs` from `rejected_runs`; rejected runs
preserve parseable elapsed time, total PSS, battery level, model SHA-256, output
directory, and rejection reason so blocked physical evidence is still
machine-readable. The verifier also avoids duplicating the idle TOTAL PSS
blocker when the idle-cleanup collector has already reported it. The
collector sets the idle field when the observation report contains the teardown
marker, which proves the LiteRT-LM engine/conversation scope unwound for that
observation. If the foreground `modelDebug` app process remains alive after the
idle wait, the verifier separately requires bounded idle PSS. The marker is
non-sensitive lifecycle telemetry only; it must not include the prompt, model
output, model path, or command text. The existing 37.6-second Qwen3 single-run
evidence intentionally fails this gate.

The idle-cleanup collector is also read-only against the phone. It requires a
supplied observation report, reads that report's bounded logcat artifact for the
fixed teardown marker, waits 60 seconds by default, and then probes only `pidof`
plus bounded `dumpsys meminfo` if the process remains. It writes local JSON
evidence and blocks if a remaining modelDebug process exceeds the idle PSS
budget.
It does not install an APK, push files, type commands, clear app state, read live
logcat, or broaden ADB. For slow-but-safe diagnostics, pass
`--max-observation-millis <limit>` to the collector only; the production
acceptance verifier still defaults to 15 seconds unless explicitly overridden.

## Lightweight Intent Classifier Candidate Gate

The current LiteRT-LM evidence is safe but too slow and memory-heavy for a
phone-first fallback. The next reusable model path is therefore a small
classification model, not another text-generation LLM. GOFFY records that
shortlist in
`docs/architecture/local-intent-classifier-candidates.json` and verifies it with:

```bash
.venv/bin/python scripts/verify_local_intent_candidates.py
```

This registry is intentionally conservative. It keeps the zero-dependency micro
fallback as the default baseline, selects TensorFlow Lite Task Text
`NLClassifier` as the first prototype candidate, keeps MediaPipe Text Classifier
as a pinned-version research backup, treats fastText as prior art only, and
marks Granite 350M as rejected for production phone use based on physical Moto
evidence. Prototype candidates must stay out of default `debug` and `release`
builds, remain observe-only, use pinned dependencies, fit an 8 MiB model budget,
add at most 2 MiB to any future default APK, finish single inferences within 250
ms, stay under 16 MiB idle PSS, pass routing-quality gates, and collect physical
Moto evidence before any production enablement claim.

`scripts/verify_all.py` runs this gate before package build. This prevents a
future dependency or model candidate from being documented as "selected" while
silently bypassing license, dependency pinning, APK budget, latency, memory,
audit, or non-authoritative-execution requirements.

TensorFlow Lite Task Text now has an optional dependency compatibility probe:

```bash
.venv/bin/python scripts/verify_tflite_task_text_android_dependency.py --mode metadata
.venv/bin/python scripts/verify_tflite_task_text_android_dependency.py --mode resolve
.venv/bin/python scripts/verify_tflite_task_text_android_dependency.py --mode build
```

Latest dependency evidence, checked on 2026-07-22:

- Coordinate: `org.tensorflow:tensorflow-lite-task-text:0.4.4`
- Maven Central latest/release: `0.4.4`
- Local toolchain: Java 17 and Gradle 9.4.1
- `--mode metadata`: passed
- `--mode resolve`: passed in an isolated Android project
- `--mode build`: passed in an isolated Android debug APK project
- Repo scan: no dynamic TensorFlow Lite Task Text versions and no Gradle usage
  outside the allowed `modelDebugImplementation` probe scope

The isolated build packages native `libtask_text_jni.so`, so any future GOFFY
runtime code must remain in `modelDebug` until APK delta, startup behavior, idle
PSS, and physical Moto inference latency are measured. The next accepted gate is
not dependency compatibility; it is a modelDebug-only tiny classifier benchmark
whose output still enters GOFFY only as an
observe-only routing hint.

GOFFY now has the first `modelDebug` Task Text runtime bridge and benchmark
harness for that next gate. The bridge lives only in the `modelDebug` source set,
accepts only app-owned `.tflite` models smaller than 8 MiB, maps only `PHONE`,
`MAC`, and `CLOUD` labels into `LocalModelIntentObservation`, and marks every
result as non-authoritative. The instrumentation test lives in
`androidTestModelDebug`, and the boundary unit tests live in `testModelDebug`, so
normal GOFFY LITE `debug`, `debugAndroidTest`, and `release` APKs do not compile
or package the classifier runtime. The `modelDebug` manifest also strips Task
Text transitive `READ_EXTERNAL_STORAGE`, `READ_PHONE_STATE`, and
`WRITE_EXTERNAL_STORAGE` permissions; if those return, the merged-manifest
security scan fails.

Compile the variant-scoped harness locally:

```bash
android/gradlew -p android -Pgoffy.testBuildType=modelDebug \
  :app:testModelDebugUnitTest \
  --tests dev.goffy.os.localmodel.TfliteTaskTextIntentClassifierTest \
  :app:assembleModelDebug :app:assembleModelDebugAndroidTest --no-daemon
```

Plan a physical Moto benchmark without mutating the phone:

```bash
.venv/bin/python scripts/run_moto_g_tflite_task_text_benchmark.py \
  --model /path/to/tiny-router.tflite
```

Run it only after selecting a tiny metadata-backed classifier model and approving
APK install/model push on the connected Moto:

```bash
.venv/bin/python scripts/run_moto_g_tflite_task_text_benchmark.py \
  --execute \
  --confirm-device-mutation \
  --model /path/to/tiny-router.tflite \
  --command "read the text in front of the camera" \
  --example-id phone_ocr_009
```

Run the full `eval` corpus as one bounded suite after the same model is ready:

```bash
.venv/bin/python scripts/run_moto_g_tflite_task_text_eval_suite.py \
  --execute \
  --confirm-device-mutation \
  --model /path/to/tiny-router.tflite
```

The suite reuses the single-command benchmark validators while keeping phone
mutation bounded: it builds once, verifies the Moto target once, installs the
modelDebug APKs once, pushes the `.tflite` once, then loops only over
instrumentation, artifact pull, and JSON verification for each `eval` example.
It passes the corpus `exampleId` into Android instrumentation, copies the
`.tflite` model into the evidence tree, writes `routing-quality-evidence.json`,
and runs the routing-quality verifier automatically. Execute mode refuses a
non-empty output directory to avoid binding stale benchmark JSON into new
evidence. Without `--execute`, it prints the planned setup and per-example run
list without installing APKs or pushing the model.

The benchmark JSON gate requires a `PASS`, at least one category, inference
timing, a terminal `Candidate` or `Rejected` observation, and
`nonAuthoritative=true`. It does not accept the classifier for production by
itself; the next missing evidence is a physical Moto run plus routing-quality,
idle-memory, and APK-delta review.

The seed local intent-router corpus lives at
`docs/architecture/local-intent-router-corpus.json`. It covers PHONE, MAC, CLOUD,
and UNKNOWN labels with separate `train` and `eval` splits, keeps blocked or
ambiguous requests in UNKNOWN, and is verified as a normal repo gate:

```bash
.venv/bin/python scripts/verify_local_intent_router_corpus.py
```

This corpus is not a model asset and is not packaged into Android builds. It is
the reproducible contract for training or selecting a tiny Task Text-compatible
`.tflite` router. The local Python environment intentionally does not require
TensorFlow, Model Maker, or TFLite Support in the standard dev install; those
remain optional export-time tools because Google documents Model Maker as the
path for average-word-vector text classifiers and Task Library integration, but
those packages are too heavy for GOFFY's normal verifier.

Create the isolated training package from the verified corpus:

```bash
.venv/bin/python scripts/create_tflite_task_text_training_package.py
```

The package writes `train.csv` and `dev.csv` with the Model Maker
`sentence,label` columns, `labels.txt`, a source-policy manifest with file
hashes, and a generated `train_with_model_maker.py` helper. The helper verifies
the manifest hashes for `train.csv`, `dev.csv`, and `labels.txt` before
training, defaults export output under the generated package directory, and
rejects non-empty export directories to avoid stale model artifacts. It follows
the official TensorFlow Lite Model Maker `average_word_vec` path because it is
the documented small text-classifier architecture for `NLClassifier` integration
and is listed as smaller than 1 MB before GOFFY's own physical-device evidence.
Run that helper only in an isolated ML environment or Colab; do not add
TensorFlow, Model Maker, or generated `.tflite` files to the normal GOFFY repo
environment. The generated README pins `tflite-model-maker==0.4.3` and uses a
disposable Python 3.10 environment because the normal GOFFY verifier runs on
Python 3.12 and intentionally does not resolve the Model Maker dependency graph.

Verify the generated package and local training environment before attempting
the export:

```bash
.venv/bin/python scripts/verify_tflite_task_text_training_environment.py \
  --package-dir .goffy-validation/tflite-task-text-training-package/<timestamp>
```

For an isolated pip dry-run compatibility check, add `--check-pip-resolve
--python /path/to/python3.10`. The preflight verifies the package manifest and
file hashes, rejects unsupported Python versions, reports Docker fallback
availability, and keeps pip resolution optional so normal GOFFY verification
does not depend on external package indexes. On this Apple Silicon
Mac, Python 3.11 failed to resolve `tflite-model-maker==0.4.3` because
`tflite-support>=0.4.2` did not have a matching wheel; Docker/Colima was also
unavailable due to a local Colima disk-lock error. That is tooling evidence, not
a model-quality decision.

The export path now has a bounded Docker runner contract:

```bash
.venv/bin/python scripts/run_tflite_task_text_model_maker_docker.py \
  --package-dir .goffy-validation/tflite-task-text-training-package/<timestamp> \
  --image ghcr.io/goffy/task-text-export@sha256:<audited-image-digest> \
  --image-audit-evidence /path/to/image-audit.json \
  --execute \
  --confirm-docker-run
```

The runner verifies the generated package first, checks Docker daemon
readiness, requires a digest-pinned audited image on `linux/amd64`, requires
image audit evidence with zero critical/high/medium findings before execution,
mounts the package read-only, mounts only the selected export directory
writable, disables container networking, drops capabilities, rejects non-empty
export directories, and verifies that `model.tflite` matches the generated
`goffy-training-report.json`. It does not run live `apt-get` or `pip install`
and does not add TensorFlow, Model Maker, or a model asset to the normal
repository environment. The audited runner defaults to 20 training epochs, the
same default as the generated helper, instead of reproducing the failed
one-epoch baseline. The `goffy.tflite-task-text-model-maker-docker.v1` report is
additive-compatible: consumers should require known safety fields and ignore
unknown fields so future non-breaking metadata can be added without weakening
execution gates.

The minimum image audit evidence schema is:

```json
{
  "schema_version": "goffy.tflite-task-text-export-image-audit.v1",
  "image": "ghcr.io/goffy/task-text-export@sha256:<audited-image-digest>",
  "ok": true,
  "vulnerability_counts": {
    "critical": 0,
    "high": 0,
    "medium": 0
  }
}
```

Create that evidence from a mature scanner output rather than writing a custom
scanner. GOFFY accepts Trivy or Grype JSON and blocks evidence creation when any
critical, high, or medium finding is present. The scanner report must also
include canonical image identity metadata exactly matching the requested
`repo@sha256:` or `sha256:` digest; GOFFY does not trust caller-supplied image
names, tags, or arbitrary strings alone:

```bash
.venv/bin/python scripts/create_tflite_task_text_export_image_audit_evidence.py \
  --image ghcr.io/goffy/task-text-export@sha256:<audited-image-digest> \
  --scanner-report /path/to/trivy-or-grype.json \
  --output /path/to/image-audit.json \
  --write
```

Current local export evidence collected on 2026-07-22:

- Training package:
  `.goffy-validation/tflite-task-text-training-package/20260722T085558218908Z`
- Exported model:
  `.goffy-validation/tflite-task-text-training-package/20260722T085558218908Z/average_word_vec/model.tflite`
- SHA-256:
  `70ad883c6e7b84d8b029a74b6faa15baa9053041ba6e538c3ed61688ce0ae31c`
- Size: 13,171 bytes
- One-epoch Model Maker report: loss `1.3863162994384766`, accuracy `0.25`

Native macOS/arm64 remains unsuitable for this pinned Model Maker package
because `tflite-support>=0.4.2` does not resolve there. Python 3.10 Docker
binary-only resolution also failed because old `matplotlib<3.5.0` has no wheel
for that path. The first export was produced through an isolated Linux/amd64
Python 3.9 Docker run with legacy Model Maker/TensorFlow pins, then security
review flagged that live dependency installation and `tensorflow==2.8.4` are not
acceptable as repeatable GOFFY tooling. The committed runner therefore blocks
execution until an audited immutable export image exists.

Physical Moto G eval-suite evidence collected on 2026-07-22 is stored under
`.goffy-validation/tflite-task-text-eval-suite/20260722T095857689565Z`. The
runner built and installed the `modelDebug` classifier APKs, pushed the model to
app-owned storage, and collected all 16 corpus eval artifacts. The model loaded
on-device and sample inference stayed small, with `phone_ocr_009` reporting
54 ms init and 9 ms inference. Routing quality is still blocked: route accuracy
was `0.000`, required route examples did not produce accepted PHONE/MAC/CLOUD
candidates at the configured threshold, and UNKNOWN rejection was `1.000`.
Therefore the generated Task Text model remains benchmark evidence only and is
not enabled for production routing.

After collecting physical Moto benchmark JSON artifacts for the `eval` split,
create an evidence manifest with schema
`goffy.tflite-task-text-routing-quality-evidence.v1`:

```json
{
  "schema_version": "goffy.tflite-task-text-routing-quality-evidence.v1",
  "model_file": "models/tiny-router.tflite",
  "model_sha256": "<lowercase-sha256>",
  "model_bytes": 4096,
  "results": [
    {
      "example_id": "phone_ocr_009",
      "artifact": "results/phone_ocr_009.json"
    }
  ]
}
```

Then run the routing-quality gate:

```bash
.venv/bin/python scripts/verify_tflite_task_text_routing_quality.py \
  /path/to/routing-quality-evidence.json
```

The gate requires every `eval` example to have a benchmark artifact, route
examples to produce the expected PHONE/MAC/CLOUD candidate at confidence 0.70 or
higher, UNKNOWN examples to be rejected, every result to be non-authoritative,
and each inference to stay within the 250 ms Moto budget. The verifier hashes
the `model_file`, checks its size against the 8 MiB limit, requires every
artifact to embed matching `modelSha256`/`modelBytes`, and binds each artifact to
the corpus row with `exampleId` plus `commandSha256` so benchmark output cannot
be replayed across examples or attributed to a different model.

## Reuse-First Scan

Checked on 2026-07-20 and refreshed on 2026-07-22:

- LiteRT-LM: Apache-2.0, current Google AI Edge path for Android/Kotlin local
  LLMs. Preferred runtime candidate after benchmarking because it is the current
  maintained Google path and has Android/Kotlin API coverage.
- TensorFlow Lite / LiteRT text classification examples and Task Library:
  Apache-2.0 prior art for on-device text classification. Not imported for the
  micro fallback because this slice needs no model asset, training pipeline, or
  added default runtime dependency.
- TensorFlow Lite Model Maker text classification: Apache-2.0 official
  export-time path for average-word-vector text classifiers with metadata for
  Task Library `NLClassifier`. Reused as a generated training package only; not
  added to the normal GOFFY Python environment because its dependency graph is
  heavy and the Moto app must stay model-free by default.
- fastText: MIT, mature lightweight text-classification prior art. Not imported
  into Android because the repository is archived/read-only, would add native
  integration surface, and still requires a trained model artifact.
- SentencePiece: Apache-2.0 tokenizer prior art. Not imported because it is a
  tokenizer rather than a complete intent classifier and would add native
  dependency surface before a trained local classifier is justified.
- Android Preferences DataStore and Compose settings libraries: not added for
  this slice because the runtime setting state is one non-sensitive app-private
  boolean and adding a new default dependency would increase GOFFY LITE footprint.
  The implementation keeps storage in the ViewModel/data layer and uses Android's
  built-in private preferences with commit/read-back verification.
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
- https://developers.google.com/edge/litert/libraries/modify/text_classification
- https://developers.google.com/edge/mediapipe/solutions/genai/llm_inference/android
- https://github.com/google-ai-edge/LiteRT-LM
- https://github.com/tensorflow/examples/blob/master/lite/examples/text_classification/android/README.md
- https://github.com/tensorflow/tflite-support
- https://central.sonatype.com/artifact/org.tensorflow/tensorflow-lite-task-text
- https://github.com/facebookresearch/fastText
- https://fasttext.cc/
- https://github.com/google/sentencepiece
- https://github.com/ggml-org/llama.cpp
- https://developer.android.com/topic/libraries/architecture/datastore
- https://developer.android.com/training/data-storage/shared-preferences
- https://github.com/alorma/Compose-Settings
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
behavior, and production LiteRT-LM activation still belong to future runtime
integration work. Label-quality checks are implemented in the deterministic
routing quality gate above; `modelDebug` can call the provider for observe-only
unsupported-command timeline entries, but the default gate is disabled and no
production LiteRT-LM provider is packaged.

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

Qwen3 `modelDebug` observe-only unsupported-command smoke result:

- Artifact:
  `.goffy-validation/modeldebug-observation-smoke/20260720T212836Z/modeldebug-observation-report.json`
- Command:
  `open settings`
- Model:
  `qwen3_0_6b_mixed_int4.litertlm`
- SHA-256:
  `b1baab462f6be49d70eada79d715c2c52cd9ece0cad00bddf6a2c097d23498e9`
- Build:
  `:app:assembleModelDebug`
- Installed package:
  `dev.goffy.os.model`
- Observation elapsed:
  37,581 ms
- Battery snapshot:
  AC powered, 100 percent
- Memory snapshot after observation:
  `TOTAL PSS: 156192` KB, `TOTAL RSS: 153288` KB, `TOTAL SWAP PSS: 57815` KB
- Captured artifacts:
  `after-launch.xml`, `local-model-enabled.xml`,
  `modeldebug-observation-command.xml`, `final-ui.xml`, `battery-after.txt`,
  `meminfo-after.txt`, and `modeldebug-logcat.txt`
- Result:
  passed because the phone displayed a terminal `FAILED` timeline card stating
  no safe deterministic route was available and the model output exceeded the
  local routing output budget. No tool executed, no approval was granted, and
  deterministic routing remained authoritative.

This is acceptable for the developer-only observation path. It is not acceptable
for default GOFFY LITE enablement because 37.6 seconds is too slow for normal
phone-first routing; repeated-run and idle-cleanup acceptance are evaluated
separately below.

Granite 350M repeated `modelDebug` observe-only evidence:

- Artifacts:
  `.goffy-validation/modeldebug-observation-smoke/granite-run-3/modeldebug-observation-report.json`,
  `.goffy-validation/modeldebug-observation-smoke/granite-run-4/modeldebug-observation-report.json`,
  `.goffy-validation/modeldebug-observation-smoke/granite-run-5/modeldebug-observation-report.json`,
  and
  `.goffy-validation/modeldebug-observation-smoke/granite-idle-cleanup.json`
- Command:
  `open settings`
- Model:
  `granite-4.0-350m_q8_ekv1280.litertlm`
- SHA-256:
  `c8e9a29493f62b7c44461fb36980987c4c1454c75e95f57ba0539a8edc9dce76`
- Observation elapsed:
  21,745 ms; 22,608 ms; 22,741 ms
- Idle cleanup after 60 seconds:
  `observation_engine_scope_closed=true`,
  `provider_closed_after_idle=true`,
  `process_running_after_idle=true`, `TOTAL PSS: 174823` KB
- Result:
  all three runs safely displayed terminal `FAILED` timeline cards, did not
  execute a tool, and preserved deterministic routing authority. Production
  acceptance remains blocked because each run exceeds the 15-second observation
  budget and idle PSS exceeds the 64 MB process-remaining budget.
