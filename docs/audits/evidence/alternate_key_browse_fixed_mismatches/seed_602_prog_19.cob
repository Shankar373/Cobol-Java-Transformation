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
           05 DAT PIC X(2).
           05 AKU PIC X(2).
           05 KEYF PIC X(2).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN OUTPUT KF
           DISPLAY "open " FS
           MOVE "K2" TO KEYF
           MOVE "DD" TO AKD
           MOVE "U4" TO AKU
           MOVE "w0" TO DAT
           WRITE KF-REC
           DISPLAY "w0 " FS
           MOVE "K2" TO KEYF
           MOVE "DD" TO AKD
           MOVE "U5" TO AKU
           MOVE "w1" TO DAT
           WRITE KF-REC
           DISPLAY "w1 " FS
           MOVE "K3" TO KEYF
           MOVE "AA" TO AKD
           MOVE "U6" TO AKU
           MOVE "w2" TO DAT
           WRITE KF-REC
           DISPLAY "w2 " FS
           MOVE "K1" TO KEYF
           MOVE "BB" TO AKD
           MOVE "U2" TO AKU
           MOVE "w3" TO DAT
           WRITE KF-REC
           DISPLAY "w3 " FS
           MOVE "K5" TO KEYF
           MOVE "BB" TO AKD
           MOVE "U3" TO AKU
           MOVE "w4" TO DAT
           WRITE KF-REC
           DISPLAY "w4 " FS
           MOVE "K2" TO KEYF
           MOVE "CC" TO AKD
           MOVE "U3" TO AKU
           MOVE "w5" TO DAT
           WRITE KF-REC
           DISPLAY "w5 " FS
           CLOSE KF
           OPEN I-O KF
           DISPLAY "open2 " FS
           MOVE "K5" TO KEYF
           START KF KEY > KEYF
           DISPLAY "s0 sp " FS
           MOVE "U1" TO AKU
           START KF KEY > AKU
           DISPLAY "s1 s " FS
           MOVE "K1" TO KEYF
           READ KF
           DISPLAY "s2 rk " FS " " AKD " " DAT " " AKU " " KEYF
           MOVE "BB" TO AKD
           START KF KEY > AKD
           DISPLAY "s3 s " FS
           MOVE "K2" TO KEYF
           MOVE "BB" TO AKD
           MOVE "U5" TO AKU
           MOVE "r4" TO DAT
           REWRITE KF-REC
           DISPLAY "s4 rw " FS
           MOVE "K5" TO KEYF
           MOVE "AA" TO AKD
           MOVE "U4" TO AKU
           MOVE "x5" TO DAT
           WRITE KF-REC
           DISPLAY "s5 w " FS
           MOVE "K6" TO KEYF
           DELETE KF RECORD
           DISPLAY "s6 d " FS
           READ KF NEXT
           DISPLAY "s7 n " FS " " AKD " " DAT " " AKU " " KEYF
           READ KF NEXT
           DISPLAY "s8 n " FS " " AKD " " DAT " " AKU " " KEYF
           READ KF NEXT
           DISPLAY "s9 n " FS " " AKD " " DAT " " AKU " " KEYF
           MOVE "K4" TO KEYF
           START KF KEY < KEYF
           DISPLAY "s10 sp " FS
           CLOSE KF
           STOP RUN.
