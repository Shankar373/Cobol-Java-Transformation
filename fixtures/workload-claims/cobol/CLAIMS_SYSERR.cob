       IDENTIFICATION DIVISION.
       PROGRAM-ID. CLAIMS.
       AUTHOR. VALIDATION-PLATFORM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
        SELECT CLAIMS-FILE ASSIGN TO "/workspace/input/claims.dat"
            ORGANIZATION IS LINE SEQUENTIAL.
        SELECT PAYMENTS-FILE ASSIGN TO "/workspace/input/payments.dat"
            ORGANIZATION IS LINE SEQUENTIAL.
        SELECT REPORT-FILE ASSIGN TO "/workspace/output/report.txt"
            ORGANIZATION IS LINE SEQUENTIAL.
        SELECT SETTLE-FILE ASSIGN TO "/workspace/output/settlement.dat"
            ORGANIZATION IS LINE SEQUENTIAL.

       DATA DIVISION.
       FILE SECTION.
       FD  CLAIMS-FILE.
       01  CLAIM-REC             PIC X(60).

       FD  PAYMENTS-FILE.
       01  PAYMENT-REC           PIC X(60).

       FD  REPORT-FILE.
       01  REPORT-REC            PIC X(80).

       FD  SETTLE-FILE.
       01  SETTLE-REC            PIC X(80).

       WORKING-STORAGE SECTION.
       01  WS-EOF-CLAIMS         PIC X(1) VALUE 'N'.
       01  WS-EOF-PAYMENTS       PIC X(1) VALUE 'N'.
       01  WS-CLAIM-COUNT        PIC 9(2) VALUE 0.
       01  WS-APPROVED-COUNT     PIC 9(2) VALUE 0.
       01  WS-REJECTED-COUNT     PIC 9(2) VALUE 0.
       01  WS-PENDING-COUNT      PIC 9(2) VALUE 0.
       01  WS-PAID-COUNT         PIC 9(2) VALUE 0.
       01  WS-UNPAID-COUNT       PIC 9(2) VALUE 0.
       01  WS-TOTAL-CLAIMS       PIC 9(6) VALUE 0.
       01  WS-TOTAL-PAYMENTS     PIC 9(6) VALUE 0.
       01  WS-CLAIM-AMOUNT       PIC 9(5) VALUE 0.
       01  WS-PAY-MATCH-AMOUNT   PIC 9(5) VALUE 0.
       01  WS-PAY-MATCH-FOUND    PIC X(1) VALUE 'N'.
       01  WS-SETTLEMENT-STATUS  PIC X(13).

       01  WS-CR-CLAIM-ID        PIC X(4).
       01  WS-CR-PATIENT-NAME    PIC X(12).
       01  WS-CR-SERVICE-DATE    PIC X(8).
       01  WS-CR-AMOUNT-STR      PIC X(5).
       01  WS-CR-STATUS          PIC X(1).
       01  WS-CR-CATEGORY        PIC X(8).

       01  WS-PR-PAY-ID          PIC X(4).
       01  WS-PR-CLAIM-ID        PIC X(4).
       01  WS-PR-PAY-DATE        PIC X(8).
       01  WS-PR-AMOUNT-STR      PIC X(5).
       01  WS-PR-METHOD          PIC X(13).

       01  WS-PAY-TABLE.
           05 WS-PAY-ENTRY OCCURS 20 TIMES.
               10 WS-PT-CLAIM-ID     PIC X(4).
               10 WS-PT-AMOUNT       PIC 9(5).
       01  WS-PAY-COUNT          PIC 9(2) VALUE 0.
       01  WS-PAY-IDX            PIC 9(2) VALUE 0.

       01  WS-HEADER             PIC X(80) VALUE
           "CLAIM   PATIENT      DATE     AMT ST CAT      SETTLEMENT".
       01  WS-SPACER             PIC X(80) VALUE SPACES.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT CLAIMS-FILE
           OPEN INPUT PAYMENTS-FILE
           OPEN OUTPUT REPORT-FILE
           OPEN OUTPUT SETTLE-FILE

           PERFORM LOAD-PAYMENTS

           MOVE WS-HEADER TO REPORT-REC
           WRITE REPORT-REC
           MOVE WS-SPACER TO REPORT-REC
           WRITE REPORT-REC

           PERFORM PROCESS-CLAIMS
               UNTIL WS-EOF-CLAIMS = 'Y'

           DISPLAY "TOTAL_CLAIMS=" WS-CLAIM-COUNT
           DISPLAY "APPROVED=" WS-APPROVED-COUNT
           DISPLAY "REJECTED=" WS-REJECTED-COUNT
           DISPLAY "PENDING=" WS-PENDING-COUNT
           DISPLAY "PAID=" WS-PAID-COUNT
           DISPLAY "UNPAID=" WS-UNPAID-COUNT
           DISPLAY "TOTAL_CLAIM_AMT=" WS-TOTAL-CLAIMS
           DISPLAY "TOTAL_PAY_AMT=" WS-TOTAL-PAYMENTS

           CLOSE CLAIMS-FILE
           CLOSE PAYMENTS-FILE
           CLOSE REPORT-FILE
           CLOSE SETTLE-FILE

           STOP RUN.

       LOAD-PAYMENTS.
           READ PAYMENTS-FILE
               AT END
                   MOVE 'Y' TO WS-EOF-PAYMENTS
               NOT AT END
                   ADD 1 TO WS-PAY-COUNT
                   UNSTRING PAYMENT-REC DELIMITED BY "|"
                       INTO WS-PR-PAY-ID
                            WS-PR-CLAIM-ID
                            WS-PR-PAY-DATE
                            WS-PR-AMOUNT-STR
                            WS-PR-METHOD
                   END-UNSTRING
                   MOVE WS-PR-CLAIM-ID
                       TO WS-PT-CLAIM-ID(WS-PAY-COUNT)
                   MOVE WS-PR-AMOUNT-STR
                       TO WS-PT-AMOUNT(WS-PAY-COUNT)
           END-READ
           IF WS-EOF-PAYMENTS NOT = 'Y'
               GO TO LOAD-PAYMENTS
           END-IF.

       PROCESS-CLAIMS.
           READ CLAIMS-FILE
               AT END
                   MOVE 'Y' TO WS-EOF-CLAIMS
               NOT AT END
                   ADD 1 TO WS-CLAIM-COUNT

                   UNSTRING CLAIM-REC DELIMITED BY "|"
                       INTO WS-CR-CLAIM-ID
                            WS-CR-PATIENT-NAME
                            WS-CR-SERVICE-DATE
                            WS-CR-AMOUNT-STR
                            WS-CR-STATUS
                            WS-CR-CATEGORY
                   END-UNSTRING

                   MOVE WS-CR-AMOUNT-STR TO WS-CLAIM-AMOUNT
                   ADD WS-CLAIM-AMOUNT TO WS-TOTAL-CLAIMS

                   MOVE 'N' TO WS-PAY-MATCH-FOUND
                   MOVE 0 TO WS-PAY-MATCH-AMOUNT

                   IF WS-CR-STATUS = 'R'
                       MOVE 'REJECTED' TO WS-SETTLEMENT-STATUS
                       ADD 1 TO WS-REJECTED-COUNT
                   ELSE
                       IF WS-CR-STATUS = 'P'
                           MOVE 'PENDING' TO WS-SETTLEMENT-STATUS
                           ADD 1 TO WS-PENDING-COUNT
                       ELSE
                           IF WS-CLAIM-AMOUNT < 500
                               MOVE 'REJECTED'
                                   TO WS-SETTLEMENT-STATUS
                               ADD 1 TO WS-REJECTED-COUNT
                           ELSE
                               MOVE 'APPROVED'
                                   TO WS-SETTLEMENT-STATUS
                               ADD 1 TO WS-APPROVED-COUNT
                               PERFORM FIND-PAYMENT
                               IF WS-PAY-MATCH-FOUND = 'Y'
                                   ADD WS-PAY-MATCH-AMOUNT
                                       TO WS-TOTAL-PAYMENTS
                                   IF WS-PAY-MATCH-AMOUNT
                                       = WS-CLAIM-AMOUNT
                                       MOVE 'PAID_IN_FULL'
                                           TO WS-SETTLEMENT-STATUS
                                       ADD 1 TO WS-PAID-COUNT
                                   ELSE
                                       MOVE 'PARTIAL'
                                           TO WS-SETTLEMENT-STATUS
                                       ADD 1 TO WS-PAID-COUNT
                                   END-IF
                               ELSE
                                   MOVE 'UNPAID'
                                       TO WS-SETTLEMENT-STATUS
                                   ADD 1 TO WS-UNPAID-COUNT
                               END-IF
                           END-IF
                       END-IF
                   END-IF

                   MOVE SPACES TO REPORT-REC
                   STRING WS-CR-CLAIM-ID DELIMITED BY SIZE
                       " " DELIMITED BY SIZE
                       WS-CR-PATIENT-NAME DELIMITED BY SIZE
                       " " DELIMITED BY SIZE
                       WS-CR-SERVICE-DATE DELIMITED BY SIZE
                       " " DELIMITED BY SIZE
                       WS-CR-AMOUNT-STR DELIMITED BY SIZE
                       " " DELIMITED BY SIZE
                       WS-CR-STATUS DELIMITED BY SIZE
                       " " DELIMITED BY SIZE
                       WS-CR-CATEGORY DELIMITED BY SIZE
                       " " DELIMITED BY SIZE
                       WS-SETTLEMENT-STATUS DELIMITED BY SIZE
                       INTO REPORT-REC
                   END-STRING
                   WRITE REPORT-REC

                   MOVE SPACES TO SETTLE-REC
                   STRING WS-CR-CLAIM-ID DELIMITED BY SIZE
                       "|" DELIMITED BY SIZE
                       WS-CR-PATIENT-NAME DELIMITED BY SIZE
                       "|" DELIMITED BY SIZE
                       WS-CR-AMOUNT-STR DELIMITED BY SIZE
                       "|" DELIMITED BY SIZE
                       WS-CR-CATEGORY DELIMITED BY SIZE
                       "|" DELIMITED BY SIZE
                       WS-SETTLEMENT-STATUS DELIMITED BY SIZE
                       "|" DELIMITED BY SIZE
                       WS-PAY-MATCH-AMOUNT DELIMITED BY SIZE
                       INTO SETTLE-REC
                   END-STRING
                   WRITE SETTLE-REC

                   IF WS-SETTLEMENT-STATUS = 'REJECTED'
                       DISPLAY "REJECT:"
                           WS-CR-CLAIM-ID
                           " " WS-CR-PATIENT-NAME
                           " reason="
                           WS-CR-STATUS
                           UPON SYSERR
                   END-IF

                   IF WS-CLAIM-AMOUNT < 500
                       AND WS-CR-STATUS = 'A'
                       DISPLAY "LOW_AMOUNT:"
                           WS-CR-CLAIM-ID
                           " " WS-CR-PATIENT-NAME
                           " amt="
                           WS-CR-AMOUNT-STR
                           UPON SYSERR
                   END-IF
           END-READ.

       FIND-PAYMENT.
           MOVE 1 TO WS-PAY-IDX
           PERFORM CHECK-PAYMENT
               UNTIL WS-PAY-IDX > WS-PAY-COUNT
               OR WS-PAY-MATCH-FOUND = 'Y'.

       CHECK-PAYMENT.
           IF WS-PT-CLAIM-ID(WS-PAY-IDX) = WS-CR-CLAIM-ID
               MOVE 'Y' TO WS-PAY-MATCH-FOUND
               MOVE WS-PT-AMOUNT(WS-PAY-IDX)
                   TO WS-PAY-MATCH-AMOUNT
           END-IF
           ADD 1 TO WS-PAY-IDX.

