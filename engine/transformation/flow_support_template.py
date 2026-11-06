"""Shared ``CobolFlow`` Java support-class template: ``GO TO`` and run-unit termination across paragraphs.

Emitted by the plain and Spring Boot generators whenever generated bodies reference ``CobolFlow``. A paragraph is a
static method; ``GO TO p`` throws ``CobolFlow.Goto(p)`` and ``STOP RUN`` / ``GOBACK`` throw ``CobolFlow.Stop``. The
scheduler runs paragraphs ``lo..hi`` in order (fall-through), re-dispatching at the target of a ``Goto`` that lands
inside the range. A ``Goto`` that leaves the range is never produced: ``engine.transformation.control_flow.goto_plan``
refuses such programs, so the lowering only covers jumps whose behaviour the GnuCOBOL differential
(``tests/integration/test_goto_oracle.py``) pins. ``Goto`` and ``Stop`` extend ``Error`` so a ``catch (Exception)``
in generated code can never swallow them.
"""

from __future__ import annotations

COBOL_FLOW_JAVA = '''final class CobolFlow {
    private CobolFlow() {}

    interface Para { void run() throws Exception; }

    static final class Goto extends Error {
        final int target;
        Goto(String target) { super(null, null, false, false); this.target = Integer.parseInt(target); }
    }

    static final class Stop extends Error {
        Stop() { super(null, null, false, false); }
    }

    /** PERFORM paragraph lo THRU paragraph hi (0-based indexes into the paragraph table). */
    static void range(int lo, int hi, Para[] paras) throws Exception {
        int pc = lo;
        while (pc <= hi) {
            try {
                paras[pc].run();
                pc++;
            } catch (Goto g) {
                if (g.target < lo || g.target > hi) { throw g; }
                pc = g.target;
            }
        }
    }

    /** The run unit: every paragraph from the first, ending at STOP RUN / GOBACK or after the last. */
    static void program(Para[] paras) throws Exception {
        try {
            range(0, paras.length - 1, paras);
        } catch (Stop s) {
            // STOP RUN / GOBACK: the run unit is over
        }
    }
}'''
