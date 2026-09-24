IDENTIFICATION DIVISION.
       PROGRAM-ID. IDX-RWDEL-START.
       AUTHOR. VALIDATION-PLATFORM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IDX-FILE ASSIGN TO "RWDEL.DAT"
               ORGANIZATION IS INDEXED
               RECORD KEY IS IDX-KEY
               ACCESS MODE IS DYNAMIC
               FILE STATUS IS WS-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  IDX-FILE.
       01  IDX-REC.
           05  IDX-KEY             PIC X(4).
           05  IDX-DATA            PIC X(20).

       WORKING-STORAGE SECTION.
       01  WS-STATUS           PIC X(2) VALUE "00".
       01  WS-EOF              PIC X VALUE "N".
       01  WS-COUNT            PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "INDEXED REWRITE/DELETE/START DEMO STARTED".

           OPEN OUTPUT IDX-FILE.
           DISPLAY "OPEN OUTPUT STATUS=" WS-STATUS.

           MOVE "R001" TO IDX-KEY.
           MOVE "REC-ONE-ORIGINAL----" TO IDX-DATA.
           WRITE IDX-REC.
           DISPLAY "WRITE R001 STATUS=" WS-STATUS.

           MOVE "R002" TO IDX-KEY.
           MOVE "REC-TWO-ORIGINAL----" TO IDX-DATA.
           WRITE IDX-REC.
           DISPLAY "WRITE R002 STATUS=" WS-STATUS.

           MOVE "R003" TO IDX-KEY.
           MOVE "REC-THREE-ORIGINAL--" TO IDX-DATA.
           WRITE IDX-REC.
           DISPLAY "WRITE R003 STATUS=" WS-STATUS.

           MOVE "R002" TO IDX-KEY.
           MOVE "REC-TWO-DUPLICATE---" TO IDX-DATA.
           WRITE IDX-REC
               INVALID KEY
                   DISPLAY "WRITE DUP R002 INVALID KEY STATUS=" WS-STATUS
           END-WRITE.
           DISPLAY "POST WRITE DUP STATUS=" WS-STATUS.

           CLOSE IDX-FILE.
           DISPLAY "CLOSE STATUS=" WS-STATUS.

           OPEN I-O IDX-FILE.
           DISPLAY "OPEN I-O STATUS=" WS-STATUS.

           MOVE "R002" TO IDX-KEY.
           MOVE "REC-TWO-REWRITTEN---" TO IDX-DATA.
           REWRITE IDX-REC.
           DISPLAY "REWRITE R002 STATUS=" WS-STATUS.

           MOVE "R002" TO IDX-KEY.
           READ IDX-FILE.
           DISPLAY "READ KEY R002 DATA=" IDX-DATA " STATUS=" WS-STATUS.

           MOVE "R001" TO IDX-KEY.
           START IDX-FILE KEY = IDX-KEY.
           DISPLAY "START = R001 STATUS=" WS-STATUS.

           MOVE "N" TO WS-EOF.
           MOVE 0 TO WS-COUNT.
           PERFORM UNTIL WS-EOF = "Y"
               READ IDX-FILE NEXT
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       DISPLAY "NEXT: KEY=" IDX-KEY " DATA=" IDX-DATA " STATUS=" WS-STATUS
               END-READ
           END-PERFORM.
           DISPLAY "RECORDS READ=" WS-COUNT.

           MOVE "R003" TO IDX-KEY.
           START IDX-FILE KEY >= IDX-KEY.
           DISPLAY "START >= R003 STATUS=" WS-STATUS.
           READ IDX-FILE NEXT
               AT END MOVE "Y" TO WS-EOF
               NOT AT END
                   DISPLAY "NEXT FROM >= R003: KEY=" IDX-KEY " DATA=" IDX-DATA
           END-READ.

           DELETE IDX-FILE RECORD.
           DISPLAY "DELETE R003 STATUS=" WS-STATUS.

           DELETE IDX-FILE RECORD
               INVALID KEY
                   DISPLAY "DELETE R003 AGAIN INVALID KEY STATUS=" WS-STATUS
           END-DELETE.

           MOVE "R999" TO IDX-KEY.
           READ IDX-FILE
               INVALID KEY
                   DISPLAY "READ R999 INVALID KEY STATUS=" WS-STATUS
           END-READ.

           MOVE "R001" TO IDX-KEY.
           READ IDX-FILE
               NOT INVALID KEY
                   DISPLAY "READ R001 OK DATA=" IDX-DATA " STATUS=" WS-STATUS
           END-READ.

           MOVE "R999" TO IDX-KEY.
           MOVE "REC-NINE-NEVER----" TO IDX-DATA.
           REWRITE IDX-REC
               INVALID KEY
                   DISPLAY "REWRITE R999 INVALID KEY STATUS=" WS-STATUS
           END-REWRITE.

           CLOSE IDX-FILE.
           DISPLAY "FINAL CLOSE STATUS=" WS-STATUS.

           STOP RUN.

