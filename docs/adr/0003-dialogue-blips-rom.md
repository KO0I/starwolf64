# ADR 0003: Optional dialogue-blip ROMs

Status: Implemented for verified US 1.1 inputs. Physical hardware validation remains pending.
Date: 2026-11-12.

The user requested a separate mod that replaces recorded dialogue with reusable clips, supports both original Star Fox and Starwolf64, and reclaims ROM space. Full narration, music, and non-vocal sound effects remain protected. Development stays in the isolated `mods/dialogue-blips` worktree.

The original resource archive and audio export remain unchanged. This decision permits the optional cartridge artifact to remove speech payloads after every corresponding voice instrument has been replaced. It is a scoped exception to the separately addressable original-recording policy in [ADR 0002](0002-audio-importer.md). The general importer and original archive retain their preservation policy.

Use one resolved voice catalog, an explicit roster, and shared encoded clip banks for the native and ROM writers. Each canonical voice receives sixteen clips. Unattributed recordings receive their own source-derived banks. No guessed character assignment or fallback spoken line fills a gap.

Keep original voice programs and completion timing. A reusable looped train supplies the audio for each instrument. Expert Fox events select a separate Vitzy instrument through an added sequence bank; logical voice IDs remain unchanged. Full Starwolf narration uses one complete reversed recording with a one-shot note. Existing narration suffix aliases remain available. Native narration cleanup clears only its own logical voice, including a pending start, so it preserves a replacement line queued during a scene change.

Repack only the voice sample banks and their soundfont metadata. Preserve radio-effect slots 124 through 126. Verify the original and generated resource graphs, retained audio bytes, encoded samples, loop states, sequence references, and cartridge checksums before publishing. Package requested targets together under an immutable release directory and atomically update the release pointer. Report physical voice-bank savings separately from the padded 16 MiB ROM and native base-archive size.

The implementation and verification commands are documented in [Dialogue blips](../dialogue-blips.md).
