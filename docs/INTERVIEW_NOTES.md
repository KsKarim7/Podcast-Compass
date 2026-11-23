# Interview notes

For each technology added after the first version: what it is, where it lives in this
repository, why it was chosen, and the questions I expect, with answers drawn from the code.
A live demo script is at the end.

## Docker

**What it is.** A container image packs the app with its exact Python and libraries, so it
runs the same on my laptop, in CI and on a server. A container is a running image.

**Where.** `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `.env.example`.

**Why this way.** `python:3.12-slim` keeps the image small. Requirements are copied and
installed before the code, so changing code reuses the cached dependency layer. The app runs
as user `app` (uid 10001), not root, and the code stays owned by root, so the process can
read its code but not change it. The key is never in the image; it arrives as an environment
variable when the container starts.

**Questions.**

1. *Why copy `requirements.txt` before the code?* Docker caches each instruction as a layer
   and reuses it while its inputs are unchanged. Dependencies change rarely and take longest
   to install, so they go first; a code change then rebuilds only the last few layers.
2. *Why not run as root?* If something in the app were exploited, the attacker would have
   root inside the container, which makes escaping it or tampering with files easier. A
   non-root user limits that. Kubernetes enforces it too, with `runAsNonRoot: true`.
3. *How does the health check work?* `HEALTHCHECK` runs a command inside the container every
   30 seconds; a non-zero exit marks it unhealthy. Mine requests Streamlit's built-in
   `/_stcore/health`. The slim image has no `curl`, so it uses Python's `urllib`, which is
   already there, instead of installing curl.
4. *How does the key get in without being baked into the image?* `docker compose` reads
   `.env` (git-ignored) and passes `GEMINI_API_KEY` as an environment variable at start-up.
   `app.py`'s `api_key()` reads the environment first, then Streamlit secrets.
5. *What does `.dockerignore` do?* It keeps files out of the build context sent to Docker:
   `.git`, tests, docs and, most importantly, `.env` and `.streamlit/secrets.toml`, so a
   secret cannot end up in a layer even by accident.
6. *Image vs container?* The image is the read-only template; a container is one running
   instance of it, with its own writable layer.

## CI with GitHub Actions

**What it is.** A workflow that GitHub runs on its own machines on every push and pull
request.

**Where.** `.github/workflows/ci.yml`, jobs `test`, `secret-scan`, `image`; `ruff.toml`.

**What runs.** `ruff check .` (pyflakes and correctness rules), then the full pytest suite;
in parallel, gitleaks over the whole git history; after the tests, a Docker build whose
container must answer `/_stcore/health` within 60 seconds.

**Questions.**

1. *How do tests pass in CI without an API key?* The provider is injected, never imported at
   the call site. Tests pass fakes (`tests/fake_providers.py`), app tests patch the two
   functions that build real clients so they raise, and `conftest.py` removes any
   `GEMINI_API_KEY` from the environment. A test also asserts `google.genai` is never
   imported.
2. *Why scan the whole history, not just the latest commit?* A key committed and later
   deleted is still in history and still usable. `fetch-depth: 0` gives the job every commit.
3. *Why start the container in CI, not just build it?* A build can succeed and the app still
   crash at start-up (a missing file, a bad import). Polling the health endpoint proves the
   image actually serves.
4. *Why does `image` need `test`?* No point building an image from code that fails its tests;
   `needs:` orders the jobs and skips `image` if `test` fails.
5. *How is the build fast?* pip downloads are cached by `setup-python` keyed on the
   requirements files, and Docker layers are cached in GitHub's cache (`type=gha`).

## CD to AWS (written, not run)

**What it is.** Continuous deployment: a push to `main` that passes CI goes live without
manual steps.

**Honest status.** The workflow job, the deploy script and the setup guide are written, but
I did not create the AWS account, so the job is skipped (it needs the `AWS_ROLE_ARN`
repository variable) and has never run. If asked, say exactly that: I designed and wrote
it, validated the YAML and the script's syntax, and stopped before creating cloud
resources. Do not describe a deploy you have not seen.

**Where.** The `deploy` job in `.github/workflows/ci.yml`, `deploy/ec2-deploy.sh`,
`docs/AWS_SETUP.md`.

**The services.**

- **ECR**: a private Docker registry. Each image is tagged with the commit SHA (exact, for
  rollback) and `latest`.
- **EC2**: one `t3.micro` virtual machine running Docker. No SSH key, no SSH port.
- **SSM Run Command**: runs a script on the instance through the SSM agent, which makes
  outbound connections to AWS, so no inbound port is needed.
- **SSM Parameter Store**: holds the Gemini key as an encrypted `SecureString`.
- **IAM + GitHub OIDC**: GitHub proves "I am a workflow on `KsKarim7/Podcast-Compass`,
  branch `main`" with a signed token; AWS trusts that and hands back temporary credentials
  for one role.

**Questions.**

1. *Why OIDC instead of AWS access keys in GitHub secrets?* Stored keys are long-lived: if
   they leak, they work until someone rotates them. OIDC credentials are issued per run and
   expire within the hour, and the role's trust policy only accepts tokens whose `sub` is
   this repository's `main` branch, so a fork or another branch cannot assume it.
2. *What does least privilege mean here?* The deploy role can push to one ECR repository,
   send commands to one instance with one document (`AWS-RunShellScript`), read command
   results and describe instances, and nothing else. The instance role can pull from that
   repository and read that one parameter, plus the SSM agent's managed policy.
3. *How does the key reach the container without appearing in logs?* The workflow never
   handles it. It sends the script with only the image name, region and parameter *name*.
   The script, on the instance, reads the value with `get-parameter --with-decryption`,
   writes it to a temp file only root can read, starts the container with `--env-file`, and
   a `trap` deletes the file when the script exits.
4. *Why no SSH?* An open port 22 is an attack surface and needs key management. SSM gives
   remote command execution with IAM permissions and an audit trail instead.
5. *How would you know a deploy worked?* The job waits for the SSM command to report
   `Success`, then polls `http://<public IP>/_stcore/health` for up to 150 seconds and fails
   the job if it never answers. (It has not run yet; see the status above.)
