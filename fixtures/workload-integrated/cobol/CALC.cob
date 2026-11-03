       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTGCALC.
       AUTHOR. PHASE-D-D4.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TMP                     PIC 9(9) VALUE 0.

       LINKAGE SECTION.
       01  LK-AMOUNT                  PIC 9(6).
       01  LK-RATE                    PIC 9(3).
       01  LK-TAX                     PIC 9(6).

       PROCEDURE DIVISION USING LK-AMOUNT LK-RATE LK-TAX.
       CALC-LOGIC.
           DISPLAY "CALC-START".
           COMPUTE WS-TMP = LK-AMOUNT * LK-RATE / 100.
           MOVE WS-TMP TO LK-TAX.
           DISPLAY "CALC TAX=" LK-TAX.
           EXIT PROGRAM.
