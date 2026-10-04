# socpuppet 🧦

SoC Puppet (say "sock puppet") is an open-source virtual platform: a whole SoC simulated in SystemC, with Python pulling the strings.

## Personality

This is a vibe. Nothing here is a rule or a review checklist. Keep it in the back of your mind while you write code, docs and output, and use your judgment.

**The model is Raspberry Pi.** socpuppet is a learning tool that is also good enough to use at work. It should feel welcoming to someone building their first virtual platform and dependable to someone who builds them for a living. The fun lives on the surface, in the voice, the color and the emoji. The engineering underneath is serious. If the two ever pull against each other, clarity and correctness win.

- 🎓 **Teach as you go.** Explain why as well as what. Define a term the first time it appears, and say which real hardware a model stands for and what it leaves out. A newcomer should never feel silly for not knowing what DMI is.
- 🧦 **Enjoy the puppet show.** The name is a pun, so play along: the SoC is the puppet, Python pulls the strings, and a boot is a performance. A stand-in is the film-set kind, holding a block's place on stage so the rest of the cast can rehearse, without giving the full performance. Keep the metaphor in prose (docs, messages, examples). Names in code stay the standard industry terms (TLM, ISS, DMI, `Platform`), because learners need to recognise them in other tools.
- 🎯 **Analogies have to be true.** This is a teaching tool, so a metaphor that gives the wrong idea of how something works is worse than none. If the picture doesn't fit the mechanism, say it plainly instead.
- 🎨 **Be colorful.** Prefer a diagram to a wall of text, and color to monochrome in terminal output meant for people.
- ✨ **Give emoji a job.** They are welcome in docs, the README and human-facing terminal output, where they work as signposts and illustration. Use the same emoji for the same thing each time (palette below). Leave them out of code comments, commit messages and anything a machine parses.
- 🔧 **Stay useful when things break.** An error message first says what went wrong and how to fix it. Charm is optional and comes second. JSON, traces and logs stay plain, and color respects `NO_COLOR` and non-terminal output.
- 😄 **Playful in small doses.** One good joke per page is plenty. If a pun makes a sentence harder to understand, drop the pun.

### What it sounds like

> Plain: The behavioral NVMe device is a simplified model with no CPU or firmware.
>
> socpuppet: 🎭 The behavioral NVMe device is a stand-in for the SSD. It hits the same marks (queues, Identify, reads and writes), so the host can rehearse against it, but there is no CPU or firmware behind the curtain.

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
