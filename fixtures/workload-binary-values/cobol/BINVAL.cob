       IDENTIFICATION DIVISION.
       PROGRAM-ID. BINVAL.
      * Binary and packed items used only by value: every result must
      * equal the same program with the USAGE clauses removed.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-SHORT          PIC S9(4) COMP VALUE -100.
       01  WS-UNSIGNED       PIC 9(4) COMP VALUE 500.
       01  WS-TINY           PIC 9(2) COMP VALUE 7.
       01  WS-LONG           PIC S9(9) BINARY VALUE 123456789.
       01  WS-BIG            PIC S9(15) COMP VALUE 0.
       01  WS-PACKED         PIC S9(5)V99 COMP-3 VALUE -987.65.
       01  WS-EVEN           PIC S9(4) COMP-3 VALUE 0.
       01  WS-UPACK          PIC 9(3)V9 PACKED-DECIMAL VALUE 12.5.
       01  WS-IDX            PIC 9(4) COMPUTATIONAL VALUE 0.
       01  WS-REM            PIC S9(4) COMP-4 VALUE 0.
       01  WS-DISP           PIC S9(5) VALUE 42.
       01  WS-TEXT           PIC X(8) VALUE SPACES.
       01  WS-DIGITS         PIC X(4) VALUE '0042'.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'INIT ' WS-SHORT ' ' WS-UNSIGNED ' ' WS-TINY
           DISPLAY 'INIT ' WS-LONG ' ' WS-BIG ' ' WS-PACKED
           DISPLAY 'INIT ' WS-EVEN ' ' WS-UPACK ' ' WS-IDX
           MOVE 12345 TO WS-SHORT
           MOVE 12345 TO WS-EVEN
           MOVE -5 TO WS-UNSIGNED
           MOVE 250 TO WS-TINY
           DISPLAY 'TRUNC ' WS-SHORT ' ' WS-EVEN ' ' WS-UNSIGNED
               ' ' WS-TINY
           MOVE 123456.789 TO WS-PACKED
           DISPLAY 'PACK ' WS-PACKED
           COMPUTE WS-PACKED ROUNDED = 10 / 3
           DISPLAY 'ROUND ' WS-PACKED
           COMPUTE WS-PACKED = -10 / 3
           DISPLAY 'TRUNCQ ' WS-PACKED
           COMPUTE WS-SHORT = 7.9
           DISPLAY 'FRAC ' WS-SHORT
           MOVE 9990 TO WS-SHORT
           ADD 20 TO WS-SHORT
           DISPLAY 'WRAP ' WS-SHORT
           MOVE 99 TO WS-TINY
           ADD 1 TO WS-TINY
           DISPLAY 'TINY ' WS-TINY
           COMPUTE WS-BIG = WS-LONG * 1000 + WS-PACKED
           DISPLAY 'BIG ' WS-BIG
           SUBTRACT WS-LONG FROM WS-BIG GIVING WS-LONG
           DISPLAY 'LONG ' WS-LONG
           MOVE WS-SHORT TO WS-TEXT
           DISPLAY 'TEXT [' WS-TEXT ']'
           MOVE WS-DIGITS TO WS-UNSIGNED
           DISPLAY 'FROMX ' WS-UNSIGNED
           MOVE WS-UNSIGNED TO WS-DISP
           MOVE WS-DISP TO WS-EVEN
           DISPLAY 'XFER ' WS-DISP ' ' WS-EVEN
           DIVIDE 47 BY 5 GIVING WS-IDX REMAINDER WS-REM
           DISPLAY 'DIV ' WS-IDX ' ' WS-REM
           MOVE 0 TO WS-REM
           PERFORM VARYING WS-IDX FROM 1 BY 1 UNTIL WS-IDX > 4
               ADD WS-IDX TO WS-REM
           END-PERFORM
           DISPLAY 'LOOP ' WS-IDX ' ' WS-REM
           IF WS-UNSIGNED = WS-DISP
               DISPLAY 'EQUAL'
           ELSE
               DISPLAY 'NOT EQUAL'
           END-IF
           IF WS-PACKED < 0 AND WS-SHORT > 0
               DISPLAY 'SIGNS OK'
           END-IF
           MOVE ZERO TO WS-PACKED
           MULTIPLY -1 BY WS-PACKED
           DISPLAY 'NEGZERO ' WS-PACKED
           INITIALIZE WS-LONG
           DISPLAY 'INITIALIZED ' WS-LONG
           STOP RUN.
