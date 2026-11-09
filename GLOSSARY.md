# Project glossary

These terms record the approved project designs. A definition does not establish that a feature is implemented.
The decisions are recorded in [Player-hosted LAN versus multiplayer](docs/adr/0001-lan-versus-multiplayer.md)
and [Audio import for native and browser builds](docs/adr/0002-audio-importer.md).

## LAN multiplayer

| Term | Meaning |
| --- | --- |
| Network session | A host and its connected guests, including the lobby and matches. The session ends when the host leaves or disconnects. |
| Match | One run of a versus stage with its scoring rules. The first playable network match uses Corneria and Points. A guest timing out does not pause or end the match for remaining players. |
| Host | The PC that runs the authoritative shared simulation. Its owner also plays, occupies one player slot, and sees a local view. |
| Guest | A player connected to the host from another PC. The guest sends controls and ship choices, predicts local movement, and receives the host's state updates. |
| Player slot | A participant's identity in the match. The Corneria proof supports two to four slots, followed by the eight-slot four-on-four target. New player-state interfaces must accommodate eight from the start. A slot is independent of the local controller and number of rendered views. |
| Local view | The full-screen camera and HUD for the player on one PC. Each PC shows one local view while other participants remain in the shared world. |
| Versus stage | An existing multiplayer arena and its associated gameplay content. The source defines Corneria, Katina, and Sector Z. Existing menu rules restrict the available stage and match-type combinations. |
| Match type | The rules that determine scoring and victory. The existing source defines Points, Battle, and Time. Points is the first network milestone. |
| Vehicle form | A category of player behavior represented by the existing `PlayerForm` enum. Initial network play uses the aircraft behavior of `FORM_ARWING`. Tanks and on-foot play are later work. |
| Crew | A pilot's roster affiliation, separate from player slot, vehicle form, ship variant, and multiplayer team. PvP permits any pilot and available aircraft. Co-op uses one crew and crew-appropriate ships, including pilot-specific assignments. Katt is Star Fox. Vitzy the axolotl and Pigma are Star Wolf. |
| Pilot identity | A stable selection key independent of the mod's existing character slots. The selected pilot stays fixed for the match. Required pilots include Fox, Falco, Slippy, Peppy, Pigma, Katt, and Vitzy. Proposed original-pilot keys are `fox_original`, `falco_original`, `slippy_original`, and `peppy_original`. |
| Pilot appearance | Per-player presentation separate from pilot identity and vehicle choice. Duplicate pilots are allowed. Every additional selection of the same pilot gets a distinct portrait, ship-marker, and laser hue, consistent across peers and respawns. |
| Friendly fire | A selectable allied-damage rule, off by default. Lock-on always ignores teammates. When enabled, killing a teammate subtracts one point from the responsible player's team score. |
| Pilot derivation | A new pilot based on another pilot's assets. Vitzy is a Star Wolf axolotl derived from Katt, with distinct identity and appearance resources. Shared source assets and the original Katt must remain unchanged. |
| Multiplayer team | A group of four human participants in the expanded respawning team-points mode. Human opponent kills contribute to a shared score. Additional AI enemies are separate from these human slots. Team membership is distinct from campaign `TEAM_ID_*` NPC ally identities and does not restrict competitive pilot or ship selection. |
| AI enemy | A host-simulated combatant forming a third faction hostile to both human teams. AI enemies are additional to the eight human slots. AI kills do not advance the victory score. Population and spawn budgets still need validation. |
| Vitzy fighter | A private magenta-and-pink appearance derived from Bill's fighter, with proposed key `vitzy_fighter`. Vitzy uses it in Star Wolf co-op as an exception to the usual Wolfen assignment. Bill's original assets stay intact. PvP retains free pilot and ship choice. |
| Venom showdown arena | The planned new versus entry based on the all-range Venom 2 showdown layout. It has its own multiplayer setup, separate from campaign NPC events and progression. |
| Character assets | The models, textures, skeletons, animations, portraits, and other presentation resources needed to show a selected character. Original Star Fox resources remain available alongside Star Wolf replacements. |
| Ship variant | A selectable aircraft appearance under shared handling, weapons, health, and collision rules. The requested variants are Arwing, Wolfen, and Vitzy's magenta-and-pink Bill-derived fighter. Models and base palettes differ. Duplicate-pilot hue assignments can alter displayed laser color. Co-op uses crew-appropriate pilot assignments. |
| Respawn selection | A player's opportunity to change vehicles after death while keeping the same pilot. The small proof uses Arwing and Wolfen. The requested aircraft roster also adds Vitzy's fighter, followed by tank and on-foot forms. Co-op retains crew and pilot-specific aircraft assignments. |
| Snapshot | A host-produced update of shared match state, associated with a simulation tick. Guests use snapshots to display the world and correct predicted movement. A snapshot is an explicit network representation, not a raw copy of a C structure. |
| Local prediction | The guest's provisional movement in response to its own controls before the host's update arrives. Prediction does not give the guest authority over damage or scoring. |
| Reconciliation | Correction of a guest's predicted movement against the host's state, with outstanding local inputs accounted for. |
| Guest timeout | The host's decision that a guest has stopped communicating. The host removes the guest's ship without stopping the other players. The duration remains an implementation tuning choice. |
| Tailscale connection | A direct-address game connection to the host's Tailscale address through a user-managed tailnet. The game uses its normal connection flow rather than managing Tailscale accounts or configuration. |

