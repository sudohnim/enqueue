# Testing the search by hand

You do not need to know anything about how this works. You are just
checking whether search finds the right things. It takes about 15 minutes.

## Before you start

1. Open the app.
2. Make sure your library has at least 20 saved items in it.
3. Have this page open so you can write down what happens.

To run against the new engine (one-time setup):

    cd ~/enqueue
    ENQ_VECTOR_STORE=sqlite-vec .venv/bin/enq reindex

Then ask questions with:

    ENQ_VECTOR_STORE=sqlite-vec .venv/bin/enq chat "your question"

or see raw retrieval with `enq search "query"`.

For every test below, write one of these three answers:
  GOOD    - the thing I wanted was the first result
  OK      - the thing I wanted was somewhere in the first five results
  BAD     - the thing I wanted was not in the first five results

The answers recorded below were against the old engine (Qdrant). After the
engine switch (see Before you start), re-run each test and record the
sqlite-vec answers in the "Engine 2: sqlite-vec" blocks.

## Test 1 - Find something by a person's name

Think of a person who is mentioned in only one of your saved items.
Search for just their name.

Did the item about that person come up?
Question: Did you find anything about Kanter?
Answer:  GOOD
Actual Response:Yes, you have several excerpts from Rosabeth Moss Kanter's 1972 book 'Commitment and Community: Communes and Utopias in Sociological Perspective' (metadata shows Harvard, Cambridge, Mass.). The saved pages cover commitment mechanisms (e.g., investment and irreversibility), problems of contemporary communes, a table on leadership prerogatives and immunities, and reflections on how utopian communities relate to the outside society. So this is definitely from Kanter.

---

**Engine 2: sqlite-vec**
Question: Did you find anything about Kanter?
Answer: GOOD
Actual response: Yes — the saved material includes pages from Rosabeth Moss Kanter's book *Commitment and Community: Communes and Utopias in America* (1972). The excerpts cover her analysis of utopian communities, including concepts like mortification, isomorphism, and leadership dynamics, as well as appendix material on methodology and data.

## Test 2 - Find something when you only half remember it

Think of something you saved but cannot remember the exact words of.
Search using your own words for it, not the words in the item.

Example: if you saved an article about staying calm under pressure,
search for "keeping cool when things go wrong".

Question: What was my max squat?
Answer: GOOD
ACtual REsponse: Your max squat is 350, from your stats updated 7/6.

---

**Engine 2: sqlite-vec**
Question: What was my max squat?
Answer: GOOD
Actual response:Your squat is listed at 350, per the stats in your workout note (updated 7/6). For context, that note also tracks Bench at 240, Deadlift at 410, Press at 167, and Pedley Row at 190, and the squat number appears to be the training max your 5/3/1 percentages are based on.

## Test 3 - Find something by an exact code or unusual word

Think of an item that has an unusual word in it. A product name,
an error code, a made-up word, a street name.
Search for exactly that word.

Question: Did the right item come up? (What was the Lumo mascot?)
Answer: BAD
Actual REsponse You haven't saved anything that says what the Lumo mascot was. The only Lumo-related note is about the visual redesign of Lumo 2.0, and it doesn't mention a mascot.

---

**Engine 2: sqlite-vec**
Question: What was the Lumo mascot?
Answer: OK
Actual response: Lumo was the mascot of Proton's Lumo AI assistant — a character created to be the face of the product and to embody its values: private, approachable, and easy to use, described as 'a trusted and independent mascot that protects your personal conversations.' The original design was playful and welcoming — apparently kitten-like, since the article about the Lumo 2.0 redesign is headed 'Lumo's not a kitten anymore.' With Lumo 2.0, Proton chose to evolve the character rather than replace it, giving it a stronger, more confident presence to match the product's growing sophistication, plus new illustrations, subtle reactive animations, and a sticker library for messaging platforms. The mascot's name stayed Lumo even as the wordmark changed to 'Lumo AI.'

## Test 4 - Find something by its title only

Pick an item whose title says what it is, but where the words in the
title do not appear in the item itself.
Search using words from the title.

Question Do we have anything regarding revisiting the commons?
Answer: GOOD
Actual Response: Yes, you have a saved item called "Revisiting the Commons: Local Lessons, Global Challenges." It's a 1999 Science review article by Elinor Ostrom, Joanna Burger, Christopher B. Field, Richard B. Norgaard, and David Policansky, revisiting Hardin's "Tragedy of the Commons" and discussing sustainable management of common-pool resources.

