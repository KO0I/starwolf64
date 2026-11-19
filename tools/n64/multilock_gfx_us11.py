"""Original US 1.1 draw entry hooks and expected instructions."""
GFX_HOOKS=(
 dict(name="draw_multilock_indicators",ram=0x80057504,expected="27bdff88afbf0074",symbol="Multi_DrawIndicators"),
 dict(name="capture_rail_actor_lock_view",ram=0x8005D954,expected="27bdffc0afb00020",symbol="Multi_DrawActorOnRails"),
 dict(name="capture_all_range_actor_lock_view",ram=0x8005DBC0,expected="27bdffa0afb0001c",symbol="Multi_DrawActorAllRange"),
)
