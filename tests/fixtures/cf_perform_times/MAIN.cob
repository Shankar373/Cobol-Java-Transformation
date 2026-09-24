       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-N PIC 9(4) VALUE 0.
       01 WS-K PIC 9(3) VALUE 2.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'TIMES-START'.
           PERFORM INCR-PARA 3 TIMES.
           DISPLAY 'A=' WS-N.
           PERFORM 2 TIMES
               ADD 10 TO WS-N
           END-PERFORM.
           DISPLAY 'B=' WS-N.
           PERFORM INCR-PARA WS-K TIMES.
           DISPLAY 'C=' WS-N.
           PERFORM 2 TIMES
               PERFORM 3 TIMES
                   ADD 1 TO WS-N
               END-PERFORM
           END-PERFORM.
           DISPLAY 'D=' WS-N.
           DISPLAY 'TIMES-END'.
           STOP RUN.
       INCR-PARA.
           ADD 1 TO WS-N.
