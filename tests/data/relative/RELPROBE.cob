       IDENTIFICATION DIVISION.
       PROGRAM-ID. RELPROBE.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT GAP-FILE ASSIGN TO "GAP.DAT"
               ORGANIZATION IS RELATIVE
               RELATIVE KEY IS WS-RRN
               ACCESS MODE IS RANDOM.
           SELECT SEQ-FILE ASSIGN TO "SEQ.DAT"
               ORGANIZATION IS RELATIVE
               ACCESS MODE IS SEQUENTIAL.
           SELECT NONE-FILE ASSIGN TO "NONE.DAT"
               ORGANIZATION IS RELATIVE
               RELATIVE KEY IS WS-RRN
               ACCESS MODE IS RANDOM.
       DATA DIVISION.
       FILE SECTION.
       FD  GAP-FILE.
       01  GAP-REC              PIC X(6).
       FD  SEQ-FILE.
       01  SEQ-REC              PIC X(4).
       FD  NONE-FILE.
       01  NONE-REC             PIC X(3).
       WORKING-STORAGE SECTION.
       01  WS-RRN               PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN OUTPUT GAP-FILE
           MOVE 2 TO WS-RRN
           MOVE 'TWO' TO GAP-REC
           WRITE GAP-REC
           MOVE 5 TO WS-RRN
           MOVE 'FIVE55' TO GAP-REC
           WRITE GAP-REC
           MOVE 7 TO WS-RRN
           MOVE 'SEVEN' TO GAP-REC
           WRITE GAP-REC
           CLOSE GAP-FILE
           OPEN I-O GAP-FILE
           MOVE 5 TO WS-RRN
           DELETE GAP-FILE
           MOVE 7 TO WS-RRN
           MOVE 'SEVEN7' TO GAP-REC
           REWRITE GAP-REC
           MOVE 5 TO WS-RRN
           MOVE 'AGAIN' TO GAP-REC
           WRITE GAP-REC
           CLOSE GAP-FILE
           OPEN OUTPUT SEQ-FILE
           MOVE 'AAAA' TO SEQ-REC
           WRITE SEQ-REC
           MOVE 'BB' TO SEQ-REC
           WRITE SEQ-REC
           CLOSE SEQ-FILE
           OPEN OUTPUT NONE-FILE
           MOVE 1 TO WS-RRN
           MOVE 'X' TO NONE-REC
           WRITE NONE-REC
           CLOSE NONE-FILE
           OPEN I-O NONE-FILE
           DELETE NONE-FILE
           CLOSE NONE-FILE
           DISPLAY 'DONE'
           STOP RUN.