6. *How would you roll back?* Every image is tagged with its commit SHA, so re-run the deploy
   of an earlier commit from the Actions tab, or send the script with an older tag.
7. *What does it cost?* On the Free plan it comes out of the credits; the public IPv4 address
   alone is USD 0.005 an hour. `docs/AWS_SETUP.md` lists every item and how to remove it all.
8. *What would you change for production?* A load balancer with HTTPS, two instances or ECS
   for zero-downtime deploys (now there is a few seconds of downtime between stopping the
   old container and starting the new one), and a shared request counter.

## Kubernetes with kind

**What it is.** Kubernetes runs containers across machines and keeps them in the state you
declare. kind runs a whole Kubernetes cluster inside Docker on one machine, for learning and
testing.

**Where.** `k8s/kind-config.yaml`, `k8s/deployment.yaml`, `k8s/service.yaml`,
`k8s/secret.example.yaml`, `Makefile`.

**Questions.**

1. *Readiness vs liveness probe?* Readiness decides whether a pod gets traffic: a failing pod
   is taken out of the Service but not restarted. Liveness decides whether the container is
   restarted. Mine starts liveness later (30 s) and checks less often, so a slow start is
   not mistaken for a hang.
2. *Why `sessionAffinity: ClientIP`?* Streamlit keeps each visitor's state in the memory of
   the pod that served them and talks over a WebSocket. If a request went to the other pod,
   it would have no session for it. Affinity sends one client address to one pod. The
   limitation: when that pod dies, the session is gone anyway.
3. *What happens in a rolling update?* `maxSurge: 1, maxUnavailable: 0`: Kubernetes starts
   one new pod, waits until its readiness probe passes, then stops one old pod, and repeats.
   There are always two ready pods. `make restart` demonstrates it.
4. *What is self-healing?* The Deployment declares two replicas; a controller compares that
   with reality. Delete a pod and it creates a new one. `make heal` deletes one and waits for
   two ready pods again.
5. *Why requests and limits?* Requests are what the scheduler reserves (100m CPU, 256 MiB);
   limits are the ceiling (500m, 512 MiB). Above the memory limit the container is killed,
   which is better than starving the node.
6. *How is the Secret handled?* `make secret` runs `kubectl create secret ... --from-env-file=.env`,
   so the real key comes from the git-ignored `.env`. Only a placeholder example is
   committed. The Deployment references it with `optional: true`, so pods start without it.
7. *Why NodePort plus `extraPortMappings`, not `kubectl port-forward`?* port-forward connects
   straight to one pod and bypasses the Service, so it would not test the Service at all.
8. *What does the daily cap do with two pods?* Each pod has its own in-memory counter, so the
   limit is per pod. A shared store (Redis, a database row) would fix it; it is the first
   item in the README's next steps.

## RAG: Ask the podcast

**What it is.** Retrieval-augmented generation: find the parts of a document relevant to a
question, then have the model answer from those parts only.

**Where.** `podcast_compass/rag.py`, `podcast_compass/ask.py`, `embed` and
`build_sdk_embedder` in `podcast_compass/llm.py`, `verify_answer` in
`podcast_compass/grounding.py`, `show_ask` and `run_ask` in `app.py`.

**How it works.** Each ~120-word segment is embedded with `gemini-embedding-001` at 768
dimensions (`RETRIEVAL_DOCUMENT`), normalised to length 1, and added to a FAISS
`IndexFlatIP`. A question is embedded (`RETRIEVAL_QUERY`), normalised and searched for the
top 5. Those segments go to the model with the question; it returns an answer and citations.
A citation counts only if its segment was among the 5 retrieved and its quote is found in
that segment by the same check as every takeaway. If none survives, the app says it is not
in the transcript.

