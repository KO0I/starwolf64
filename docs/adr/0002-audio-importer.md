# ADR 0002: Audio import for native and browser builds

Status: Accepted design. Replacement import has not started under this decision.
Date: 2026-11-09
Approval: The user accepted Q1 through Q5 and Q6 through Q10 in two interview rounds, then identified upstream Starship as the primary reuse target.
Related terms: [Project glossary](../../GLOSSARY.md).

## Context

Starwolf64 needs a repeatable way to replace voice lines and gameplay sound effects in native Starship and the browser game.
The first proof is dialogue message 2050 playing a recognizable replacement in both builds, at the intended pitch and completion time.

Upstream HarbourMasters/Starship is the primary reuse target for the importer.
Starwolf64 is its first integration and the browser ROM writer is an additional consumer.
Reuse by the original-N64 decompilation project is not a required initial deliverable.

The original audio has been exported before replacement work.
The current export contains 1,280 WAV previews, 4,434 original audio resources, and 46 distinct sequences covering 66 sequence IDs.
The inventory preserves sample data, predictor books, loops, instrument tuning, and soundfont relationships.
It does not yet map dialogue and sound IDs to their final samples or establish safe recording durations.

The existing builder writes a native mod archive and a modified ROM.
The browser exporter packages a delta against the user's original US v1.1 ROM.
The current delta builder requires a 16 MiB target ROM.

Original Star Fox voices must remain separately addressable alongside replacement voices.
This extends the original-resource preservation direction in [ADR 0001](0001-lan-versus-multiplayer.md).
That earlier decision did not settle voice selection.

## Decision

Use a command-line importer driven by authored WAV recordings and a readable replacement manifest.
Reuse the existing audio catalog for browsing.
Build matching native and browser artifacts from the same conversion results.

The accepted behavior is:

| Decision | Behavior |
| --- | --- |
| Q1: Targets and publication | In the Starwolf64 workflow, produce native and browser outputs together. Validate the complete pair before publication. If either target fails, preserve the previously published pair. |
| Q2: Initial scope | Support voice lines and sound effects. Full music-track replacement is later work. |
| Q3: Authoring | Use WAV files, a readable manifest, and a command-line build. Reuse the listening catalog. A dedicated editor is later work. |
| Q4: Original voices | Preserve original and replacement voice resources under stable, separately addressable identities. A replacement lookup must not make the original unreachable. |
| Q5: Scene timing | Preserve existing scene schedules. Reject a recording that exceeds its reviewed playback window. Do not extend scenes, truncate speech, or time-stretch it to force a fit. |
| Q6: Replacement scope | Apply a replacement to every occurrence of its logical dialogue or sound ID within the selected audio set. Different recordings for individual scenes are later work. |
| Q7: Conversion | Convert input WAVs to mono 32 kHz PCM and encode the same ADPCM audio for both builds. Automatically downmix and resample. Preserve intended speed and pitch. Do not apply loudness normalization. |
| Q8: ROM growth | Allow the target ROM to grow beyond 16 MiB when needed, subject to a tested size limit. Report required space and reject an unsupported size. |
| Q9: Interruptions | Keep existing radio priority, gameplay interruption, and scene-transition behavior. Passing a duration check does not guarantee uninterrupted playback. |
| Q10: Loops | Require explicit start and end markers for looping replacements. Do not guess markers or copy original frame positions onto a different recording. Voice lines and one-shot effects need no loop markers. |

### Make the tooling reusable by upstream Starship

Separate reusable audio conversion and native asset writing from Starwolf64 policy.
An upstream Starship caller must be able to produce native audio assets without building a browser ROM or importing Wolf-specific modules.
Starwolf64 orchestration retains the accepted requirement to validate and publish its native and browser outputs together.

Use these ownership boundaries:

| Owner | Responsibility |
| --- | --- |
| Shared audio tooling | WAV conversion, ADPCM encoding, sample and predictor-book representations, explicit loop conversion, and reusable validation. |
| SF64 catalog and revision data | Logical voice and sound mappings, source-asset identities, tuning, and reviewed timing evidence for each supported revision. |
| Native writer and Starship runtime | Native archive representation and any game-side lookup or completion behavior required to use replacements while preserving originals. |
| Browser ROM writer | ROM bank layout, relocation, pointer updates, capacity checks, and the browser-specific output representation. |
| Starwolf64 integration | Wolf dialogue edits, the policy that mutes changed text until a matching recording exists, selection of the replacement audio set, and paired artifact publication. |

