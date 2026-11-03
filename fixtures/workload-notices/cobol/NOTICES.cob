       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOTICES.
      * Customer notice batch: writes a LINE SEQUENTIAL report through a
      * single-quoted ASSIGN, uses continued literals and words, and
      * doubled-quote escapes, then reads the report back.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT NOTICE-FILE
               ASSIGN TO 'NOTICES.TXT'
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-STATUS.
       DATA DIVISION.
       FILE SECTION.
       FD  NOTICE-FILE.
       01  NOTICE-REC              PIC X(60).
       WORKING-STORAGE SECTION.
       01  WS-STATUS               PIC XX VALUE '00'.
       01  WS-EOF                  PIC X VALUE 'N'.
       01  WS-LINES                PIC 99 VALUE 0.
       01  WS-HEADER               PIC X(60) VALUE 'CUSTOMER NOTICE BAT
      -    'CH - QUARTERLY STATEMENT RUN'.
       01  WS-OVERDUE-MESSAGE      PIC X(60) VALUE
           'ACCOUNT OVERDUE; PLEASE CALL YOUR BRANCH''S DESK'.
       01  WS-THANKS               PIC X(31)
           VALUE "THANK YOU FOR ""BANKING"" WITH US".
       01  WS-CUSTOMER-NAME        PIC X(20) VALUE "O'BRIEN".
       01  WS-BALANCE-DUE          PIC 9(5) VALUE 12
      -    345.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT NOTICE-FILE.
           MOVE WS-HEADER TO NOTICE-REC.
           WRITE NOTICE-REC.
           MOVE SPACES TO NOTICE-REC.
           STRING 'DEAR ' DELIMITED BY SIZE
               WS-CUSTOMER-NAME DELIMITED BY SPACE
               INTO NOTICE-REC
           END-STRING.
           WRITE NOTICE-REC.
           MOVE WS-OVERDUE-MESSAGE TO NOTICE-REC.
           WRITE NOTICE-REC.
           MOVE WS-THANKS TO NOTICE-REC.
           WRITE NOTICE-REC.
           CLOSE NOTICE-FILE.
           DISPLAY 'WRITE STATUS=' WS-STATUS.
           DISPLAY 'BALANCE DUE=' WS-BALAN
      -    CE-DUE.
           OPEN INPUT NOTICE-FILE.
           PERFORM UNTIL WS-EOF = 'Y'
               READ NOTICE-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-LINES
                       DISPLAY '> ' NOTICE-REC
               END-READ
           END-PERFORM.
           CLOSE NOTICE-FILE.
           DISPLAY 'LINES READ=' WS-LINES ' ''DONE'''.
           STOP RUN.
