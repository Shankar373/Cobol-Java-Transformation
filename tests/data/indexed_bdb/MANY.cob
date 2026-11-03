       IDENTIFICATION DIVISION.
       PROGRAM-ID. MANY.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO 'MANY.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS F-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  F-REC.
           05 F-KEY  PIC 9(6).
           05 F-DATA PIC X(94).
       WORKING-STORAGE SECTION.
       01 I     PIC 9(6).
       01 EOF   PIC X VALUE 'N'.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT F.
           PERFORM VARYING I FROM 400 BY -1 UNTIL I = 0
               MOVE I TO F-KEY
               MOVE ALL 'D' TO F-DATA
               MOVE I TO F-DATA(1:6)
               WRITE F-REC
           END-PERFORM.
           CLOSE F.
           OPEN I-O F.
           PERFORM VARYING I FROM 7 BY 7 UNTIL I > 400
               MOVE I TO F-KEY
               DELETE F
           END-PERFORM.
           PERFORM VARYING I FROM 5 BY 5 UNTIL I > 400
               MOVE I TO F-KEY
               READ F
                   INVALID KEY CONTINUE
                   NOT INVALID KEY
                       MOVE 'REWRITTEN' TO F-DATA(7:9)
                       REWRITE F-REC
               END-READ
           END-PERFORM.
           CLOSE F.
           OPEN INPUT F.
           PERFORM UNTIL EOF = 'Y'
               READ F NEXT
                   AT END MOVE 'Y' TO EOF
                   NOT AT END DISPLAY F-REC
               END-READ
           END-PERFORM.
           CLOSE F.
           STOP RUN.