Torch is a candidate home for shared conversion and sample-format work.
It is already a HarbourMasters submodule with NAudio and SF64 factories, and Starship uses its executable for extraction and archive packing.
The final code placement must follow the interfaces found during implementation.
This decision does not claim upstream maintainer approval or authorize submitting changes.

Keep shared modules independent of `build_wolfen.py`, `wolf_dialogue.py`, Wolf dialogue text, and this mod's deployment paths.
Game-specific mapping belongs in SF64 data or adapters rather than the codec.
Select ROM layouts using identified revisions instead of embedding US v1.1 offsets in shared conversion code.
The first proof remains US v1.1. Existing US v1.0 manifests are evidence for a revision boundary, not proof that importing that revision works.

The accepted mono 32 kHz ADPCM settings remain the Starwolf64 workflow's conversion policy.
Represent conversion settings explicitly so reuse does not force every upstream consumer to adopt that policy.
Both Starwolf64 outputs still use the same settings and conversion result.

Use synthetic audio fixtures for reusable conversion and loop tests.
Keep those tests runnable without the Starwolf64 builder or a browser deployment.
Game-specific playback proofs still require the appropriate local source assets and runtime.

### Identify replacements by logical sound

A replacement entry identifies its audio set, target kind, logical ID, and recording.
The authored manifest is separate from the generated export manifest.
Raw archive offsets and sample paths remain catalog data rather than the main authoring identity.

A dialogue message ID can appear in several scenes or gameplay paths.
A global replacement must cover those uses within the selected audio set.
Shared sample storage must not cause a replacement for one logical ID to change another ID silently.
The writers must preserve or separate those references as needed.

Preserving original voices requires independent lookup identities while replacements are active.
This decision does not add a crew selector, per-player audio selection, or network replication.
Those features can later use the preserved sets.

### Convert once and write both representations

The converted ADPCM payload, predictor book, and logical loop information are shared conversion results.
Each writer still owns its target's headers, byte order, addresses, tuning, endpoint, and bank layout.
Matching encoded bytes alone do not establish matching playback.

Keep source recordings and the original resource archive unchanged.
Padding needed for codec frames must not extend the declared audible endpoint.

Explicit loop markers refer to the replacement recording.
Conversion must map markers through resampling and generate valid predictor state for the resulting loop.
Reject markers outside the recording or a loop that cannot be represented correctly.

### Establish timing before accepting a target

An exported WAV preview does not prove a voice line's in-game duration.
Sequence note pitch, instrument tuning, note duration, gate time, and completion signaling can change playback.

For each supported target, record the verified sequence-to-sample mapping and fixed timing constraints.
For a logical ID with several supported uses, enforce the shortest applicable fixed playback window.
Retain evidence for that limit, including the relevant call sites and actor-script uses.

Normal event-driven interruptions remain valid and do not become a promise of a minimum uninterrupted duration.
Reject a requested target when its mapping or required timing constraints have not been established.
Report the target and the missing evidence rather than guessing a sample or duration.

### Keep muting and publication consistent

The following publication and edited-dialogue rules belong to Starwolf64 orchestration.
They are not prerequisites for using the shared tooling or native writer upstream.

A changed dialogue line stays muted until a matching replacement has been packaged and verified for both targets.
Unedited lines without an override continue to use original audio.
An invalid declared replacement fails the paired build.

Prepare the native archive, modified browser ROM, and associated patch and cache metadata as one matching result.
Publish that result only after both target validations succeed.
Failure recovery must not expose one new target alongside the previous version of the other target.

Repeated builds from the same source assets, recordings, manifest, conversion settings, and encoder version must produce reproducible artifacts.

### Bound ROM and runtime resource use

Permission to grow beyond 16 MiB does not establish a safe larger maximum.
Determine and enforce a tested target-ROM limit.
Update target-size assumptions in the builder, delta exporter, and browser validation together.
Keep the required base-ROM identity unchanged.

Also validate soundfont and bank limits, audio heap use, and simultaneous playback.
Mono 32 kHz replacements can consume more ROM and runtime resources than the original low-rate voice samples.
Do not silently lower the agreed conversion rate to satisfy those limits.

## First proof: message 2050

Trace message 2050 from the voice sequence to its sample, effective pitch, note lifetime, and completion flag.
Establish its recording limit from those facts and its fixed Corneria scene schedule.
The countdown value at its trigger is evidence to investigate, not an assumed recording allowance.

