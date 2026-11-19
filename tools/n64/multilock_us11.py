"""Verified original US 1.1 hooks; ROM offset is RAM minus 0x7ffff400."""
HOOKS = [
    dict(name="shot_initialize",ram=2147704392,expected="0080102524040070",symbol="Multi_ShotInitialized",link=False,delay=0),
    dict(name="actor_initialize",ram=2147881924,expected="0080102500001825",symbol="Multi_ActorInitialized",link=False,delay=0),
    dict(name="item_initialize",ram=2147882052,expected="008010252404006c",symbol="Multi_ItemInitialized",link=False,delay=0),
    dict(name="find_lock_target",ram=2147728204,expected="27bdffd8afb1001c",symbol="Multi_FindLockTarget",link=False,delay=0),
    dict(name="can_lock_on",ram=2148192536,expected="3c03801624633fe0",symbol="Multi_CanLockOn",link=False,delay=0),
    dict(name="update_lock_on",ram=2148192756,expected="27bdffc0afb00020",symbol="Multi_UpdateLockOn",link=False,delay=0),
    dict(name="assigned_target_homing",ram=2147733748,expected="3c05800d44808000",symbol="Multi_HomingGate",link=False,delay=0),
    dict(name="impact_preserve_other_locks",ram=2147705800,expected="3c0140f044815000",symbol="Multi_ImpactGate",link=False,delay=0),
    dict(name="preserve_charge_with_locks",ram=2147916776,expected="ac2079c8960200c4",symbol="Multi_ChargeGate",link=False,delay=2516713668),
    dict(name="dropped_item_conversion",ram=2147901808,expected="0c0184aee608000c",symbol="Multi_DropInfo",link=True,delay=3859283980),
    dict(name="bomb_pickup_upgrade",ram=2147908744,expected="8c4c000024e78280",symbol="Multi_CollectBombGate",link=False,delay=0),
    dict(name="upgrade_item_draw",ram=2147863364,expected="27bdffe8afbf0014",symbol="Multi_DrawItem",link=False,delay=0),
    dict(name="clear_stage_objects",ram=2148163912,expected="27bdffe0afbf001c",symbol="Multi_ClearObjects",link=False,delay=0),
    dict(name="player_down",ram=2148221420,expected="27bdffe0afb00018",symbol="Multi_PlayerDown",link=False,delay=0),
    dict(name="down_state_update",ram=2148224776,expected="0c0138f602002025",symbol="Multi_PlayerDownUpdate",link=True,delay=0x02002025),
]
