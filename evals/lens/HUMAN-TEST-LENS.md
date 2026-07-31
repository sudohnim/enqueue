# Testing the topic view by hand

You do not need to know anything about how this works. You are checking
whether asking for a topic shows you the right things. It takes about 10 minutes.

## Before you start

1. Open the app.
2. Make sure you have at least 30 saved items.
3. Have this page open so you can write your answers.

For each test write one of these:
  GOOD    - it did what I expected
  OK      - mostly right, a few odd ones
  BAD     - it got this wrong

## Test 1 - A topic you have a lot about

Think of a subject you have saved several things about.
Type it in as a topic, in your own words.

Did the related section contain the things you were thinking of?
Answer: ______

## Test 2 - Did anything obvious get missed

Look at the second section, the things it said were not related.
Read through the first ten.

Did anything in there clearly belong in the topic?
Answer: ______
If yes, write down what it was: ______

## Test 3 - Did anything wrong sneak in

Look at the related section.

Was anything in there clearly not about the topic?
Answer: ______
If yes, write down what it was: ______

## Test 4 - Does it explain itself

Look at the notes shown under the related items.

Do they explain why that item is about the topic, in a way that makes sense?
Answer: ______

## Test 5 - A topic you have nothing about

Type in a topic you are sure you have saved nothing about.

Did it tell you clearly that nothing matched, instead of showing random
unrelated things?
Answer: ______

## Test 6 - Say it a different way

Take the topic from Test 1 and type it again using different words
that mean the same thing.

Did you get roughly the same related items?
Answer: ______

## Test 7 - Does it feel fast

Type a brand new topic and count how long until you see the two sections.
Then clear it and type the same topic again.

Was the first one acceptable, and the second one instant?
Answer: ______

## Test 8 - Nothing got changed

Clear the topic and go back to your normal view.

Is everything where it was before, in the same order, with nothing moved
to the top or marked as recently touched?
Answer: ______

## When you are done

Send back your eight answers.

For anything you marked BAD, also write down:

- the topic you typed
- what you expected to see
- what you saw instead

That last part is the most useful thing you can give us.

## Running it without the app (API-only)

The wall UI for the lens is currently reverted; the endpoint is fully
live. Every test below works against the engine directly. The engine is
http://127.0.0.1:8787 when running normally.

A topic split is a POST with an SSE reply:

    curl -N -X POST http://127.0.0.1:8787/lens \
      -H 'Content-Type: application/json' \
      -d '{"lens":"YOUR TOPIC","judge_top":10}'

The first event (stage: split) lists related/other/pinned artifact ids
and titles immediately. Judgment events follow with the placard under
the `placard` field. The last event (stage: done) has the totals.

The eight tests map like this:

- Test 1 and 6 (right things, rephrased): read the `related` ids and
  titles in the split event. Try a second topic that means the same
  thing and compare which ids came back.
- Test 2 (misses): read the `other` list, first ten entries.
- Test 3 (wrong in): read the `related` list.
- Test 4 (placards): read the `placard` fields on the judgment events.
- Test 5 (a topic you have nothing about): the split event comes back
  with an empty `related` list.
- Test 7 (speed): time the first split with `time curl`; run the same
  lens again - the second one returns instantly with every judgment
  already cached (no model calls).
- Test 8 (nothing changed): `curl http://127.0.0.1:8787/artifacts`
  before and after a split, and confirm the same ordering both times.
