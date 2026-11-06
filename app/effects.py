"""Catalog of cosmetics: ~100 effects + titles + sticker packs. Single source of truth:
   * the shop API serves it (names, rarity, prices),
   * tools/gen_effects.py turns RECIPES into assets/effects.css for the frontend.
Item ids look like "frame.spin_aurora", "name.grad_ember", "banner.aurora_a", "card.gborder_rose", "title.void_walker", "pack.spirits"."""

RANK_NAMES = ["Newcomer", "Void Initiate", "Shadow Watcher", "Rift Walker", "Void Sage", "Ascended"]
RARITY = {  # price (VP), minimum rank index
    "common": (120, 0), "uncommon": (320, 0), "rare": (700, 1), "epic": (1500, 2), "legendary": (3200, 3),
}
PALETTES = {  # name -> three colours (used by rings, gradients, glows)
    "aurora": ("#4ff0d2", "#8a7bff", "#ff5fa8"), "ember": ("#ffd23f", "#ff7a18", "#e63946"),
    "ocean": ("#00e5ff", "#2979ff", "#7c4dff"), "toxic": ("#b6ff3b", "#00e676", "#00bfa5"),
    "royal": ("#fff3b0", "#ffd700", "#b8860b"), "frost": ("#ffffff", "#7fd8ff", "#c9f0ff"),
    "sunset": ("#ffb347", "#ff6a88", "#ff9a8b"), "candy": ("#ff8ad8", "#8ad6ff", "#fff08a"),
    "mint": ("#e8fff5", "#3ddbb0", "#a8ffd9"), "violet": ("#ff9ae6", "#8a3dff", "#d6a8ff"),
    "blood": ("#ff5a73", "#ff0033", "#7a0010"), "mono": ("#ffffff", "#8a8fa3", "#ffffff"),
    "rainbow": ("red", "lime", "blue"),
}
GLOWS = {"aqua": "#4ff0d2", "rose": "#ff5fa8", "gold": "#ffd23f", "lime": "#b6ff3b", "violet": "#a78bff", "white": "#ffffff"}

ITEMS: dict[str, dict] = {}
RECIPES: dict[str, tuple] = {}   # id -> (family, params) consumed by the CSS generator


def _add(kind, key, name, rarity, family, params, *, price=None, min_rank=None):
    iid = f"{kind}.{key}"
    p, r = RARITY[rarity]
    ITEMS[iid] = {"id": iid, "kind": kind, "name": name, "rarity": rarity,
                  "price": p if price is None else price, "min_rank": r if min_rank is None else min_rank}
    RECIPES[iid] = (family, params)


# ------------------------------------------------------------------ avatar decorations (illustrated SVG overlays, built in the browser)
# family params are read by assets/decorations.js; colours are [main, light, dark/accent]
def _deco(key, name, rarity, fam, **p):
    _add("frame", key, name, rarity, fam, p)

