# High on Sugar: to do next

## 1. Worn gold and netherite armor still look vanilla

**Problem:** the inventory icons show the new designs (crown, suit, hooded set), but when the armor is worn the player still shows the default gold and netherite armor.

**Likely cause:** the pack stores armor textures with Java Edition names (`textures/models/armor/gold_layer_1.png`, `gold_layer_2.png`, `netherite_layer_1.png`, `netherite_layer_2.png`). Bedrock most likely looks for `gold_1.png` / `gold_2.png` and `netherite_1.png` / `netherite_2.png`, so the new layers are never loaded.

**Fix to try:**
1. Copy `gold_layer_1.png` → `gold_1.png` and `gold_layer_2.png` → `gold_2.png` in `textures/models/armor/`.
2. Do the same for netherite (`netherite_1.png`, `netherite_2.png`).
3. If the worn armor still doesn't change, check the vanilla armor attachables (`attachables/golden_chestplate.json` and so on in Mojang's bedrock-samples) for the exact texture paths they use, and match those names.
4. Restart Minecraft and check in third person and on the inventory paper doll.

Gold = suit, tie and crown (the helmet is only the crown). Netherite = dark hooded set. Both were mapped from player skins.

## 2. Still to check in game

- Netherite armor icon file names (`netherite_helmet.png` and so on) were guessed. Make sure the icons show.
- Gun hand positions and the greatsword hand and back positions.