Import a short, recognizable test recording for message 2050 in the replacement audio set.
Verify the following behavior in native Starship and the browser game:

- The intended replacement plays at the correct pitch and speed.
- The recording completes within its reviewed playback window and signals completion correctly.
- Existing interruption and scene-transition behavior remains intact.
- The original recording remains independently addressable.
- Other logical IDs and sounds retain their original content.
- The line is unmuted only in a successfully validated paired result.
- A failed build preserves the previous published artifacts.
- Repeated builds reproduce the same output bytes.

After that proof, expand the verified target catalog and support batch voice and sound-effect imports.
The first proof does not establish that every exported sample has a verified logical-ID mapping.

## Source evidence

These observations refer to the working tree based on commit `d404e14d`.
They describe current behavior, not an implemented importer.

| Source | Observation |
| --- | --- |
| [Audio exporter](../../tools/export_audio.py) | Exports the original audio resources, WAV previews, metadata, and sequences. Preview sample rates use instrument tuning and a heuristic for samples with multiple tunings. |
| [Audio catalog](../../tools/audio_catalog.py) | Provides local sample playback, search, category filtering, and sequence downloads. |
| [Voice playback](../../src/audio/audio_general.c) | `Audio_UpdateVoice` splits a message ID into bank and voice values for the voice sequence. `Audio_GetCurrentVoice` reads sequence completion state. |
| [Radio behavior](../../src/engine/fox_radio.c) | Radio progression can wait for voice completion. Existing priority rules allow messages to replace active dialogue. |
| [Actor scripts](../../src/engine/fox_enmy2.c) | Scripts can trigger numeric message IDs. Direct C call-site searches alone do not cover every use. |
| [Sequence player](../../src/audio/audio_seqplayer.c) | Sequence pitch, note duration, and gate time affect actual playback. |
| [Corneria scene](../../src/overlays/ovl_i1/fox_co.c) | Message 2050 starts at countdown 200. Later countdown events and the transition at zero do not wait for the recording automatically. |
| [Dialogue edits](../../tools/wolf_dialogue.py) | Changed dialogue currently suppresses the original recording. Its muting logic must account for verified replacement availability. |
| [Asset builder](../../tools/build_wolfen.py) | Builds native resources and the modified browser ROM. Current writes do not establish the proposed paired publication behavior. |
| [Delta exporter](../../tools/rom_patch.py) and [browser patch loader](../../browser/rom-patch.mjs) | Reconstruct and verify the browser ROM. The delta exporter currently requires a 16 MiB target. |
| [Torch submodule](../../.gitmodules), [Torch build](../../tools/Torch/CMakeLists.txt), and [Starship build](../../CMakeLists.txt) | Torch contains shared NAudio and SF64 conversion factories. Starship links Torch and invokes its standalone executable for extraction and packing. |
| [Sample writer](../../tools/Torch/src/factories/naudio/v1/SampleFactory.cpp) and [sample loader](../../src/port/resource/importers/audio/SampleFactory.cpp) | Define existing sample data, predictor-book, and loop resource representations. |

## Alternatives considered

A native-only importer would be smaller, but would postpone the agreed browser behavior and permit the two versions to diverge.

Keeping high-quality WAV playback in native Starship while using separate browser conversion would permit different audio quality.
The accepted initial design uses the same mono 32 kHz ADPCM conversion for predictable parity.

Replacing a sample resource globally is a convenient low-level operation.
It does not express the accepted logical-ID scope when sample data or sequence paths are shared.

Extending scenes or changing recording speed could accommodate longer speech.
The accepted design keeps scene schedules and asks the author to supply a recording that fits.

A graphical editor and full music-track importer would broaden the first release.
The existing catalog and manifest provide the approved initial authoring workflow.

## Remaining engineering unknowns

- The verified sample and sequence mapping for message 2050 and later supported dialogue and sound IDs.
- Effective pitch, note and gate changes needed to preserve recording duration and completion signaling.
- Encoder compatibility and audible behavior in both targets.
- Stable resource identities and lookup rules that preserve original and replacement sets together.
- Tested ROM, bank, heap, and simultaneous-playback limits.
- Correct loop-state generation after resampling.
- Paired artifact publication and recovery mechanics.

These unknowns require source tracing and executable proofs.
They do not reopen the accepted user choices.
Implementation remains a separate, explicitly authorized stage.