# wreaths: leaves / petals / feathers around the whole picture
_deco("ivy_wreath", "Ivy Wreath", "common", "wreath", shape="leaf", n=14, c=["#3f9e4a", "#8fdc6d", "#1d4d26"], an="sway", t=3.4)
_deco("maple_ring", "Maple Ring", "uncommon", "wreath", shape="maple", n=12, c=["#e8541c", "#ffb347", "#7a2410"], an="spin", t=60)
_deco("frost_fern", "Frost Fern", "uncommon", "wreath", shape="fern", n=14, c=["#8fd0f5", "#eaf8ff", "#3a6f94"], an="pulse", t=3.8)
_deco("blossom_ring", "Blossom Ring", "uncommon", "wreath", shape="petal", n=18, c=["#ff9ec4", "#ffd9e8", "#a8456f"], an="sway", t=4.2)
_deco("gilded_laurel", "Gilded Laurel", "rare", "wreath", shape="laurel", n=16, c=["#d9a520", "#fff0a0", "#7a5a08"], an="pulse", t=4.6)
_deco("bamboo_loop", "Bamboo Loop", "common", "wreath", shape="bamboo", n=10, c=["#6bbf59", "#c8f08a", "#2c6b2a"], an="sway", t=3.9)
_deco("rose_vine", "Rose Vine", "rare", "wreath", shape="vine", n=14, c=["#2f7d3a", "#e8344f", "#12361a"], an="spin", t=80)
_deco("raven_feathers", "Raven Feathers", "rare", "wreath", shape="feather", n=14, c=["#2b2638", "#7a6aa8", "#0f0e13"], an="sway", t=3.6)
_deco("autumn_drift", "Autumn Drift", "uncommon", "wreath", shape="leaf", n=12, c=["#c2571a", "#f0a04b", "#5a2208"], an="spinR", t=70)
_deco("clover_ring", "Lucky Clover", "common", "wreath", shape="clover", n=12, c=["#2fa84f", "#a8f08a", "#16602b"], an="bloom", t=3.2)
_deco("pine_garland", "Pine Garland", "uncommon", "wreath", shape="pine", n=14, c=["#1f6b45", "#f2f8ff", "#0e3524"], an="sway", t=4.4)
_deco("moonleaf", "Moonleaf", "rare", "wreath", shape="leaf", n=12, c=["#7fb3ff", "#e3eeff", "#2c4f8f"], an="pulse", t=4.1)
# flower crowns (top arc)
_deco("daisy_crown", "Daisy Crown", "common", "flowers", kind="daisy", n=7, c=["#ffffff", "#ffc83a", "#3fa14d"], an="bloom")
_deco("rosebud_crown", "Rosebud Crown", "uncommon", "flowers", kind="rose", n=6, c=["#e8344f", "#ff9aa8", "#2f7d3a"], an="sway")
_deco("lavender_arch", "Lavender Arch", "uncommon", "flowers", kind="lavender", n=9, c=["#a58cff", "#d9ccff", "#3f8f4d"], an="sway")
_deco("sunflower_halo", "Sunflower Halo", "rare", "flowers", kind="sunflower", n=6, c=["#ffc21a", "#5a3410", "#3fa14d"], an="bloom")
_deco("lotus_crown", "Lotus Crown", "rare", "flowers", kind="lotus", n=5, c=["#ff8fb8", "#fff0f6", "#3f9e6a"], an="bloom")
_deco("tulip_garland", "Tulip Garland", "uncommon", "flowers", kind="tulip", n=7, c=["#ff5a5a", "#ffd0d0", "#3fa14d"], an="sway")
# flame rings
for i, (k, n_, cols, rar, t_) in enumerate([("ember", "Ember Ring", ["#ff5a1f", "#ffb02e", "#fff2b0"], "uncommon", 1.1), ("azure", "Azure Fire", ["#2f7dff", "#6fd0ff", "#e6fbff"], "rare", 1.3),
        ("violet", "Violet Blaze", ["#8a3dff", "#d58bff", "#fff0ff"], "rare", 1.0), ("jade", "Jade Flame", ["#12a672", "#5ef2b0", "#e8fff5"], "rare", 1.2),
        ("white", "White-hot", ["#ffd9a0", "#fff4dc", "#ffffff"], "epic", 0.9), ("crimson", "Crimson Pyre", ["#c4122f", "#ff4d4d", "#ffd0a0"], "epic", 1.15),
        ("gold", "Solar Flare", ["#ff9f1c", "#ffe066", "#fffbe0"], "epic", 1.0), ("shadow", "Shadow Fire", ["#241a3a", "#6a3dd9", "#cdb8ff"], "legendary", 1.25)]):
    _deco(f"flame_{k}", n_, rar, "flame", n=16, c=cols, t=t_)
# crystal shard rings
for k, n_, cols, rar, an in [("ice", "Ice Shards", ["#9fd8ff", "#eaf8ff", "#3a6f94"], "uncommon", "shimmer"), ("amethyst", "Amethyst Crown", ["#9a5cff", "#dcc2ff", "#4a1f8f"], "rare", "shimmer"),
        ("emerald", "Emerald Burst", ["#18b87a", "#a8ffd8", "#0a5a3a"], "rare", "spin"), ("quartz", "Rose Quartz", ["#ff9ec4", "#ffe0ee", "#a8456f"], "uncommon", "shimmer"),
        ("citrine", "Citrine Spikes", ["#ffb52e", "#fff0a0", "#8a5a08"], "rare", "spin"), ("obsidian", "Obsidian Thorns", ["#1d1a26", "#6a5a8a", "#0a090d"], "epic", "shimmer"),
        ("ruby", "Ruby Halo", ["#d6143a", "#ff8fa8", "#6a0a1f"], "epic", "shimmer"), ("moonstone", "Moonstone Ring", ["#c9d6ff", "#ffffff", "#5a6aa8"], "legendary", "spin")]:
    _deco(f"crystal_{k}", n_, rar, "crystal", n=14, c=cols, an=an)
