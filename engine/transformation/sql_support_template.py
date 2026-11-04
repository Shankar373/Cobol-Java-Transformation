"""Shared ``CobolSql`` Java support-class template: embedded SQL on JDBC.

Emitted by the plain and Spring Boot generators whenever generated method bodies reference
``CobolSql`` (a COBOL program performs a certified ``EXEC SQL`` statement).

Semantics follow the OCESQL + PostgreSQL reference (``Dockerfile.ocesql-pg``,
``tests/integration/test_sql_jdbc_oracle.py``), not DB2:

* statements run in one transaction (auto-commit off); ``COMMIT`` / ``ROLLBACK`` end it;
* success is SQLCODE 0 / SQLSTATE ``00000``; no row for a singleton ``SELECT`` or a ``FETCH``
  past the last row is SQLCODE 100 / ``02000``; a zero-row ``UPDATE`` / ``DELETE`` is SQLCODE 0
  (the reference does not report 100 as DB2 does);
* a host variable is bound as the field holds it (a ``PIC X(n)`` value padded to n characters);
* a failed statement is rolled back to a savepoint, so the transaction stays usable (DB2
  behaviour; the reference leaves PostgreSQL's transaction aborted).  SQLCODE is the DB2 code for
  the SQLSTATE where one is documented, else -1, and SQLSTATE is PostgreSQL's.  Programs must not
  compare the error number with the reference's; SQLSTATE of the first failure is the comparable.

The JDBC URL prefix comes from ``COBOL_SQL_URL`` (default ``jdbc:postgresql://localhost:5432/``).
"""

from __future__ import annotations

