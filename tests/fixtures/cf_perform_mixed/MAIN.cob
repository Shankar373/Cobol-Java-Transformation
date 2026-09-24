       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-S PIC 9(4) VALUE 0.
       01 WS-I PIC 9(4) VALUE 0.
       01 WS-J PIC 9(4) VALUE 0.
       01 WS-V PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'MIXED-START'.
           PERFORM SET-PARA.
           DISPLAY 'A=' WS-S.
           PERFORM R1-PARA THRU R3-PARA.
           DISPLAY 'B=' WS-S.
           PERFORM V-PARA VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 4.
           DISPLAY 'C=' WS-S.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 6
               IF WS-I = 2
                   ADD 10 TO WS-V
               ELSE
                   ADD 1 TO WS-V
               END-IF
           END-PERFORM.
           DISPLAY 'D=' WS-V.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 2
               PERFORM VARYING WS-J FROM 1 BY 1 UNTIL WS-J > 3
                   ADD 1 TO WS-S
               END-PERFORM
           END-PERFORM.
           DISPLAY 'E=' WS-S.
           DISPLAY 'MIXED-END'.
           STOP RUN.
       SET-PARA.
           MOVE 42 TO WS-S.
       R1-PARA.
           ADD 1 TO WS-S.
       R2-PARA.
           ADD 2 TO WS-S.
       R3-PARA.
           ADD 3 TO WS-S.
       V-PARA.
           ADD 1 TO WS-S.
