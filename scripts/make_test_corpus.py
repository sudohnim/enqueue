#!/usr/bin/env python3
"""Generate a synthetic test corpus of 50 Markdown artifacts for search eval.

Deterministic: the same seed (recorded below) produces byte-identical files every run.

Categories (total 50):
  10  title-only        — a person's name appears ONLY in the title and never in the body
  10  paraphrase        — an idea described without the obvious search term for it
   5  rare-string       — each contains one rare exact string (e.g. ERR_QUEUE_4412)
   5  near-duplicate    — near-duplicates of each other with one meaningful difference
   5  long              — over 5000 words each
   5  short             — under 30 words each
  10  ordinary          — mixed length, no special property
"""

from __future__ import annotations

import json
import os
import random

SEED = 20250730
CORPUS_DIR = os.path.join(os.path.dirname(__file__), "..", "evals", "corpus")
MANIFEST_PATH = os.path.join(CORPUS_DIR, "MANIFEST.json")

# ---------------------------------------------------------------------------
# Lorum-substitute: a pool of paragraphs about plausible topics so the text
# looks real, reads naturally, and does not accidentally contain search terms
# that would interfere with the controlled categories.
# ---------------------------------------------------------------------------

PARAS: list[str] = [
    (
        "The morning light fell across the workbench in long amber stripes. "
        "Tools hung in neat rows on the pegboard, each one outlined in marker "
        "so anyone could see when something was missing. A half-finished chair "
        "sat in the centre, its joints clamped and waiting."
    ),
    (
        "The old warehouse had been divided into studios years ago, and the "
        "walls were thin enough that you could hear a potter's wheel through "
        "one and a typewriter through the next. The landlord called it an "
        "artist collective. The tenants called it a miracle they could still "
        "afford the rent."
    ),
    (
        "She walked the same route every morning, past the bakery where the "
        "second batch was always going in, past the school where the crossing "
        "guard knew her dog's name, and down to the pier where the gulls "
        "assembled on the railings like they were waiting for a meeting to start."
    ),
    (
        "The garden had been designed by someone who understood colour better "
        "than most painters. Nothing bloomed at the same time. The purple "
        "alliums gave way to orange lilies, and those to white japonica, so "
        "there was always something to look at and nothing ever clashed."
    ),
    (
        "Train stations have their own acoustics. The announcements bounce off "
        "the curved ceiling and arrive at your ears a split second late, "
        "layered over the hiss of brakes and the rumble of the next departure "
        "board flipping its tiles. It is a sound that says you are between "
        "places and that is all right."
    ),
    (
        "The kitchen was the warmest room in the house, not because of the "
        "radiator but because someone was always in it. A kettle simmering, a "
        "spoon resting against a bowl, the radio tuned to a station no one "
        "would admit to liking. The table had a permanent scatter of papers "
        "and pens."
    ),
    (
        "Clouds over the valley moved in a way that made you feel the planet "
        "was turning. They slid west in long grey sheets, and where the sun "
        "broke through, the light fell in columns that tracked across the "
        "fields like a slow searchlight. The farmers watched the sky the way "
        "sailors watch the sea."
    ),
    (
        "The bookshop occupied a narrow building that had once been a "
        "haberdasher's. The new owner kept the old wooden drawers and filled "
        "them with index cards instead of buttons. There was no computer. If "
        "you wanted a book, you asked, and she would go upstairs to look."
    ),
    (
        "Rain on a tin roof sounds different from rain on tiles. It is louder, "
        "closer, more insistent, as if the weather is trying to tell you "
        "something directly. The old shed had a tin roof and a dirt floor, and "
        "on stormy afternoons it was the best place in the world to sit and "
        "do nothing."
    ),
    (
        "The bridge was built in 1927 and nobody had painted it since. The "
        "ironwork had rusted to a deep brown that matched the autumn trees on "
        "either bank. Walking across it made a hollow sound, like footsteps on "
        "a drum, and if you stopped mid-span you could feel the whole thing "
        "vibrating gently with the water below."
    ),
    (
        "The observatory sat on a hill that was just high enough to clear the "
        "town lights. On a clear night you could see the Andromeda galaxy as "
        "a faint smudge, and the volunteers would point their telescopes at "
        "whatever wandered into view and explain what you were looking at in "
        "terms that made sense to someone who had never thought about it before."
    ),
    (
        "Ferries have a rhythm that planes do not. The hum of the engine, the "
        "smell of diesel and salt water, the way the deck tilts as you round "
        "the headland. Crossing on the ferry took forty minutes and by the end "
        "of it you felt you had actually travelled somewhere, not just been "
        "deposited."
    ),
    (
        "The library had a reading room with green glass lamps and leather "
        "chairs that creaked when you sat down. The newspapers were hung on "
        "wooden frames, and the older patrons read them in a specific order, "
        "starting with the obituaries to make sure they were still in the "
        "running."
    ),
    (
        "The canyon trail switchbacked down a cliff face that was layered like "
        "a stack of old encyclopedias. Each stratum was a different colour: "
        "ochre, grey, rust, chalk. The guide pointed out fossils embedded in "
        "the rock, things that had lived and died before the first humans drew "
        "a line on a cave wall."
    ),
    (
        "Markets in the old town square sold vegetables that still had soil on "
        "them, and the sellers knew who had grown each one. The prices were "
        "negotiated in a tone that sounded like arguing but was actually "
        "friendship. A woman sold honey from hives kept on a rooftop somewhere "
        "nearby."
    ),
    (
        "The canal paths were empty on weekday afternoons. A narrowboat drifted "
        "past every hour or so, its chimney smoking, and the occupant would "
        "wave without looking up from whatever they were reading. Ducks "
        "patrolled the edges in pairs, beaks skimming the surface for insects."
    ),
    (
        "The physics department occupied the top floor of a building that had "
        "been designed when everyone thought the future would look like a "
        "computing manual from 1968. The carpets were orange. The coffee "
        "machine made a sound like a small engine turning over. The blackboards "
        "were covered in equations that looked like art to anyone passing by."
    ),
    (
        "The lighthouse was automated now, but the keeper's cottage was still "
        "maintained, and every summer a painter stayed there for a month. The "
        "view from the upstairs window changed with every tide, and the light "
        "changed with every cloud, so no two paintings were ever the same."
    ),
    (
        "The bakery opened at five in the morning, and by six the first batch "
        "of sourdough was out of the oven. The baker had been doing this for "
        "thirty years and could tell from the sound of the loaf whether it had "
        "proved long enough. He was rarely wrong, and when he was, he gave "
        "that loaf away."
    ),
    (
        "The forest floor was soft with fallen needles, and the air smelled "
        "of resin and damp earth. Mushrooms grew in rings around the base of "
        "old pines, and deer paths wound between the trunks like a web that "
        "only the animals understood. In the deep parts the canopy blocked "
        "the sun and the temperature dropped several degrees."
    ),
    (
        "The clock tower in the centre of town had not worked since 1983, but "
        "nobody wanted to fix it because the silence was a landmark in itself. "
        "Visitors always asked about it, and locals always told a different "
        "story about why it stopped. The truth was lost somewhere between the "
        "versions."
    ),
    (
        "The pottery studio smelled of wet clay and woodsmoke. The wheel was "
        "in the corner under a window that looked out onto a courtyard full of "
        "ferns. Pots in various stages of completion lined the shelves, and "
        "the kiln ticked as it cooled from the morning firing."
    ),
    (
        "The harbour at dawn was a study in grey. Grey water, grey sky, grey "
        "stones, grey nets piled on grey docks. Then the first ray of sun hit "
        "the white hull of a fishing boat and suddenly everything had colour. "
        "The fishermen had been out since three and were already on their way "
        "back."
    ),
    (
        "The archive was in the basement of the municipal building, in filing "
        "cabinets that nobody had opened in decades. The archivist had been "
        "trying to digitise them for years, but every time she started a new "
        "project, the budget was cut. The oldest document she had found was a "
        "letter from 1842."
    ),
    (
        "The footpath along the ridge was exposed to the wind, and on gusty "
        "days you had to lean into it to stay upright. The view was worth it: "
        "the whole valley laid out below, farms and woods and the silver "
        "thread of a river that caught the light at certain times of day."
    ),
    (
        "The greenhouse was humid and warm even in winter, and the air was "
        "thick with the smell of damp earth and growing things. Tomatoes "
        "ripened on the vine, and herbs grew in long troughs along the walls."
        "The gardener kept a stool by the door where she sat to take her boots "
        "off at the end of the day."
    ),
    (
        "The print shop used a press from the 1950s that still worked perfectly. "
        "The owner liked the way it felt: the resistance of the handle, the "
        "sound of the plate meeting the paper, the smell of ink and solvents. "
        "She could have replaced it with a digital machine ten times faster, "
        "but she said the work would not be the same."
    ),
    (
        "The natural history museum had a room full of birds that nobody ever "
        "visited. Rows of cabinets with glass fronts, each containing a dozen "
        "species arranged by some nineteenth-century classification system. "
        "The labels were handwritten in ink and said things like 'collected "
        "near the upper Nile, 1897'."
    ),
    (
        "The carpenter's workshop was at the back of a yard that was full of "
        "wood offcuts that he was 'going to use one day'. The shavings on the "
        "floor were deep enough to muffle footsteps. He worked without music "
        "because he said he needed to hear what the wood was telling him."
    ),
    (
        "The vineyard terraces climbed a south-facing slope that caught the "
        "sun from mid-morning until evening. The soil was thin and chalky, and "
        "the vines looked scraggly up close, but the grapes that grew there "
        "had a concentration of flavour that made the winemaker drive an hour "
        "every day to check on them."
    ),
]

