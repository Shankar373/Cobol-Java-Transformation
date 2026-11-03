       IDENTIFICATION DIVISION.
       PROGRAM-ID. BALCHECK.
      * Account balance review: sign conditions, signed thresholds and
      * ZERO comparisons in IF, EVALUATE and PERFORM UNTIL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-IDX                PIC 9(2) VALUE 0.
       01  WS-BALANCE            PIC S9(5)V99 VALUE 0.
       01  WS-LIMIT              PIC S9(5)V99 VALUE -250.00.
       01  WS-COUNTDOWN          PIC 9(2) VALUE 3.
       01  WS-OVERDRAWN          PIC 9(2) VALUE 0.
       01  WS-FLAT               PIC 9(2) VALUE 0.
       01  WS-STATUS-CODE        PIC X(3) VALUE '000'.
       01  WS-DELTA              PIC S9(3) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM VARYING WS-IDX FROM 1 BY 1 UNTIL WS-IDX > 6
               PERFORM LOAD-BALANCE
               PERFORM CLASSIFY
           END-PERFORM
           DISPLAY 'OVERDRAWN ' WS-OVERDRAWN ' FLAT ' WS-FLAT
           PERFORM UNTIL WS-COUNTDOWN IS ZERO
               DISPLAY 'COUNTDOWN ' WS-COUNTDOWN
               SUBTRACT 1 FROM WS-COUNTDOWN
           END-PERFORM
           IF WS-STATUS-CODE = ZERO
               DISPLAY 'STATUS CLEAR'
           END-IF
           MOVE '0 0' TO WS-STATUS-CODE
           IF WS-STATUS-CODE NOT = ZEROS
               DISPLAY 'STATUS NOT CLEAR'
           END-IF
           MOVE -5 TO WS-DELTA
           IF WS-DELTA < +0 AND WS-DELTA > -10
               DISPLAY 'SMALL NEGATIVE DELTA ' WS-DELTA
           END-IF
           STOP RUN.

       LOAD-BALANCE.
           EVALUATE WS-IDX
               WHEN 1 MOVE 1200.50 TO WS-BALANCE
               WHEN 2 MOVE -75.25 TO WS-BALANCE
               WHEN 3 MOVE 0 TO WS-BALANCE
               WHEN 4 MOVE -300.00 TO WS-BALANCE
               WHEN 5 MOVE -250.00 TO WS-BALANCE
               WHEN OTHER MOVE 0.01 TO WS-BALANCE
           END-EVALUATE.

       CLASSIFY.
           EVALUATE TRUE
               WHEN WS-BALANCE IS ZERO
                   ADD 1 TO WS-FLAT
                   DISPLAY WS-IDX ' FLAT ' WS-BALANCE
               WHEN WS-BALANCE < WS-LIMIT
                   ADD 1 TO WS-OVERDRAWN
                   DISPLAY WS-IDX ' OVER LIMIT ' WS-BALANCE
               WHEN WS-BALANCE IS NEGATIVE
                   ADD 1 TO WS-OVERDRAWN
                   DISPLAY WS-IDX ' OVERDRAWN ' WS-BALANCE
               WHEN OTHER
                   DISPLAY WS-IDX ' IN CREDIT ' WS-BALANCE
           END-EVALUATE
           IF WS-BALANCE IS NOT POSITIVE AND WS-BALANCE > -100.00
               DISPLAY WS-IDX ' WATCH'
           END-IF
           IF WS-BALANCE = -250
               DISPLAY WS-IDX ' AT LIMIT'
           END-IF.
