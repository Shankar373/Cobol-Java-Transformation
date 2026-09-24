IDENTIFICATION DIVISION.
       PROGRAM-ID. FILE-WRITE-READ.
       AUTHOR. VALIDATION-PLATFORM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO "/workspace/output/wr.dat"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-OUT-STATUS.
           SELECT IN-FILE ASSIGN TO "/workspace/output/wr.dat"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-IN-STATUS.

       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-REC.
           05  OUT-ID               PIC X(4).
           05  OUT-VAL              PIC X(12).
       FD  IN-FILE.
       01  IN-REC.
           05  IN-ID                PIC X(4).
           05  IN-VAL               PIC X(12).

       WORKING-STORAGE SECTION.
       01  WS-OUT-STATUS        PIC X(2) VALUE "00".
       01  WS-IN-STATUS         PIC X(2) VALUE "00".
       01  WS-EOF               PIC X VALUE "N".
       01  WS-COUNT             PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "SEQUENTIAL WRITE/READ DEMO STARTED".

           OPEN OUTPUT OUT-FILE.
           DISPLAY "OPEN OUTPUT STATUS=" WS-OUT-STATUS.

           MOVE "R001" TO OUT-ID.
           MOVE "VALUE-ONE---" TO OUT-VAL.
           WRITE OUT-REC.
           DISPLAY "WRITE R001 STATUS=" WS-OUT-STATUS.

           MOVE "R002" TO OUT-ID.
           MOVE "VALUE-TWO---" TO OUT-VAL.
           WRITE OUT-REC.
           DISPLAY "WRITE R002 STATUS=" WS-OUT-STATUS.

           MOVE "R003" TO OUT-ID.
           MOVE "VALUE-THREE-" TO OUT-VAL.
           WRITE OUT-REC.
           DISPLAY "WRITE R003 STATUS=" WS-OUT-STATUS.

           CLOSE OUT-FILE.
           DISPLAY "CLOSE OUT STATUS=" WS-OUT-STATUS.

           OPEN INPUT IN-FILE.
           DISPLAY "OPEN INPUT STATUS=" WS-IN-STATUS.

           MOVE "N" TO WS-EOF.
           MOVE 0 TO WS-COUNT.
           PERFORM UNTIL WS-EOF = "Y"
               READ IN-FILE
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       DISPLAY "READ: ID=" IN-ID " VAL=" IN-VAL " STATUS=" WS-IN-STATUS
               END-READ
           END-PERFORM.
           DISPLAY "RECORDS READ=" WS-COUNT.

           CLOSE IN-FILE.
           DISPLAY "CLOSE IN STATUS=" WS-IN-STATUS.

           STOP RUN.
