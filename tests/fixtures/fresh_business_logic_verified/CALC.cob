       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALC.
       AUTHOR. VALIDATION-PLATFORM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PRICE           PIC 9(4) VALUE 50.
       01  WS-QTY             PIC 9(4) VALUE 3.
       01  WS-DISCOUNT        PIC 9(4) VALUE 10.
       01  WS-SUBTOTAL        PIC 9(6) VALUE 0.
       01  WS-TOTAL           PIC 9(6) VALUE 0.
       01  WS-TAX             PIC 9(6) VALUE 0.
       01  WS-FINAL           PIC 9(6) VALUE 0.
       01  WS-CATEGORY        PIC X(10) VALUE SPACES.
       01  WS-LOOP-CNT        PIC 9(2) VALUE 0.
       01  WS-SUM             PIC 9(6) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "CALC-START".
           MULTIPLY WS-PRICE BY WS-QTY GIVING WS-SUBTOTAL.
           DISPLAY "SUBTOTAL=" WS-SUBTOTAL.
           SUBTRACT WS-DISCOUNT FROM WS-SUBTOTAL GIVING WS-TOTAL.
           DISPLAY "AFTER-DISCOUNT=" WS-TOTAL.
           COMPUTE WS-TAX = WS-TOTAL * 10 / 100.
           DISPLAY "TAX=" WS-TAX.
           COMPUTE WS-FINAL = WS-TOTAL + WS-TAX.
           DISPLAY "FINAL=" WS-FINAL.
           EVALUATE WS-FINAL
               WHEN 0
                   MOVE "FREE" TO WS-CATEGORY
               WHEN 1 THRU 100
                   MOVE "BASIC" TO WS-CATEGORY
               WHEN 101 THRU 500
                   MOVE "STANDARD" TO WS-CATEGORY
               WHEN 501 THRU 9999
                   MOVE "PREMIUM" TO WS-CATEGORY
               WHEN OTHER
                   MOVE "UNKNOWN" TO WS-CATEGORY
           END-EVALUATE.
           DISPLAY "CATEGORY=" WS-CATEGORY.
           PERFORM VARYING WS-LOOP-CNT FROM 1 BY 1
               UNTIL WS-LOOP-CNT > 5
               ADD WS-LOOP-CNT TO WS-SUM
               DISPLAY "LOOP=" WS-LOOP-CNT " SUM=" WS-SUM
           END-PERFORM.
           DISPLAY "VARYING-SUM=" WS-SUM.
           DISPLAY "CALC-END".
