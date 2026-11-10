       IDENTIFICATION DIVISION.
       PROGRAM-ID. EDITED.
      *> Invoice report: numeric-edited pictures fed by computed,
      *> zero and negative amounts (zero suppression, floating and
      *> fixed currency, trailing sign / CR, insertion characters,
      *> check protection, BLANK WHEN ZERO).
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-LINE-NO         PIC 9(2) VALUE 0.
       01 WS-QTY             PIC 9(3) VALUE 0.
       01 WS-PRICE           PIC 9(4)V99 VALUE 0.
       01 WS-DISC-PCT        PIC 9(2) VALUE 0.
       01 WS-GROSS           PIC S9(7)V99 VALUE 0.
       01 WS-DISC            PIC S9(7)V99 VALUE 0.
       01 WS-NET             PIC S9(7)V99 VALUE 0.
       01 WS-TOTAL           PIC S9(9)V99 COMP-3 VALUE 0.
       01 WS-DATE            PIC 9(8) VALUE 20261103.
       01 WS-RATE            PIC 9V9(4) VALUE 0.0725.
       01 WS-TAX             PIC S9(7)V99 VALUE 0.
       01 ED-QTY             PIC ZZ9 BLANK WHEN ZERO.
       01 ED-PRICE           PIC ZZ,ZZ9.99.
       01 ED-GROSS           PIC $$$,$$9.99.
       01 ED-DISC            PIC ---,--9.99.
       01 ED-NET             PIC ZZZ,ZZ9.99CR.
       01 ED-FIXED           PIC $ZZZ,ZZ9.99.
       01 ED-CHECK           PIC ***,**9.99.
       01 ED-DATE            PIC 99/99/9999.
       01 ED-RATE            PIC 9.9999.
       01 ED-TOTAL           PIC $$$,$$$,$$9.99-.
       01 ED-LINE            PIC Z9.
       01 WS-TEXT            PIC X(20).
       01 WS-OUT             PIC X(60).
       PROCEDURE DIVISION.
       MAIN-PARA.
           MOVE WS-DATE TO ED-DATE
           MOVE WS-RATE TO ED-RATE
           DISPLAY "INVOICE " ED-DATE " RATE " ED-RATE
           DISPLAY "UNINITIALISED: " ED-PRICE "|" ED-QTY "|" ED-TOTAL
           PERFORM LINE-PARA
               VARYING WS-LINE-NO FROM 1 BY 1 UNTIL WS-LINE-NO > 6
           MOVE WS-TOTAL TO ED-TOTAL
           MOVE WS-TOTAL TO ED-FIXED
           MOVE WS-TOTAL TO ED-CHECK
           DISPLAY "TOTAL " ED-TOTAL "|" ED-FIXED "|" ED-CHECK
           STRING "NET=" DELIMITED BY SIZE
                  ED-TOTAL DELIMITED BY SIZE
                  INTO WS-OUT
           DISPLAY WS-OUT
           MOVE ED-TOTAL TO WS-TEXT
           DISPLAY "TEXT[" WS-TEXT "]"
           MOVE 0 TO ED-QTY
           MOVE -0.5 TO ED-DISC
           MOVE ZERO TO ED-GROSS
           DISPLAY "EDGE " ED-QTY "|" ED-DISC "|" ED-GROSS
           STOP RUN.
       LINE-PARA.
           EVALUATE WS-LINE-NO
               WHEN 1 MOVE 12 TO WS-QTY
                      MOVE 19.99 TO WS-PRICE
                      MOVE 0 TO WS-DISC-PCT
               WHEN 2 MOVE 3 TO WS-QTY
                      MOVE 1250.5 TO WS-PRICE
                      MOVE 10 TO WS-DISC-PCT
               WHEN 3 MOVE 0 TO WS-QTY
                      MOVE 99.99 TO WS-PRICE
                      MOVE 0 TO WS-DISC-PCT
               WHEN 4 MOVE 100 TO WS-QTY
                      MOVE 0.01 TO WS-PRICE
                      MOVE 50 TO WS-DISC-PCT
               WHEN 5 MOVE 999 TO WS-QTY
                      MOVE 9999.99 TO WS-PRICE
                      MOVE 15 TO WS-DISC-PCT
               WHEN OTHER MOVE 1 TO WS-QTY
                      MOVE 5 TO WS-PRICE
                      MOVE 100 TO WS-DISC-PCT
           END-EVALUATE
           COMPUTE WS-GROSS = WS-QTY * WS-PRICE
           COMPUTE WS-DISC = WS-GROSS * WS-DISC-PCT / 100
           COMPUTE WS-NET = WS-GROSS - WS-DISC
           IF WS-LINE-NO = 6
               COMPUTE WS-NET = 0 - WS-NET - 42.5
           END-IF
           COMPUTE WS-TAX = WS-NET * WS-RATE
           ADD WS-NET TO WS-TOTAL
           MOVE WS-LINE-NO TO ED-LINE
           MOVE WS-QTY TO ED-QTY
           MOVE WS-PRICE TO ED-PRICE
           MOVE WS-GROSS TO ED-GROSS
           MOVE WS-DISC TO ED-DISC
           MOVE WS-NET TO ED-NET
           MOVE WS-NET TO ED-CHECK
           DISPLAY ED-LINE " " ED-QTY " " ED-PRICE " " ED-GROSS " "
                   ED-DISC " " ED-NET " " ED-CHECK
           MOVE WS-TAX TO ED-DISC
           DISPLAY "   TAX " ED-DISC.
