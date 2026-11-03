       IDENTIFICATION DIVISION.
       PROGRAM-ID. RELREAD.
      * GnuCOBOL's own view of GAP.DAT: every live record, by RRN.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT GAP-FILE ASSIGN TO "GAP.DAT"
               ORGANIZATION IS RELATIVE
               RELATIVE KEY IS WS-RRN
               ACCESS MODE IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  GAP-FILE.
       01  GAP-REC              PIC X(6).
       WORKING-STORAGE SECTION.
       01  WS-RRN               PIC 9(4).
       01  WS-EOF               PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT GAP-FILE
           PERFORM UNTIL WS-EOF = 'Y'
               READ GAP-FILE NEXT
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END DISPLAY WS-RRN '|' GAP-REC '|'
               END-READ
           END-PERFORM
           CLOSE GAP-FILE
           STOP RUN.
