"""Which port is connected to which, read out of a platform's description."""

import json


def what_drives(platform, sink):
    """The paths of the ports connected to `sink`, a port, as its sources.

    A wire has one driver, so for a wire's sink there is at most one.
    """
    return [
        each["source"]
        for each in json.loads(platform.to_json())["connections"]
        if each["sink"] == sink.path
    ]


def implementations_in(platform):
    """The implementations of every component the platform describes."""
    components = json.loads(platform.to_json())["components"]
    return {each["implementation"] for each in components.values()}
