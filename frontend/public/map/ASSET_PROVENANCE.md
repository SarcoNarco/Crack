# Crack Operations Floor Asset Provenance

- **Tool:** OpenAI built-in ImageGen
- **Date:** 2026-09-01
- **Purpose:** Static top-down pixel-art industrial security-lab floor background for the Crack frontend architecture-map presentation.
- **Originality:** Generated as an original Crack-specific composition. No commercial-game assets, characters, props, room layouts, logos, or readable text were copied or traced.
- **Reference handling:** The supplied screenshot informed only the broad top-down viewpoint and compact environmental density. It was not used as an edit target or reproduced.
- **Local-use provenance:** Created for local use in this Crack project and stored as `frontend/public/map/crack-operations-floor.png`; no external runtime asset URL, CDN, or third-party asset dependency is used.

## Agent concept sprites

- **Assets:** `frontend/public/map/agents/mapper.png`, `frontend/public/map/agents/authorization-tester.png`, `frontend/public/map/agents/verifier-a.png`, and `frontend/public/map/agents/verifier-b.png`.
- **Tool and date:** Generated with OpenAI built-in ImageGen on 2026-09-01, then mechanically cropped and packaged as transparent 32 × 32 PNG sprites with nearest-neighbor resampling.
- **Purpose:** Original static concept sprites for the fixed Mapper, Authorization Tester, Verifier A, and Verifier B roles in the Crack frontend architecture-map presentation. Labels remain rendered by the application; no text is embedded in these PNGs.
- **Creator attribution:** OpenAI ImageGen generated the source concepts from Crack-specific prompts; a Codex agent selected and packaged the final project assets for the Crack contributors.
- **Originality:** The sprites were generated as original Crack-specific characters. No commercial-game character, sprite, room, prop, logo, text, palette, or other third-party asset was copied, traced, or used as an edit target. The supplied commercial-game screenshot informed only the broad top-down pixel-art direction and was neither committed nor reproduced.
- **Repository-compatible rights:** Copyright 2026 Crack contributors. These generated project assets may be used, modified, and distributed with this repository under the repository's applicable project terms; no separate third-party asset license, runtime attribution requirement, or external asset dependency applies.

## Agent movement sprite sheets

- **Assets:** `frontend/public/map/agents/mapper-walk.png`, `frontend/public/map/agents/authorization-tester-walk.png`, `frontend/public/map/agents/verifier-a-walk.png`, and `frontend/public/map/agents/verifier-b-walk.png`.
- **Tool and date:** Created on 2026-09-01 by mechanically deriving additional cardinal poses from the original ImageGen character concepts, then arranging them as transparent `256 × 32` PNG sheets with nearest-neighbor pixel handling.
- **Frame contract:** Eight fixed `32 × 32` frames in the order `down0`, `down1`, `right0`, `right1`, `up0`, `up1`, `left0`, `left1`. Labels remain application-rendered; no text is embedded in the sheets.
- **Purpose:** Finite, authored Sprint 24 dock, cardinal-walk, face, acknowledge, return, and reduced-motion presentation for the four fixed Crack roles. These assets contain no tool attack effects or audio.
- **Integrity:** SHA-256: Mapper `1ba75e8d6bb3a13c4be116cafaf771c590a635d461261a2edaf227227a031fbb`; Authorization Tester `9eb6281dd2ecefde23ed9cd3ac15107c32f1f5bb11610fe5996951932be88d60`; Verifier A `ef88bdb77c7b437a26983e3ea8ef404a7db8c115b77f6d977269708ecb0965d6`; Verifier B `bfe463c4f557f04d98e1bb9758ab030710cffef51416c7650439093a97b3779f`.
- **Originality and rights:** The same originality and repository-compatible rights statement above applies. No commercial-game character, sprite, animation, palette, or other third-party asset was copied, traced, or used as an edit target; no external runtime asset dependency applies.

## Event-tied audio cues

- **Assets:** `frontend/public/map/audio/footsteps.wav`, `scan.wav`, `probe.wav`, `pickaxe.wav`, `beam.wav`, `consensus.wav`, and `failure.wav`.
- **Tool and date:** Generated locally on 2026-09-02 by the deterministic repository script `frontend/scripts/generate-map-audio.mjs`; mono 16-bit PCM at 22,050 Hz, with fixed durations of 0.21–0.40 seconds.
- **Purpose:** Low-volume, single-channel feedback for user-started recorded presentation events. The cues are never selected by event-provided paths or URLs and are not used as security evidence.
- **Integrity:** SHA-256: Footsteps `6829b0eb14fa3c5b2be2c66bd5fef09e69d3cf20e6bec4e8f4722c19fd7c3bfe`; Scan `e589fa7ca5e6fbfb65e83facee3f275605ace116c75ff3a7428cf4ab0058b244`; Probe `1b0edd6c19fa0cf4546f65a17c3ea1b9a7fe331e0bdc5780662392acbb39a1dd`; Pickaxe `915e14700e223918ac2df580468975b5f678d3ed6445f5b4c2ba141f07b76d91`; Beam `e42e19145c0b9e8e8e4175a6bcfb037eb314197932a6fd1e7272b9436d0fb066`; Consensus `28960db98f8994adab8cafa9585dfc15b85936d444d8395cb14ecd3abcf6f9bd`; Failure `5aa373b88bcd5d1ac1c621d7b16eac4d28f80e2278044ed00103c9eedac08c88`.
- **Originality and rights:** The sounds are original deterministic synthesized waveforms created for Crack. They copy no commercial-game or third-party recording, require no runtime attribution, download, CDN, or external license, and may be used, modified, and distributed with this repository under its applicable project terms.