COBOL_SQL_JAVA = '''final class CobolSql {
    private CobolSql() {}

    static java.sql.Connection conn;
    static int code = 0;
    static String state = "00000";
    private static Object[] row;
    private static final java.util.Map<String, String> CURSOR_SQL = new java.util.HashMap<>();
    private static final java.util.Map<String, Object[]> CURSOR_ARGS = new java.util.HashMap<>();
    private static final java.util.Map<String, java.sql.ResultSet> CURSORS = new java.util.HashMap<>();
    private static final java.util.Map<String, java.sql.PreparedStatement> CURSOR_STMT = new java.util.HashMap<>();

    private static void ok() {
        code = 0;
        state = "00000";
    }

    private static void fail(java.sql.SQLException e) {
        state = e.getSQLState() == null ? "HY000" : e.getSQLState();
        switch (state) {
            case "21000": code = -811; break;
            case "23505": code = -803; break;
            case "23503": code = -530; break;
            case "23502": code = -407; break;
            case "22001": code = -302; break;
            case "22003": code = -413; break;
            case "22012": code = -802; break;
            case "42P01": code = -204; break;
            case "42703": code = -206; break;
            case "42601": code = -104; break;
            case "40001": case "40P01": code = -911; break;
            default: code = -1;
        }
    }

    private static void noData() {
        code = 100;
        state = "02000";
    }

    private static void bind(java.sql.PreparedStatement ps, Object[] args) throws java.sql.SQLException {
        for (int i = 0; i < args.length; i++) {
            ps.setObject(i + 1, args[i]);
        }
    }

    private static java.sql.Savepoint mark() throws java.sql.SQLException {
        return conn.setSavepoint();
    }

    private static void undo(java.sql.Savepoint sp) {
        try {
            if (sp != null) {
                conn.rollback(sp);
            }
        } catch (java.sql.SQLException ignored) {
            // the original failure is what the program reports
        }
    }

    static void connect(String user, String password, String database) {
        try {
            String prefix = System.getenv("COBOL_SQL_URL");
            if (prefix == null) {
                prefix = "jdbc:postgresql://localhost:5432/";
            }
            conn = java.sql.DriverManager.getConnection(prefix + database.trim(), user.trim(), password.trim());
            conn.setAutoCommit(false);
            ok();
        } catch (java.sql.SQLException e) {
            fail(e);
        }
    }

    static void disconnect() {
        try {
            if (conn != null) {
                conn.rollback();
                conn.close();
                conn = null;
            }
            ok();
        } catch (java.sql.SQLException e) {
            fail(e);
        }
    }

    static void commit() {
        try {
            conn.commit();
            ok();
        } catch (java.sql.SQLException e) {
            fail(e);
        }
    }

    static void rollback() {
        try {
            conn.rollback();
            ok();
        } catch (java.sql.SQLException e) {
            fail(e);
        }
    }

    /** INSERT / UPDATE / DELETE. */
    static void execute(String sql, Object... args) {
        java.sql.Savepoint sp = null;
        try {
            sp = mark();
            try (java.sql.PreparedStatement ps = conn.prepareStatement(sql)) {
                bind(ps, args);
                ps.executeUpdate();
            }
            ok();
        } catch (java.sql.SQLException e) {
            undo(sp);
            fail(e);
        }
    }

    /** Singleton SELECT ... INTO: the first row is read by {@code str}/{@code integer}/{@code dec}. */
    static void selectInto(String sql, Object... args) {
        row = null;
        java.sql.Savepoint sp = null;
        try {
            sp = mark();
            try (java.sql.PreparedStatement ps = conn.prepareStatement(sql)) {
                bind(ps, args);
                try (java.sql.ResultSet rs = ps.executeQuery()) {
                    if (rs.next()) {
                        row = read(rs);
                        ok();
                    } else {
                        noData();
                    }
                }
            }
        } catch (java.sql.SQLException e) {
            undo(sp);
            fail(e);
        }
    }

    private static Object[] read(java.sql.ResultSet rs) throws java.sql.SQLException {
        int n = rs.getMetaData().getColumnCount();
        Object[] values = new Object[n];
        for (int i = 0; i < n; i++) {
            values[i] = rs.getObject(i + 1);
        }
        return values;
    }

    static void declare(String name, String sql, Object... args) {
        CURSOR_SQL.put(name, sql);
        CURSOR_ARGS.put(name, args);
    }

    static void open(String name, Object... args) {
        java.sql.Savepoint sp = null;
        try {
            sp = mark();
            java.sql.PreparedStatement ps = conn.prepareStatement(CURSOR_SQL.get(name));
            bind(ps, args);
            CURSOR_STMT.put(name, ps);
            CURSORS.put(name, ps.executeQuery());
            ok();
        } catch (java.sql.SQLException e) {
            undo(sp);
            fail(e);
        }
    }

    static void fetch(String name) {
        row = null;
        try {
            java.sql.ResultSet rs = CURSORS.get(name);
            if (rs == null) {
                code = -501;
                state = "24501";
            } else if (rs.next()) {
                row = read(rs);
                ok();
            } else {
                noData();
            }
        } catch (java.sql.SQLException e) {
            fail(e);
        }
    }

    static void close(String name) {
        try {
            java.sql.ResultSet rs = CURSORS.remove(name);
            java.sql.PreparedStatement ps = CURSOR_STMT.remove(name);
            if (rs != null) {
                rs.close();
            }
            if (ps != null) {
                ps.close();
            }
            ok();
        } catch (java.sql.SQLException e) {
            fail(e);
        }
    }

    // ---- host-variable reads from the last fetched row; no row leaves the variable unchanged ----

    static String str(int column, int width, String current) {
        if (row == null) {
            return current;
        }
        Object v = row[column];
        String s = v == null ? "" : v.toString();
        StringBuilder sb = new StringBuilder(s.length() > width ? s.substring(0, width) : s);
        while (sb.length() < width) {
            sb.append(' ');
        }
        return sb.toString();
    }

    private static java.math.BigDecimal number(Object v) {
        return v instanceof java.math.BigDecimal ? (java.math.BigDecimal) v : new java.math.BigDecimal(v.toString());
    }

    static long integer(int column, int digits, long current) {
        if (row == null || row[column] == null) {
            return current;
        }
        java.math.BigDecimal d = number(row[column]).setScale(0, java.math.RoundingMode.DOWN);
        return d.remainder(java.math.BigDecimal.TEN.pow(digits)).longValue();
    }

    static java.math.BigDecimal dec(int column, int integerDigits, int scale, java.math.BigDecimal current) {
        if (row == null || row[column] == null) {
            return current;
        }
        return number(row[column]).setScale(scale, java.math.RoundingMode.DOWN)
            .remainder(java.math.BigDecimal.TEN.pow(integerDigits));
    }
}
'''
