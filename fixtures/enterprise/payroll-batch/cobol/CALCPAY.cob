       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALCPAY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO INDD
               ORGANIZATION IS LINE SEQUENTIAL.
           SELECT OUT-FILE ASSIGN TO OUTDD
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD IN-FILE.
       01 IN-REC.
           05 IN-NAME PIC X(8).
           05 IN-AMT PIC 9(4).
       FD OUT-FILE.
       01 OUT-REC.
           05 OUT-NAME PIC X(8).
           05 OUT-AMT PIC 9(4).
       WORKING-STORAGE SECTION.
       01 EOF-FLAG PIC X VALUE "N".
       01 TOTAL PIC 9(6) VALUE 0.
       01 COUNTER PIC 9(3) VALUE 0.
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE
           OPEN OUTPUT OUT-FILE
           PERFORM UNTIL EOF-FLAG = "Y"
               READ IN-FILE
                   AT END MOVE "Y" TO EOF-FLAG
                   NOT AT END
                       MOVE IN-NAME TO OUT-NAME
                       COMPUTE OUT-AMT = IN-AMT * 2
                       ADD OUT-AMT TO TOTAL
                       ADD 1 TO COUNTER
                       WRITE OUT-REC
               END-READ
           END-PERFORM
           CLOSE IN-FILE
           CLOSE OUT-FILE
           DISPLAY "CALCPAY " COUNTER " RECORDS TOTAL " TOTAL
           IF TOTAL > 500
               MOVE 4 TO RETURN-CODE
           END-IF
           STOP RUN.