Question: How many pages is Commitment and Community" and it answwered:"Your saved materials don't specify the total page count of Commitment and Community.
Answer: BAD
Actual REsponse (within the artifact): The saved passages show page numbers 3, 5, 6, 7, 8, 9, 10, and 11 from the book, but they don't state the book's total number of pages.
Actual REsponse (within Everything): Your saved materials don't specify the total page count of Commitment and Community.

---

**Engine 2: sqlite-vec**
Question: Do we have anything regarding revisiting the commons?
Answer: GOOD
Actual response: Yes — you've saved Ostrom, Burger, Field, Norgaard, and Policansky's 1999 Science article "Revisiting the Commons: Local Lessons, Global Challenges," which is exactly on point. Written thirty years after Garrett Hardin's "The Tragedy of the Commons" (which you also have, at least as a citation), it reassesses Hardin's claim that commons users are locked into an inevitable process of destroying the resources they depend on. The authors' core argument is that Hardin understated the range of solutions: people have self-organized to manage common-pool resources for thousands of years, and neither government ownership nor privatization — Hardin's two remedies — is immune to failure. They give the striking example of a satellite image across northern China, Mongolia, and southern Siberia: Mongolia's traditional group-property pastoralist institutions, with large-scale seasonal movement, show far less grassland degradation than the state-run collectives on the Russian and Chinese sides. The hardest problems, they argue, are now global in scale — international river basins, large marine ecosystems, global climate — and require cooperation across nested institutions at local, national, and international levels. Their closing thought is that institutional diversity may matter as much for long-term survival as biological diversity.

Question: How many pages is Commitment and Community?
Answer: GOOD
Actual response: Nothing you saved states the total page count directly, but your copy of Kanter's Commitment and Community (Harvard, 1972) can be bounded from what was captured: the scan runs to at least page 322, and the book's own numbered pages reach at least 264, where the Appendix on sample and methodology begins. So the digitized copy is roughly 320+ scan pages, with the main text and appendix extending past page 264 — but the exact final numbered page isn't shown in what you've saved

## Test 5 - Search for something you never saved

Search for something you are certain you never saved.
NOTE: I did this twice

Question: Do I have notes regarding making my own sourdough bread?
Answer: GOOD
Actual REsponse: You haven't saved anything about making your own sourdough bread. The notes you have cover medieval agriculture economics, a RAG explanation, and utopian communities, but nothing on sourdough.

---

**Engine 2: sqlite-vec**
Question: Do I have notes regarding making my own sourdough bread?
Answer: GOOD
Actual response: You haven't saved anything about making your own sourdough bread. Bread does come up in your collection, but only in passing and in unrelated contexts: a piece on medieval agriculture discusses grain storage, bread prices, and caloric content, and a book on utopian communes mentions that baking bread held spiritual meaning for the Shakers. Neither contains anything about actually baking bread yourself — no starter, recipe, or technique — and nothing in your notes touches on sourdough at all.

## Test 6 - Same words, different order

Pick any item. Search for three words from it, in the wrong order.

Did the right item still come up?
Question: What is a boxer's advantage?
Answer: GOOD
Actual REsponse: A boxer's greatest advantage comes from their sparring partner—adversity is treated as input rather than obstacle, and the partner is the mechanism by which that adversity compounds, so what looks like harm is actually the process working.

---

**Engine 2: sqlite-vec**
Question: What is a boxer's advantage?
Answer: GOOD
Actual response: According to what you've saved, a boxer's greatest advantage is their sparring partner. The idea is that adversity functions as input rather than obstacle — the partner is the mechanism by which that adversity compounds into growth. What looks like harm (getting hit) is actually the process working as intended.

## Test 7 - Does it feel fast

Do five searches in a row. Count roughly how long each takes.

Did every search feel instant, or did any of them make you wait?
Answer: Each took around 5-10 seconds

---

**Engine 2: sqlite-vec**
Answer: Same speed (for reference, the automated eval measured p95 = 21 ms per query)

---

## Test 8 - The same search on two devices

Only do this test if you have the app on more than one device.
Do the exact same search on both.

Did you get the same results in the same order?
Answer: ______

---

**Engine 2: sqlite-vec**
(Skip this test unless you have the app on a second device.)
Answer: ____

---

## When you are done

Send back your eight answers.

If you wrote BAD for any test, also write down:

- what you searched for
- what you expected to find
- what came up instead

That last part is the most useful thing you can give us.

---

**Outcome (Phase 20, recorded 2025):** sqlite-vec matched or beat Qdrant on every
test above (Test 3 went BAD to OK, the Test 4 second-query went BAD to GOOD, the
rest stayed GOOD; Test 7 latencies were equal). The bake-off then switched the
engine to sqlite-vec and removed the Qdrant backend, so "Engine 2: Qdrant" above
no longer exists - there is nothing to switch back to.
