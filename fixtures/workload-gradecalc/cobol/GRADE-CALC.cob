       IDENTIFICATION DIVISION.
       PROGRAM-ID. GRADE-CALC.
       AUTHOR. SYSTEMA-OPS.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STUDENT-ID      PIC X(4).
       01  WS-STUDENT-NAME    PIC X(12).
       01  WS-SCORE-1         PIC 9(3) VALUE 0.
       01  WS-SCORE-2         PIC 9(3) VALUE 0.
       01  WS-SCORE-3         PIC 9(3) VALUE 0.
       01  WS-TOTAL           PIC 9(4) VALUE 0.
       01  WS-AVERAGE         PIC 9(3) VALUE 0.
       01  WS-GRADE           PIC X(2).
       01  WS-COUNT           PIC 9(3) VALUE 0.
       01  WS-PASS-COUNT      PIC 9(3) VALUE 0.
       01  WS-FAIL-COUNT      PIC 9(3) VALUE 0.
       01  WS-TOTAL-SCORES    PIC 9(5) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE '1001' TO WS-STUDENT-ID
           MOVE 'Alice' TO WS-STUDENT-NAME
           MOVE 85 TO WS-SCORE-1
           MOVE 90 TO WS-SCORE-2
           MOVE 78 TO WS-SCORE-3
           ADD 1 TO WS-COUNT
           ADD WS-SCORE-1 TO WS-TOTAL
           ADD WS-SCORE-2 TO WS-TOTAL
           ADD WS-SCORE-3 TO WS-TOTAL
           ADD WS-SCORE-1 TO WS-TOTAL-SCORES
           ADD WS-SCORE-2 TO WS-TOTAL-SCORES
           ADD WS-SCORE-3 TO WS-TOTAL-SCORES
           DIVIDE WS-TOTAL BY 3 GIVING WS-AVERAGE
           IF WS-AVERAGE >= 90
               MOVE 'A' TO WS-GRADE
               ADD 1 TO WS-PASS-COUNT
           END-IF
           IF WS-AVERAGE >= 80 AND WS-AVERAGE < 90
               MOVE 'B' TO WS-GRADE
               ADD 1 TO WS-PASS-COUNT
           END-IF
           IF WS-AVERAGE >= 70 AND WS-AVERAGE < 80
               MOVE 'C' TO WS-GRADE
               ADD 1 TO WS-PASS-COUNT
           END-IF
           IF WS-AVERAGE >= 60 AND WS-AVERAGE < 70
               MOVE 'D' TO WS-GRADE
               ADD 1 TO WS-PASS-COUNT
           END-IF
           IF WS-AVERAGE < 60
               MOVE 'F' TO WS-GRADE
               ADD 1 TO WS-FAIL-COUNT
           END-IF
           DISPLAY "STUDENT=" WS-STUDENT-ID " " WS-STUDENT-NAME
           DISPLAY "AVERAGE=" WS-AVERAGE
           DISPLAY "GRADE=" WS-GRADE
           DISPLAY "COUNT=" WS-COUNT
           DISPLAY "PASS=" WS-PASS-COUNT
           DISPLAY "FAIL=" WS-FAIL-COUNT
           DISPLAY "TOTAL_SCORES=" WS-TOTAL-SCORES
           STOP RUN.
