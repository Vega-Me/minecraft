Guts: third-person walking/sprinting experiment

The installable build is texture-packs/dist/Guts_Locomotion_Test.mcpack.
It has its own pack name and UUIDs so it can be installed alongside Guts.

Implementation
Only entity/player.entity.json, manifest.json and two new namespaced
animation/controller files change the resource pack. The original vanilla
root controller, player skin geometry, all Guts weapon attachables, weapon
animations, render controllers, textures and sounds remain intact.

The move.arms, move.legs and bob aliases route to small controllers. Outside
grounded third-person movement those controllers call the original vanilla
animations. Walking uses Actions & Stuff's animation.actor.move limb/body
curves; sprinting uses its 1.18 cadence multiplier and the steady-state
lean_forward pose. These are adaptations, not an unmodified full donor port.
Root translation, head motion, cape motion, dust, jump, stop and combat clips
from the donor are excluded. Original cape/look/holding layers stay active.

The prototype turns off during attacks, item use, charging, loaded crossbow,
blocking, first person, inventory paperdoll, map icon, spectator/death, falling,
jumping, sneaking, swimming/fading swim, gliding, crawling, riding, sleep and
emotes. Donor clip blend weights are hard-gated to stop outgoing transitions
from continuing to apply a donor pose in those conditions.

Build
python3 tools/build_guts_locomotion.py /path/to/extracted/Actions-and-Stuff
python3 tools/verify_guts_locomotion.py

Evidence and limits
static-verification.json records file/alias/gating checks. Motion samples and
the Blender preview evaluate the exported JSON curves on a neutral mannequin
using Mojang's classic humanoid reference hierarchy. This is an offline
approximation. It does not emulate Minecraft's full controller stack, engine
queries, skin switching, multiplayer interpolation or attachable rendering.
The preview uses actual Guts back-sword geometry, not a rebuilt lookalike.

Required game checks before considering this production-ready: first/third
person switching, classic/slim skins, armor/capes, gait transitions, held
weapons, back-sword visibility, attacks/use while moving, offhand/shields,
charged ranged weapons and viewing another player remotely.

Sources
Donor supplied by user: actions-stuff-1-0-3.mcpack.zip.
Its manifest identifies Actions & Stuff 1.0.2 (minimum engine 1.20.80).
Original Guts manifest credits Soulless | packsmc.com.
Vanilla humanoid reference and controller/alias call sites checked against:
https://github.com/Mojang/bedrock-samples/blob/main/resource_pack/models/entity/humanoid.custom.geo.json
https://github.com/Mojang/bedrock-samples/blob/main/resource_pack/animations/player.animation.json
https://github.com/Mojang/bedrock-samples/blob/main/resource_pack/animation_controllers/player.animation_controllers.json
