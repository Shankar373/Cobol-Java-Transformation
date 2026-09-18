       IDENTIFICATION DIVISION.
       PROGRAM-ID. ARITHMETIC.
       AUTHOR. VALIDATION-PLATFORM.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A            PIC 9(4) VALUE 10.
       01  WS-B            PIC 9(4) VALUE 5.
       01  WS-SUM          PIC 9(4).
       01  WS-DIFF         PIC 9(4).
       01  WS-PROD         PIC 9(8).
       01  WS-QUOT         PIC 9(4).
       01  WS-REM          PIC 9(4).
       01  WS-RESULT       PIC X(20).
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           COMPUTE WS-SUM = WS-A + WS-B
           COMPUTE WS-DIFF = WS-A - WS-B
           COMPUTE WS-PROD = WS-A * WS-B
           DIVIDE WS-A BY WS-B GIVING WS-QUOT REMAINDER WS-REM
           
           DISPLAY "SUM=" WS-SUM
           DISPLAY "DIFF=" WS-DIFF
           DISPLAY "PROD=" WS-PROD
           DISPLAY "QUOT=" WS-QUOT
           DISPLAY "REM=" WS-REM
           
           IF WS-A > WS-B THEN
               DISPLAY "A_GT_B=TRUE"
           ELSE
               DISPLAY "A_GT_B=FALSE"
           END-IF
           
           IF WS-A = WS-B THEN
               DISPLAY "A_EQ_B=TRUE"
           ELSE
               DISPLAY "A_EQ_B=FALSE"
           END-IF
           
           IF WS-A < WS-B THEN
               DISPLAY "A_LT_B=TRUE"
           ELSE
               DISPLAY "A_LT_B=FALSE"
           END-IF
           
           STOP RUN.
