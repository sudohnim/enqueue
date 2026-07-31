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

or see raw retrieval with `enq search "query"`. To switch back to Qdrant
later, run `ENQ_VECTOR_STORE=qdrant .venv/bin/enq reindex`; the Qdrant index
is untouched by the sqlite-vec runs.

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
Answer: ____
Actual response: ____

## Test 2 - Find something when you only half remember it

Think of something you saved but cannot remember the exact words of.
Search using your own words for it, not the words in the item.

Example: if you saved an article about staying calm under pressure,
search for "keeping cool when things go wrong".

Question: Did the right item come up? (What was my max squat?)
Answer: GOOD
ACtual REsponse: Your max squat is 350, from your stats updated 7/6.

---

**Engine 2: sqlite-vec**
Question: Did the right item come up? (What was my max squat?)
Answer: ____
Actual response: ____

## Test 3 - Find something by an exact code or unusual word

Think of an item that has an unusual word in it. A product name,
an error code, a made-up word, a street name.
Search for exactly that word.

Question: Did the right item come up? (What was the Lumo mascot?)
Answer: BAD
Actual REsponse You haven't saved anything that says what the Lumo mascot was. The only Lumo-related note is about the visual redesign of Lumo 2.0, and it doesn't mention a mascot.

---

**Engine 2: sqlite-vec**
Question: Did the right item come up? (What was the Lumo mascot?)
Answer: ____
Actual response: ____

## Test 4 - Find something by its title only

Pick an item whose title says what it is, but where the words in the
title do not appear in the item itself.
Search using words from the title.

Question Did the right item come up? (Do we have anything regarding revisiting the commons?)
Answer: GOOD
Actual Response: Yes, you have a saved item called "Revisiting the Commons: Local Lessons, Global Challenges." It's a 1999 Science review article by Elinor Ostrom, Joanna Burger, Christopher B. Field, Richard B. Norgaard, and David Policansky, revisiting Hardin's "Tragedy of the Commons" and discussing sustainable management of common-pool resources.

Question: How many pages is Commitment and Community" and it answwered:"Your saved materials don't specify the total page count of Commitment and Community.
Answer: BAD
Actual REsponse (within the artifact): The saved passages show page numbers 3, 5, 6, 7, 8, 9, 10, and 11 from the book, but they don't state the book's total number of pages.
Actual REsponse (within Everything): Your saved materials don't specify the total page count of Commitment and Community.

---

**Engine 2: sqlite-vec**
Question: Did the right item come up? (Do we have anything regarding revisiting the commons?)
Answer: ____
Actual response: ____

Question: How many pages is Commitment and Community?
Answer: ____
Actual response: ____

## Test 5 - Search for something you never saved

Search for something you are certain you never saved.
NOTE: I did this twice

Question: Did it correctly show nothing, or almost nothing? (Do I have notes regarding making my own sourdough bread?)
Answer: GOOD
Actual REsponse: You haven't saved anything about making your own sourdough bread. The notes you have cover medieval agriculture economics, a RAG explanation, and utopian communities, but nothing on sourdough.

---

**Engine 2: sqlite-vec**
Question: Did it correctly show nothing, or almost nothing? (Do I have notes regarding making my own sourdough bread?)
Answer: ____
Actual response: ____

## Test 6 - Same words, different order

Pick any item. Search for three words from it, in the wrong order.

Did the right item still come up?
Question: What is a boxer's advantage?
Answer: GOOD
Actual REsponse: A boxer's greatest advantage comes from their sparring partner—adversity is treated as input rather than obstacle, and the partner is the mechanism by which that adversity compounds, so what looks like harm is actually the process working.

---

**Engine 2: sqlite-vec**
Question: What is a boxer's advantage?
Answer: ____
Actual response: ____

## Test 7 - Does it feel fast

Do five searches in a row. Count roughly how long each takes.

Did every search feel instant, or did any of them make you wait?
Answer: Each took around 5-10 seconds

---

**Engine 2: sqlite-vec**
Answer: ____ (for reference, the automated eval measured p95 = 21 ms per query)

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
