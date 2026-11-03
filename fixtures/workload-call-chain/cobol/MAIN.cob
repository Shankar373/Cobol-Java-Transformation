       IDENTIFICATION DIVISION.
       PROGRAM-ID. CHAINMAIN.
       AUTHOR. PHASE-D-D2.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A           PIC 9(4) VALUE 12.
       01  WS-B           PIC 9(4) VALUE 8.
       01  WS-TOTAL       PIC 9(6) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "CHAIN-START".
           DISPLAY "A=" WS-A.
           DISPLAY "B=" WS-B.
           CALL "MIDPROG" USING WS-A WS-B WS-TOTAL.
           DISPLAY "TOTAL-AFTER-MID=" WS-TOTAL.
           DISPLAY "CHAIN-END".
           STOP RUN.