# ---------------------------------------------------------------------------
# Title pools
# ---------------------------------------------------------------------------

TITLE_ONLY_NAMES = [
    "Hypatia",
    "Ibn Sina",
    "Mary Anning",
    "Cheng Ho",
    "Rosalind Franklin",
    "Hypatia of Alexandria",
    "Sima Qian",
    "Emmy Noether",
    "Wangari Maathai",
    "Claudius Ptolemy",
]

TITLE_ONLY_TITLES = [
    "On the Writings of Hypatia",
    "The Canon of Ibn Sina",
    "Mary Anning and the Fossil Coast",
    "The Fleets of Cheng Ho",
    "Rosalind Franklin's Photograph 51",
    "Teaching the Works of Hypatia of Alexandria",
    "The Historical Records of Sima Qian",
    "Emmy Noether's Symmetry Theorem",
    "The Green Legacy of Wangari Maathai",
    "Mapping the Heavens with Claudius Ptolemy",
]

PARAPHRASE_DATA = [
    (
        "The quality of being able to continue despite difficulties",
        "grit",
        "Perseverance in everyday life is not about grand gestures. It is "
        "about the small decision to keep going when the easier path is to "
        "stop. Studies show that people who develop this trait tend to "
        "outperform those who rely on talent alone, because talent without "
        "the willingness to endure setbacks rarely reaches its potential.\n\n"
        "In practical terms, it means showing up on days when you would "
        "rather not, finishing what you start, and treating failure as "
        "information rather than a verdict. The people who succeed over the "
        "long term are rarely the most gifted. They are the ones who simply "
        "refuse to quit.",
    ),
    (
        "The ability to form a clear mental picture of something not present",
        "imagination",
        "Children build whole worlds out of cardboard boxes and bedsheets. "
        "Adults call this play, but it is actually a form of problem-solving "
        "that predates language. The capacity to see what does not yet exist "
        "is what drives every invention, every story, every plan that looks "
        "beyond the present moment.\n\n"
        "When we lose touch with this ability, the world becomes smaller. "
        "Problems become obstacles instead of invitations. The best engineers, "
        "artists, and leaders are those who have kept the childhood muscle of "
        "picturing something that has never been built and then working "
        "backward from that picture to figure out how to make it real.",
    ),
    (
        "The tendency to prefer what is familiar over what is new",
        "neophobia",
        "Marketers have long observed that consumers gravitate toward products "
        "they recognise even when an objectively better alternative is "
        "available. This bias is not limited to shopping. It affects hiring "
        "decisions, relationship choices, and the way we evaluate ideas in a "
        "meeting.\n\n"
        "Evolutionary psychology suggests this preference was once adaptive: "
        "the food you recognised was safe to eat, and the person you knew was "
        "safe to approach. But in a world of rapid change, this same instinct "
        "keeps us anchored to the mediocre simply because it is known.",
    ),
    (
        "The process of reducing uncertainty by gathering information",
        "inquiry",
        "Every field advances the same way: someone notices something they "
        "cannot explain, and instead of looking away, they lean in. This "
        "movement from confusion toward clarity is the engine behind every "
        "scientific discovery and every piece of good journalism.\n\n"
        "The best questioners share a set of habits. They ask what the "
        "evidence is before forming an opinion. They seek out people who "
        "disagree with them. They treat surprise as a signal that their model "
        "of the world needs updating, not as something to dismiss.",
    ),
    (
        "The state of being without a fixed home or regular employment",
        "vagrancy",
        "He carried everything he owned in a single bag. His route through "
        "the city followed the weather: doorways when it rained, park benches "
        "when it was dry. He knew which cafes would let him sit for an hour "
        "if he bought a cheap coffee, and which libraries had the warmest "
        "corners.\n\n"
        "People looked past him on the street. They assumed they understood "
        "his story, but the truth was more ordinary and more complicated. He "
        "had once had an apartment, a job, a routine. Then the routine broke, "
        "and he had not found a way to build a new one.",
    ),
    (
        "The practice of systematically preserving digital records",
        "archiving",
        "Every photograph, email, and document you create today will "
        "deteriorate faster than a medieval manuscript if nobody takes care "
        "of it. File formats become obsolete, storage media degrade, and "
        "metadata gets separated from the thing it describes.\n\n"
        "Libraries and museums have developed rigorous methods for keeping "
        "digital materials accessible across decades. The principles are "
        "straightforward: use open formats, store in multiple locations, "
        "verify integrity regularly, and document what you did so the next "
        "person can continue where you left off.",
    ),
    (
        "The technique of growing plants without soil using nutrient solutions",
        "hydroponics",
        "In a warehouse on the outskirts of the city, lettuce grows in stacks "
        "under purple LED lights. There is no dirt, no rain, and no soil "
        "microbes. The roots dangle in a shallow stream of water mixed with "
        "carefully measured minerals, and the whole system is monitored by "
        "sensors that adjust the light spectrum depending on the growth stage.",
    ),
    (
        "The philosophical view that the mind and body are separate substances",
        "dualism",
        "If the mind is not the brain, then what is it? This question has "
        "occupied philosophers for centuries. One school holds that thoughts, "
        "emotions, and consciousness belong to a different category of stuff "
        "than the physical matter of the skull and its neurons.\n\n"
        "The position has intuitive appeal: it certainly feels as though your "
        "thoughts are something other than electrical impulses. But the more "
        "we learn about how the brain works, the harder it becomes to locate "
        "the boundary where the physical ends and the mental begins.",
    ),
    (
        "The economic concept of allocating resources through voluntary exchange",
        "market efficiency",
        "When a farmer sells apples at a price that covers her costs and a "
        "customer pays that price because the apples are worth more to him "
        "than the money, both parties walk away better off. This simple "
        "insight is the foundation of a vast edifice of economic theory.\n\n"
        "Under ideal conditions, the repeated interactions of buyers and "
        "sellers produce prices that reflect the true scarcity of goods. "
        "But the conditions are rarely ideal, and the question of what happens "
        "when information is uneven or competition is weak occupies the "
        "majority of modern economic research.",
    ),
    (
        "The study of what happens after death in various cultural traditions",
        "afterlife beliefs",
        "Every human culture has had to confront the fact that people stop "
        "living and have devised some story about what happens next. These "
        "stories vary enormously: reincarnation, ancestor realms, heavenly "
        "gardens, absorption into a cosmic whole, or simple extinction.\n\n"
        "Despite the diversity, certain patterns recur. There is often a "
        "journey, a judgement, a transformation. The common thread is that "
        "death is rarely treated as a simple end. It is a passage, a door, "
        "a change of state. The stories we tell about it reveal more about "
        "how we live than about what awaits.",
    ),
]