# orbiting objects
_deco("twin_moons", "Twin Moons", "rare", "orbit", obj="moon", n=2, c=["#f6e7a8", "#bba35a"], rad=41, spd=9, tilt=1.0)
_deco("star_chain", "Star Chain", "uncommon", "orbit", obj="star", n=6, c=["#ffd24a", "#fff3b0"], rad=41, spd=14, tilt=1.0)
_deco("rune_circle", "Rune Circle", "rare", "orbit", obj="rune", n=6, c=["#7fd0ff", "#e6f6ff"], rad=42, spd=20, tilt=1.0)
_deco("firefly_orbit", "Firefly Orbit", "uncommon", "orbit", obj="firefly", n=5, c=["#d8ff6a", "#fffbb0"], rad=40, spd=11, tilt=0.8)
_deco("bubble_orbit", "Bubble Orbit", "common", "orbit", obj="bubble", n=5, c=["#8fe0ff", "#ffffff"], rad=41, spd=13, tilt=1.0)
_deco("comet_loop", "Comet Loop", "epic", "orbit", obj="comet", n=2, c=["#ffb347", "#fff2c8"], rad=42, spd=5, tilt=1.0)
_deco("paper_cranes", "Paper Cranes", "epic", "orbit", obj="crane", n=3, c=["#ffffff", "#ff5a4f"], rad=42, spd=18, tilt=0.9)
_deco("gear_ring", "Clockwork", "rare", "orbit", obj="gear", n=3, c=["#d9a520", "#7a5a08"], rad=41, spd=16, tilt=1.0)
_deco("petal_swirl", "Petal Swirl", "uncommon", "orbit", obj="petal", n=8, c=["#ff9ec4", "#ffd9e8"], rad=41, spd=15, tilt=0.85)
# halos
_deco("gold_halo", "Gold Halo", "uncommon", "halo", style="ring", c=["#ffd24a", "#fff3b0"])
_deco("twin_halo", "Twin Halo", "rare", "halo", style="twin", c=["#ffd24a", "#ffffff"])
_deco("thorn_halo", "Thorn Halo", "rare", "halo", style="thorn", c=["#d9d3ff", "#6a5a8a"])
_deco("rune_halo", "Rune Halo", "epic", "halo", style="rune", c=["#7fd0ff", "#e6f6ff"])
_deco("eclipse_halo", "Eclipse", "epic", "halo", style="eclipse", c=["#ffb347", "#1d1a26"])
_deco("lotus_halo", "Lotus Halo", "rare", "halo", style="lotus", c=["#ff8fb8", "#fff0f6"])
_deco("broken_halo", "Broken Halo", "legendary", "halo", style="broken", c=["#ffe9a8", "#ff5a36"])
# ears / horns / headwear on top
_deco("cat_ears_ink", "Ink Cat Ears", "common", "ears", kind="cat", c=["#2b2638", "#ff9aa8"], an="twitch")
_deco("cat_ears_snow", "Snow Cat Ears", "common", "ears", kind="cat", c=["#f4f1ec", "#ffb3c4"], an="wiggle")
_deco("cat_ears_ginger", "Ginger Cat Ears", "uncommon", "ears", kind="cat", c=["#f28a3a", "#ffd0a0"], an="twitch")
_deco("fox_ears", "Fox Ears", "uncommon", "ears", kind="fox", c=["#f26a1f", "#fff0dc"], an="wiggle")
_deco("bunny_ears", "Bunny Ears", "uncommon", "ears", kind="bunny", c=["#fbf6f0", "#ffb3c4"], an="bob")
_deco("wolf_ears", "Wolf Ears", "rare", "ears", kind="wolf", c=["#6b7385", "#c9d0de"], an="twitch")
_deco("devil_horns", "Devil Horns", "rare", "ears", kind="devil", c=["#c4122f", "#ff6a6a"], an="bob")
_deco("oni_horns", "Oni Horns", "epic", "ears", kind="oni", c=["#f4ead8", "#d9a520"], an="bob")
_deco("antlers", "Spring Antlers", "rare", "ears", kind="antlers", c=["#8a5a2b", "#3fa14d"], an="sway")
_deco("unicorn_horn", "Unicorn Horn", "epic", "ears", kind="unicorn", c=["#ffe9a8", "#ff9ec4"], an="glint")
_deco("bear_ears", "Bear Ears", "common", "ears", kind="bear", c=["#8a5a2b", "#d9a87a"], an="wiggle")
_deco("elf_ears", "Elf Ears", "uncommon", "ears", kind="elf", c=["#f2d2b4", "#e8a88a"], an="twitch")
# crowns
_deco("gold_crown", "Gold Crown", "rare", "crown", style="king", c=["#f2b824", "#fff0a0", "#d6143a"])
_deco("jewel_tiara", "Jewel Tiara", "rare", "crown", style="tiara", c=["#d9d9e8", "#ffffff", "#5a9bff"])
_deco("laurel_crown", "Victory Laurel", "uncommon", "crown", style="laurel", c=["#d9a520", "#fff0a0", "#7a5a08"])
_deco("thorn_crown", "Thorn Crown", "epic", "crown", style="thorn", c=["#3a2a1f", "#8a6a4a", "#d6143a"])
_deco("star_diadem", "Star Diadem", "epic", "crown", style="star", c=["#ffd24a", "#fff3b0", "#7fd0ff"])
_deco("moon_crown", "Moon Crown", "legendary", "crown", style="moon", c=["#e6e9ff", "#ffffff", "#8a7bff"])
# wings (behind the picture)
_deco("angel_wings", "Angel Wings", "epic", "wings", kind="feather", c=["#ffffff", "#dfe7ff", "#aab6e8"], t=3.2)
_deco("bat_wings", "Bat Wings", "rare", "wings", kind="bat", c=["#2b2638", "#6a3dd9", "#0f0e13"], t=2.6)
_deco("butterfly_wings", "Butterfly Wings", "epic", "wings", kind="butterfly", c=["#ff7ab8", "#ffd24a", "#5a1f8f"], t=2.8)
_deco("dragon_wings", "Dragon Wings", "epic", "wings", kind="bat", c=["#b01a2f", "#ff7a3a", "#3a0a12"], t=3.6)
_deco("fairy_wings", "Fairy Wings", "rare", "wings", kind="butterfly", c=["#9fe8ff", "#e8fbff", "#3a8fb8"], t=2.2)
_deco("crystal_wings", "Crystal Wings", "legendary", "wings", kind="feather", c=["#9fd8ff", "#ffffff", "#5a7fd8"], t=3.8)
_deco("ember_wings", "Ember Wings", "legendary", "wings", kind="feather", c=["#ff5a1f", "#ffd24a", "#7a1a08"], t=2.9)
# magic circles (behind, rotating)
_deco("gold_seal", "Gold Seal", "uncommon", "magic", style="hex", c=["#f2b824", "#fff0a0"])
_deco("azure_seal", "Azure Seal", "rare", "magic", style="rings", c=["#4fa8ff", "#e6f4ff"])
_deco("crimson_seal", "Crimson Seal", "rare", "magic", style="star", c=["#e8344f", "#ffb0b8"])
_deco("jade_seal", "Jade Seal", "rare", "magic", style="hex", c=["#18b87a", "#c8ffe8"])
_deco("violet_seal", "Violet Seal", "epic", "magic", style="star", c=["#9a5cff", "#e6d4ff"])
_deco("shadow_seal", "Shadow Seal", "legendary", "magic", style="rings", c=["#3a2a5a", "#cdb8ff"])
# auras
_deco("spirit_wisps", "Spirit Wisps", "rare", "aura", kind="wisps", c=["#7fd0ff", "#e6f6ff"])
_deco("storm_arcs", "Storm Arcs", "epic", "aura", kind="arcs", c=["#ffe14a", "#ffffff"])
_deco("smoke_curl", "Smoke Curl", "uncommon", "aura", kind="smoke", c=["#8a8fa3", "#cfd3e0"])
_deco("ripple_rings", "Ripple Rings", "uncommon", "aura", kind="ripple", c=["#5ac8ff", "#d8f3ff"])
_deco("wind_swirl", "Wind Swirl", "rare", "aura", kind="wind", c=["#b8f0d8", "#ffffff"])
# accessories
_deco("sprout", "Sprout", "common", "cap", kind="sprout", c=["#3fa14d", "#8fdc6d", "#1d4d26"])
_deco("toadstool_red", "Toadstool Cap", "uncommon", "cap", kind="mush", c=["#e8344f", "#ffffff", "#f2d9b8"])
_deco("toadstool_blue", "Moonshroom", "rare", "cap", kind="mush", c=["#4f6fff", "#cfe0ff", "#e6e0f2"])
_deco("snow_cap", "Snow Cap", "uncommon", "cap", kind="snow", c=["#ffffff", "#cfe8ff", "#8fb8d8"])
_deco("rain_cloud", "Rain Cloud", "rare", "cap", kind="cloud", c=["#c9d3e8", "#8fa0c0", "#5ac8ff"])
_deco("kasa_hat", "Straw Kasa", "rare", "cap", kind="kasa", c=["#e8c27a", "#b8924a", "#7a5a2a"])
_deco("witch_hat", "Witch Hat", "epic", "cap", kind="witch", c=["#3a2a5a", "#d9a520", "#8a5cff"])
_deco("sakura_branch", "Sakura Branch", "epic", "cap", kind="branch", c=["#7a4a2a", "#ff9ec4", "#ffe0ee"])
# floating particles
_deco("glitter_ring", "Glitter", "common", "part", obj="sparkle", n=10, c=["#fff3b0", "#ffd24a"], t=2.4, dir="twinkle")
_deco("rising_hearts", "Rising Hearts", "uncommon", "part", obj="heart", n=8, c=["#ff5a7a", "#ffb0c0"], t=4.0, dir="up")
_deco("bubble_rise", "Soap Bubbles", "common", "part", obj="bubble", n=8, c=["#8fe0ff", "#ffffff"], t=4.4, dir="up")
_deco("petal_fall", "Petal Fall", "uncommon", "part", obj="petal", n=10, c=["#ff9ec4", "#ffd9e8"], t=5.0, dir="down")
_deco("snow_fall", "Snow Globe", "common", "part", obj="dot", n=14, c=["#ffffff", "#cfe8ff"], t=4.6, dir="down")
_deco("leaf_fall", "Leaf Fall", "uncommon", "part", obj="leaf", n=8, c=["#e8541c", "#ffb347"], t=5.2, dir="down")
_deco("star_fall", "Star Fall", "rare", "part", obj="star", n=8, c=["#ffd24a", "#fff3b0"], t=3.6, dir="down")
_deco("ember_rise", "Rising Embers", "uncommon", "part", obj="dot", n=14, c=["#ff7a1f", "#ffd24a"], t=3.2, dir="up")
# tech
_deco("pixel_ring", "Pixel Ring", "uncommon", "tech", kind="pixel", c=["#4fd0ff", "#ff5a7a"])
_deco("hud_reticle", "HUD Reticle", "rare", "tech", kind="reticle", c=["#5ef2b0", "#e8fff5"])
_deco("radar_sweep", "Radar Sweep", "rare", "tech", kind="radar", c=["#5ef2b0", "#12a672"])
_deco("glitch_frame", "Glitch Frame", "epic", "tech", kind="glitch", c=["#ff3d6e", "#3dd6ff"])
# starters are free and unlock by rank (legacy frame names map onto them)
for iid, rank in {"frame.sprout": 0, "frame.ivy_wreath": 1, "frame.cat_ears_ink": 2, "frame.flame_ember": 3, "frame.gold_seal": 4, "frame.angel_wings": 5}.items():
    ITEMS[iid]["price"], ITEMS[iid]["min_rank"] = 0, rank
