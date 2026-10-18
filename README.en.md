# backroom · Endless Liminal Rooms (v2.0 · rebuilt on the 3dworld engine)

> Repo: <https://gitee.com/siwpan/backroom> ｜ License: MIT-0 (MIT No Attribution) — see [LICENSE](LICENSE)

A Backrooms-style **pseudo-infinite** first-person walk.
v1 was a pygame 2D raycaster demo (single 1349-line file, now archived in [`archive/`](archive/)).
**v2 is a full rebuild on the [3dworld](https://gitee.com/siwpan/3dworld) engine** — it keeps and
strengthens v1's core asset, the *pseudo-infinite chunk map*, and moves rendering to a real 3D PBR pipeline.

## v1 → v2

| | v1 (pygame raycaster) | v2 (3dworld engine) |
|---|---|---|
| Rendering | 2D raycasting (fake 3D) | True 3D PBR + IBL + SSAO/Bloom/ACES |
| Map | Chunked, but coupled to rendering/entities in one file | Standalone algorithm layer `backroom/mapgen.py` (stdlib only) |
| Collision | Hand-rolled point test | `world3d.engine.physics` per-axis resolution (wall sliding) |
| State | none | `world3d.engine.fsm.Machine` |
| Events | none | `world3d.engine.orchestration.Bus` declarative cascade |
| Materials | Flat colors | `world3d.engine.proctex` procedural PBR (zero external assets) |
| Walls | Per-cell casting | `world3d.engine.greedy_mesh` greedy batching |
| Audio | sounddevice, realtime | Procedural 3-layer bed, cached to WAV |
| Deps | pygame + numpy + sounddevice | **`3dworld` only** |

## Layout

```
backroom/
  mapgen.py   pseudo-infinite chunk map (stdlib only)
  kernel.py   player / levels / FSM / events / pathfinding / auto-pilot
  world.py    rendering (greedy batching + procedural materials + instanced lamps + streaming chunks)
  audio.py    procedural ambience (3 layers, WAV cached)
  app.py      entry assembly (EngineApp: HUD / perf panel / CLI)
tests/test_kernel.py   13 headless tests
archive/               v1 pygame raycaster (kept as-is)
```

## Run

```bash
pip install 3dworld          # the only dependency
python main.py               # normal run
python main.py auto          # auto-pilot (unattended / recording)
python main.py seed1234      # fixed seed (same seed = same infinite map)
python main.py --smoke       # smoke test, auto-close
python main.py --shot        # capture 3 verification screenshots to docs/
python main.py --bench 5     # 5s benchmark
```

Controls: `WASD` move　drag to look　`SHIFT` sprint　`A` auto-pilot　`T` descend a level　
`R` new map　`SPACE` pause　`F1` HUD　`F2` perf　`ESC` quit

## Gameplay (map only — no entities)

- **Pseudo-infinite**: the world extends in 24×24-cell chunks; generated on demand, unloaded out of view.
- **Descending levels**: the farther from origin, the deeper the level (Level 0 Hall → 4 Depths),
  with progressively darker palette, shorter fog distance and sparser lamps.
- **noclip**: stepping into an anomaly tile triggers the cascade —
  *found → noclip → descend → level change → lights flicker → landed*.
- **Lamp flicker**: fluorescent lights stutter for 1.6s on every level change.

## Tests

```bash
python -m tests.test_kernel    # 13 headless tests
```

Contracts pinned: same seed ⇒ same map; all walkable cells in a chunk are mutually reachable;
cross-chunk queries are continuous; collision never tunnels through walls; the anomaly cascade runs
end to end; noclip always displaces the player; auto-pilot must leave the spawn chunk within 150s;
trajectories are deterministic (required for reproducible recordings).

## Lineage

- v1: from the krieger-clone raycasting experiments (archived in `archive/`).
- v2: driven by [3dworld](https://gitee.com/siwpan/3dworld) (siwpan) — its `liminall` kernel proved
  that "Backrooms subject + 3dworld layering" works; this repo formally ports the differentiating
  asset, the *pseudo-infinite map*, onto that engine.

## License

MIT-0 · Copyright (c) 2026 siwpan
