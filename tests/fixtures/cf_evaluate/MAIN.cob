       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-G PIC X(1) VALUE 'B'.
       01 WS-R PIC X(5) VALUE SPACES.
       01 WS-SCORE PIC 9(4) VALUE 75.
       01 WS-GRADE PIC X(7) VALUE SPACES.
       01 WS-FLAG PIC X(1) VALUE 'N'.
       01 WS-F PIC X(3) VALUE SPACES.
       01 WS-N1 PIC 9(4) VALUE 5.
       01 WS-N2 PIC 9(4) VALUE 10.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'EVAL-START'.
           EVALUATE WS-G
               WHEN 'A'
                   MOVE 'ALPHA' TO WS-R
               WHEN 'B'
                   MOVE 'BETA ' TO WS-R
               WHEN OTHER
                   MOVE 'OTHER' TO WS-R
           END-EVALUATE.
           DISPLAY 'R=' WS-R.
           EVALUATE WS-SCORE
               WHEN 0 THRU 59
                   MOVE 'FAIL   ' TO WS-GRADE
               WHEN 60 THRU 79
                   MOVE 'PASS   ' TO WS-GRADE
               WHEN 80 THRU 100
                   MOVE 'GOOD   ' TO WS-GRADE
               WHEN OTHER
                   MOVE 'UNKNOWN' TO WS-GRADE
           END-EVALUATE.
           DISPLAY 'G=' WS-GRADE.
           EVALUATE WS-FLAG
               WHEN 'Y'
                   MOVE 'YES' TO WS-F
               WHEN 'y'
                   MOVE 'YES' TO WS-F
               WHEN 'N'
                   MOVE 'NO ' TO WS-F
               WHEN OTHER
                   MOVE '???' TO WS-F
           END-EVALUATE.
           DISPLAY 'F=' WS-F.
           IF WS-N1 < WS-N2 AND WS-FLAG = 'N'
               DISPLAY 'IF-AND-OK'
           ELSE
               DISPLAY 'IF-AND-BAD'
           END-IF.
           IF WS-N1 > WS-N2 OR WS-FLAG = 'N'
               DISPLAY 'IF-OR-OK'
           ELSE
               DISPLAY 'IF-OR-BAD'
           END-IF.
           IF NOT (WS-N1 = WS-N2)
               DISPLAY 'IF-NOT-OK'
           ELSE
               DISPLAY 'IF-NOT-BAD'
           END-IF.
           DISPLAY 'EVAL-END'.
           STOP RUN.