LEGACY_FRAMES = {"glow": "frame.sprout", "sakura": "frame.ivy_wreath", "neon": "frame.cat_ears_ink", "flame": "frame.flame_ember", "galaxy": "frame.gold_seal", "rainbow": "frame.angel_wings"}

# ------------------------------------------------------------------ name effects
for i, pal in enumerate(["aurora", "ember", "ocean", "toxic", "royal", "frost", "sunset", "candy", "mint", "violet"]):
    _add("name", f"grad_{pal}", f"{pal.title()} Gradient", ["common", "common", "uncommon", "uncommon", "rare", "uncommon", "uncommon", "rare", "common", "rare"][i], "grad", {"pal": pal})
for i, g in enumerate(GLOWS):
    _add("name", f"glow_{g}", f"{g.title()} Glow", ["common", "uncommon", "uncommon", "uncommon", "rare", "common"][i], "glow", {"col": GLOWS[g]})
for i, g in enumerate(["aqua", "rose", "gold", "violet"]):
    _add("name", f"shimmer_{g}", f"{g.title()} Shimmer", ["rare", "rare", "epic", "epic"][i], "shimmer", {"col": GLOWS[g]})
for i, g in enumerate(["aqua", "rose", "lime"]):
    _add("name", f"flicker_{g}", f"{g.title()} Neon", ["rare", "rare", "epic"][i], "flicker", {"col": GLOWS[g]})
