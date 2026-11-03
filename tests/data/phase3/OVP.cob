       IDENTIFICATION DIVISION.
       PROGRAM-ID. OVP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  S   PIC S9(3).
       01  S2  PIC S9(3)V9.
       01  T   PIC X(20).
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           MOVE 0 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '0 ' T
           MOVE 1 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '1 ' T
           MOVE 2 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '2 ' T
           MOVE 3 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '3 ' T
           MOVE 4 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '4 ' T
           MOVE 5 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '5 ' T
           MOVE 6 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '6 ' T
           MOVE 7 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '7 ' T
           MOVE 8 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '8 ' T
           MOVE 9 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '9 ' T
           MOVE 0 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '0 ' T
           MOVE -1 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-1 ' T
           MOVE -2 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-2 ' T
           MOVE -3 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-3 ' T
           MOVE -4 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-4 ' T
           MOVE -5 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-5 ' T
           MOVE -6 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-6 ' T
           MOVE -7 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-7 ' T
           MOVE -8 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-8 ' T
           MOVE -9 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-9 ' T
           MOVE -120 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '-120 ' T
           MOVE 7 TO S
           MOVE SPACES TO T
           STRING '[' S ']' DELIMITED BY SIZE INTO T
           DISPLAY '7 ' T
           MOVE -12.5 TO S2
           MOVE SPACES TO T
           STRING '[' S2 ']' DELIMITED BY SIZE INTO T
           DISPLAY 'DEC ' T
           STOP RUN.
