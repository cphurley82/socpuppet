# socpuppet 🧦

SoC Puppet (say "sock puppet") is an open-source virtual platform: a whole SoC simulated in SystemC, with Python pulling the strings.

[docs/vision.md](docs/vision.md) has the aims, the readers and the rules that order the work. Read it before planning a milestone or settling a decision, and cite the rule a decision rests on. [docs/roadmap.md](docs/roadmap.md) has the phases, the milestones and what is next, and stays short: a settled decision goes to [docs/history/decisions.md](docs/history/decisions.md), a lesson to [docs/history/lessons.md](docs/history/lessons.md), and the step-by-step of a milestone lives in its commits.

## Personality

A vibe, not a checklist. Keep it in mind while writing code, docs and output.

**The model is Raspberry Pi.** A learning tool that is also good enough to use at work. Write by default for someone who knows a little Python and has never seen a chip: the expert skims what the beginner needs, but the beginner cannot fill in what the expert skipped. The fun lives on the surface, in the voice, the color and the emoji; the engineering underneath is serious. When the two pull against each other, clarity and correctness win.

- 🎓 **Teach as you go.** Say what a page is for in its first line. Define a term where it first appears on that page, then call the thing by that one name everywhere, in prose and in code: readers often have an AI assistant beside them, and it follows exact names too. Say which real hardware a model stands for and what it leaves out.
- 🧦 **Enjoy the puppet show.** The SoC is the puppet, Python pulls the strings, a boot is a performance, and a stand-in holds a block's place on stage so the rest of the cast can rehearse. The metaphor is a signpost beside the plain word, never instead of it: the first time a page says stand-in, it also says simplified model. Keep it in prose; names in code stay the industry's (TLM, ISS, DMI, `Platform`), so learners recognise them elsewhere.
- 🎪 **Two troupes, one stage.** Monty Python's Flying Circus, because the language is named for it, and the Muppets, because this is a puppet show with a cast and sketches. A sketch is a short scene with a small cast that makes one point and ends, which is also what a good example is. The humor is deadpan: state the absurd thing with a straight face and carry on. A line is plain English first and a joke second: most readers have never seen either show, so a sentence must make complete sense without the reference, and the reference is never explained. `spam` and `eggs` are the placeholder names, as in Python's own tutorial; everything else in code is named for what it is (the RAM is `ram`).
- 🎯 **Analogies have to be true.** A metaphor that gives the wrong idea of a mechanism is worse than none. If the picture does not fit, say it plainly.
- 🎨 **Be colorful.** A diagram over a wall of text; color over monochrome in terminal output meant for people.
- ✨ **Give emoji a job.** Signposts in docs, the README, code comments and human-facing output, the same emoji for the same thing (palette below).
- 🔧 **Stay useful when things break.** An error says what went wrong and how to fix it; charm comes second. JSON, traces and logs stay plain, and color respects `NO_COLOR` and non-terminals.
- 😄 **Playful in small doses.** One good joke per page, shared by the puppets and both troupes, and never in the sentence that carries the mechanism.

### What it sounds like

> Plain: The behavioral NVMe device is a simplified model with no CPU or firmware.
>
> socpuppet: 🎭 The behavioral NVMe device is a stand-in for the SSD: a simplified model that answers the way the real one does (queues, Identify, reads and writes), so the host can rehearse against it, but there is no CPU or firmware behind the curtain.

And with the Flying Circus:

> Plain: The SystemC kernel cannot be restarted, so a process can build only one platform.
>
> socpuppet: ⚠️ The SystemC kernel cannot be restarted. After a run it is not resting, it is an ex-kernel. So a process can build exactly one `Platform`.

The second passes the test: without the sketch, the reader still learns that the kernel is finished after a run and that a process gets one.

### Emoji palette

Add to it when something new keeps coming up.

| Emoji | Means |
|---|---|
| 🧦 | socpuppet itself |
| 🧵 | the Python API (the strings) |
| 🎭 | stand-ins |
| 🎓 | a teaching aside: the real hardware, or why it is this way |
| 💡 | tip, or why something works the way it does |
| ⚠️ | gotcha |
| ✅ / ❌ | pass / fail |
| 🚧 | not built yet |
| 🦜 | deprecated or removed (an ex-feature) |
| 📮 | something to send upstream |
| 🩺 | the doctor's check of a machine (`tools/doctor.py`) |
| 🧭 | the vision: why, for whom, and how choices get made |
| 🌱 | the first rung: a reader who knows a little Python and nothing of chips |
| 🐧 | Linux |

## Workflow

Changes are test-first, with the skills in `.claude/skills/`: `/tdd [specification]` drives a change through Canon TDD (agree the specifications, one failing test, make it pass, commit), running `/test-design-review` on each new test and `/software-design-review` on the code once it is green. Both reviews also run on their own against the working tree. `spikes/` is exploratory and not test-first, and nothing outside it may depend on it.

## Borrow before building

Using existing open source matters as much as teaching. Before writing a model, a parser or a tool, look for an open one, starting with the projects already in the build and their siblings.

- A borrowed model sits behind an adapter of ours and a contract suite written first, so the tests say what socpuppet relies on.
- Where it falls short, fix it first. Writing our own is a decision for the maintainer, brought with the failing tests.
- A change to someone else's code is a `git apply` file in `cmake/patches/`, and the same commit adds an entry to [docs/upstream.md](docs/upstream.md): what is wrong, how to see it, what to propose. A limitation worked around without a patch gets an entry too.
- Nothing is sent upstream unless the maintainer asks; that page is the list.

## Style

[docs/style.md](docs/style.md) has the rules and their reasons. While writing:

- C++ is Google style: `CamelCase()` functions, `lower_case` variables, `kCamelCase` constants, `member_` for private members, 80 columns. Names imposed by TLM, SystemC and the coroutine protocol keep their spelling.
- Python is ruff-formatted and fully type-annotated in the package, with Google docstrings.
- Markdown is one paragraph per line; never wrap prose by hand.
- A register of one of our own blocks is written once, in `regs/<block>.rdl`. The C header, the Python module and the docs table are generated and checked in; nothing else may state an offset or a bit.
- `uv run python tools/lint.py --fix` repairs what it can, including regenerating from the register maps and the address-map tables from the boards; `uv run ctest --preset dev` includes the lint. Tools in the repo are tested in `tests/tooling/`.
- CI is two workflows, each job a thin wrapper around `tools/ci.py`, which holds the steps; a new check goes there, not in the YAML. Each job is in a tier, which it states: the quick tier, `.github/workflows/ci.yml`, on every push and pull request, and the nightly tier, `.github/workflows/nightly.yml`, everything on every machine, every night. A job of both is word for word the same in both workflows but for its machines. `uv run python tools/ci.py` runs the nightly tier's jobs that can run here and `--quick` the quick tier's, `tests/tooling/test_ci_workflow.py` keeps the workflows and the runner in step, and a run starts by asking `tools/doctor.py` what the machine is missing, so a job's `areas` names what it needs.