for i, g in enumerate(["aqua", "rose"]):
    _add("name", f"glitch_{g}", f"{g.title()} Glitch", "epic", "glitch", {"col": GLOWS[g]})
_add("name", "rainbow", "Rainbow Flow", "legendary", "rainbowtext", {})
_add("name", "metal_gold", "Liquid Gold", "legendary", "metal", {})
_add("name", "outline", "Hollow Neon", "rare", "outline", {"col": GLOWS["aqua"]})

# ------------------------------------------------------------------ banner scenes (animated particle scenes + silhouettes, built in the browser)
def _ban(key, name, rarity, fam, **p):
    _add("banner", key, name, rarity, fam, p)

_ban("sakura_drift", "Sakura Drift", "common", "b_fall", obj="petal", n=26, c=["#ffb3cf", "#ffe0ec", "#ff8fb8"], dur=[7, 12], dir="down", sway=18)
_ban("night_blossom", "Night Blossom", "rare", "b_fall", obj="petal", n=30, c=["#ffffff", "#ffd0e4", "#ff9ec4"], dur=[8, 13], dir="down", sway=22, sky=["#1b1230", "#3a1f4a"], moon=True)
_ban("maple_fall", "Maple Fall", "common", "b_fall", obj="leaf", n=22, c=["#e8541c", "#ffb347", "#c2371a"], dur=[7, 12], dir="down", sway=26)
_ban("gingko_fall", "Gingko Fall", "common", "b_fall", obj="leaf", n=22, c=["#ffd24a", "#fff0a0", "#e8b020"], dur=[8, 13], dir="down", sway=24)
_ban("snowfall", "Snowfall", "common", "b_fall", obj="dot", n=40, c=["#ffffff", "#dcefff", "#bcd8f0"], dur=[6, 11], dir="down", sway=10)
_ban("blizzard", "Blizzard", "uncommon", "b_fall", obj="dot", n=70, c=["#ffffff", "#dcefff", "#bcd8f0"], dur=[2.4, 4.4], dir="diag", sway=4, sky=["#0e1a2e", "#1f3552"])
_ban("ember_rise", "Ember Rise", "uncommon", "b_fall", obj="spark", n=34, c=["#ff7a1f", "#ffd24a", "#ff4d2e"], dur=[3, 6], dir="up", sway=14, sky=["#1a0a0a", "#3a1208"])
_ban("volcanic_ash", "Volcanic Ash", "rare", "b_fall", obj="ash", n=36, c=["#6a6470", "#a8a2b0", "#ff7a1f"], dur=[5, 9], dir="down", sway=16, sky=["#16100f", "#3a1a12"])
_ban("bubble_rise", "Bubble Rise", "common", "b_fall", obj="bubble", n=22, c=["#bfeaff", "#ffffff", "#8fd0f0"], dur=[6, 11], dir="up", sway=14, sky=["#0c2a3f", "#124a66"])
_ban("deep_sea", "Deep Sea", "rare", "b_scene", scene="ocean", c=["#0a2a44", "#145a80", "#6fd0ff"], bub=18)
_ban("heartfall", "Heartfall", "uncommon", "b_fall", obj="heart", n=22, c=["#ff5a7a", "#ffb0c0", "#e8344f"], dur=[6, 10], dir="up", sway=16)
_ban("confetti_pop", "Confetti Pop", "uncommon", "b_fall", obj="confetti", n=44, c=["#ff5a36", "#ffbe3b", "#38d6a0", "#5aa9ff", "#b06bff"], dur=[4, 8], dir="down", sway=20)
_ban("meteor_shower", "Meteor Shower", "rare", "b_stars", shoot=6, stars=40, c=["#ffffff", "#ffe9a8", "#9fd0ff"], sky=["#070a18", "#171f45"])
_ban("twinkle_sky", "Twinkle Sky", "uncommon", "b_stars", shoot=1, stars=60, c=["#ffffff", "#fff3b0", "#cfe0ff"], sky=["#0a0f24", "#1a2250"])
_ban("firefly_meadow", "Firefly Meadow", "uncommon", "b_fire", n=18, c=["#d8ff6a", "#fffbb0"], sky=["#0b1a12", "#173a24"])
_ban("amber_fireflies", "Amber Fireflies", "rare", "b_fire", n=22, c=["#ffb02e", "#fff0b0"], sky=["#1a1008", "#3a2410"])
_ban("rainfall", "Rainfall", "common", "b_rain", n=60, c=["#9fc4e8", "#d8ecff"], sky=["#141a26", "#242f45"], bolt=False)
_ban("thunderstorm", "Thunderstorm", "epic", "b_rain", n=70, c=["#9fc4e8", "#d8ecff"], sky=["#0c0f1a", "#1c2238"], bolt=True)
_ban("drifting_fog", "Drifting Fog", "common", "b_fog", c=["#cfd6e4", "#e8ecf4"], sky=["#161a24", "#2a3142"])
_ban("mountain_mist", "Mountain Mist", "rare", "b_scene", scene="mountain", c=["#1a2338", "#2c3a58", "#5a6a8f", "#e8ecf4"])
_ban("tokyo_night", "Tokyo Night", "epic", "b_scene", scene="city", c=["#0b0d1c", "#1a1f3d", "#ffd24a", "#7fd0ff"])
_ban("dusk_city", "Dusk City", "epic", "b_scene", scene="dusk", c=["#2a1240", "#ff5a5a", "#ffb347", "#120c1f"])
_ban("ocean_swell", "Ocean Swell", "uncommon", "b_scene", scene="waves", c=["#0a2a44", "#1a6a9a", "#7fd0ff", "#e6f8ff"])
_ban("sky_lanterns", "Sky Lanterns", "epic", "b_lantern", n=14, c=["#ffb347", "#ff5a36", "#fff0b0"], sky=["#0b0a1c", "#1d1840"])
_ban("paper_cranes", "Paper Cranes", "epic", "b_crane", n=7, c=["#ffffff", "#ff5a4f", "#ffd24a"], sky=["#14122a", "#2a2450"])
_ban("pine_snow", "Pine Snow", "rare", "b_scene", scene="pines", c=["#0d1b2a", "#16324a", "#e8f4ff", "#0a1420"])
_ban("sunbeam_dust", "Sunbeam Dust", "uncommon", "b_dust", c=["#fff0b0", "#ffd24a"], sky=["#2a1a10", "#6a3a1a"])
_ban("neon_rain", "Neon Rain", "rare", "b_rain", n=60, c=["#ff3d9a", "#3dd6ff"], sky=["#0a0714", "#1f0f33"], bolt=False)
_ban("starfall_violet", "Starfall", "uncommon", "b_fall", obj="star", n=24, c=["#cdb8ff", "#ffffff", "#9a5cff"], dur=[5, 9], dir="down", sway=12, sky=["#100a24", "#241450"])
_ban("golden_leaves", "Golden Leaves", "rare", "b_fall", obj="leaf", n=30, c=["#ffd24a", "#f2a81a", "#fff0a0"], dur=[6, 10], dir="diag", sway=30, sky=["#1a1204", "#3a2a0a"])
_ban("jellyfish_drift", "Jellyfish Drift", "epic", "b_scene", scene="jelly", c=["#0a1a33", "#ff7ab8", "#7fd0ff", "#b78cff"])