RARE_STRINGS = [
    "ERR_QUEUE_4412",
    "XKCD_REF_9274",
    "API_KEY_PLACEHOLDER_abc",
    "FACTORIAL_OVERFLOW_64",
    "Z40_GHOST_CONNECTION",
]

NEAR_DUP_BASE = (
    "The co-op was founded in 1987 by three friends who wanted to buy "
    "organic vegetables without going through a distributor. It started as a "
    "weekly collection from a single farm and grew into a network of forty "
    "producers serving six hundred households. The governance was flat: every "
    "member got one vote, and decisions were made at monthly meetings that "
    "sometimes ran past midnight."
)

NEAR_DUP_VARIANTS = [
    NEAR_DUP_BASE
    + "\n\nThe key disagreement was over whether to open a second location across the river.",
    NEAR_DUP_BASE
    + "\n\nThe key disagreement was over whether to start a delivery service for elderly members.",
    NEAR_DUP_BASE + "\n\nThe key disagreement was over whether to invest in a refrigerated truck.",
    NEAR_DUP_BASE
    + "\n\nThe key disagreement was over whether to accept produce from non-organic farms.",
    NEAR_DUP_BASE + "\n\nThe key disagreement was over whether to hire a paid coordinator.",
]

LONG_TOPICS = [
    "The development of the邮政 service in the 19th century",
    "How tides work and why they matter to coastal communities",
    "A complete beginner's guide to keeping sourdough starter alive",
    "The history of colour pigments used in European painting",
    "Why migratory birds travel thousands of miles each year",
]

