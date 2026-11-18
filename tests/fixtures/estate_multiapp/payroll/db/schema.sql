-- Payroll schema: the tables PAYROLL.cbl reads (HR.EMPLOYEE) and rewrites
-- (HR.PAYSTUB).  Kept beside the sources it belongs to so discovery can bind
-- the program's SELECT/UPDATE statements to a definition in the same estate.
CREATE TABLE HR.EMPLOYEE (
    EMP_NO      INTEGER      NOT NULL,
    NAME        VARCHAR(30)  NOT NULL,
    DEPT        VARCHAR(4)   NOT NULL,
    HIRED       DATE         NOT NULL,
    SALARY      DECIMAL(9,2) NOT NULL,
    PRIMARY KEY (EMP_NO)
);

CREATE INDEX HR.EMPIX ON HR.EMPLOYEE (EMP_NO);

CREATE TABLE HR.PAYSTUB (
    EMP_NO      INTEGER      NOT NULL,
    PERIOD      CHAR(7)      NOT NULL,
    GROSS       DECIMAL(9,2) NOT NULL,
    TAX         DECIMAL(9,2) NOT NULL,
    NET         DECIMAL(9,2) NOT NULL,
    PRIMARY KEY (EMP_NO, PERIOD),
    CONSTRAINT PAYSTUB_EMP FOREIGN KEY (EMP_NO) REFERENCES HR.EMPLOYEE (EMP_NO)
);
