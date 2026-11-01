       IDENTIFICATION DIVISION.
       PROGRAM-ID. BIG.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO 'BIG.DAT'
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS F-KEY.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  F-REC.
           05 F-KEY  PIC X(4).
           05 F-DATA PIC X(5996).
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN OUTPUT F.
           MOVE 'K001' TO F-KEY.
           MOVE ALL 'X' TO F-DATA.
           WRITE F-REC.
           CLOSE F.
           STOP RUN.
