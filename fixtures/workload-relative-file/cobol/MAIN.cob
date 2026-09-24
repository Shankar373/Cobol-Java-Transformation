IDENTIFICATION DIVISION.
       PROGRAM-ID. RELATIVE-FILE-DEMO.
       AUTHOR. VALIDATION-PLATFORM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT REL-FILE ASSIGN TO "RELFILE.DAT"
               ORGANIZATION IS RELATIVE
               RELATIVE KEY IS WS-RRN
               ACCESS MODE IS DYNAMIC
               FILE STATUS IS WS-FILE-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  REL-FILE.
       01  REL-REC.
           05  REL-DATA            PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-RRN              PIC 9(4) COMP VALUE 0.
       01  WS-FILE-STATUS      PIC X(2) VALUE "00".
       01  WS-EOF              PIC X VALUE "N".
       01  WS-COUNT            PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "RELATIVE FILE DEMO STARTED".

           OPEN OUTPUT REL-FILE.
           DISPLAY "OPEN OUTPUT STATUS=" WS-FILE-STATUS.

           MOVE 1 TO WS-RRN.
           MOVE "REL-RECORD-ONE-----" TO REL-DATA.
           WRITE REL-REC.
           DISPLAY "WRITE RRN=1 STATUS=" WS-FILE-STATUS.

           MOVE 2 TO WS-RRN.
           MOVE "REL-RECORD-TWO-----" TO REL-DATA.
           WRITE REL-REC.
           DISPLAY "WRITE RRN=2 STATUS=" WS-FILE-STATUS.

           MOVE 3 TO WS-RRN.
           MOVE "REL-RECORD-THREE----" TO REL-DATA.
           WRITE REL-REC.
           DISPLAY "WRITE RRN=3 STATUS=" WS-FILE-STATUS.

           CLOSE REL-FILE.
           DISPLAY "CLOSE STATUS=" WS-FILE-STATUS.

           OPEN I-O REL-FILE.
           DISPLAY "OPEN I-O STATUS=" WS-FILE-STATUS.

           MOVE 2 TO WS-RRN.
           MOVE "REL-REC-TWO-UPD----" TO REL-DATA.
           REWRITE REL-REC.
           DISPLAY "REWRITE RRN=2 STATUS=" WS-FILE-STATUS.

           MOVE 1 TO WS-RRN.
           DELETE REL-FILE RECORD.
           DISPLAY "DELETE RRN=1 STATUS=" WS-FILE-STATUS.

           MOVE 0 TO WS-RRN.
           MOVE "N" TO WS-EOF.
           MOVE 0 TO WS-COUNT.
           PERFORM UNTIL WS-EOF = "Y"
               ADD 1 TO WS-RRN
               READ REL-FILE
                   INVALID KEY
                       DISPLAY "READ RRN=" WS-RRN " INVALID KEY STATUS=" WS-FILE-STATUS
                   NOT INVALID KEY
                       ADD 1 TO WS-COUNT
                       DISPLAY "READ: RRN=" WS-RRN " DATA=" REL-DATA " STATUS=" WS-FILE-STATUS
               END-READ
               IF WS-RRN >= 3
                   MOVE "Y" TO WS-EOF
               END-IF
           END-PERFORM.
           DISPLAY "RECORDS READ=" WS-COUNT.

           CLOSE REL-FILE.
           DISPLAY "FINAL CLOSE STATUS=" WS-FILE-STATUS.

           STOP RUN.