LONG_BODIES = [
    (
        "The postal service did not start with stamps. It started with "
        "messengers who ran between cities carrying bags of letters, and the "
        "person who received the letter paid for delivery. This meant that "
        "only the wealthy could reliably send and receive correspondence, and "
        "even then the service was unpredictable.\n\n"
        "The transformation began in the nineteenth century with the "
        "introduction of the postage stamp. For the first time, the sender "
        "paid in advance, and the price was uniform regardless of distance. "
        "This seemingly small change had enormous consequences. It made it "
        "possible for ordinary people to stay in touch across long distances. "
        "Newspapers could be mailed to subscribers. Commerce could rely on "
        "written orders and receipts.\n\n"
        "The expansion of the postal network required infrastructure that we "
        "now take for granted: sorting offices, mail coaches, railway carriages "
        "converted into travelling post offices where letters were sorted en "
        "route. The system was so efficient that in some countries, mail "
        "arrived faster in the nineteenth century than it does today.\n\n"
        "The legacy of this era is visible in the way we still address "
        "envelopes, the design of postboxes, and the universal service "
        "obligation that requires postal operators to deliver to every address "
        "regardless of how remote. Digital communication has reduced the "
        "volume of physical mail, but the infrastructure built during this "
        "period still carries parcels, official documents, and the occasional "
        "handwritten letter that means more than any email could."
    ),
    (
        "Tides are the slow breathing of the ocean. They rise and fall on a "
        "cycle that is predictable decades in advance, yet the mechanism that "
        "drives them is subtle enough that it took humanity thousands of years "
        "to understand it correctly.\n\n"
        "The gravitational pull of the moon is the primary driver. The moon's "
        "gravity pulls water toward it, creating a bulge on the side of the "
        "Earth facing the moon. A corresponding bulge forms on the opposite "
        "side because the inertia of the water pulls it away from the Earth. "
        "As the Earth rotates, a given point on the surface passes through "
        "both bulges each day, producing two high tides and two low tides.\n\n"
        "The sun also contributes, though its effect is about half as strong "
        "because it is much farther away. When the sun and moon are aligned, "
        "their gravitational forces combine to produce spring tides, which "
        "are higher and lower than average. When they are at right angles, "
        "neap tides result, with a smaller range.\n\n"
        "The shape of the coastline matters enormously. In narrow channels, "
        "the same volume of water has to squeeze through a smaller space, so "
        "the tidal range can be amplified. The Bay of Fundy in Canada "
        "experiences the largest tides in the world, with a range of over "
        "fifteen metres. In enclosed seas like the Mediterranean, the tidal "
        "range is barely noticeable.\n\n"
        "Coastal communities have always organised their lives around the "
        "tides. Fishermen know when to leave harbour. Harbour masters know "
        "when the water will be deep enough for ships to enter. Foragers "
        "know when the tide will expose the richest parts of the shoreline. "
        "The tide table is one of the oldest published reference works still "
        "in regular use."
    ),
    (
        "Keeping a sourdough starter alive is simpler than most people think. "
        "You need flour, water, a jar, and the patience to wait while "
        "microorganisms do what they have been doing for millions of years.\n\n"
        "Start with whole grain flour. Rye or whole wheat works best because "
        "they carry more of the bacteria and yeast that drive fermentation. "
        "Mix equal parts flour and water by weight in a clean jar. Cover "
        "loosely and leave at room temperature. The next day, discard half "
        "and feed again with fresh flour and water.\n\n"
        "After three or four days, you will see bubbles. After a week, the "
        "starter should be doubling in volume between feedings. This is a "
        "sign that the yeast population is strong enough to leaven bread. "
        "The starter will smell sour, which is good, and fruity, which is "
        "also good. If it smells like acetone, it needs more frequent "
        "feeding.\n\n"
        "Once established, a starter can be kept in the refrigerator and "
        "fed once a week. If you bake regularly, keep it on the counter and "
        "feed it daily. The ratio can be adjusted: a stiffer starter ferments "
        "more slowly and produces a milder flavour. A wetter starter ferments "
        "faster and produces a more pronounced tang.\n\n"
        "The microorganisms in your starter are a reflection of your local "
        "environment. A starter made in San Francisco will taste different "
        "from one made in Tokyo, even with the same flour and water. This is "
        "why bakers who move cities often restart their starter from scratch "
        "to capture the local microbes.\n\n"
        "If your starter stops bubbling, do not throw it away. Feed it twice "
        "a day for a few days and it will almost always recover. The only "
        "thing that kills a starter is mould, which means the balance of "
        "bacteria and yeast has gone wrong. If you see pink or orange spots, "
        "start over."
    ),
    (
        "Before synthetic pigments, every colour had a story. Ultramarine was "
        "ground from lapis lazuli, a stone more expensive than gold, mined in "
        "Afghanistan and shipped across Asia and the Mediterranean. "
        "Artists reserved it for the robes of the Virgin Mary, the most "
        "important blue in a painting.\n\n"
        "Red came from the cochineal insect, which was dried, crushed, and "
        "treated with alum to produce a pigment so vibrant that it was traded "
        "across the Atlantic. The Spanish guarded the source for centuries, "
        "passing off the dye as a seed rather than an insect to protect their "
        "monopoly.\n\n"
        "Yellow was made from ochre, a clay coloured by iron oxide, or from "
        "the sap of the buckthorn plant. The most vivid yellow came from "
        "orpiment, a arsenic sulphide mineral that was poisonous to grind and "
        "prone to darkening over time when mixed with other pigments.\n\n"
        "Green was the hardest colour to get right. Verdigris, made by "
        "exposing copper to vinegar fumes, was brilliant but unstable and "
        "corroded the paper or canvas over time. Terre verte was stable but "
        "muddy. Malachite was bright but expensive.\n\n"
        "The nineteenth century changed everything. Chemists discovered how "
        "to synthesise pigments from coal tar, producing colours that were "
        "brighter, cheaper, and more stable than anything available before. "
        "Mauveine, the first synthetic dye, was discovered by accident in "
        "1856 and sparked a revolution that transformed fashion, printing, "
        "and art.\n\n"
        "Modern pigments are tested for lightfastness, toxicity, and "
        "consistency. An artist today can buy a tube of paint knowing exactly "
        "how it will behave and how long it will last. But something was lost "
        "when pigments became industrial products. The connection between the "
        "colour on the canvas and the earth it came from became invisible, "
        "and painting became a little less magical."
    ),
    (
        "Every autumn, billions of birds leave their breeding grounds in the "
        "northern hemisphere and fly south. Some travel a few hundred "
        "kilometres. Others cross oceans and continents, navigating by "
        "stars, magnetic fields, and landmarks that no human could perceive.\n\n"
        "The Arctic tern holds the record for the longest migration. These "
        "small birds fly from the Arctic to the Antarctic and back each year, "
        "a round trip of roughly seventy thousand kilometres. They experience "
        "more daylight than any other creature on Earth, seeing two summers "
        "in a single year.\n\n"
        "How do they do it? The leading theory is that birds use multiple "
        "navigation systems in parallel. During the day, they use the position "
        "of the sun. At night, they use the stars. When neither is visible, "
        "they sense the Earth's magnetic field through special proteins in "
        "their eyes that respond to magnetic fields by changing the bird's "
        "visual field.\n\n"
        "Young birds on their first migration often travel separately from "
        "adults, which means the route is partly instinctive rather than "
        "learned. They know which direction to fly and when to stop, but they "
        "may not know the best places to rest and feed until they have made "
        "the journey once.\n\n"
        "Climate change is disrupting migration patterns. Warmer temperatures "
        "mean that insects emerge earlier in the spring, and birds that "
        "arrive at their breeding grounds on the old schedule find less food "
        "waiting for them. Some species have shifted their timing, but others "
        "cannot adjust fast enough, and their populations are declining as a "
        "result.\n\n"
        "Conservation efforts now focus on protecting stopover sites along "
        "migration routes. A bird that cannot find food and shelter during its "
        "journey will not complete it, no matter how strong its navigation "
        "system is. Protecting these sites requires international cooperation "
        "because the birds cross borders that humans have drawn in places the "
        "birds have never recognised."
    ),
]