# ------------------------------------------------------------------ comment / profile card styles
for i, pal in enumerate(["aurora", "ember", "ocean", "violet", "mint", "sunset"]):
    _add("card", f"gborder_{pal}", f"{pal.title()} Edge", ["uncommon", "uncommon", "rare", "rare", "uncommon", "rare"][i], "c_gborder", {"pal": pal})
for i, g in enumerate(["aqua", "rose", "violet"]):
    _add("card", f"glass_{g}", f"{g.title()} Glass", ["common", "common", "uncommon"][i], "c_glass", {"col": GLOWS[g]})
for i, pal in enumerate(["aurora", "candy"]):
    _add("card", f"holo_{pal}", f"{pal.title()} Hologram", "epic", "c_holo", {"pal": pal})
for i, g in enumerate(["aqua", "rose", "gold"]):
    _add("card", f"neon_{g}", f"{g.title()} Neon Box", ["rare", "rare", "epic"][i], "c_neon", {"col": GLOWS[g]})
for i, pal in enumerate(["ocean", "ember"]):
    _add("card", f"flow_{pal}", f"{pal.title()} Flow", "epic", "c_flow", {"pal": pal})

EFFECT_COUNT = len(ITEMS)
DECORATIONS = sum(1 for i in ITEMS.values() if i['kind'] == 'frame')

