# Local-inference landscape (surveyed 2026-10-27)

Lens: 2018 Intel Mini, 8 GB, CPU-only Ollama 0.32.1. Stars/activity
from the GitHub API, same day.

## Act on / try

- **llama.cpp discussion #19813** (ggml-org/llama.cpp, note: URL in the
  request had a `ggml-org.cpp` typo): "[Local AI] Optimization Beyond
  Hardware: 6th Gen Intel to RTX 50". Author ran 0.5B–1.5B stably on
  an LG Gram i7-6500U/8GB/iGPU ("hostile hardware"), and 7B at 0.53s
  TTFT / 28.87 tok/s on an RTX 5050 laptop (8GB VRAM). Closest public
  analogue to our Mini envelope. CORRECTION (round-2 sparring read the
  full thread): closed-source commercial promo ("Source Code: Still
  Private"), GPU-only benches; the one substantive reply (RevolutionAI)
  is Linux NUMA + CPU-governor + batch sweeps, mostly N/A to a
  single-socket macOS Mini. Downgraded to "skim the one reply" — only
  transferable item is micro-benchmarking ubatch.
- **incoai/splash** (C++, 1863 stars, pushed today, Apache-2.0): local
  engine for Apple silicon (M3+), DFlash2 speculative decoding,
  Metal kernels, OpenAI+Anthropic APIs, `splash claude/codex` agent
  wrappers, Unsloth GGUF incl. UD quants. Not for the Intel Mini —
  but the prime MacBook experiment, and it validates UD quants.
- **statefullm/lim** (C++, 4 stars, pushed Oct 22): terminal LLM
  controller on llama.cpp with NEVER-discarded KV-cache (O(input)
  per turn, +73% vs chatbot-mode at 222k ctx), /undo, fs tools.
  `make GGML_CUDA=off` CPU build exists. Candidate Mini experiment
  for persistent long agent sessions.
- **Starmorph 2026 guide** (blog.starmorph.com — request spelled
  "stormorpth", DNS-dead; found via search): Ollama 166k stars is
  the developer default, llama.cpp 98.6k the foundation, Q4_K_M the
  practical quant. Author runs M4 Pro Mac Mini + Ollama. Validates
  our stack; links a Mac Mini buying guide for local LLMs.

## Watch

- **local-inference-lab** (org, 181 followers, 22 repos, active):
  big-iron crowd — rtx6kpro wiki (1158 stars, 397B models on PCIe
  GPUs), llm-inference-bench (121 stars, Rich TUI decode bench),
  blackwell-llm-docker. Opposite scale; steal bench methodology only.
- **localinference** (org, Finland, 0 followers, 5 repos, quiet since
  March): Schema-aligned Transformer micro-models "that run locally
  anywhere". Mission-aligned, traction-zero. Watch.
- **TensorSharp** (zhongkaifu, .NET 10, trending #2 repo of day):
  GGUF engine for Win/Mac/Linux with CLI, browser chat,
  Ollama/OpenAI APIs, CUDA/Metal/Vulkan + managed C# CPU kernels,
  speculative decoding, agent skills. Immature vs Ollama, but the
  Metal path (MacBook) and CPU kernels (Mini?) make it the one
  alternative runtime to re-check in 6 months.
- **NVIDIA/flare-local-inference** (Python, 679 stars, pushed today):
  research-prototype server for SM120/SM121 (Blackwell/RTX50, DGX
  Spark); PyTorch-build to Rust-serve, explicit memory/state
  planning. NVIDIA-only, zero Mini use; design ethos matches ours.
- **Arc Pro B70** (32GB, $949): the 2026 budget inference GPU —
  llama.cpp SYCL ~1.7x faster than Vulkan on Mesa 25.x, 27B dense
  Q4–Q6 in 32GB, Ollama/LM Studio work (avoid the IPEX Ollama
  bundle: NaN bugs on Battlemage). No Mini story, but the obvious
  next hardware step if the lab outgrows CPU. See awesome-b70.
- **Exo** (42.7k stars, per Starmorph): distributed inference over
  Mac/Linux/mobile, MLX/tinygrad. Only path if we ever go multi-Mac
  (cf. 671B-across-8-Minis builds). Not now.

## Skip

- **intel/ipex-llm** (8844 stars, last push Jan 2026): ARCHIVED.
  Intel ended support, cites known security issues. Was the Intel
  XPU/CPU accel lib (Ollama + llama.cpp portable zips). Do not
  adopt; successor ideas live in vLLM-XPU / OpenVINO / LLM Scaler.
- **intel/intel-accel-for-llm** (C, 17 stars, pushed today): QAT/IAA/
  DSA hardware KV-cache DEFLATE compression for vLLM on Xeon
  servers (needs QAT drivers, IOMMU, TP setup). Datacenter-only.
- **intel/enterprise-inference** (Python, 8 stars, pushed today):
  k8s LLM serving (vLLM + OpenVINO Model Server + AI gateway,
  NUMA-aware Xeon). Datacenter-only.
- **canonical/gemma4-snap + deepseek-r1-snap** (Shell, 8 stars each):
  Ubuntu snap packaging for one-model inference. Linux-only;
  packaging precedent at best.

## Bottom line

Stay on Ollama (default endorsed everywhere, incl. B70 guides);
do not chase ipex-llm (dead); splash goes on the MacBook trial
list; lim goes on the Mini experiment list (with a RAM-ceiling flag);
discussion #19813 downgraded to "skim the one reply" (closed-source
promo, GPU benches, one Linux reply).
