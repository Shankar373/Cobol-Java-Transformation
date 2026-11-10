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
           05 AKD PIC X(2).
           05 KEYF PIC X(2).
           05 DAT PIC X(2).
           05 AKU PIC X(2).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN OUTPUT KF
           DISPLAY "open " FS
           MOVE "K5" TO KEYF
           MOVE "AA" TO AKD
           MOVE "U4" TO AKU
           MOVE "w0" TO DAT
           WRITE KF-REC
           DISPLAY "w0 " FS
           MOVE "K4" TO KEYF
           MOVE "DD" TO AKD
           MOVE "U7" TO AKU
           MOVE "w1" TO DAT
           WRITE KF-REC
           DISPLAY "w1 " FS
           MOVE "K2" TO KEYF
           MOVE "AA" TO AKD
           MOVE "U1" TO AKU
           MOVE "w2" TO DAT
           WRITE KF-REC
           DISPLAY "w2 " FS
           CLOSE KF
           OPEN I-O KF
           DISPLAY "open2 " FS
           MOVE "K3" TO KEYF
           READ KF
           DISPLAY "s0 rk " FS " " AKD " " KEYF " " DAT " " AKU
           MOVE "BB" TO AKD
           READ KF KEY IS AKD
           DISPLAY "s1 ra " FS " " AKD " " KEYF " " DAT " " AKU
           MOVE "DD" TO AKD
           START KF KEY >= AKD
           DISPLAY "s2 s " FS
           MOVE "K2" TO KEYF
           READ KF
           DISPLAY "s3 rk " FS " " AKD " " KEYF " " DAT " " AKU
           MOVE "CC" TO AKD
           READ KF KEY IS AKD
           DISPLAY "s4 ra " FS " " AKD " " KEYF " " DAT " " AKU
           READ KF NEXT
           DISPLAY "s5 n " FS " " AKD " " KEYF " " DAT " " AKU
           MOVE "K4" TO KEYF
           START KF KEY >= KEYF
           DISPLAY "s6 sp " FS
           MOVE "K4" TO KEYF
           READ KF
           DISPLAY "s7 rk " FS " " AKD " " KEYF " " DAT " " AKU
           MOVE "BB" TO AKD
           START KF KEY > AKD
           DISPLAY "s8 s " FS
           MOVE "K1" TO KEYF
           DELETE KF RECORD
           DISPLAY "s9 d " FS
           CLOSE KF
           STOP RUN.
