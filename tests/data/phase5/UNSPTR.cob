       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNSPTR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TEXT     PIC X(30) VALUE "ALPHA,BETA,GAMMA,DELTA".
       01  WS-A        PIC X(8).
       01  WS-B        PIC X(4).
       01  WS-C        PIC X(8).
       01  WS-PTR      PIC 9(3) VALUE 1.
       01  WS-CNT      PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
           UNSTRING WS-TEXT DELIMITED BY ","
               INTO WS-A WS-B
               WITH POINTER WS-PTR
               TALLYING IN WS-CNT
           END-UNSTRING
           DISPLAY "A=[" WS-A "] B=[" WS-B "]"
           DISPLAY "PTR=" WS-PTR " CNT=" WS-CNT
           UNSTRING WS-TEXT DELIMITED BY ","
               INTO WS-C
               WITH POINTER WS-PTR
               TALLYING IN WS-CNT
           END-UNSTRING
           DISPLAY "C=[" WS-C "]"
           DISPLAY "PTR=" WS-PTR " CNT=" WS-CNT
           MOVE 7 TO WS-PTR
           MOVE 0 TO WS-CNT
           UNSTRING WS-TEXT DELIMITED BY ","
               INTO WS-A
               WITH POINTER WS-PTR
               TALLYING IN WS-CNT
           END-UNSTRING
           DISPLAY "A=[" WS-A "] PTR=" WS-PTR " CNT=" WS-CNT
           STOP RUN.