# ------------------------------------------------------------------ titles (text badges next to the name)
_TITLES = [  # key, label, rarity
    ("wanderer", "Wanderer", "common"), ("night_owl", "Night Owl", "common"), ("binge_pilot", "Binge Pilot", "common"), ("opening_skipper", "Opening Skipper", "common"),
    ("side_character", "Side Character", "common"), ("sub_enjoyer", "Sub Enjoyer", "common"), ("dub_defender", "Dub Defender", "common"), ("filler_survivor", "Filler Survivor", "common"),
    ("plot_twist", "Plot Twist", "uncommon"), ("cliffhanger", "Cliffhanger", "uncommon"), ("slice_of_life", "Slice of Life", "uncommon"), ("shonen_spirit", "Shonen Spirit", "uncommon"),
    ("mecha_pilot", "Mecha Pilot", "uncommon"), ("credits_watcher", "Credits Watcher", "uncommon"), ("ost_addict", "OST Addict", "uncommon"), ("hype_train", "Hype Train", "uncommon"),
    ("main_character", "Main Character", "rare"), ("isekai_veteran", "Isekai Veteran", "rare"), ("tsundere_whisperer", "Tsundere Whisperer", "rare"), ("season_finale", "Season Finale", "rare"),
    ("rewatch_royalty", "Rewatch Royalty", "rare"), ("plot_armor", "Plot Armor", "rare"), ("frame_collector", "Frame Collector", "rare"), ("rift_runner", "Rift Runner", "rare"),
    ("void_walker", "Void Walker", "epic"), ("sakuga_sage", "Sakuga Sage", "epic"), ("final_boss", "Final Boss", "epic"), ("neon_samurai", "Neon Samurai", "epic"),
    ("dimension_hopper", "Dimension Hopper", "epic"), ("starlit_sage", "Starlit Sage", "epic"),
    ("anime_oracle", "Anime Oracle", "legendary"), ("eternal_watcher", "Eternal Watcher", "legendary"), ("legend_of_the_void", "Legend of the Void", "legendary"), ("void_emperor", "Void Emperor", "legendary"),
]
for key, label, rar in _TITLES:
    _add("title", key, label, rar, "title", {})

