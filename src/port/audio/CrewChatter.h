#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Called by the text renderer on the game thread, once per visible radio line. */
int CrewChatter_Observe(int speaker, const void* message, int index, int glyph, float volume);
/* Publish the frame before waking the audio thread; missing text stops playback. */
void CrewChatter_Commit(void);
void CrewChatter_Mix(int16_t* samples, uint32_t frames, int channels);
#ifdef __cplusplus
}
#endif
