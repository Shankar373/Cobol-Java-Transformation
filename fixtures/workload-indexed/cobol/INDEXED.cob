       IDENTIFICATION DIVISION.
       PROGRAM-ID. INDEXED.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IDX-FILE ASSIGN TO "IDX.DAT"
               ORGANIZATION IS INDEXED
               RECORD KEY IS IDX-KEY
               ACCESS MODE IS DYNAMIC.

       DATA DIVISION.
       FILE SECTION.
       FD  IDX-FILE.
       01  IDX-REC.
           05  IDX-KEY             PIC X(4).
           05  IDX-DATA            PIC X(16).

       WORKING-STORAGE SECTION.
       01  WS-EOF                 PIC X VALUE 'N'.
       01  WS-RRN                 PIC 9(4) COMP.
       01  WS-STATUS              PIC X(2) VALUE '00'.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN OUTPUT IDX-FILE

           MOVE 'K001' TO IDX-KEY
           MOVE 'RECORD-ONE--0001' TO IDX-DATA
           WRITE IDX-REC INVALID KEY DISPLAY 'W-FAIL K001'
           END-WRITE

           MOVE 'K002' TO IDX-KEY
           MOVE 'RECORD-TWO--0002' TO IDX-DATA
           WRITE IDX-REC INVALID KEY DISPLAY 'W-FAIL K002'
           END-WRITE

           MOVE 'K003' TO IDX-KEY
           MOVE 'RECORD-THREE-003' TO IDX-DATA
           WRITE IDX-REC INVALID KEY DISPLAY 'W-FAIL K003'
           END-WRITE

           CLOSE IDX-FILE

           OPEN I-O IDX-FILE

           MOVE 'K002' TO IDX-KEY
           MOVE 'REC-TWO-UPD--002' TO IDX-DATA
           REWRITE IDX-REC INVALID KEY DISPLAY 'RW-FAIL K002'
           END-REWRITE

           MOVE 'K002' TO IDX-KEY
           DELETE IDX-FILE INVALID KEY DISPLAY 'D-FAIL K002'
           END-DELETE

           MOVE 'K001' TO IDX-KEY
           START IDX-FILE KEY >= IDX-KEY
               INVALID KEY DISPLAY 'START-FAIL'
           END-START

           MOVE 'N' TO WS-EOF
           PERFORM UNTIL WS-EOF = 'Y'
               READ IDX-FILE NEXT
                   AT END MOVE 'Y' TO WS-EOF
               END-READ
               IF WS-EOF = 'N'
                   DISPLAY IDX-KEY '|' IDX-DATA
               END-IF
           END-PERFORM

           MOVE '00' TO WS-STATUS
           CLOSE IDX-FILE

           DISPLAY 'FILESTATUS=' WS-STATUS
           DISPLAY 'END'
           STOP RUN.
