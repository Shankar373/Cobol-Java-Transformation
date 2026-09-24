       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAIN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(4) VALUE 5.
       01 WS-V PIC X(4) VALUE 'WXYZ'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY 'CALL-START'.
           CALL 'SUBV' USING BY REFERENCE WS-A
               BY VALUE WS-V.
           DISPLAY 'A=' WS-A.
           DISPLAY 'V=' WS-V.
           DISPLAY 'CALL-END'.
           STOP RUN.
