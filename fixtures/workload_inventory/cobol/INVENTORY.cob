       IDENTIFICATION DIVISION.
       PROGRAM-ID. INVENTORY.
       AUTHOR. VALIDATION-PLATFORM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT RPT-FILE ASSIGN TO "/workspace/output/report.txt"
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT REC-FILE ASSIGN TO "/workspace/output/inventory.dat"
               ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  RPT-FILE.
       01  RPT-RECORD             PIC X(60).

       FD  REC-FILE.
       01  REC-RECORD             PIC X(60).

       WORKING-STORAGE SECTION.
       01  WS-IDX                 PIC 9(1).
       01  WS-ITEM-COUNT          PIC 9(1) VALUE 0.
       01  WS-TOTAL-VALUE         PIC 9(7)V99 VALUE 0.
       01  WS-TOTAL-VALUE-OUT     PIC 9(9) VALUE 0.
       01  WS-AVG-VALUE           PIC 9(7)V99 VALUE 0.
       01  WS-AVG-VALUE-OUT       PIC 9(9) VALUE 0.

       01  WS-ITEM-CODE           PIC X(7).
       01  WS-ITEM-NAME           PIC X(10).
       01  WS-QTY                 PIC 9(4).
       01  WS-UNIT-PRICE          PIC 9(3)V99.
       01  WS-UNIT-PRICE-OUT      PIC 9(6) VALUE 0.
       01  WS-TOTAL-ITEM          PIC 9(5)V99 VALUE 0.
       01  WS-TOTAL-ITEM-OUT      PIC 9(8) VALUE 0.
       01  WS-REORDER-POINT       PIC 9(4) VALUE 20.

       01  WS-HEADER              PIC X(60) VALUE
           "CODE    NAME       QTY  PRICE   VALUE".
       01  WS-SPACER              PIC X(60) VALUE SPACES.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN OUTPUT RPT-FILE
           OPEN OUTPUT REC-FILE

           MOVE WS-HEADER TO RPT-RECORD
           WRITE RPT-RECORD
           MOVE WS-SPACER TO RPT-RECORD
           WRITE RPT-RECORD

           PERFORM PROCESS-ITEM
               VARYING WS-IDX FROM 1 BY 1
               UNTIL WS-IDX > 6

           COMPUTE WS-TOTAL-VALUE-OUT =
               WS-TOTAL-VALUE * 100
           COMPUTE WS-AVG-VALUE =
               WS-TOTAL-VALUE / WS-ITEM-COUNT
           COMPUTE WS-AVG-VALUE-OUT =
               WS-AVG-VALUE * 100

           DISPLAY "TOTAL_VALUE=" WS-TOTAL-VALUE-OUT
           DISPLAY "ITEM_COUNT=" WS-ITEM-COUNT
           DISPLAY "AVERAGE_VALUE=" WS-AVG-VALUE-OUT

           CLOSE RPT-FILE
           CLOSE REC-FILE

           STOP RUN.

       PROCESS-ITEM.
           EVALUATE WS-IDX
               WHEN 1
                   MOVE "ITEM001" TO WS-ITEM-CODE
                   MOVE "WIDGET A  " TO WS-ITEM-NAME
                   MOVE 100 TO WS-QTY
                   MOVE 25.50 TO WS-UNIT-PRICE
                   COMPUTE WS-UNIT-PRICE-OUT =
                       WS-UNIT-PRICE * 100
               WHEN 2
                   MOVE "ITEM002" TO WS-ITEM-CODE
                   MOVE "GADGET B  " TO WS-ITEM-NAME
                   MOVE 50 TO WS-QTY
                   MOVE 15.75 TO WS-UNIT-PRICE
                   COMPUTE WS-UNIT-PRICE-OUT =
                       WS-UNIT-PRICE * 100
               WHEN 3
                   MOVE "ITEM003" TO WS-ITEM-CODE
                   MOVE "GIZMO C   " TO WS-ITEM-NAME
                   MOVE 200 TO WS-QTY
                   MOVE 8.25 TO WS-UNIT-PRICE
                   COMPUTE WS-UNIT-PRICE-OUT =
                       WS-UNIT-PRICE * 100
               WHEN 4
                   MOVE "ITEM004" TO WS-ITEM-CODE
                   MOVE "TOOL D    " TO WS-ITEM-NAME
                   MOVE 10 TO WS-QTY
                   MOVE 45.00 TO WS-UNIT-PRICE
                   COMPUTE WS-UNIT-PRICE-OUT =
                       WS-UNIT-PRICE * 100
               WHEN 5
                   MOVE "ITEM005" TO WS-ITEM-CODE
                   MOVE "PART E    " TO WS-ITEM-NAME
                   MOVE 300 TO WS-QTY
                   MOVE 3.50 TO WS-UNIT-PRICE
                   COMPUTE WS-UNIT-PRICE-OUT =
                       WS-UNIT-PRICE * 100
               WHEN 6
                   MOVE "ITEM006" TO WS-ITEM-CODE
                   MOVE "BOLT F    " TO WS-ITEM-NAME
                   MOVE 5 TO WS-QTY
                   MOVE 99.99 TO WS-UNIT-PRICE
                   COMPUTE WS-UNIT-PRICE-OUT =
                       WS-UNIT-PRICE * 100
           END-EVALUATE

           COMPUTE WS-TOTAL-ITEM =
               WS-QTY * WS-UNIT-PRICE
           COMPUTE WS-TOTAL-ITEM-OUT =
               WS-TOTAL-ITEM * 100

           ADD WS-TOTAL-ITEM TO WS-TOTAL-VALUE
           ADD 1 TO WS-ITEM-COUNT

           MOVE SPACES TO RPT-RECORD
           STRING WS-ITEM-CODE DELIMITED BY SIZE
               " " DELIMITED BY SIZE
               WS-ITEM-NAME DELIMITED BY SIZE
               " " DELIMITED BY SIZE
               WS-QTY DELIMITED BY SIZE
               " " DELIMITED BY SIZE
               WS-UNIT-PRICE-OUT DELIMITED BY SIZE
               " " DELIMITED BY SIZE
               WS-TOTAL-ITEM-OUT DELIMITED BY SIZE
               INTO RPT-RECORD
           END-STRING
           WRITE RPT-RECORD

           MOVE SPACES TO REC-RECORD
           STRING WS-ITEM-CODE DELIMITED BY SIZE
               "|" DELIMITED BY SIZE
               WS-ITEM-NAME DELIMITED BY SIZE
               "|" DELIMITED BY SIZE
               WS-QTY DELIMITED BY SIZE
               "|" DELIMITED BY SIZE
               WS-UNIT-PRICE-OUT DELIMITED BY SIZE
               "|" DELIMITED BY SIZE
               WS-TOTAL-ITEM-OUT DELIMITED BY SIZE
               INTO REC-RECORD
           END-STRING
           WRITE REC-RECORD

           IF WS-QTY < WS-REORDER-POINT THEN
               DISPLAY "WARN:" WS-ITEM-CODE
                   " " WS-ITEM-NAME
                   " qty=" WS-QTY
                   " below reorder"
                   UPON STDERR
           END-IF
           .
