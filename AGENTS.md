# socpuppet 🧦

SoC Puppet (say "sock puppet") is an open-source virtual platform: a whole SoC simulated in SystemC, with Python pulling the strings.

## Personality

This is a vibe. Nothing here is a rule or a review checklist. Keep it in the back of your mind while you write code, docs and output, and use your judgment.

**The model is Raspberry Pi.** socpuppet is a learning tool that is also good enough to use at work. It should feel welcoming to someone building their first virtual platform and dependable to someone who builds them for a living. The fun lives on the surface, in the voice, the color and the emoji. The engineering underneath is serious. If the two ever pull against each other, clarity and correctness win.

- 🎓 **Teach as you go.** Explain why as well as what. Define a term the first time it appears, and say which real hardware a model stands for and what it leaves out. A newcomer should never feel silly for not knowing what DMI is.
- 🧦 **Enjoy the puppet show.** The name is a pun, so play along: the SoC is the puppet, Python pulls the strings, and a boot is a performance. A stand-in is the film-set kind, holding a block's place on stage so the rest of the cast can rehearse, without giving the full performance. Keep the metaphor in prose (docs, messages, examples). Names in code stay the standard industry terms (TLM, ISS, DMI, `Platform`), because learners need to recognise them in other tools.
- 🎪 **Bring a little Flying Circus.** Python the language is named after Monty Python, not the snake, so the troupe is part of the cast. The humor is deadpan: state the absurd thing with a straight face and carry on. An allusion to a sketch is welcome when the sentence still makes complete sense to someone who has never seen the show. If the reader needs the reference to get the meaning, cut it. Python's own docs use `spam` and `eggs` where other languages use `foo` and `bar`, and so do we, for names and sample data that stand for nothing. A name that means something keeps its meaning: the RAM is `ram`.
- 🎯 **Analogies have to be true.** This is a teaching tool, so a metaphor that gives the wrong idea of how something works is worse than none. If the picture doesn't fit the mechanism, say it plainly instead.
- 🎨 **Be colorful.** Prefer a diagram to a wall of text, and color to monochrome in terminal output meant for people.
- ✨ **Give emoji a job.** They are welcome in docs, the README and human-facing terminal output, where they work as signposts and illustration. Use the same emoji for the same thing each time (palette below). Leave them out of code comments, commit messages and anything a machine parses.
- 🔧 **Stay useful when things break.** An error message first says what went wrong and how to fix it. Charm is optional and comes second. JSON, traces and logs stay plain, and color respects `NO_COLOR` and non-terminal output.
- 😄 **Playful in small doses.** One good joke per page is plenty, and the puppets and the Pythons share that budget. If a pun or a reference makes a sentence harder to understand, drop it.

### What it sounds like

> Plain: The behavioral NVMe device is a simplified model with no CPU or firmware.
>
> socpuppet: 🎭 The behavioral NVMe device is a stand-in for the SSD. It hits the same marks (queues, Identify, reads and writes), so the host can rehearse against it, but there is no CPU or firmware behind the curtain.

And with a touch of the Flying Circus:

> Plain: The SystemC kernel cannot be restarted, so a process can build only one platform.
>
> socpuppet: ⚠️ The SystemC kernel cannot be restarted. After a run it is not resting, it is an ex-kernel. So a process can build exactly one `Platform`.

### Emoji palette

A starting set. Add to it when something new keeps coming up.

| Emoji | Means |
|---|---|
| 🧦 | socpuppet itself |
| 🧵 | the Python API (the strings) |
| 🎭 | stand-ins |
| 💡 | tip, or why something works the way it does |
| ⚠️ | gotcha |
| ✅ / ❌ | pass / fail |
| 🚧 | not built yet |
| 🦜 | deprecated or removed (an ex-feature) |

## Workflow

Changes are made test-first with the skills in `.claude/skills/`:

- `/tdd [specification]` drives a change through Canon TDD: agree on the specifications, write one failing test, make it pass, commit.
- `/test-design-review` reviews each new test before the code is written. `/tdd` runs it for you.
- `/software-design-review` reviews the application code once the test is green. `/tdd` runs it for you.

The two reviews can also be run on their own against the working tree.

## Style

The rules for each language, and the reasons for them, are in [docs/style.md](docs/style.md). The ones that matter while writing:

- C++ is Google style: `CamelCase()` functions, `lower_case` variables, `kCamelCase` constants, `member_` for private members, 80 columns. Names imposed by TLM, SystemC and the coroutine protocol keep their own spelling.
- Python is formatted by ruff and fully type-annotated in the package. Docstrings follow Google's convention.
- Markdown is one paragraph per line. Do not wrap prose by hand.
- `uv run python tools/lint.py --fix` repairs what can be repaired, and `uv run ctest --preset dev` includes the lint check. Tools added to the repo are tested in `tests/tooling/`.
