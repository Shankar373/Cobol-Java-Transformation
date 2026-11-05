"""Shared ``CobolSort`` Java support-class template: file-to-file ``SORT ... USING ... GIVING``.

Emitted by the plain and Spring Boot generators whenever generated method bodies reference ``CobolSort``.
It reads every record of the USING file through ``CobolFileIo`` (so ddname and path mapping are the program's
own), sorts them with a **stable** sort on the keys, and writes the GIVING file through ``CobolFileIo`` the way
a MOVE + WRITE does (trailing spaces trimmed on a LINE SEQUENTIAL record).

Behaviour pinned by the GnuCOBOL 3.1.2 differential in ``tests/integration/test_sort_oracle.py``:

* records with equal keys keep their input order;
* keys compare as characters in ASCII order, which for unsigned DISPLAY numeric keys of equal width is numeric
  order; ``D`` keys reverse the comparison, and later keys break ties of earlier ones;
* a USING file that does not exist is an empty input: the GIVING file is still produced, empty, and the
  program goes on (no error).

Key spec strings: ``A:offset:length`` (ascending) or ``D:offset:length`` (descending), offsets from 0.
"""

from __future__ import annotations

COBOL_SORT_JAVA = '''final class CobolSort {
    private CobolSort() {}

    static void run(String in, String out, int length, String... keys) {
        java.util.List<String> records = new java.util.ArrayList<>();
        if ("00".equals(CobolFileIo.open(in, "INPUT", 0))) {
            String line;
            while ((line = CobolFileIo.readNext(in)) != null) {
                records.add(CobolFileIo.pad(line, length, false).substring(0, length));
            }
            CobolFileIo.close(in);
        }
        final boolean[] descending = new boolean[keys.length];
        final int[] offset = new int[keys.length];
        final int[] width = new int[keys.length];
        for (int k = 0; k < keys.length; k++) {
            String[] part = keys[k].split(":");
            descending[k] = part[0].equals("D");
            offset[k] = Integer.parseInt(part[1]);
            width[k] = Integer.parseInt(part[2]);
        }
        // List.sort is stable: equal keys keep their input order.
        records.sort((a, b) -> {
            for (int k = 0; k < offset.length; k++) {
                int c = a.substring(offset[k], offset[k] + width[k])
                    .compareTo(b.substring(offset[k], offset[k] + width[k]));
                if (c != 0) {
                    return descending[k] ? -c : c;
                }
            }
            return 0;
        });
        CobolFileIo.open(out, "OUTPUT", 0);
        for (String record : records) {
            CobolFileIo.write(out, record.replaceFirst(" +$", ""), 0);
        }
        CobolFileIo.close(out);
    }
}
'''
