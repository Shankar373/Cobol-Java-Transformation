IDENTIFICATION DIVISION.
       PROGRAM-ID. COPYBOOK-FILE-MULTI.
       AUTHOR. VALIDATION-PLATFORM.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT EMP-FILE ASSIGN TO "/workspace/output/emp.dat"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-OUT-STATUS.
           SELECT EMP-RD-FILE ASSIGN TO "/workspace/output/emp.dat"
               ORGANIZATION IS LINE SEQUENTIAL
               FILE STATUS IS WS-IN-STATUS.

       DATA DIVISION.
       FILE SECTION.
FD  EMP-FILE.
       01  EMP-REC.
           05  EMP-ID              PIC X(4).
           05  EMP-NAME            PIC X(12).
           05  EMP-DEPT            PIC X(8).
       FD  EMP-RD-FILE.
       01  EMP-RD-REC.
           05  EMP-RD-ID           PIC X(4).
           05  EMP-RD-NAME         PIC X(12).
           05  EMP-RD-DEPT         PIC X(8).

       WORKING-STORAGE SECTION.
       COPY EMPREC.
       01  WS-OUT-STATUS       PIC X(2) VALUE "00".
       01  WS-IN-STATUS        PIC X(2) VALUE "00".
       01  WS-EOF              PIC X VALUE "N".
       01  WS-COUNT            PIC 9(2) VALUE 0.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "COPYBOOK FILE MULTI DEMO STARTED".

           OPEN OUTPUT EMP-FILE.
           DISPLAY "OPEN OUTPUT STATUS=" WS-OUT-STATUS.

           MOVE "E001" TO EMP-SRC-ID.
           MOVE "ALICE" TO EMP-SRC-NAME.
           MOVE "SALES001" TO EMP-SRC-DEPT.
           MOVE EMP-SRC-ID TO EMP-ID.
           MOVE EMP-SRC-NAME TO EMP-NAME.
           MOVE EMP-SRC-DEPT TO EMP-DEPT.
           WRITE EMP-REC.
           DISPLAY "WRITE E001 STATUS=" WS-OUT-STATUS " SRC-ID=" EMP-SRC-ID.

           MOVE "E002" TO EMP-SRC-ID.
           MOVE "BOB" TO EMP-SRC-NAME.
           MOVE "ENGG0001" TO EMP-SRC-DEPT.
           MOVE EMP-SRC-ID TO EMP-ID.
           MOVE EMP-SRC-NAME TO EMP-NAME.
           MOVE EMP-SRC-DEPT TO EMP-DEPT.
           WRITE EMP-REC.
           DISPLAY "WRITE E002 STATUS=" WS-OUT-STATUS " SRC-ID=" EMP-SRC-ID.

           MOVE "E003" TO EMP-SRC-ID.
           MOVE "CAROL" TO EMP-SRC-NAME.
           MOVE "TECH0001" TO EMP-SRC-DEPT.
           MOVE EMP-SRC-ID TO EMP-ID.
           MOVE EMP-SRC-NAME TO EMP-NAME.
           MOVE EMP-SRC-DEPT TO EMP-DEPT.
           WRITE EMP-REC.
           DISPLAY "WRITE E003 STATUS=" WS-OUT-STATUS " SRC-ID=" EMP-SRC-ID.

           CLOSE EMP-FILE.
           DISPLAY "CLOSE OUT STATUS=" WS-OUT-STATUS.

           OPEN INPUT EMP-RD-FILE.
           DISPLAY "OPEN INPUT STATUS=" WS-IN-STATUS.

           MOVE "N" TO WS-EOF.
           MOVE 0 TO WS-COUNT.
           PERFORM UNTIL WS-EOF = "Y"
               READ EMP-RD-FILE
                   AT END MOVE "Y" TO WS-EOF
                   NOT AT END
                       ADD 1 TO WS-COUNT
                       DISPLAY "READ: ID=" EMP-RD-ID " NAME=" EMP-RD-NAME " DEPT=" EMP-RD-DEPT
               END-READ
           END-PERFORM.
           DISPLAY "RECORDS READ=" WS-COUNT.

           CLOSE EMP-RD-FILE.
           DISPLAY "CLOSE IN STATUS=" WS-IN-STATUS.

           STOP RUN.

