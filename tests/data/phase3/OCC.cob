       IDENTIFICATION DIVISION.
       PROGRAM-ID. OCC.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUMS.
           05  WS-N              PIC 9(3) OCCURS 5 TIMES.
       01  WS-NAMES.
           05  WS-NAME           PIC X(4) OCCURS 3 TIMES VALUE 'NONE'.
       01  WS-RATES.
           05  WS-RATE           PIC 9V99 OCCURS 4.
       01  WS-I                  PIC 9(2) VALUE 0.
       01  WS-J                  PIC 9(2) VALUE 0.
       01  WS-TOTAL              PIC 9(5) VALUE 0.
       01  WS-PICK               PIC 9 VALUE 2.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5
               COMPUTE WS-N(WS-I) = WS-I * WS-I + 1
           END-PERFORM
           MOVE 999 TO WS-N(3)
           ADD WS-N(1) TO WS-N(5)
           MOVE WS-N(5) TO WS-N(4)
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5
               ADD WS-N(WS-I) TO WS-TOTAL
               DISPLAY 'N(' WS-I ')=' WS-N(WS-I)
           END-PERFORM
           DISPLAY 'TOTAL ' WS-TOTAL
           DISPLAY 'NAMES ' WS-NAME(1) WS-NAME(2) WS-NAME(3)
           MOVE 'ALFA' TO WS-NAME(1)
           MOVE 'BO' TO WS-NAME(WS-PICK)
           DISPLAY 'NAMES [' WS-NAME(1) '|' WS-NAME(2) '|'
               WS-NAME(3) ']'
           IF WS-NAME(2) = 'BO'
               DISPLAY 'PADDED COMPARE OK'
           END-IF
           MOVE 1.25 TO WS-RATE(1)
           MOVE 0.5 TO WS-RATE(2)
           COMPUTE WS-RATE(3) ROUNDED = WS-RATE(1) * WS-RATE(2)
           COMPUTE WS-RATE(4) = WS-RATE(3) + 9
           DISPLAY 'RATES ' WS-RATE(1) ' ' WS-RATE(2) ' ' WS-RATE(3)
               ' ' WS-RATE(4)
           MOVE 1 TO WS-J
           MOVE WS-N(WS-J) TO WS-I
           DISPLAY 'INDIRECT ' WS-N(WS-I)
           IF WS-N(2) > WS-N(1) AND WS-RATE(1) > 1
               DISPLAY 'COMPARE OK'
           END-IF
           MOVE 995 TO WS-N(2)
           ADD 10 TO WS-N(2)
           DISPLAY 'WRAP ' WS-N(2)
           STOP RUN.
