       IDENTIFICATION DIVISION.
       PROGRAM-ID. ACCRUE.
      * Interest accrual with ON SIZE ERROR guards: rounded interest
      * that can overflow its field, per-term averages with zero
      * terms, and an accumulator that saturates.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IDX                PIC 9(2) VALUE 0.
       01  WS-PRINCIPAL          PIC 9(7)V99 VALUE 0.
       01  WS-RATE               PIC 9V9999 VALUE 0.
       01  WS-TERMS              PIC 9(2) VALUE 0.
       01  WS-INTEREST           PIC 9(5)V99 VALUE 0.
       01  WS-PER-TERM           PIC 9(5)V99 VALUE 0.
       01  WS-TOTAL              PIC 9(6)V99 VALUE 0.
       01  WS-ERRORS             PIC 9(2) VALUE 0.
       01  WS-CAPPED             PIC 9(2) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM VARYING WS-IDX FROM 1 BY 1 UNTIL WS-IDX > 5
               PERFORM LOAD-ACCOUNT
               PERFORM ACCRUE-INTEREST
           END-PERFORM
           DISPLAY 'TOTAL ' WS-TOTAL ' ERRORS ' WS-ERRORS
               ' CAPPED ' WS-CAPPED
           ADD 999999 TO WS-TOTAL ON SIZE ERROR
               DISPLAY 'TOTAL SATURATED ' WS-TOTAL.
           MULTIPLY 2 BY WS-ERRORS
               NOT ON SIZE ERROR DISPLAY 'ERRORS DOUBLED ' WS-ERRORS
           END-MULTIPLY
           STOP RUN.

       LOAD-ACCOUNT.
           EVALUATE WS-IDX
               WHEN 1 MOVE 10000.00 TO WS-PRINCIPAL
                      MOVE 0.0525 TO WS-RATE
                      MOVE 12 TO WS-TERMS
               WHEN 2 MOVE 2500000.00 TO WS-PRINCIPAL
                      MOVE 0.0800 TO WS-RATE
                      MOVE 4 TO WS-TERMS
               WHEN 3 MOVE 750.50 TO WS-PRINCIPAL
                      MOVE 0.0333 TO WS-RATE
                      MOVE 0 TO WS-TERMS
               WHEN 4 MOVE 999999.99 TO WS-PRINCIPAL
                      MOVE 0.0999 TO WS-RATE
                      MOVE 3 TO WS-TERMS
               WHEN OTHER MOVE 1.00 TO WS-PRINCIPAL
                      MOVE 0.0050 TO WS-RATE
                      MOVE 1 TO WS-TERMS
           END-EVALUATE.

       ACCRUE-INTEREST.
           COMPUTE WS-INTEREST ROUNDED = WS-PRINCIPAL * WS-RATE
               ON SIZE ERROR
                   ADD 1 TO WS-CAPPED
                   DISPLAY WS-IDX ' INTEREST TOO LARGE, KEPT '
                       WS-INTEREST
               NOT ON SIZE ERROR
                   ADD WS-INTEREST TO WS-TOTAL
                   DISPLAY WS-IDX ' INTEREST ' WS-INTEREST
           END-COMPUTE
           DIVIDE WS-INTEREST BY WS-TERMS GIVING WS-PER-TERM ROUNDED
               ON SIZE ERROR
                   ADD 1 TO WS-ERRORS
                   DISPLAY WS-IDX ' NO TERMS'
               NOT ON SIZE ERROR
                   DISPLAY WS-IDX ' PER TERM ' WS-PER-TERM
           END-DIVIDE.
