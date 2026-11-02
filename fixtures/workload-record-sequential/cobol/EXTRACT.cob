       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXTRACT.
      * Nightly extract: fixed-length record SEQUENTIAL files (no
      * ORGANIZATION clause, and an explicit ORGANIZATION SEQUENTIAL).
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EXTRACT-FILE ASSIGN TO "EXTRACT.DAT"
               FILE STATUS IS WS-EXT-STATUS.
           SELECT SUMMARY-FILE ASSIGN TO "SUMMARY.DAT"
               ORGANIZATION IS SEQUENTIAL
               ACCESS MODE IS SEQUENTIAL.
       DATA DIVISION.
       FILE SECTION.
       FD  EXTRACT-FILE.
       01  EXT-REC.
           05  EXT-ACCOUNT       PIC X(6).
           05  EXT-BRANCH        PIC X(3).
           05  EXT-AMOUNT        PIC 9(7).
           05  EXT-NAME          PIC X(10).
       FD  SUMMARY-FILE.
       01  SUM-REC               PIC X(30).
       WORKING-STORAGE SECTION.
       01  WS-EXT-STATUS         PIC XX.
       01  WS-EOF                PIC X VALUE 'N'.
       01  WS-COUNT              PIC 9(4) VALUE 0.
       01  WS-TOTAL              PIC 9(9) VALUE 0.
       01  WS-MANUAL.
           05  WS-M-ACCOUNT      PIC X(6) VALUE 'A00900'.
           05  WS-M-BRANCH       PIC X(3) VALUE 'NYC'.
           05  WS-M-AMOUNT       PIC 9(7) VALUE 0000250.
           05  WS-M-NAME         PIC X(10) VALUE 'ADJUSTMENT'.
       01  WS-SUMMARY.
           05  FILLER            PIC X(8) VALUE 'RECORDS='.
           05  WS-S-COUNT        PIC 9(4).
           05  FILLER            PIC X(7) VALUE ' TOTAL='.
           05  WS-S-TOTAL        PIC 9(9).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN OUTPUT EXTRACT-FILE
           DISPLAY 'OPEN OUTPUT ' WS-EXT-STATUS
           MOVE 'A00100' TO EXT-ACCOUNT
           MOVE 'BOS' TO EXT-BRANCH
           MOVE 1500 TO EXT-AMOUNT
           MOVE 'SMITH' TO EXT-NAME
           WRITE EXT-REC
           MOVE 'A00200' TO EXT-ACCOUNT
           MOVE 'CHI' TO EXT-BRANCH
           MOVE 27 TO EXT-AMOUNT
           MOVE 'O''BRIEN' TO EXT-NAME
           WRITE EXT-REC
           CLOSE EXTRACT-FILE
           OPEN EXTEND EXTRACT-FILE
           DISPLAY 'OPEN EXTEND ' WS-EXT-STATUS
           WRITE EXT-REC FROM WS-MANUAL
           DISPLAY 'AFTER FROM ' EXT-ACCOUNT ' ' EXT-AMOUNT
           CLOSE EXTRACT-FILE
           OPEN INPUT EXTRACT-FILE
           PERFORM UNTIL WS-EOF = 'Y'
               READ EXTRACT-FILE
                   AT END
                       MOVE 'Y' TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       ADD EXT-AMOUNT TO WS-TOTAL
                       DISPLAY EXT-ACCOUNT '|' EXT-BRANCH '|'
                           EXT-AMOUNT '|' EXT-NAME '|'
               END-READ
           END-PERFORM
           DISPLAY 'READ STATUS ' WS-EXT-STATUS
           CLOSE EXTRACT-FILE
           MOVE WS-COUNT TO WS-S-COUNT
           MOVE WS-TOTAL TO WS-S-TOTAL
           OPEN OUTPUT SUMMARY-FILE
           WRITE SUM-REC FROM WS-SUMMARY
           CLOSE SUMMARY-FILE
           DISPLAY 'RECORDS ' WS-COUNT ' TOTAL ' WS-TOTAL
           STOP RUN.