SHORT_BODIES = [
    "The train arrived at 8:47. She was the only one who got off.",
    "It worked perfectly until someone read the manual.",
    "He said it would never fly. Then it flew.",
    "The last page was blank. That was the point.",
    "Three notes. A pause. Then the room began to listen.",
]

ORDINARY_TOPICS = [
    "Notes on canoe repair",
    "A recipe for lentil soup",
    "Thoughts on the film I watched last night",
    "Bookmark: CSS Grid layout reference",
    "Packing list for the coast trip",
    "Ideas for the community garden plot",
    "Phone number for the plumber (recommended)",
    "Quick reference: bash one-liners",
    "Why I switched from a notebook to digital notes",
    "Things to fix before winter",
]

ORDINARY_BODIES = [
    (
        "Canoe repair is mostly about finding the leak and patching it. "
        "Fiberglass cloth and epoxy resin are the standard materials. Sand "
        "the area around the damage, cut a patch that overlaps by at least "
        "two centimetres, wet it out with epoxy, and let it cure overnight. "
        "For small holes in Royalex canoes, G/flex epoxy works better because "
        "it stays slightly flexible."
    ),
    (
        "Lentil soup that actually tastes good: saute one diced onion in "
        "olive oil until translucent. Add two chopped carrots, two celery "
        "stalks, and three cloves of garlic. Cook for five minutes. Add one "
        "cup of brown lentils, one can of diced tomatoes, and six cups of "
        "vegetable stock. Simmer for thirty minutes. Season with cumin, "
        "smoked paprika, salt, and pepper. Stir in a handful of spinach at "
        "the end."
    ),
    (
        "Watched that documentary about the typewriter repairman in Brooklyn. "
        "There is something moving about someone who has spent forty years "
        "learning to fix a machine that almost nobody uses anymore. He keeps "
        "a drawer of parts salvaged from machines that were thrown away. The "
        "sound of a fully restored typewriter is a very specific kind of "
        "satisfaction."
    ),
    (
        "CSS Grid: container needs display: grid. Columns defined with "
        "grid-template-columns. Rows with grid-template-rows. Gap between "
        "items with gap. Items can span multiple columns or rows with "
        "grid-column and grid-row. The fr unit is fractional and fills "
        "remaining space. Auto-fit and minmax() together create responsive "
        "layouts without media queries."
    ),
    (
        "Coast trip packing: swimsuit, towel, sunscreen (reef-safe), "
        "sunglasses, hat, sandals, rain jacket, warm layer for evening, "
        "water bottle, snacks, book, headphones, camera, charger, dry bag "
        "for phone. Check tide times before swimming at any beach that is "
        "not patrolled. Rip currents are the main danger."
    ),
    (
        "Community garden plot for next season: expand the herb bed, add "
        "a second compost bin, plant tomatoes along the south wall where "
        "they will get the most sun, try growing okra this year. Needs a "
        "watering schedule for when I am away. The automatic timer was a "
        "good investment."
    ),
    (
        "Plumber is at 555-0199. She fixed the kitchen sink last time and "
        "it cost less than I expected. She was here by nine and done by ten. "
        "Recommended by three different neighbours, which is a good sign. "
        "Does not charge for estimates."
    ),
    (
        'Bash one-liners I keep forgetting: find . -name "*.py" -exec wc -l '
        "{}+ to count lines in Python files. history | awk '{print $2}' | "
        "sort | uniq -c | sort -rn | head to see most-used commands. "
        "ffmpeg -i input.mp4 -vf scale=1280:720 output.mp4 to resize a video."
    ),
    (
        "I switched from a paper notebook to Obsidian about six months ago. "
        "The main advantage is search. I used to spend minutes flipping "
        "through pages looking for something I wrote down two weeks ago. Now "
        "it takes seconds. The main disadvantage is that writing by hand "
        "felt more deliberate and I remembered things better. I am trying a "
        "hybrid: handwritten daily notes, digital for reference."
    ),
    (
        "Before winter: insulate the attic hatch, seal the gaps around the "
        "front door, drain the outdoor tap, service the boiler, check the "
        "chimney for bird nests, buy a new shovel to replace the one that "
        "broke last year, stock up on salt for the steps, test the carbon "
        "monoxide detector."
    ),
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_rng = random.Random(SEED)


def _repeat_to_wordcount(text: str, target: int) -> str:
    """Pad text by repeating and varying it until it reaches target words."""
    words = text.split()
    if len(words) >= target:
        return " ".join(words[:target])
    chunks = [text]
    while len(" ".join(chunks).split()) < target:
        chunk = _rng.choice(PARAS)
        chunks.append(chunk)
    full = " ".join(chunks)
    return " ".join(full.split()[:target])


def make_title_only(idx: int) -> tuple[str, str, str]:
    """Returns (filename, title, body). Name appears only in title."""
    name = TITLE_ONLY_NAMES[idx]
    title = TITLE_ONLY_TITLES[idx]
    body_parts = _rng.sample(PARAS, 3)
    body = "\n\n".join(body_parts)
    # Ensure name never appears in the body
    for n in name.split():
        body = body.replace(n, "[omitted]")
    filename = f"title_only_{idx+1:04d}.md"
    return filename, f"# {title}", body


def make_paraphrase(idx: int) -> tuple[str, str, str]:
    """Returns (filename, title, body). Obvious term does not appear."""
    description, term, body_text = PARAPHRASE_DATA[idx]
    title = f"The meaning of {description.lower()}"
    # Ensure the forbidden term never appears
    body = body_text.replace(term, "[described differently]")
    # Also ensure variations don't leak
    body = body.replace(term.capitalize(), "[described differently]")
    filename = f"paraphrase_{idx+1:04d}.md"
    return filename, f"# {title}", body


def make_rare_string(idx: int) -> tuple[str, str, str]:
    """Returns (filename, title, body) containing one rare exact string."""
    rare = RARE_STRINGS[idx]
    title = f"Debug log: {rare}"
    parts = _rng.sample(PARAS, 2)
    body = "\n\n".join(parts)
    # Insert the rare string naturally
    body = body + f"\n\nEncountered during testing: `{rare}`. Further investigation required."
    filename = f"rare_string_{idx+1:04d}.md"
    return filename, f"# {title}", body


def make_near_duplicate(idx: int) -> tuple[str, str, str]:
    """Returns (filename, title, body) — one of five near-duplicates."""
    title = f"The co-op decision, version {idx + 1}"
    body = NEAR_DUP_VARIANTS[idx]
    filename = f"near_dup_{idx+1:04d}.md"
    return filename, f"# {title}", body


def make_long(idx: int) -> tuple[str, str, str]:
    """Returns (filename, title, body) — over 5000 words."""
    title = LONG_TOPICS[idx]
    body = _repeat_to_wordcount(LONG_BODIES[idx], 5100)
    filename = f"long_{idx+1:04d}.md"
    return filename, f"# {title}", body


def make_short(idx: int) -> tuple[str, str, str]:
    """Returns (filename, title, body) — under 30 words total."""
    title = SHORT_BODIES[idx]
    body = title
    filename = f"short_{idx+1:04d}.md"
    return filename, f"# Short: {title}", body


def make_ordinary(idx: int) -> tuple[str, str, str]:
    """Returns (filename, title, body) — mixed length, no special property."""
    title = ORDINARY_TOPICS[idx]
    body = ORDINARY_BODIES[idx]
    filename = f"ordinary_{idx+1:04d}.md"
    return filename, f"# {title}", body


# ---------------------------------------------------------------------------
# Generators — deterministic via SEED
# ---------------------------------------------------------------------------

CATEGORY_GENERATORS = {
    "title-only": (make_title_only, 10),
    "paraphrase": (make_paraphrase, 10),
    "rare-string": (make_rare_string, 5),
    "near-duplicate": (make_near_duplicate, 5),
    "long": (make_long, 5),
    "short": (make_short, 5),
    "ordinary": (make_ordinary, 10),
}


def generate() -> list[dict]:
    """Generate all artifacts. Returns the manifest entries."""
    try:
        os.makedirs(CORPUS_DIR, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"could not create corpus dir {CORPUS_DIR}: {e}") from e
    manifest_entries: list[dict] = []

    for category, (generator, count) in CATEGORY_GENERATORS.items():
        for i in range(count):
            filename, title, body = generator(i)
            artifact_id = filename.replace(".md", "")

            filepath = os.path.join(CORPUS_DIR, filename)
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(title + "\n\n" + body)
            except OSError as e:
                raise RuntimeError(f"could not write {filepath}: {e}") from e

            entry: dict = {
                "id": artifact_id,
                "filename": filename,
                "category": category,
            }

            if category == "title-only":
                entry["name"] = TITLE_ONLY_NAMES[i]
            elif category == "paraphrase":
                _, term, _ = PARAPHRASE_DATA[i]
                entry["forbidden_term"] = term
            elif category == "rare-string":
                entry["rare_string"] = RARE_STRINGS[i]
            elif category == "near-duplicate":
                entry["variant"] = i + 1

            manifest_entries.append(entry)

    try:
        with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
            json.dump({"seed": SEED, "artifacts": manifest_entries}, f, indent=2)
    except OSError as e:
        raise RuntimeError(f"could not write manifest {MANIFEST_PATH}: {e}") from e

    return manifest_entries


if __name__ == "__main__":
    entries = generate()
    print(f"Generated {len(entries)} artifacts into {CORPUS_DIR}")
    for entry in entries:
        print(f"  {entry['id']:40s} {entry['category']}")
