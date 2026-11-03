       IDENTIFICATION DIVISION.
       PROGRAM-ID. VALIDATE.
      * Nightly validation step: writes a transaction extract, reads it
      * back, classifies each record and ends with the job-step return
      * code a scheduler acts on (0 clean, 4 warnings, 8 errors).
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT TXN-FILE ASSIGN TO 'TXNS.DAT'
               ORGANIZATION IS LINE SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  TXN-FILE.
       01  TXN-REC.
           05 TXN-ID               PIC X(4).
           05 TXN-AMOUNT           PIC 9(5).
           05 TXN-CODE             PIC X.
       WORKING-STORAGE SECTION.
       01  WS-EOF                  PIC X VALUE 'N'.
       01  WS-COUNTS.
           05 WS-READ              PIC 99 VALUE 0.
           05 WS-WARN              PIC 99 VALUE 0.
           05 WS-ERR               PIC 99 VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           PERFORM WRITE-EXTRACT.
           PERFORM CHECK-EXTRACT.
           EVALUATE TRUE
               WHEN WS-ERR > 0
                   MOVE 8 TO RETURN-CODE
               WHEN WS-WARN > 0
                   MOVE 4 TO RETURN-CODE
               WHEN OTHER
                   MOVE 0 TO RETURN-CODE
           END-EVALUATE.
           DISPLAY 'READ=' WS-READ ' WARN=' WS-WARN ' ERR=' WS-ERR.
           DISPLAY 'STEP RC=' RETURN-CODE.
           STOP RUN.
       WRITE-EXTRACT.
           OPEN OUTPUT TXN-FILE.
           MOVE 'T001' TO TXN-ID.
           MOVE 125 TO TXN-AMOUNT.
           MOVE 'A' TO TXN-CODE.
           WRITE TXN-REC.
           MOVE 'T002' TO TXN-ID.
           MOVE 99999 TO TXN-AMOUNT.
           MOVE 'A' TO TXN-CODE.
           WRITE TXN-REC.
           MOVE 'T003' TO TXN-ID.
           MOVE 40 TO TXN-AMOUNT.
           MOVE 'R' TO TXN-CODE.
           WRITE TXN-REC.
           CLOSE TXN-FILE.
       CHECK-EXTRACT.
           OPEN INPUT TXN-FILE.
           PERFORM UNTIL WS-EOF = 'Y'
               READ TXN-FILE
                   AT END MOVE 'Y' TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-READ
                       PERFORM CLASSIFY
               END-READ
           END-PERFORM.
           CLOSE TXN-FILE.
       CLASSIFY.
           IF TXN-CODE NOT = 'A' AND TXN-CODE NOT = 'R'
               ADD 1 TO WS-ERR
               DISPLAY TXN-ID ' ERROR BAD CODE'
           ELSE
               IF TXN-AMOUNT > 50000
                   ADD 1 TO WS-WARN
                   DISPLAY TXN-ID ' WARNING LARGE AMOUNT'
               END-IF
           END-IF.
