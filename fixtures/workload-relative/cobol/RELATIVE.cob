       IDENTIFICATION DIVISION.
       PROGRAM-ID. RELATIVE.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT REL-FILE ASSIGN TO "REL.DAT"
               ORGANIZATION IS RELATIVE
               RELATIVE KEY IS WS-RRN
               ACCESS MODE IS DYNAMIC.

       DATA DIVISION.
       FILE SECTION.
       FD  REL-FILE.
       01  REL-REC.
           05  REL-DATA            PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-RRN                 PIC 9(4) COMP.
       01  WS-CURR-RRN            PIC 9(4) COMP VALUE 0.
       01  WS-MAX-RRN             PIC 9(4) COMP VALUE 5.
       01  WS-STATUS              PIC X(2) VALUE '00'.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN OUTPUT REL-FILE

           MOVE 1 TO WS-RRN
           MOVE 'REL-RECORD-A----01' TO REL-REC
           WRITE REL-REC INVALID KEY DISPLAY 'W-FAIL RRN=1'
           END-WRITE

           MOVE 2 TO WS-RRN
           MOVE 'REL-RECORD-B----02' TO REL-REC
           WRITE REL-REC INVALID KEY DISPLAY 'W-FAIL RRN=2'
           END-WRITE

           MOVE 3 TO WS-RRN
           MOVE 'REL-RECORD-C----03' TO REL-REC
           WRITE REL-REC INVALID KEY DISPLAY 'W-FAIL RRN=3'
           END-WRITE

           CLOSE REL-FILE

           OPEN I-O REL-FILE

           MOVE 2 TO WS-RRN
           MOVE 'REL-REC-B-UPD--02' TO REL-REC
           REWRITE REL-REC INVALID KEY DISPLAY 'RW-FAIL RRN=2'
           END-REWRITE

           CLOSE REL-FILE

           OPEN INPUT REL-FILE

           MOVE 0 TO WS-CURR-RRN
           PERFORM UNTIL WS-CURR-RRN >= WS-MAX-RRN
               ADD 1 TO WS-CURR-RRN
               MOVE WS-CURR-RRN TO WS-RRN
               READ REL-FILE
                   INVALID KEY
                       CONTINUE
                   NOT INVALID KEY
                       DISPLAY WS-RRN '|' REL-DATA
               END-READ
           END-PERFORM

           MOVE '00' TO WS-STATUS
           CLOSE REL-FILE

           DISPLAY 'FILESTATUS=' WS-STATUS
           DISPLAY 'END'
           STOP RUN.