# ------------------------------------------------------------------ sticker packs + reactions + glyphs
STICKERS = {
    "blobs": ["happy", "sad", "angry", "love", "shock", "sleepy", "cool", "laugh"],
    "words": ["gg", "omg", "wow", "lol", "nice", "hype", "rip", "uwu"],
    "spirits": ["boo", "shy", "smug", "dizzy", "sick", "panic", "zen", "glee"],
    "sparks": ["heart", "star", "flame", "drop", "bolt", "ring", "crown", "sparkle"],
    "critters": ["cat_happy", "cat_sleepy", "cat_angry", "cat_love", "fox_wink", "fox_smug", "bun_shy", "bun_happy"],
}
PACK_META = {"blobs": ("Blobbies", 0), "words": ("Hype Words", 0), "spirits": ("Little Spirits", 600), "sparks": ("Living Sparks", 800), "critters": ("Critter Club", 1000)}
for pk, (label, price) in PACK_META.items():
    ITEMS[f"pack.{pk}"] = {"id": f"pack.{pk}", "kind": "pack", "name": label, "rarity": "common" if price == 0 else ("rare" if price < 900 else "epic"), "price": price, "min_rank": 0}

REACTIONS = ["like", "love", "haha", "wow", "sad", "angry", "fire", "clap"]
AVATAR_GLYPHS = ["initial", "fox", "cat", "wolf", "dragon", "ghost", "flower", "bolt", "flame", "moon", "star", "headphones", "sword", "crown", "heart", "skull", "bunny", "owl"]
BANNER_PRESETS = [f"p{i}" for i in range(1, 9)]
TITLE_COLORS = 20

KIND_SLOTS = ["frame", "name", "banner", "card", "title"]   # equip slots


def sticker_ok(code: str) -> bool:
    pack, _, sid = (code or "").partition(":")
    return sid in STICKERS.get(pack, [])
