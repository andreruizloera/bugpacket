"""BugPacket: turn a software failure into the smallest useful debugging context.

BugPacket is strictly local. It contains no networking code of any kind and
never uploads anything anywhere. See tests/test_no_network.py, which enforces
that claim against the source tree.
"""

__version__ = "0.1.0"