**Questions.**

1. *What is an embedding?* A list of numbers representing a text's meaning, such that texts
   with similar meaning have vectors pointing in similar directions.
2. *Why normalise, and why `IndexFlatIP`?* Cosine similarity compares direction only. For
   unit-length vectors the inner product equals the cosine, so normalising and then using an
   inner-product index gives a cosine search. Normalising also matters because a 768-number
   embedding cut down from 3072 is no longer unit length.
3. *Why a flat (exact) index?* A transcript is at most about 250 segments. Comparing against
   all of them takes microseconds; approximate indexes (IVF, HNSW) are for millions of
   vectors and trade accuracy for speed I do not need.
4. *Where is the index stored?* In the visitor's `st.session_state`, keyed by a SHA-256 of
   the segments, so it is reused for later questions on the same transcript, rebuilt for a
   new one, and discarded when the session ends. It is never shared between visitors.
5. *How does it avoid hallucinated answers?* The model only sees the retrieved segments, and
   the answer is shown only with a citation whose quote is really in a retrieved segment.
   Otherwise it shows "not in the transcript". The limit: a verified quote proves the source
   text exists, not that the answer's reasoning from it is right.
6. *What about prompt injection in the question?* The question is capped at 300 characters,
   lines that look like our delimiters are defused, and it is passed inside a block labelled
   as data, with the rules in a separate system instruction. Even if the model obeyed an
   injected instruction, it could not get an invented claim shown, because the quote check
   would fail.
7. *What does a question cost?* The first question on a transcript: one request per 100
   segments to index, one for the question's embedding, and up to three for the answer
   (fallback model, repair retry). The app reserves that worst case before sending anything
   and settles afterwards.
8. *Why no fallback for embeddings?* Vectors from a different model live in a different space
   and cannot be compared with those already in the index.

## MCP server

**What it is.** The Model Context Protocol is a standard way for AI applications to call
external tools. A server declares tools with typed inputs and outputs; a client such as
Claude Desktop discovers and calls them.

**Where.** `mcp_server.py`, `requirements-mcp.txt`, `tests/test_mcp_server.py`,
`docs/MCP.md`.

**Questions.**

1. *What tools does it expose?* `load_transcript` (no API call), `search_transcript`,
   `ask_podcast` and `generate_quiz`, all using the same package code as the app.
2. *Why stdio?* The client starts the server as a subprocess and talks through its standard
   input and output: no port, no network exposure, no authentication to build. That is why
   nothing may print to stdout, and logging goes to stderr.
3. *How are inputs validated?* Typed parameters with Pydantic constraints (`max_length`,
   `ge`/`le`), which the SDK turns into the tool's JSON Schema and enforces before my code
   runs. The transcript then goes through the same `parse_transcript` limits as the app.
4. *How are outputs grounded?* Search returns segments' own text; answers go through
   `verify_answer`; quizzes go through `verify_quiz`. Times come from the cues.
5. *How are errors reported?* As MCP tool errors whose text starts with a code
   (`invalid_input`, `unknown_transcript`, `not_configured`, `quota_exceeded`,
   `provider_error`, `unverifiable`), so a client or model can react to the kind of failure.
6. *How is it tested without a network?* The SDK's in-memory `Client` speaks the real
   protocol to the server object; `create_server` takes fake model and embedding factories.
7. *How is memory bounded?* Only the five most recent transcripts are kept, in an
   `OrderedDict` that drops the oldest.

## If asked "what would you do next?"

1. A shared, durable request counter, so the cap holds across restarts, pods and hosts.
2. Measure how often the exact-quote rule rejects a correct item before loosening it.
3. Set up the AWS deployment that is already written, then add HTTPS and a load balancer.

## Live demo script (about 8 minutes)

1. **Repo tour (1 min).** Show the README diagram. Point at `podcast_compass/` (logic),
   `app.py` (UI only), `mcp_server.py`, `k8s/`, `.github/workflows/ci.yml`.
2. **CI (1 min).** Open the Actions tab, a green run: lint and test, secret scan, image build
   with the health check. Point out the deploy job is skipped and why.
3. **The live app (2 min).** Open the Streamlit Cloud URL, or `docker compose up` locally.
   Load the example episode, show a citation
   with its time, answer one quiz question, then **Ask the podcast**: "What equipment do you
   need?" Show the verified quote. Ask something not covered, "What does a queen bee cost?",
   and show "not in the transcript".
4. **Kubernetes (2 min).** `make status` shows two ready pods. `make heal` deletes one; the
   output shows a new pod being created and ready. `make restart` shows a rolling update.
5. **MCP (1.5 min).** Open MCP Inspector or Claude Desktop, call `load_transcript` with the
   sample, then `ask_podcast`. Show the structured citations.
6. **Close (30 s).** "Every path ends at the same check: a claim is shown only if its quote
   is really in the transcript, and times come from the subtitle file, never the model."
