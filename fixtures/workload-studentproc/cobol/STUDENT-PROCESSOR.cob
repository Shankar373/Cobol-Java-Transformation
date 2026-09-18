       IDENTIFICATION DIVISION.
       PROGRAM-ID. STUDENT-PROCESSOR.
       AUTHOR. SYSTEMA-OPS.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
        SELECT STUDENT-FILE ASSIGN TO "/workspace/input/students.dat"
            ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  STUDENT-FILE.
       01  STUDENT-REC        PIC X(60).

       WORKING-STORAGE SECTION.
       01  WS-EOF             PIC X(1) VALUE 'N'.
       01  WS-ID              PIC X(4).
       01  WS-NAME            PIC X(12).
       01  WS-SCORE-1         PIC 9(3).
       01  WS-SCORE-2         PIC 9(3).
       01  WS-SCORE-3         PIC 9(3).
       01  WS-TOTAL           PIC 9(4) VALUE 0.
       01  WS-AVERAGE         PIC 9(3) VALUE 0.
       01  WS-GRADE           PIC X(2).
       01  WS-COUNT           PIC 9(3) VALUE 0.
       01  WS-PASS-COUNT      PIC 9(3) VALUE 0.
       01  WS-FAIL-COUNT      PIC 9(3) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT STUDENT-FILE
           PERFORM PROCESS-RECORDS
               UNTIL WS-EOF = 'Y'
           CLOSE STUDENT-FILE
           DISPLAY "TOTAL=" WS-COUNT
           DISPLAY "PASS=" WS-PASS-COUNT
           DISPLAY "FAIL=" WS-FAIL-COUNT
           STOP RUN.

       PROCESS-RECORDS.
           READ STUDENT-FILE
               AT END
                   MOVE 'Y' TO WS-EOF
               NOT AT END
                   ADD 1 TO WS-COUNT
                   MOVE 0 TO WS-TOTAL
                   UNSTRING STUDENT-REC DELIMITED BY "|"
                       INTO WS-ID
                            WS-NAME
                            WS-SCORE-1
                            WS-SCORE-2
                            WS-SCORE-3
                   END-UNSTRING
                   ADD WS-SCORE-1 TO WS-TOTAL
                   ADD WS-SCORE-2 TO WS-TOTAL
                   ADD WS-SCORE-3 TO WS-TOTAL
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
                   DISPLAY "STUDENT=" WS-ID " " WS-NAME " GRADE=" WS-GRADE
           END-READ.
