# Rules for implementation agents

These rules apply to every task in this repository.

1. **Issue body is the source of truth.** The GitHub issue body is the requirement
   source of truth for the current task. Do not silently choose a different product
   requirement or reinterpret it.
2. **Do not broaden scope.** Implement exactly what the current issue asks. Do not
   pull in features "while you're there".
3. **Run tests before completion.** Run the relevant test suite (`pytest`) before
   declaring a task done.
4. **Preserve raw artifacts and provenance.** Raw downloaded media and raw model
   responses must never be overwritten or discarded. Every derived artifact carries
   provenance (see `docs/architecture.md`).
5. **No unrequested infrastructure.** No queues, orchestration frameworks, databases,
   cloud services, or agent scaffolding unless the current issue explicitly requires
   them.
6. **Old repo is reference-only.** `matpeltier/tiktok-factory` may be consulted for
   product learnings only. Never merge or copy its codebase, history, runtime state,
   or test artifacts into this repository.
7. **Fail loudly.** No silent fallbacks. Failures must surface explicitly.
8. **One micro-niche.** All dataset experiments stay inside the single defined
   micro-niche until a roadmap issue changes that.
