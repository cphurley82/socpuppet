"""What the repo's generators share.

Some of what is checked in is generated: a whole file, or a part of a
page between two marker comments that name it,

    <!-- regs:dma_engine start -->
    <!-- regs:dma_engine end -->

A name is a kind, a colon, and which one of that kind. Each generator
(tools/address_map_docs.py, tools/regs.py) has its own kinds, and says
what each file should hold. What is here finds the marked places, fills
them, and then writes the files or checks that they are already so. What
goes in a place has so far always been a table, and the messages say so.
"""

import re


def pages(paths, known):
    """What each page should hold, once its marked places are filled.

    `known` is what goes in each place, by the place's name. Returns three
    things:

    - what each page that has a place for one of them should hold, by its
      path,
    - where each place of the kinds `known` has is marked, by the place's
      name, whether `known` has that name or not,
    - and a line for each place that cannot be filled, saying why.

    What a caller makes of a place whose name it does not know, or of a
    name that has no place, is its own business.
    """
    kinds = {name.partition(":")[0] for name in known}
    wanted, placed, problems = {}, {}, []
    for path in paths:
        text = path.read_text()
        whole = [place["name"] for place in _marked(known).finditer(text)]
        for name in _starts(text, kinds):
            placed.setdefault(name, path)
            if name in known and name not in whole:
                problems.append(
                    f"{path}: the table {name} starts and never ends. "
                    "After its start marker there has to be "
                    f"`<!-- {name} end -->`, on a line of its own."
                )
        if whole:
            wanted[path] = _marked(known).sub(
                lambda place: (
                    f"<!-- {place['name']} start -->\n\n"
                    f"{known[place['name']]}\n\n"
                    f"<!-- {place['name']} end -->\n"
                ),
                text,
            )
    return wanted, placed, problems


def settle(command, wanted, source):
    """Write the files, or check that they are written. Returns the status.

    `wanted` is what each file should hold, by its path, and `command` is
    `write` or `check`. `source` is what the files are generated from, for
    the line that says a file is not what it should be.
    """
    status = 0
    for path, text in wanted.items():
        if path.exists() and path.read_text() == text:
            continue
        if command == "write":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        else:
            print(
                f"{path} is not what {source} give. "
                "`uv run python tools/lint.py --fix` writes it again."
            )
            status = 1
    return status


def markdown_table(header, rows):
    """A table in Markdown, with no line after the last."""
    return "\n".join(
        "|" + "".join(f" {cell} |" if cell else " |" for cell in cells)
        for cells in (header, ["---"] * len(header), *rows)
    )


def _starts(text, kinds):
    """The names of the places a page's text marks the start of, in order.

    Only those of the `kinds` named: another generator's are its own.
    """
    kind = "|".join(re.escape(kind) for kind in kinds)
    return re.findall(rf"^<!-- ((?:{kind}):\S+) start -->$", text, re.MULTILINE)


def _marked(known):
    """What matches a whole marked place with one of the names in `known`."""
    name = "|".join(re.escape(name) for name in known)
    return re.compile(
        rf"^<!-- (?P<name>{name}) start -->\n.*?^<!-- (?P=name) end -->\n",
        re.MULTILINE | re.DOTALL,
    )
