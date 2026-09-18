"""Transformation producers package.

Contains producer implementations:
- InternalNativeJavaProducer: Primary standalone native Java producer
- OpenSourceCOBOL4JProducerAdapter: Alternative producer (requires libcobj.jar)
"""

from engine.transformation.producers.internal_native import InternalNativeJavaProducer
from engine.transformation.producers.opensource4j import OpenSourceCOBOL4JProducerAdapter

__all__ = [
    "InternalNativeJavaProducer",
    "OpenSourceCOBOL4JProducerAdapter",
]
