# Separate dialogue blips mod implementation record

Status: Software implemented in the isolated worktree. Physical N64 hardware validation remains pending.
Date: 2026-11-12.
Worktree: `/home/amber/proj/Starship-dialogue-blips`.
Branch: `mods/dialogue-blips`.
Base commit: `12a36c5525c5f18d6667b8c94e1e5165e5b66eb0`.

The optional mod supports both original Star Fox 64 and Starwolf64. It replaces non-narration speech with reusable sixteen-clip banks and packages matching native and cartridge audio. Music, sound effects, training beeps, and full narration remain protected. Starwolf retains Krystal’s approved 7 kHz IMA-processed sound and the five approved crew banks.

The main worktree’s unrelated character and browser UI work remains separate. The inherited audio seed is recorded in [the workspace receipt](voice-blips-workspace.json). Source ROM, original archive, exported audio, and prepared Starwolf inputs remain unchanged. New artifacts live under this worktree’s `build/dialogue-blips/` directory.

The completed catalog resolves 725 speech events and all 725 populated speech instrument slots. It preserves 54 text entries with no recording, four control IDs, and seven narration dispatch aliases. Recorded dialogue has 724 ordinary text messages plus unused recording 20256. C callers, static briefing and title tables, and typed actor-script commands supply speaker evidence. Thirty-two recordings lack reliable names and use their own source audio. Four conflicting Andross audition assignments have explicit overrides, with raw evidence retained in the report.

The implementation stages produced these results:

1. Catalog and roster. One catalog and authored roster drive both writers. Every speech region has an observed note and explicit tuning. Missing or conflicting assignments fail the build.
2. Codec. Shared 4-bit N64 ADPCM uses a valid zero predictor book. The actual game decoder verifies the encoder and decoder byte for byte. All banks retain sixteen distinct decoded clips and pass quality checks.
3. Driver proof. The standalone ROM plays reusable trains through the original sequencer. Repeated logical-voice retriggers do not complete normally, so the final driver keeps original event timing and completion. Expert routing preserves current logical IDs and selects Vitzy only for Fox events.
4. Full banks. Both editions build complete rosters. Starwolf reuses approved crew clips, adds Expert Vitzy, and retains the full reversed narrator as a one-shot recording.
5. Packaging. Native resources and cartridge data share identical encoded samples. The ROM writer removes replaced speech payloads, repacks voice metadata, and preserves radio effects, music, and narration. The native runtime disables the legacy PCM player while the add-on is active.
6. Export. Both editions produce a native add-on, 16 MiB ROM, delta, catalog, mappings, and detailed report. Immutable result directories and an atomic pointer preserve the previous result on failure. Repeated complete builds reproduce identical outputs. Both deltas reconstruct the exact generated ROM through the existing browser patch loader.
7. Verification. Sixteen focused tests pass. Full native Starship compiles. Actual native-engine and standalone-ROM probes capture audible PCM, preserve logical IDs, and observe completion. Native volume checks cover audible and muted playback. The complete Starwolf narrator plays for about 62 seconds and completes. Both EmulatorJS cores, mupen64plus_next and parallel_n64, pass playback checks. Native narration start, pending cancellation, skip, replacement-line ownership, pause/resume, volume, real dialogue lookup, and legacy-mixer suppression pass. Runtime evidence is summarized in [the verification record](dialogue-blips-verification.json).

Measured free space inside the original voice-bank range is 2,768,560 bytes for original Star Fox and 1,674,752 bytes for Starwolf64. These are internal free-space figures. The padded ROM remains 16 MiB. The native add-on retains the separately installed original archive.

See [usage and verification](../dialogue-blips.md), [the scoped ROM preservation decision](../adr/0003-dialogue-blips-rom.md), and the local decision trail at `.audit/voice-blips-decisions.tsv`. Physical hardware remains an explicit separate validation task; it is not inferred from emulator success.

The Poteto principles shaped these implementation choices:

| Principle | Concrete choice |
| --- | --- |
| Foundational Thinking | Define encoded samples, logical endpoints, books, and loop state before either writer. |
| Model the Domain | Use one evidence-based catalog and explicit rosters for both casts. |
| Build the Lever | Generate every replacement through one CLI rather than editing individual recordings. |
| Type System Discipline | Validate immutable encoded samples and parse native activation metadata at its boundary. |
| Separate Before Serializing Shared State | Keep this worktree and generated outputs separate from ongoing source-worktree work. |
| Sequence Verifiable Units | Establish decoder and single-voice proofs before generating the complete roster. |
| Prove It Works | Capture actual native and emulator PCM and verify the packaged resource graphs. |
