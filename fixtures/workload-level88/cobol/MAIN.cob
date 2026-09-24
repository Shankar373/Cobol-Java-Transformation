IDENTIFICATION DIVISION.
       PROGRAM-ID. LEVEL88-DEMO.
       AUTHOR. VALIDATION-PLATFORM.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-STATUS         PIC 9(2) VALUE 10.
           88  STAT-OK            VALUE 00.
           88  STAT-WARNING       VALUE 01 THRU 09.
           88  STAT-ERROR         VALUE 10 THRU 99.
       01  WS-GENDER         PIC X VALUE 'M'.
           88  GENDER-MALE        VALUE 'M'.
           88  GENDER-FEMALE      VALUE 'F'.
       01  WS-RESULT         PIC X(20) VALUE SPACES.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "LEVEL-88 DEMO STARTED".

           EVALUATE TRUE
               WHEN STAT-OK
                   MOVE "STATUS OK" TO WS-RESULT
               WHEN STAT-WARNING
                   MOVE "STATUS WARNING" TO WS-RESULT
               WHEN STAT-ERROR
                   MOVE "STATUS ERROR" TO WS-RESULT
           END-EVALUATE.
           DISPLAY "STATUS CHECK: " WS-RESULT.

           IF GENDER-MALE
               DISPLAY "GENDER IS MALE"
           ELSE
               DISPLAY "GENDER IS FEMALE"
           END-IF.

           SET STAT-OK TO TRUE.
           DISPLAY "AFTER SET STAT-OK: WS-STATUS=" WS-STATUS.

           SET GENDER-FEMALE TO TRUE.
           DISPLAY "AFTER SET GENDER-FEMALE: WS-GENDER=" WS-GENDER.

           STOP RUN.