The source definitions are in [`sf64level.h`](include/sf64level.h) and [`sf64player.h`](include/sf64player.h).
`gCamCount` currently serves both simulation and rendering roles. It is not the canonical meaning of player slot or local view.

## Audio import

The terms below describe the accepted [audio importer design](docs/adr/0002-audio-importer.md).
The export and listening catalog exist. Replacement import is not yet implemented.

| Term | Meaning |
| --- | --- |
| Recording | An authored WAV file supplied as input to the importer. The source recording remains unchanged during conversion. |
| Audio sample | An engine audio resource containing encoded waveform data and references to its predictor book and loop metadata. Several logical sounds can refer to the same sample. |
| Voice line | Spoken content addressed by a dialogue message ID, such as 2050. Its sequence chooses samples, pitch, note duration, and completion signaling. A voice line is distinct from an exported sample file. |
| Sound effect | A logical gameplay sound addressed by a sound ID. It can be a one-shot sound or a looping sound. |
| Audio set | A separately addressable collection of audio choices, such as original Star Fox audio or replacement Star Wolf audio. Preserving an audio set does not imply that a crew-selection interface exists. |
| Replacement entry | A manifest entry that assigns a recording to a voice or sound-effect ID within one audio set. It applies to every use of that ID in the selected set. |
| Replacement manifest | The authored input declaring replacement entries and explicit loop markers where needed. It is distinct from the generated export manifest at `audio_data/manifest.json`. |
| Audio catalog | The inventory of audio resources and their relationships, extended with verified logical-ID mappings and timing evidence for supported replacements. The existing listening catalog exposes sample and soundfont metadata. |
| Playback window | A reviewed maximum duration imposed by fixed scene schedules across supported uses of a logical ID. It is measured at effective in-game pitch and timing. Normal gameplay interruptions can still end a line earlier. |
| Audio interruption | Existing game behavior that replaces or stops a playing sound, including radio priority rules and scene transitions. The importer retains those rules. |
| Loop markers | Authored start and end points in the replacement recording. Conversion maps these points to the converted sample and generates the decoder state needed to repeat it. |
| ADPCM predictor book | Coefficients used to decode an ADPCM sample. The replacement payload, predictor book, endpoint, and loop state must agree. |
| Paired audio build | Starwolf64's matching native archive and browser game artifacts produced from the same replacement manifest and conversion results. Neither target becomes the published result if either target fails validation. Shared tooling and the native writer can also be used independently by upstream Starship. |
