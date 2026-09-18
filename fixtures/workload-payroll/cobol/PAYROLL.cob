       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAYROLL.
       AUTHOR. VALIDATION-PLATFORM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO "/workspace/output/report.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REC-FILE ASSIGN TO "/workspace/output/records.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE.
       01  RPT-RECORD             PIC X(60).

       FD  REC-FILE.
       01  REC-RECORD             PIC X(60).

       WORKING-STORAGE SECTION.
       01  WS-IDX                 PIC 9(1).
       01  WS-EMP-COUNT           PIC 9(1) VALUE 0.
       01  WS-TOTAL-PAYROLL       PIC 9(7) VALUE 0.
       01  WS-AVERAGE-PAY         PIC 9(7) VALUE 0.

       01  WS-EMP-NAME            PIC X(10).
       01  WS-BASE-PAY            PIC 9(5).
       01  WS-YEARS               PIC 9(2).
       01  WS-BONUS               PIC 9(5) VALUE 0.
       01  WS-TOTAL-PER           PIC 9(6) VALUE 0.

       01  WS-HEADER              PIC X(60) VALUE
           "NAME      BASE  YEARS BONUS  TOTAL".
       01  WS-SPACER              PIC X(60) VALUE SPACES.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN OUTPUT RPT-FILE
           OPEN OUTPUT REC-FILE

           MOVE WS-HEADER TO RPT-RECORD
           WRITE RPT-RECORD
           MOVE WS-SPACER TO RPT-RECORD
           WRITE RPT-RECORD

           PERFORM PROCESS-EMPLOYEE
               VARYING WS-IDX FROM 1 BY 1
               UNTIL WS-IDX > 5

           COMPUTE WS-AVERAGE-PAY =
               WS-TOTAL-PAYROLL / WS-EMP-COUNT

           DISPLAY "TOTAL_PAYROLL=" WS-TOTAL-PAYROLL
           DISPLAY "EMPLOYEE_COUNT=" WS-EMP-COUNT
           DISPLAY "AVERAGE_PAY=" WS-AVERAGE-PAY

           CLOSE RPT-FILE
           CLOSE REC-FILE

           STOP RUN.

       PROCESS-EMPLOYEE.
           EVALUATE WS-IDX
               WHEN 1
                   MOVE "ALICE" TO WS-EMP-NAME
                   MOVE 10000 TO WS-BASE-PAY
                   MOVE 3 TO WS-YEARS
               WHEN 2
                   MOVE "BOB" TO WS-EMP-NAME
                   MOVE 15000 TO WS-BASE-PAY
                   MOVE 7 TO WS-YEARS
               WHEN 3
                   MOVE "CHARLIE" TO WS-EMP-NAME
                   MOVE 12000 TO WS-BASE-PAY
                   MOVE 5 TO WS-YEARS
               WHEN 4
                   MOVE "DIANA" TO WS-EMP-NAME
                   MOVE 18000 TO WS-BASE-PAY
                   MOVE 10 TO WS-YEARS
               WHEN 5
                   MOVE "EVE" TO WS-EMP-NAME
                   MOVE 11000 TO WS-BASE-PAY
                   MOVE 2 TO WS-YEARS
           END-EVALUATE

           COMPUTE WS-BONUS =
               WS-BASE-PAY * WS-YEARS * 2 / 100

           COMPUTE WS-TOTAL-PER =
               WS-BASE-PAY + WS-BONUS

           ADD WS-TOTAL-PER TO WS-TOTAL-PAYROLL
           ADD 1 TO WS-EMP-COUNT

           MOVE SPACES TO RPT-RECORD
           STRING WS-EMP-NAME DELIMITED BY SPACE
               " " DELIMITED BY SIZE
               WS-BASE-PAY DELIMITED BY SIZE
               " " DELIMITED BY SIZE
               WS-YEARS DELIMITED BY SIZE
               " " DELIMITED BY SIZE
               WS-BONUS DELIMITED BY SIZE
               " " DELIMITED BY SIZE
               WS-TOTAL-PER DELIMITED BY SIZE
               INTO RPT-RECORD
           END-STRING
           WRITE RPT-RECORD

           MOVE SPACES TO REC-RECORD
           STRING WS-EMP-NAME DELIMITED BY SPACE
               "|" DELIMITED BY SIZE
               WS-BASE-PAY DELIMITED BY SIZE
               "|" DELIMITED BY SIZE
               WS-YEARS DELIMITED BY SIZE
               "|" DELIMITED BY SIZE
               WS-BONUS DELIMITED BY SIZE
               "|" DELIMITED BY SIZE
               WS-TOTAL-PER DELIMITED BY SIZE
               INTO REC-RECORD
           END-STRING
           WRITE REC-RECORD

           IF WS-YEARS > 5 THEN
               DISPLAY "WARN:" WS-EMP-NAME
                   " years=" WS-YEARS
                   UPON STDERR
           END-IF
           .
