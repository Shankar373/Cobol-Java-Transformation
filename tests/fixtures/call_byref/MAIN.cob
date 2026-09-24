       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4) VALUE 5.
       01 WS-B PIC 9(4) VALUE 7.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'CALL-START'.
           DISPLAY 'A0=' WS-A.
           CALL 'DOUBLE' USING BY REFERENCE WS-A
               BY CONTENT WS-B.
           DISPLAY 'A=' WS-A.
           DISPLAY 'B=' WS-B.
           DISPLAY 'CALL-END'.
           STOP RUN.
