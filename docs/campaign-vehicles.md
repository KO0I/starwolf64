# Campaign vehicle selection

Story missions use the VS selection panel and direct button confirmation. Macbeth and Titania offer A for the selected flying ship and B for Landmaster. The Star Wolf campaign uses Wolfen artwork. There is no campaign on-foot choice.

| Story stage | Allowed form |
| --- | --- |
| Macbeth, Titania | Flying ship or Landmaster |
| Aquas | Blue Marine |
| Corneria, Meteo, all sectors, Solar, and other story stages | Flying ship |

A stage with one allowed form starts with that form and has no vehicle panel. Choosing an aircraft form preserves the pilot's accepted ship model in online play.

Native VS keeps A for Arwing and adds Z for Wolfen. The Arwing choice uses the original radar silhouette at 80% scale. The on-foot logo has a faceted eyepatch whose upper strap runs over the center of the crown. Ground vehicles retain the original VS unlock rules and remain unavailable in the aerial VS arenas. Online battle retains the ship confirmed in the room, which already offers both Arwing and Wolfen.

The co-op bridge currently synchronizes Corneria. Macbeth, Titania, and the other unaudited story missions still leave remote guests waiting while the host continues. The vehicle policy and companion selection do not enable those stages' network scene support.

Run the native vehicle checks from this worktree:

```sh
python3 tools/check_campaign_vehicles_native.py --native-build /home/amber/proj/Starship/build-cmake
```

The check compiles the actual policy and native VS selector with engine types. It verifies stage restrictions, the separate aircraft buttons, and the original VS ground unlock rules.

Build and inspect an isolated native preview:

```sh
python3 tools/preview_campaign_vehicles.py --native-build /home/amber/proj/Starship/build-cmake
python3 tools/check_campaign_vehicles_ui.py --native-build /home/amber/proj/Starship/build-cmake
```

The runtime check captures both selectors, checks independent companion forms and respawn in the native simulation, and verifies the forced forms on Corneria and Aquas. It does not claim network synchronization on Macbeth or Titania.
