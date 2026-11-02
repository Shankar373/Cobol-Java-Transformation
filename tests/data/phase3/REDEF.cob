       IDENTIFICATION DIVISION.
       PROGRAM-ID. REDEF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATE               PIC 9(8) VALUE 20261102.
       01  WS-DATE-R REDEFINES WS-DATE.
           05  WS-YYYY           PIC 9(4).
           05  WS-MM             PIC 9(2).
           05  WS-DD             PIC 9(2).
       01  WS-CODE               PIC X(6) VALUE 'AB1234'.
       01  WS-CODE-R REDEFINES WS-CODE.
           05  WS-PFX            PIC X(2).
           05  WS-NUM            PIC 9(4).
       01  WS-AMT                PIC 9(6) VALUE 123.
       01  WS-AMT-X REDEFINES WS-AMT PIC X(6).
       01  WS-TWICE              PIC 9(5) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'R1 ' WS-YYYY '|' WS-MM '|' WS-DD
           MOVE 12 TO WS-MM
           DISPLAY 'R2 ' WS-DATE
           MOVE 19991231 TO WS-DATE
           DISPLAY 'R3 ' WS-YYYY '|' WS-MM '|' WS-DD
           DISPLAY 'R4 ' WS-PFX '|' WS-NUM
           MOVE 7 TO WS-NUM
           DISPLAY 'R5 ' WS-CODE
           MOVE 'XY0099' TO WS-CODE
           DISPLAY 'R6 ' WS-PFX '|' WS-NUM
           COMPUTE WS-TWICE = WS-NUM * 2
           DISPLAY 'R7 ' WS-TWICE
           DISPLAY 'R8 ' WS-AMT-X
           MOVE '000456' TO WS-AMT-X
           DISPLAY 'R9 ' WS-AMT
           MOVE 12345678 TO WS-AMT
           DISPLAY 'R10 ' WS-AMT-X
           MOVE 'Q' TO WS-PFX
           DISPLAY 'R11 [' WS-CODE ']'
           STOP RUN.
