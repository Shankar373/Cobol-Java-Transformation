IDENTIFICATION DIVISION.
       PROGRAM-ID. CALCULATE.
       AUTHOR. MULTI-PROG DEMO.
       
       DATA DIVISION.
       LINKAGE SECTION.
       01  LS-INPUT-A        PIC 9(4).
       01  LS-INPUT-B        PIC 9(4).
       01  LS-RESULT         PIC 9(6).
       
       WORKING-STORAGE SECTION.
       01  WS-TEMP           PIC 9(6) VALUE 0.
       
       PROCEDURE DIVISION USING LS-INPUT-A, LS-INPUT-B, LS-RESULT.
       MAIN-LOGIC.
           DISPLAY "SUBROUTINE CALCULATE STARTED".
           DISPLAY "INPUT A=" LS-INPUT-A.
           DISPLAY "INPUT B=" LS-INPUT-B.
           
           COMPUTE WS-TEMP = LS-INPUT-A + LS-INPUT-B.
           MOVE WS-TEMP TO LS-RESULT.
           
           DISPLAY "SUBROUTINE RESULT=" WS-TEMP.
           
           GOBACK.