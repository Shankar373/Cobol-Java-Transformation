       IDENTIFICATION DIVISION.
       PROGRAM-ID. INTGMAIN.
       AUTHOR. PHASE-D-D4.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TAX-OUT ASSIGN TO "/workspace/output/taxout.dat"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-OUT-STATUS.
           SELECT TAX-IN ASSIGN TO "/workspace/output/taxout.dat"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-IN-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  TAX-OUT.
       01  OUT-REC.
           05  OUT-ID                 PIC X(6).
           05  OUT-AMOUNT             PIC 9(6).
       FD  TAX-IN.
       01  IN-REC.
           05  IN-ID                  PIC X(6).
           05  IN-AMOUNT              PIC 9(6).

       WORKING-STORAGE SECTION.
       COPY TAXREC.

       01  WS-OUT-STATUS              PIC X(2) VALUE "00".
       01  WS-IN-STATUS               PIC X(2) VALUE "00".
       01  WS-EOF                     PIC X VALUE "N".
       01  WS-TAX                     PIC 9(6) VALUE 0.
       01  WS-COUNT                   PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "INTEGRATED DEMO STARTED".

           MOVE "C-1001" TO TAX-ID.
           MOVE 125000 TO TAX-AMOUNT.
           MOVE 12 TO TAX-RATE.
           DISPLAY "INPUT ID=" TAX-ID " AMOUNT=" TAX-AMOUNT.

           CALL "INTGCALC" USING TAX-AMOUNT TAX-RATE WS-TAX.
           DISPLAY "TAX-RESULT=" WS-TAX.

           OPEN OUTPUT TAX-OUT.
           MOVE TAX-ID TO OUT-ID.
           MOVE WS-TAX TO OUT-AMOUNT.
           WRITE OUT-REC.
           CLOSE TAX-OUT.
           DISPLAY "WRITE STATUS=" WS-OUT-STATUS.

           OPEN INPUT TAX-IN.
           MOVE "N" TO WS-EOF.
           MOVE 0 TO WS-COUNT.
           PERFORM UNTIL WS-EOF = "Y"
               READ TAX-IN
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       DISPLAY "FILE ID=" IN-ID " AMOUNT=" IN-AMOUNT
               END-READ
           END-PERFORM.
           CLOSE TAX-IN.

           DISPLAY "READ COUNT=" WS-COUNT.
           DISPLAY "INTEGRATED DEMO ENDED".
           STOP RUN.
