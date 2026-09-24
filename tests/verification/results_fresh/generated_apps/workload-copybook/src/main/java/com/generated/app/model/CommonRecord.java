package com.generated.app.model;

/**
 * Shared data model materialized from COPYBOOK COMMON.
 * Auto-generated: data definition only, no business logic.
 */
public class CommonRecord {
    private String CLAIM_ID = "C-001";
    private int CLAIM_AMOUNT = 500;

    public CommonRecord() {}

    public String getCLAIM_ID() {
        return this.CLAIM_ID;
    }

    public void setCLAIM_ID(String value) {
        this.CLAIM_ID = value;
    }

    public int getCLAIM_AMOUNT() {
        return this.CLAIM_AMOUNT;
    }

    public void setCLAIM_AMOUNT(int value) {
        this.CLAIM_AMOUNT = value;
    }

}