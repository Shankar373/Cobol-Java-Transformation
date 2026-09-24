       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-N PIC 9(4) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'GOTO-START'.
           GO TO END-PARA.
           ADD 100 TO WS-N.
       END-PARA.
           DISPLAY 'N=' WS-N.
           DISPLAY 'GOTO-END'.
           STOP RUN.
