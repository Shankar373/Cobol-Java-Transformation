       IDENTIFICATION DIVISION.
       PROGRAM-ID. ALT.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT KF ASSIGN TO "ALT.DAT"
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS KEYF
               ALTERNATE RECORD KEY IS AKD WITH DUPLICATES
               ALTERNATE RECORD KEY IS AKU
               FILE STATUS IS FS.
       DATA DIVISION.
       FILE SECTION.
       FD KF.
       01 KF-REC.
           05 KEYF PIC X(2).
           05 AKD PIC X(2).
           05 AKU PIC X(2).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN OUTPUT KF
           DISPLAY "open " FS
           MOVE "K1" TO KEYF
           MOVE "CC" TO AKD
           MOVE "U5" TO AKU
           WRITE KF-REC
           DISPLAY "w0 " FS
           MOVE "K1" TO KEYF
           MOVE "DD" TO AKD
           MOVE "U7" TO AKU
           WRITE KF-REC
           DISPLAY "w1 " FS
           MOVE "K4" TO KEYF
           MOVE "CC" TO AKD
           MOVE "U3" TO AKU
           WRITE KF-REC
           DISPLAY "w2 " FS
           CLOSE KF
           OPEN I-O KF
           DISPLAY "open2 " FS
           MOVE "K6" TO KEYF
           MOVE "DD" TO AKD
           MOVE "U1" TO AKU
           REWRITE KF-REC
           DISPLAY "s0 rw " FS
           MOVE "K3" TO KEYF
           MOVE "DD" TO AKD
           MOVE "U4" TO AKU
           REWRITE KF-REC
           DISPLAY "s1 rw " FS
           MOVE "K2" TO KEYF
           MOVE "CC" TO AKD
           MOVE "U6" TO AKU
           REWRITE KF-REC
           DISPLAY "s2 rw " FS
           MOVE "K5" TO KEYF
           DELETE KF RECORD
           DISPLAY "s3 d " FS
           MOVE "U4" TO AKU
           START KF KEY = AKU
           DISPLAY "s4 s " FS
           MOVE "K5" TO KEYF
           READ KF
           DISPLAY "s5 rk " FS " " KEYF " " AKD " " AKU
           MOVE "K3" TO KEYF
           DELETE KF RECORD
           DISPLAY "s6 d " FS
           MOVE "AA" TO AKD
           READ KF KEY IS AKD
           DISPLAY "s7 ra " FS " " KEYF " " AKD " " AKU
           MOVE "K1" TO KEYF
           READ KF
           DISPLAY "s8 rk " FS " " KEYF " " AKD " " AKU
           MOVE "CC" TO AKD
           START KF KEY >= AKD
           DISPLAY "s9 s " FS
           MOVE "K6" TO KEYF
           READ KF
           DISPLAY "s10 rk " FS " " KEYF " " AKD " " AKU
           READ KF NEXT
           DISPLAY "s11 n " FS " " KEYF " " AKD " " AKU
           READ KF NEXT
           DISPLAY "s12 n " FS " " KEYF " " AKD " " AKU
           CLOSE KF
           STOP RUN.
