IDENTIFICATION DIVISION.
       PROGRAM-ID. EVALUATE-DEMO.
       AUTHOR. VALIDATION-PLATFORM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GRADE          PIC 9(2) VALUE 85.
       01  WS-RESULT         PIC X(20) VALUE SPACES.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "EVALUATE DEMO STARTED".
           DISPLAY "GRADE=" WS-GRADE.

           EVALUATE WS-GRADE
               WHEN 90 THRU 100
                   MOVE "A" TO WS-RESULT
               WHEN 80 THRU 89
                   MOVE "B" TO WS-RESULT
               WHEN 70 THRU 79
                   MOVE "C" TO WS-RESULT
               WHEN 60 THRU 69
                   MOVE "D" TO WS-RESULT
               WHEN OTHER
                   MOVE "F" TO WS-RESULT
           END-EVALUATE.

           DISPLAY "LETTER GRADE=" WS-RESULT.

           EVALUATE TRUE
               WHEN WS-GRADE >= 90
                   DISPLAY "EXCELLENT"
               WHEN WS-GRADE >= 80
                   DISPLAY "GOOD"
               WHEN WS-GRADE >= 70
                   DISPLAY "AVERAGE"
               WHEN WS-GRADE >= 60
                   DISPLAY "BELOW AVERAGE"
               WHEN OTHER
                   DISPLAY "FAILING"
           END-EVALUATE.

           STOP RUN.