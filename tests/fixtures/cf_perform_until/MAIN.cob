       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-N PIC 9(4) VALUE 0.
       01 WS-Z PIC 9(4) VALUE 9.
       01 WS-M PIC 9(4) VALUE 0.
       01 WS-O PIC 9(4) VALUE 0.
       01 WS-P PIC 9(4) VALUE 0.
       01 WS-T PIC 9(4) VALUE 0.
       01 WS-E PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'UNTIL-START'.
           PERFORM LOOP-PARA UNTIL WS-N >= 5.
           DISPLAY 'A=' WS-N.
           PERFORM SKIP-PARA UNTIL WS-Z >= 5.
           DISPLAY 'B=' WS-Z.
           PERFORM UNTIL WS-M >= 4
               ADD 1 TO WS-M
           END-PERFORM.
           DISPLAY 'C=' WS-M.
           PERFORM UNTIL WS-O >= 2
               MOVE 0 TO WS-P
               PERFORM UNTIL WS-P >= 3
                   ADD 1 TO WS-T
                   ADD 1 TO WS-P
               END-PERFORM
               ADD 1 TO WS-O
           END-PERFORM.
           DISPLAY 'D=' WS-T.
           PERFORM E-PARA UNTIL WS-E = 3.
           DISPLAY 'E=' WS-E.
           DISPLAY 'UNTIL-END'.
           STOP RUN.
       LOOP-PARA.
           ADD 1 TO WS-N.
       SKIP-PARA.
           ADD 1 TO WS-Z.
       E-PARA.
           ADD 1 TO WS-E.
