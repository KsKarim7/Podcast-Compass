# Debugging log

Notes on the problems I hit building this, what I did about them, and what I took away.

## Main example: the first click on Generate did nothing

### What went wrong

After typing or pasting a transcript into the text area, the first click on **Generate**
produced no visible response. A second click ran the generation. I reproduced it with a
short paste (`hello there`) and with a WebVTT paste, both typed and pasted.

The uncomfortable part is that the test suite was green at the time — 282 tests, including
twenty-odd that drove the app itself through Streamlit's `AppTest` harness. Several of
those tests clicked **Generate** and asserted the resulting message. They passed while the
app needed two clicks.

### How I investigated

I started with the tests rather than the app, because a suite that passes on broken
behaviour is telling you something about the suite.

The app tests all looked like this:

```python
app.text_area[0].set_value("too short").run()
button(app, "Generate").click().run()
```

Two `.run()` calls. Each one is a separate server round trip, so this sequence is not one
click — it is "commit the text, rerun, then press the button, rerun". That is exactly the
two-step interaction the browser was forcing on me, written down as the expectation.

That pointed at the widget protocol. `st.text_area` does not send its value on every
keystroke; it sends it when the field loses focus. Clicking a button blurs the text area,
so that first click was consumed committing the text and triggering a rerun, and during
that rerun the button had not been pressed. The press was never delivered.

The live character counter under the input made this harder to spot, because something
visibly changed on the first click — the counter appeared — so it looked like the click had
registered and the app had decided to do nothing.

### What I changed and tested

I moved the text area, the file uploader and both buttons inside `st.form`. Form widgets
hold their values until a submit button is pressed, so the text and the press arrive in one
message and the script runs once with both.

Switching to a form broke eighteen tests, in two distinct groups.

Six were in the app tests. Five of those had been setting the text in one cycle and
pressing in another — the tests that had encoded the two-click behaviour — and they now
fail unless the value and the press happen in a single cycle. The sixth asserted the live
character counter, which a form cannot update because a form does not rerun on change. I
removed the counter: the limit is still stated under the input, and the rejection messages
quote the real count, so nothing load-bearing was lost.

The other twelve were a problem of my own making, and took longer to understand because
they passed when run individually and failed when run as a file. Two tests had imported a
helper directly from the app module. Importing it executes the whole script outside a
session context, which left Streamlit's form state dirty for every test that ran
afterwards, and those tests failed with "Forms cannot be nested in other forms". Moving the
helper they wanted into the package — where it belonged anyway, since it is input
validation rather than layout — fixed all twelve. No test imports the app module now.

I added a regression test that sets the value and presses the button in one run cycle,
with a docstring explaining that this is precisely one browser click and that an
intervening `run()` would be a second one. Without that note the distinction is invisible
to the next person reading it.

### Was it resolved

Yes. In the browser, one click now works for typed input, pasted input, and the example
episode button. I re-checked the revision and undo controls after the change, since both
sit on the same page, and both still behave. The suite is green again at 300 tests.

### What I learned

A passing test can encode a bug as the expected behaviour, and that is a worse failure
than no test at all, because it actively reassures you. The harness was faithful to
Streamlit's protocol and unfaithful to the user: setting a widget value and rerunning is a
legitimate sequence, it just is not what one click is.

For anything interaction-shaped I now try to model the gesture rather than the state
transition. One click is one message to the server. If a test needs two round trips to
reach the assertion, it is describing two clicks, and I should ask whether a user would
accept that.

The second takeaway is about manual testing. I found this by using the app, not by reading
code or adding tests, and nothing in the automated suite would ever have found it. The
whole class of bug — "the app works but the interaction is wrong" — needs someone to
actually click the thing.

## Other issues found

**A fallback encoding that never failed.** My decoding rule was UTF-8, then cp1252, then
reject. The reject branch almost never fired, because cp1252 has only five undefined bytes
and decodes nearly anything. A UTF-16 file — which is what Windows subtitle exporters
often produce — came out as mojibake and was accepted as a valid transcript. I found it
when a test asserting that undecodable bytes are rejected failed, because
`b"\xff\xfe\x00\x00"` decoded "successfully". The fix is ordering: check for a UTF-16
byte-order mark before trying UTF-8 and cp1252. Silently accepting garbage would have cost
a request and produced nonsense the user could not explain.

**A validation rule that no short transcript could satisfy.** On the deployed app, a
70-word paste was rejected every time with "we could not verify enough of that result",
three attempts in a row, three requests spent. The validator required at least two
verified chapters, and chapters must start at strictly increasing transcript segments — a
70-word paste makes one segment, so two chapters were arithmetically impossible. Every
grounding test used multi-segment fixtures, so the impossible case was the one input
nobody had tested. I raised the input minimum to 250 words checked before any request,
made the chapter requirement follow the input instead of being fixed, and made rejection
messages state the reason. A rule that cannot be satisfied is worse than one that is
sometimes violated, because it fails silently and charges you each time.

**A stale module after a redeploy.** The first visit to the live app after a push raised
`AttributeError: module messages has no attribute GROUNDING_REJECTED_BECAUSE`, for a
constant that exists in the deployed commit. The host had picked up the new entry-point
script but kept an already-imported package module in memory, so the two halves disagreed.
A reboot from the hosting dashboard reimports everything and fixed it. This cannot be
reproduced locally, because running the app locally reimports on every restart, so the only
way to find it was to visit the deployed URL straight after a push. It is now a deployment
note in the README: reboot after any deploy that changes files inside the package.

**A test that quietly started spending money.** After I added a local secrets file for
manual testing, one app test began making a real API request: it clicked **Generate** with
valid input, and the secrets file meant a real key was now available to the test harness.
I noticed because a test asserting that the provider SDK is never imported during the
offline suite started failing, and the suite time jumped from about 7 seconds to 13.4. The
test had been safe only because of something absent from the environment. It cost one
request. There are now two independent guards: every app test blanks the key, and a fixture
replaces the only function that builds a provider client with one that raises, so reaching
the provider fails the test loudly instead of costing money.

**Provider error handling that the documentation got wrong.** The SDK's README says to
catch `errors.APIError` and read `.code`. The endpoint I use raises from a different,
private module, and those exceptions are not instances of the documented class — I checked
`isinstance` directly and it returns `False` — and they expose `.status_code` rather than
`.code`. Following the documentation would have let every provider error escape as an
unhandled exception. I also found that an invalid API key returns HTTP 400 with
"API key not valid", not the 401 the published error-code table lists, which matters
because 400 otherwise means "our bug". My client catches broadly at the single call site
and branches on `status_code`, and an opt-in test confirms the invalid-key path against the
real API using a deliberately invalid key, so it costs no quota.

## Latency

The measurements taken, and what was not measured, are in [ENGINEERING.md section E](ENGINEERING.md#e-cost-and-maintenance).
