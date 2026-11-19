#ifndef CAMPAIGN_VEHICLE_H
#define CAMPAIGN_VEHICLE_H
#define CAMPAIGN_VEHICLE_PENDING 100
static inline bool CampaignVehicle_StageHasChoice(s32 level) { return level == LEVEL_MACBETH || level == LEVEL_TITANIA; }
static inline PlayerForm CampaignVehicle_ForcedForm(s32 level) { return level == LEVEL_AQUAS ? FORM_BLUE_MARINE : FORM_ARWING; }
static inline PlayerForm CampaignVehicle_FormForChoice(s32 level, u16 buttons) {
    if (!CampaignVehicle_StageHasChoice(level)) return CampaignVehicle_ForcedForm(level);
    if (buttons & A_BUTTON) return FORM_ARWING;
    if (buttons & B_BUTTON) return FORM_LANDMASTER;
    return FORM_NONE;
}
void CampaignVehicle_Setup(Player* player);
bool CampaignVehicle_Intro(Player* player);
void CampaignVehicle_Draw(void);
#endif
