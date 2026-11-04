"""Versioned subsystem simulators (MQ, later IMS and CICS) with canonical traces.

A simulator is a *specification* implemented twice -- a Python reference model and a Java library --
and kept equal by a differential on scripted input.  Equivalence proven this way is relative to the
simulator specification, never to IBM's runtime, and carries the verdict label ``SIMULATOR_VERIFIED``
(distinct from ``IBM_VERIFIED``, which nothing here can produce).
"""

from __future__ import annotations

SIMULATOR_VERIFIED = "SIMULATOR_VERIFIED"
IBM_VERIFIED = "IBM_VERIFIED"  # never produced by this package
