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
           05 DAT PIC X(2).
           05 AKU PIC X(2).
           05 AKD PIC X(2).
           05 KEYF PIC X(2).
       WORKING-STORAGE SECTION.
       01 FS PIC XX.
       PROCEDURE DIVISION.
           OPEN OUTPUT KF
           DISPLAY "open " FS
           MOVE "K4" TO KEYF
           MOVE "AA" TO AKD
           MOVE "U6" TO AKU
           MOVE "w0" TO DAT
           WRITE KF-REC
           DISPLAY "w0 " FS
           MOVE "K2" TO KEYF
           MOVE "DD" TO AKD
           MOVE "U7" TO AKU
           MOVE "w1" TO DAT
           WRITE KF-REC
           DISPLAY "w1 " FS
           MOVE "K4" TO KEYF
           MOVE "AA" TO AKD
           MOVE "U4" TO AKU
           MOVE "w2" TO DAT
           WRITE KF-REC
           DISPLAY "w2 " FS
           MOVE "K4" TO KEYF
           MOVE "CC" TO AKD
           MOVE "U5" TO AKU
           MOVE "w3" TO DAT
           WRITE KF-REC
           DISPLAY "w3 " FS
           CLOSE KF
           OPEN I-O KF
           DISPLAY "open2 " FS
           MOVE "K1" TO KEYF
           READ KF
           DISPLAY "s0 rk " FS " " DAT " " AKU " " AKD " " KEYF
           READ KF NEXT
           DISPLAY "s1 n " FS " " DAT " " AKU " " AKD " " KEYF
           MOVE "U7" TO AKU
           START KF KEY = AKU
           DISPLAY "s2 s " FS
           MOVE "K4" TO KEYF
           DELETE KF RECORD
           DISPLAY "s3 d " FS
           MOVE "K1" TO KEYF
           DELETE KF RECORD
           DISPLAY "s4 d " FS
           MOVE "K4" TO KEYF
           READ KF
           DISPLAY "s5 rk " FS " " DAT " " AKU " " AKD " " KEYF
           READ KF NEXT
           DISPLAY "s6 n " FS " " DAT " " AKU " " AKD " " KEYF
           MOVE "K3" TO KEYF
           MOVE "DD" TO AKD
           MOVE "U4" TO AKU
           MOVE "x7" TO DAT
           WRITE KF-REC
           DISPLAY "s7 w " FS
           READ KF NEXT
           DISPLAY "s8 n " FS " " DAT " " AKU " " AKD " " KEYF
           READ KF NEXT
           DISPLAY "s9 n " FS " " DAT " " AKU " " AKD " " KEYF
           MOVE "K3" TO KEYF
           START KF KEY > KEYF
           DISPLAY "s10 sp " FS
           MOVE "K2" TO KEYF
           DELETE KF RECORD
           DISPLAY "s11 d " FS
           MOVE "K4" TO KEYF
           START KF KEY >= KEYF
           DISPLAY "s12 sp " FS
           CLOSE KF
           STOP RUN.
