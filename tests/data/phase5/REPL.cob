       IDENTIFICATION DIVISION.
       PROGRAM-ID. REPL.
       REPLACE ==:LIMIT:== BY ==5==
               ==:LABEL:== BY =="TOTAL="==.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-I        PIC 9(2) VALUE 0.
       01  WS-SUM      PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > :LIMIT:
               ADD WS-I TO WS-SUM
           END-PERFORM
           DISPLAY :LABEL: WS-SUM
           DISPLAY "LIMIT " :LIMIT:
           STOP RUN.
